// dowprobe_launcher.exe – uruchamia Dawn of War: DE z sondą dowprobe.dll albo rejestratorem dowrec.dll
// (tylko do powtórek offline).
//
// Użycie: dowprobe_launcher.exe [--rec] [--out <nagrania>] [--logs <dzienniki>] [folder_gry]
//   v2.1: gdy gra już działa (np. uruchomiona przez Steam), z --rec podłącza do niej rejestrator (Attach)
//   folder gry domyślnie z bibliotek Steam (libraryfolders.vdf, aplikacja 3556750), inaczej domyślna ścieżka
//   --rec  ładuje dowrec.dll zamiast sondy i ustawia DOWREC_OUT=<projekt>\recordings
// - nie modyfikuje plików gry,
// - jeśli W40k.exe już działa: z --rec podłącza rejestrator (dowrec.cfg zamiast zmiennych), bez --rec odmawia,
// - ustawia DOWPROBE_LAUNCHER=1 i DOWPROBE_LOG=<ścieżka> (bez tego DLL nic nie robi),
// - po załadowaniu DLL moda (W40kMod/WXPMod/DXP2Mod/DXP3Mod) wstrzykuje dowprobe.dll przez CreateRemoteThread(LoadLibraryW).

#include <windows.h>
#include <psapi.h>
#include <tlhelp32.h>
#include <stdio.h>
#include <fcntl.h>
#include <io.h>
#include <string>
#include <vector>

static const wchar_t* kDefaultGameDir = L"C:\\Program Files (x86)\\Steam\\steamapps\\common\\Dawn of War Definitive Edition";

static DWORD FindProcess(const wchar_t* exe)
{
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    PROCESSENTRY32W pe = { sizeof(pe) };
    DWORD pid = 0;
    for (BOOL ok = Process32FirstW(snap, &pe); ok; ok = Process32NextW(snap, &pe))
        if (_wcsicmp(pe.szExeFile, exe) == 0) { pid = pe.th32ProcessID; break; }
    CloseHandle(snap);
    return pid;
}

static bool HasModule(HANDLE proc, const wchar_t* name)
{
    HMODULE mods[1024]; DWORD need = 0;
    if (!EnumProcessModulesEx(proc, mods, sizeof(mods), &need, LIST_MODULES_64BIT)) return false;
    for (DWORD i = 0; i < need / sizeof(HMODULE); ++i) {
        wchar_t n[MAX_PATH];
        if (GetModuleBaseNameW(proc, mods[i], n, MAX_PATH) && _wcsicmp(n, name) == 0) return true;
    }
    return false;
}

// Gra uruchomiona z terminala w tle potrafi stać na czarnym ekranie bez fokusu i nie ładuje DLL moda
// (zaobserwowane 2026-10-17). Wyciągamy jej widoczne okno na wierzch (Alt pozwala zmienić okno pierwszoplanowe).
static void BringToFront(DWORD pid)
{
    struct Ctx { DWORD pid; HWND h; } c = { pid, nullptr };
    EnumWindows([](HWND h, LPARAM l) -> BOOL {
        auto c = (Ctx*)l; DWORD p = 0; GetWindowThreadProcessId(h, &p);
        if (p == c->pid && IsWindowVisible(h)) { c->h = h; return FALSE; }
        return TRUE;
    }, (LPARAM)&c);
    if (!c.h || GetForegroundWindow() == c.h) return;
    keybd_event(VK_MENU, 0, 0, 0);
    SetForegroundWindow(c.h);
    keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0);
}

static bool Inject(HANDLE proc, const std::wstring& dll)
{
    size_t bytes = (dll.size() + 1) * sizeof(wchar_t);
    void* mem = VirtualAllocEx(proc, nullptr, bytes, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!mem || !WriteProcessMemory(proc, mem, dll.c_str(), bytes, nullptr)) return false;
    auto loadLib = (LPTHREAD_START_ROUTINE)GetProcAddress(GetModuleHandleW(L"kernel32.dll"), "LoadLibraryW");
    HANDLE th = CreateRemoteThread(proc, nullptr, 0, loadLib, mem, 0, nullptr);
    if (!th) return false;
    WaitForSingleObject(th, 15000);
    DWORD code = 0; GetExitCodeThread(th, &code); // młodsze 32 bity HMODULE; 0 = błąd
    CloseHandle(th);
    VirtualFreeEx(proc, mem, 0, MEM_RELEASE);
    return code != 0;
}

