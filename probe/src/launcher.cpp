// dowprobe_launcher.exe – uruchamia Dawn of War: DE z sondą dowprobe.dll albo rejestratorem dowrec.dll
// (tylko do powtórek offline).
//
// Użycie: dowprobe_launcher.exe [--rec] [--out <nagrania>] [--logs <dzienniki>] [folder_gry]
//   folder gry domyślnie z bibliotek Steam (libraryfolders.vdf, aplikacja 3556750), inaczej domyślna ścieżka
//   --rec  ładuje dowrec.dll zamiast sondy i ustawia DOWREC_OUT=<projekt>\recordings
// - nie modyfikuje plików gry,
// - odmawia startu, jeśli W40k.exe już działa,
// - ustawia DOWPROBE_LAUNCHER=1 i DOWPROBE_LOG=<ścieżka> (bez tego DLL nic nie robi),
// - po załadowaniu DLL moda (W40kMod/WXPMod/DXP2Mod/DXP3Mod) wstrzykuje dowprobe.dll przez CreateRemoteThread(LoadLibraryW).

#include <windows.h>
#include <psapi.h>
#include <tlhelp32.h>
#include <stdio.h>
#include <string>
#include <vector>

static const wchar_t* kDefaultGameDir = L"C:\\Program Files (x86)\\Steam\\steamapps\\common\\Dawn of War Definitive Edition";

static bool IsRunning(const wchar_t* exe)
{
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    PROCESSENTRY32W pe = { sizeof(pe) };
    bool found = false;
    for (BOOL ok = Process32FirstW(snap, &pe); ok; ok = Process32NextW(snap, &pe))
        if (_wcsicmp(pe.szExeFile, exe) == 0) { found = true; break; }
    CloseHandle(snap);
    return found;
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

int wmain(int argc, wchar_t** argv)
{
    // dowprobe_launcher.exe [--rec] [--out <folder nagrań>] [--logs <folder dzienników>] [folder_gry]
    bool rec = false;
    std::wstring game, outArg, logsArg;
    for (int i = 1; i < argc; ++i) {
        if (_wcsicmp(argv[i], L"--rec") == 0) rec = true;
        else if (_wcsicmp(argv[i], L"--out") == 0 && i + 1 < argc) outArg = argv[++i];
        else if (_wcsicmp(argv[i], L"--logs") == 0 && i + 1 < argc) logsArg = argv[++i];
        else if (_wcsicmp(argv[i], L"--where") != 0) game = argv[i];
    }
    if (game.empty()) game = FindGameDir();
    for (int i = 1; i < argc; ++i)
        if (_wcsicmp(argv[i], L"--where") == 0) {  // diagnostyka: tylko wypisz znaleziony folder gry
            wprintf(L"%ls\n%ls\n", game.c_str(), HasGame(game) ? L"OK" : L"BRAK W40k.exe");
            return HasGame(game) ? 0 : 1;
        }
    std::wstring exe = game + L"\\W40k.exe";

    wchar_t self[MAX_PATH]; GetModuleFileNameW(nullptr, self, MAX_PATH);
    std::wstring dir = self; dir = dir.substr(0, dir.find_last_of(L'\\'));
    std::wstring dll = dir + (rec ? L"\\dowrec.dll" : L"\\dowprobe.dll");

    if (GetFileAttributesW(exe.c_str()) == INVALID_FILE_ATTRIBUTES) { wprintf(L"Brak %ls\n", exe.c_str()); return 1; }
    if (GetFileAttributesW(dll.c_str()) == INVALID_FILE_ATTRIBUTES) { wprintf(L"Brak %ls\n", dll.c_str()); return 1; }
    if (IsRunning(L"W40k.exe")) { wprintf(L"W40k.exe juz dziala - zamknij gre i uruchom launcher ponownie.\n"); return 1; }

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

    wprintf(L"UWAGA: sonda jest przeznaczona TYLKO do ogladania powtorek offline.\n"
            L"       Nie wchodz w tej sesji gry do rozgrywek online/rankingowych.\n\n");
    wprintf(L"Gra: %ls\nDLL: %ls\nLog: %ls\n", exe.c_str(), dll.c_str(), full);
    if (rec) wprintf(L"Zapisy: %ls\n", recDir);
    wprintf(L"\n");

    STARTUPINFOW si = { sizeof(si) };
    PROCESS_INFORMATION pi = {};
    std::wstring cmd = L"\"" + exe + L"\"";
    if (!CreateProcessW(exe.c_str(), cmd.data(), nullptr, nullptr, FALSE, 0, nullptr, game.c_str(), &si, &pi)) {
        wprintf(L"CreateProcess nie powiodl sie (blad %lu)\n", GetLastError()); return 1;
    }
    wprintf(L"Gra uruchomiona (pid %lu). Czekam na DLL moda - przejdz w grze do menu glownego...\n", pi.dwProcessId);

    // Wstrzykujemy dopiero, gdy załadowana jest DLL moda. Wstrzyknięcie w trakcie ładowania statycznych DLL
    // (np. zaraz po SimEngine.dll) zatrzymywało start gry (test 2026-10-17). Czekamy bez limitu czasu.
    static const wchar_t* mods[] = { L"DXP3Mod.dll", L"DXP2Mod.dll", L"WXPMod.dll", L"W40kMod.dll" };
    bool ready = false;
    for (int iter = 0; !ready; ++iter) {
        if (iter % 4 == 0) BringToFront(pi.dwProcessId);
        if (WaitForSingleObject(pi.hProcess, 500) == WAIT_OBJECT_0) break;
        for (const wchar_t* m : mods) if (HasModule(pi.hProcess, m)) { ready = true; wprintf(L"Wykryto %ls.\n", m); break; }
    }
    if (ready) Sleep(1000); // niech mod dokończy inicjalizację
    if (!ready) {
        DWORD ec = 0; GetExitCodeProcess(pi.hProcess, &ec);
        wprintf(L"Gra zakonczyla sie przed zaladowaniem moda (proces %ls, kod %lu). Jesli gra wystartowala przez Steam jako nowy proces,\n"
                L"sonda nie zostala wstrzyknieta - zgłoś to.\n", ec == STILL_ACTIVE ? L"dziala" : L"zakonczony", ec);
        return 2;
    }
    bool ok = Inject(pi.hProcess, dll);
    wprintf(ok ? L"Sonda wstrzyknieta. Mozesz otworzyc powtorke w grze.\n" : L"Wstrzykniecie NIE powiodlo sie (blad %lu).\n", GetLastError());
    CloseHandle(pi.hThread); CloseHandle(pi.hProcess);
    return ok ? 0 : 3;
}