// Folder gry ze Steam (działa też, gdy gra stoi w innej bibliotece niż domyślna):
// HKCU\Software\Valve\Steam\SteamPath -> steamapps\libraryfolders.vdf -> biblioteka ("path") zawierająca
// aplikację 3556750 (DoW: Definitive Edition) -> <path>\steamapps\common\Dawn of War Definitive Edition.
static bool HasGame(const std::wstring& dir)
{
    return GetFileAttributesW((dir + L"\\W40k.exe").c_str()) != INVALID_FILE_ATTRIBUTES;
}

static std::wstring FindGameDir()
{
    static const wchar_t* kSub = L"\\steamapps\\common\\Dawn of War Definitive Edition";
    wchar_t steam[MAX_PATH]; DWORD size = sizeof(steam);
    if (RegGetValueW(HKEY_CURRENT_USER, L"Software\\Valve\\Steam", L"SteamPath", RRF_RT_REG_SZ, nullptr, steam, &size)
        == ERROR_SUCCESS) {
        FILE* f = nullptr;
        if (_wfopen_s(&f, (std::wstring(steam) + L"\\steamapps\\libraryfolders.vdf").c_str(), L"rb") == 0 && f) {
            char line[1024];
            std::string lib;
            std::vector<std::string> libs;
            while (fgets(line, sizeof(line), f)) {
                std::string l = line;
                size_t p = l.find("\"path\"");
                if (p != std::string::npos) {               // "path"  "C:\\Program Files (x86)\\Steam"
                    size_t a = l.find('"', p + 6), b = l.rfind('"');
                    lib.clear();
                    for (size_t i = a + 1; a != std::string::npos && i < b; ++i)
                        if (!(l[i] == '\\' && i + 1 < b && l[i + 1] == '\\')) lib += l[i];
                    libs.push_back(lib);
                } else if (l.find("\"3556750\"") != std::string::npos && !lib.empty()) {
                    std::wstring dir(lib.begin(), lib.end());
                    if (HasGame(dir + kSub)) { fclose(f); return dir + kSub; }
                }
            }
            fclose(f);
            for (auto& s : libs) {                          // zapas: każda biblioteka po kolei
                std::wstring dir(s.begin(), s.end());
                if (HasGame(dir + kSub)) return dir + kSub;
            }
        }
    }
    return kDefaultGameDir;
}

// ---------------------------------------------------------------- język komunikatów (pl / en / ru)
// Jak w podglądzie: "lang" z settings.json (paczka: <folder launchera>\..\settings.json), inaczej język Windows.
static int g_lang = 1;  // 0 pl, 1 en, 2 ru

static void DetectLanguage(const std::wstring& dir)
{
    LANGID ui = GetUserDefaultUILanguage() & 0x3FF;
    g_lang = ui == 0x15 ? 0 : ui == 0x19 ? 2 : 1;
    FILE* f = nullptr;
    if (_wfopen_s(&f, (dir + L"\\..\\settings.json").c_str(), L"rb") == 0 && f) {
        char buf[4096] = {0};
        fread(buf, 1, sizeof(buf) - 1, f);
        fclose(f);
        if (strstr(buf, "\"lang\": \"pl\"")) g_lang = 0;
        else if (strstr(buf, "\"lang\": \"en\"")) g_lang = 1;
        else if (strstr(buf, "\"lang\": \"ru\"")) g_lang = 2;
    }
}

static const wchar_t* T(const wchar_t* pl, const wchar_t* en, const wchar_t* ru)
{
    return g_lang == 0 ? pl : g_lang == 2 ? ru : en;
}

// v2.1: podłączenie rejestratora do gry, która już działa (np. uruchomionej przez Steam). Gra nie ma zmiennych
// środowiskowych launchera, więc ustawienia (folder nagrań, dziennik) zapisujemy w <folder DLL>\dowrec.cfg – DLL
// czyta go przy wczytaniu i usuwa. Bezpiecznik bez zmian: rejestrator włącza się dopiero po otwarciu powtórki,
// więc jeśli powtórka już trwa, trzeba wyjść do menu i włączyć ją ponownie.
static int Attach(DWORD pid, const std::wstring& dll, const wchar_t* recDir, const wchar_t* logPath,
                  const std::wstring& ecoPath)
{
    HANDLE proc = OpenProcess(PROCESS_CREATE_THREAD | PROCESS_QUERY_INFORMATION | PROCESS_VM_OPERATION |
                              PROCESS_VM_WRITE | PROCESS_VM_READ | SYNCHRONIZE, FALSE, pid);
    if (!proc) {
        wprintf(T(L"Nie można podłączyć się do działającej gry (błąd %lu).\n",
                  L"Cannot attach to the running game (error %lu).\n",
                  L"Не удалось подключиться к запущенной игре (ошибка %lu).\n"), GetLastError());
        return 3;
    }
    if (HasModule(proc, L"dowrec.dll")) {
        wprintf(T(L"Rejestrator jest już podłączony do gry. W grze: Powtórki -> wybierz powtórkę -> Odtwórz.\n",
                  L"The recorder is already attached. In the game: Replays -> choose a replay -> Play.\n",
                  L"Регистратор уже подключён. В игре: Реплеи -> выберите реплей -> Воспроизвести.\n"));
        CloseHandle(proc);
        return 0;
    }
    wprintf(T(L"Gra już działa – podłączam rejestrator...\n", L"The game is already running – attaching the recorder...\n",
              L"Игра уже запущена – подключаю регистратор...\n"));
    static const wchar_t* mods[] = { L"DXP3Mod.dll", L"DXP2Mod.dll", L"WXPMod.dll", L"W40kMod.dll" };
    bool ready = false;
    while (!ready) {  // gra mogła dopiero startować – czekamy na DLL moda jak przy zwykłym uruchomieniu
        for (const wchar_t* m : mods) if (HasModule(proc, m)) { ready = true; break; }
        if (!ready && WaitForSingleObject(proc, 500) == WAIT_OBJECT_0) {
            wprintf(T(L"Gra została zamknięta.\n", L"The game was closed.\n", L"Игра была закрыта.\n"));
            CloseHandle(proc);
            return 2;
        }
    }
    std::wstring cfg = dll.substr(0, dll.find_last_of(L'\\')) + L"\\dowrec.cfg";
    FILE* f = nullptr;
    if (_wfopen_s(&f, cfg.c_str(), L"w, ccs=UTF-16LE") == 0 && f) {
        fwprintf(f, L"OUT=%ls\nLOG=%ls\n", recDir, logPath);
        if (!ecoPath.empty()) fwprintf(f, L"ECO=%ls\n", ecoPath.c_str());
        fclose(f);
    }
    bool ok = Inject(proc, dll);
    DeleteFileW(cfg.c_str());  // DLL usuwa go sama; tu na wypadek nieudanego wczytania
    CloseHandle(proc);
    if (ok)
        wprintf(T(L"Gotowe. W grze: Powtórki -> wybierz powtórkę -> Odtwórz.\n"
                  L"Jeśli powtórka już trwa – wyjdź do menu i włącz ją ponownie (rejestrator startuje przy otwarciu powtórki).\n",
                  L"Ready. In the game: Replays -> choose a replay -> Play.\n"
                  L"If a replay is already playing, return to the menu and start it again (the recorder starts when a replay is opened).\n",
                  L"Готово. В игре: Реплеи -> выберите реплей -> Воспроизвести.\n"
                  L"Если реплей уже идёт – вернитесь в меню и запустите его снова (регистратор включается при открытии реплея).\n"));
    else
        wprintf(T(L"Wczytanie rejestratora NIE powiodło się (błąd %lu).\n", L"Loading the recorder FAILED (error %lu).\n",
                  L"Не удалось загрузить регистратор (ошибка %lu).\n"), GetLastError());
    return ok ? 0 : 3;
}

int wmain(int argc, wchar_t** argv)
{
    // dowprobe_launcher.exe [--rec] [--eco] [--out <folder nagrań>] [--logs <folder dzienników>] [--check] [--where] [folder_gry]
    //   --eco    jak --rec + sonda ekonomii (zrzuty pamięci obiektów graczy co 5 s, analysis/eco_scan.py)
    //   --check  tylko sprawdź: gra znaleziona (kod 0; działająca gra nie jest błędem – Attach) – komunikat w języku użytkownika (Start.bat)
    // polskie znaki i cyrylica: w konsoli UTF-16 (WriteConsoleW), przy przekierowaniu do pliku/potoku UTF-8
    _setmode(_fileno(stdout), GetFileType(GetStdHandle(STD_OUTPUT_HANDLE)) == FILE_TYPE_CHAR ? _O_U16TEXT : _O_U8TEXT);
    bool rec = false, check = false, where = false, eco = false;
    std::wstring game, outArg, logsArg;
    for (int i = 1; i < argc; ++i) {
        if (_wcsicmp(argv[i], L"--rec") == 0) rec = true;
        else if (_wcsicmp(argv[i], L"--check") == 0) check = true;
        else if (_wcsicmp(argv[i], L"--where") == 0) where = true;
        else if (_wcsicmp(argv[i], L"--eco") == 0) eco = rec = true;  // sonda ekonomii (zrzuty pamięci graczy)
        else if (_wcsicmp(argv[i], L"--out") == 0 && i + 1 < argc) outArg = argv[++i];
        else if (_wcsicmp(argv[i], L"--logs") == 0 && i + 1 < argc) logsArg = argv[++i];
        else game = argv[i];
    }
    wchar_t self[MAX_PATH]; GetModuleFileNameW(nullptr, self, MAX_PATH);
    std::wstring dir = self; dir = dir.substr(0, dir.find_last_of(L'\\'));
    DetectLanguage(dir);

    if (game.empty()) game = FindGameDir();
    if (where) {  // diagnostyka: tylko wypisz znaleziony folder gry
        wprintf(L"%ls\n%ls\n", game.c_str(), HasGame(game) ? L"OK" : L"W40k.exe ?");
        return HasGame(game) ? 0 : 1;
    }
    std::wstring exe = game + L"\\W40k.exe";
    std::wstring dll = dir + (rec ? L"\\dowrec.dll" : L"\\dowprobe.dll");

    if (!HasGame(game)) {
        wprintf(T(L"Nie znaleziono Dawn of War: Definitive Edition w bibliotekach Steam.\nUpewnij się, że gra jest zainstalowana przez Steam.\n",
                  L"Dawn of War: Definitive Edition was not found in your Steam libraries.\nMake sure the game is installed through Steam.\n",
                  L"Dawn of War: Definitive Edition не найдена в библиотеках Steam.\nУбедитесь, что игра установлена через Steam.\n"));
        return 1;
    }
    // v2.1: działająca gra (np. uruchomiona przez Steam) nie jest błędem – rejestrator podłączamy do niej (Attach)
    DWORD runningPid = FindProcess(L"W40k.exe");
    if (check) return 0;
    if (runningPid && !rec) {
        wprintf(T(L"Gra już działa. Zamknij Dawn of War i uruchom ponownie.\n",
                  L"The game is already running. Close Dawn of War and try again.\n",
                  L"Игра уже запущена. Закройте Dawn of War и попробуйте снова.\n"));
        return 1;
    }
    if (GetFileAttributesW(dll.c_str()) == INVALID_FILE_ATTRIBUTES) { wprintf(L"%ls: %ls\n", T(L"Brak", L"Missing", L"Нет файла"), dll.c_str()); return 1; }

    // log: --logs albo <folder launchera>\..\logs\probe_YYYYMMDD_HHMMSS.log
    std::wstring logs = logsArg.empty() ? dir + L"\\..\\logs" : logsArg;
    CreateDirectoryW(logs.c_str(), nullptr);
    SYSTEMTIME st; GetLocalTime(&st);
    wchar_t name[64];
    swprintf_s(name, L"\\%ls_%04d%02d%02d_%02d%02d%02d.log", rec ? L"rec" : L"probe", st.wYear, st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond);
    wchar_t full[MAX_PATH]; GetFullPathNameW((logs + name).c_str(), MAX_PATH, full, nullptr);

    SetEnvironmentVariableW(L"DOWPROBE_LAUNCHER", L"1");
    SetEnvironmentVariableW(L"DOWPROBE_LOG", full);
    wchar_t recDir[MAX_PATH] = L"";
    if (rec) {
        GetFullPathNameW((outArg.empty() ? dir + L"\\..\\..\\recordings" : outArg).c_str(), MAX_PATH, recDir, nullptr);
        CreateDirectoryW(recDir, nullptr);
        SetEnvironmentVariableW(L"DOWREC_OUT", recDir);
    }
    std::wstring ecoName;
    if (eco) {  // --eco: rejestrator dodatkowo zrzuca co 5 s pamięć obiektów graczy do <dzienniki>\eco_<data>.bin
        // name = "\rec_YYYYMMDD_HHMMSS.log" -> "\eco_YYYYMMDD_HHMMSS.bin" w tym samym folderze co dziennik
        ecoName = full;
        ecoName = ecoName.substr(0, ecoName.find_last_of(L'\\')) + L"\\eco" + (name + 4);
        ecoName = ecoName.substr(0, ecoName.size() - 4) + L".bin";
        SetEnvironmentVariableW(L"DOWREC_ECO", ecoName.c_str());
        wprintf(L"ECO: %ls\n", ecoName.c_str());
    }

    wprintf(T(L"UWAGA: tylko do oglądania powtórek. Do gry sieciowej/rankingowej uruchamiaj grę normalnie przez Steam.\n\n",
              L"NOTE: for watching replays only. For online/ranked games start the game normally through Steam.\n\n",
              L"ВНИМАНИЕ: только для просмотра реплеев. Для сетевой/рейтинговой игры запускайте игру через Steam.\n\n"));
    wprintf(L"%ls: %ls\nDLL: %ls\nLog: %ls\n", T(L"Gra", L"Game", L"Игра"), exe.c_str(), dll.c_str(), full);
    if (rec) wprintf(L"%ls: %ls\n", T(L"Nagrania", L"Recordings", L"Записи"), recDir);
    wprintf(L"\n");
    if (runningPid) return Attach(runningPid, dll, recDir, full, ecoName);

    STARTUPINFOW si = { sizeof(si) };
    PROCESS_INFORMATION pi = {};
    std::wstring cmd = L"\"" + exe + L"\"";
    if (!CreateProcessW(exe.c_str(), cmd.data(), nullptr, nullptr, FALSE, 0, nullptr, game.c_str(), &si, &pi)) {
        wprintf(L"CreateProcess: %ls %lu\n", T(L"błąd", L"error", L"ошибка"), GetLastError()); return 1;
    }
    wprintf(T(L"Gra uruchomiona. Czekam na menu główne (jeśli ekran jest czarny – kliknij okno gry)...\n",
              L"Game started. Waiting for the main menu (if the screen stays black, click the game window)...\n",
              L"Игра запущена. Ожидание главного меню (если экран чёрный – щёлкните окно игры)...\n"));

    // Wstrzykujemy dopiero, gdy załadowana jest DLL moda. Wstrzyknięcie w trakcie ładowania statycznych DLL
    // (np. zaraz po SimEngine.dll) zatrzymywało start gry (test 2026-10-17). Czekamy bez limitu czasu.
    static const wchar_t* mods[] = { L"DXP3Mod.dll", L"DXP2Mod.dll", L"WXPMod.dll", L"W40kMod.dll" };
    bool ready = false;
    for (int iter = 0; !ready; ++iter) {
        if (iter % 4 == 0) BringToFront(pi.dwProcessId);
        if (WaitForSingleObject(pi.hProcess, 500) == WAIT_OBJECT_0) break;
        for (const wchar_t* m : mods) if (HasModule(pi.hProcess, m)) { ready = true; wprintf(L"%ls: %ls\n", T(L"Wykryto", L"Detected", L"Обнаружено"), m); break; }
    }
    if (ready) Sleep(1000); // niech mod dokończy inicjalizację
    if (!ready) {
        DWORD ec = 0; GetExitCodeProcess(pi.hProcess, &ec);
        wprintf(T(L"Gra zakończyła się przed załadowaniem menu (kod %lu) – rejestrator nie został wczytany.\n",
                  L"The game exited before reaching the menu (code %lu) – the recorder was not loaded.\n",
                  L"Игра завершилась до главного меню (код %lu) – регистратор не загружен.\n"), ec);
        return 2;
    }
    bool ok = Inject(pi.hProcess, dll);
    if (ok)
        wprintf(T(L"Gotowe. W grze: Powtórki -> wybierz powtórkę -> Odtwórz.\n",
                  L"Ready. In the game: Replays -> choose a replay -> Play.\n",
                  L"Готово. В игре: Реплеи -> выберите реплей -> Воспроизвести.\n"));
    else
        wprintf(T(L"Wczytanie rejestratora NIE powiodło się (błąd %lu).\n", L"Loading the recorder FAILED (error %lu).\n",
                  L"Не удалось загрузить регистратор (ошибка %lu).\n"), GetLastError());
    CloseHandle(pi.hThread); CloseHandle(pi.hProcess);
    return ok ? 0 : 3;
}
