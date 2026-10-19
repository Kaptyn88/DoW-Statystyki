// dowrec.dll – rejestrator zdarzeń walki dla Dawn of War: Definitive Edition (tylko do powtórek offline).
//
// Na podstawie ustaleń sondy (NOTES.md):
//   ApplyDamage(rcx=ofiara Entity*, rdx=atakujący Entity*, r8, r9=WeaponInfo*, f5, b6) -> xmm0 = nominalne obrażenia
//   SetHealth(HealthExt*, nowe HP)  – faktyczna strata HP (wewnątrz ApplyDamage)
//   Death(HealthExt*, flaga)        – zgon modelu
//   Entity* = [[HealthExt+8]+0x10]; nazwa broni = *(char**)[WeaponInfo+8]; ID broni = [WeaponInfo+0x10]
//
// Wynik: <DOWREC_OUT>\<nazwa powtórki>_<data>.jsonl, jedna sesja na każde odtworzenie powtórki.
// Rekordy (pole "t" = typ):
//   meta   {replay, mod, tps}                          – początek sesji (tps = ticki na sekundę)
//   player {pid, name}                                 – gracz przy pierwszym wystąpieniu
//   ent    {id, bp, sq, sqbp, pid}                     – encja przy pierwszym wystąpieniu i przy zmianie oddziału
//   wpn    {wid, name, melee}                          – broń przy pierwszym użyciu
//   dmg    {tick, a, as, v, vs, w, hp, nom, k, ff}     – skuteczne ApplyDamage: atakujący/ofiara (id, oddział),
//          broń (wid, -1 = bez WeaponInfo), hp = faktyczna strata HP, nom = nominalne obrażenia, k = zabity model ofiary,
//          ff = friendly fire (ten sam gracz)
//   die    {tick, v, vs, by}                           – zgon spoza ApplyDamage (by = 0) lub innej encji niż ofiara
//   clock  {tick}                                      – co ~1 s czasu rzeczywistego: bieżący tick powtórki
//   sel    {tick, sq:[id oddziałów], e:[id encji]}     – zaznaczenie gracza w grze (przy zmianie, odczyt co ~0,1 s)
//   hp     {tick, v, vs, hp, src}                      – spadek HP poza ApplyDamage (atakujący nieznany; src = ścieżka kodu)
//   eco    {tick, pid, req, pow, ir, ip}               – co ~1 s: stan rekwizycji/energii gracza i dochód na tick (DXP3)
//   res    {tick, pid, name}                           – ukończone badanie (ulepszenie) gracza, nazwa pliku z attrib/research
//   dmg bez broni (w=-1) ma dodatkowo src (ścieżka kodu), ab/abf (nazwa pliku i folder danych gry źródła, np.
//          eldar_psychic_storm / abilities – hipoteza, zob. SourcePath) i abo (odległość ścieżki od r8, -1 = brak);
//          gdy abo=-1: sw = ostatnia broń wręcz atakującego (heurystyka: atak specjalny wręcz)
//
// Bezpiecznik jak w sondzie: rejestruje tylko po otwarciu *.rec do odczytu, wyłącza się po zapisie *.rec bez
// wcześniejszego odczytu (gra na żywo). DLL nic nie robi bez DOWPROBE_LAUNCHER=1 (ustawia launcher).

#include <windows.h>
#include <winternl.h>
#include <stdio.h>
#include <share.h>
#include <stdint.h>
#include <string.h>
#include <wchar.h>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include "MinHook.h"

// ---------------------------------------------------------------- stan globalny
static FILE*        g_log;                       // dziennik diagnostyczny rejestratora
static FILE*        g_out;                       // bieżąca sesja .jsonl
static SRWLOCK      g_lock = SRWLOCK_INIT;       // chroni g_out i stan sesji
static SRWLOCK      g_logLock = SRWLOCK_INIT;    // chroni g_log (osobno: Log() bywa wołane pod g_lock)
static wchar_t      g_outDir[MAX_PATH];
static uintptr_t    g_modBase, g_modSize;
static const wchar_t* g_modName;
static void**       g_worldGlobal;
static void*        g_tSetHealth, *g_tDeath, *g_tApplyDamage;
static volatile LONG g_armed;
static HANDLE       g_armEvent;

// sesja
static wchar_t      g_replayName[MAX_PATH];      // ostatnio otwarta do odczytu powtórka
static wchar_t      g_sessionReplay[MAX_PATH];   // powtórka bieżącej sesji
static int          g_lastTick = -1;
static long long    g_cntDmg, g_cntDie;

// ---------------------------------------------------------------- pomiar narzutu (PERF w dzienniku co 10 s)
// Liczony jest tylko czas NASZEGO kodu w hookach (bez czasu oryginalnych funkcji gry) – w wątku gry.
static volatile LONG64 g_perfTicks, g_perfCalls, g_perfMax, g_selTicks;

static inline LONG64 Qpc()
{
    LARGE_INTEGER t; QueryPerformanceCounter(&t); return t.QuadPart;
}

static inline void PerfAdd(LONG64 dt)
{
    InterlockedAdd64(&g_perfTicks, dt);
    InterlockedIncrement64(&g_perfCalls);
    if (dt > g_perfMax) g_perfMax = dt;  // przybliżone maksimum (hooki działają praktycznie w jednym wątku)
}
static std::unordered_map<unsigned long, unsigned long>* g_entSquad; // id encji -> ostatni zapisany oddział
static std::unordered_set<unsigned long>* g_players;
static std::unordered_map<unsigned long, uintptr_t>* g_playerObj;  // pid -> obiekt gracza (sonda ekonomii, pod g_lock)
static std::unordered_set<int>* g_weapons;
static std::unordered_map<unsigned long, int>* g_lastMelee; // id encji -> ostatnia broń wręcz (do ataków specjalnych)

// eksporty SimEngine.dll
typedef const char*    (*FnGetBp)(const void*);
typedef unsigned long  (*FnGetId)(const void*);
typedef void*          (*FnGetPtr)(void*);
typedef int            (*FnWorldTicks)(const void*);
typedef const wchar_t* (*FnPlayerName)(const void*);
static FnGetBp  pEntGetBp, pSquadGetBp;
static FnGetId  pEntGetId, pSquadGetId, pPlayerGetId;
static FnGetPtr pEntGetSquad, pEntGetOwner;
static FnWorldTicks pWorldTicks;
typedef void*          (*FnPlayerFromId)(void*, unsigned long);
static FnPlayerFromId pPlayerFromId;   // World::GetPlayerFromID (sonda ekonomii: gracze od pierwszej sekundy)
static FnPlayerName pPlayerName;

// oryginały (konwencja x64 MS, zob. sonda)
typedef void  (*FnSetHealth)(void* self, float value);
typedef void  (*FnDeath)(void* self, uint64_t flag);
typedef float (*FnApplyDamage)(void* victim, void* attacker, void* r8, void* r9, float f5, uint64_t b6);
typedef NTSTATUS (NTAPI* FnNtCreateFile)(PHANDLE, ACCESS_MASK, POBJECT_ATTRIBUTES, PIO_STATUS_BLOCK, PLARGE_INTEGER,
                                         ULONG, ULONG, ULONG, ULONG, PVOID, ULONG);
static FnSetHealth    oSetHealth;
static FnDeath        oDeath;
static FnApplyDamage  oApplyDamage;
static FnNtCreateFile oNtCreateFile;

// ---------------------------------------------------------------- dziennik
static void Log(const char* fmt, ...)
{
    if (!g_log) return;
    va_list ap; va_start(ap, fmt);
    AcquireSRWLockExclusive(&g_logLock);
    vfprintf(g_log, fmt, ap);
    ReleaseSRWLockExclusive(&g_logLock);
    va_end(ap);
}

// ---------------------------------------------------------------- bezpieczne odczyty
static bool SafeReadPtr(const void* p, uintptr_t* out)
{
    __try { *out = *(const uintptr_t*)p; return true; }
    __except (EXCEPTION_EXECUTE_HANDLER) { return false; }
}

// kopiuje napis jako bezpieczną zawartość JSON (bez cudzysłowów, ukośników i znaków sterujących)
static void SafeJsonStr(const char* s, char* out, size_t cap)
{
    out[0] = 0;
    if (!s) return;
    __try {
        size_t i = 0;
        for (; i + 1 < cap && s[i]; ++i) {
            char c = s[i];
            out[i] = (c < 32 || c > 126 || c == '"' || c == '\\') ? '_' : c;
        }
        out[i] = 0;
    } __except (EXCEPTION_EXECUTE_HANDLER) { out[0] = 0; }
}

// bp/sqbp to wskaźniki do nazw w blueprintach (trwałe), zbierane razem z resztą przed ApplyDamage
struct Ent { uintptr_t p; unsigned long id, sq, pid; uintptr_t owner; const char* bp; const char* sqbp; bool ok; };

static void QueryEnt(void* ent, Ent* e)
{
    memset(e, 0, sizeof(*e));
    e->p = (uintptr_t)ent;
    if (!ent) return;
    __try {
        e->id = pEntGetId(ent);
        void* sq = pEntGetSquad(ent);
        e->sq = sq ? pSquadGetId(sq) : 0;
        e->bp = pEntGetBp(ent);
        e->sqbp = sq ? pSquadGetBp(sq) : nullptr;
        e->owner = (uintptr_t)pEntGetOwner(ent);
        e->pid = e->owner && pPlayerGetId ? pPlayerGetId((void*)e->owner) : 0;
        e->ok = true;
    } __except (EXCEPTION_EXECUTE_HANDLER) { e->ok = false; }
}

static uintptr_t EntityFromHealthExt(void* hx)
{
    uintptr_t a = 0, ent = 0;
    if (!SafeReadPtr((char*)hx + 8, &a) || !a) return 0;
    if (!SafeReadPtr((char*)a + 0x10, &ent)) return 0;
    return ent;
}

static int GameTicks()
{
    uintptr_t w = 0;
    if (!g_worldGlobal || !SafeReadPtr(g_worldGlobal, &w) || !w || !pWorldTicks) return -1;
    __try { return pWorldTicks((void*)w); } __except (EXCEPTION_EXECUTE_HANDLER) { return -1; }
}

static float ReadHealth(void* hx)
{
    __try { return *(float*)((char*)hx + 0x28) * *(float*)((char*)hx + 0x2c); }
    __except (EXCEPTION_EXECUTE_HANDLER) { return 0.f; }
}

static void WeaponInfoOf(void* wi, int* wid, char* name, size_t cap, bool* melee)
{
    *wid = -1; name[0] = 0; *melee = false;
    if (!wi) return;
    __try {
        *wid = *(int*)((char*)wi + 0x10);
        uintptr_t p = *(uintptr_t*)((char*)wi + 8);
        if (p) SafeJsonStr(*(const char**)p, name, cap);
        // std::string pod +0xe0: 'Melee' dla broni wręcz (dane inline, bo krótki napis)
        size_t size = *(size_t*)((char*)wi + 0xe0 + 0x10);
        *melee = size == 5 && memcmp((char*)wi + 0xe0, "Melee", 5) == 0;
    } __except (EXCEPTION_EXECUTE_HANDLER) {}
}

// ---------------------------------------------------------------- zapis sesji (wołać pod g_lock)
static void Out(const char* fmt, ...)
{
    if (!g_out) return;
    va_list ap; va_start(ap, fmt);
    vfprintf(g_out, fmt, ap);
    va_end(ap);
}

static void CloseSession()
{
    if (!g_out) return;
    fclose(g_out); g_out = nullptr;
    Log("SESSION closed dmg=%lld die=%lld lastTick=%d\n", g_cntDmg, g_cntDie, g_lastTick);
}

// otwiera nową sesję, gdy: brak sesji, inna powtórka, albo czas cofnął się (ponowne odtworzenie)
static void EnsureSession(int tick)
{
    if (g_out && wcscmp(g_sessionReplay, g_replayName) == 0 && tick >= g_lastTick) { g_lastTick = tick; return; }
    CloseSession();
    wcscpy_s(g_sessionReplay, g_replayName);
    g_lastTick = tick; g_cntDmg = g_cntDie = 0;
    g_entSquad->clear(); g_players->clear(); g_weapons->clear(); g_lastMelee->clear();
    if (g_playerObj) g_playerObj->clear();

    wchar_t base[MAX_PATH]; wcscpy_s(base, g_sessionReplay[0] ? g_sessionReplay : L"unknown");
    for (wchar_t* c = base; *c; ++c) if (wcschr(L"#<>:\"/\\|?* ", *c)) *c = L'_';
    size_t n = wcslen(base);
    if (n > 4 && _wcsicmp(base + n - 4, L".rec") == 0) base[n - 4] = 0;
    SYSTEMTIME st; GetLocalTime(&st);
    wchar_t path[MAX_PATH];
    swprintf_s(path, L"%s\\%s_%04d%02d%02d_%02d%02d%02d.jsonl", g_outDir, base, st.wYear, st.wMonth, st.wDay,
               st.wHour, st.wMinute, st.wSecond);
    g_out = _wfsopen(path, L"wb", _SH_DENYWR);
    if (!g_out) return;
    setvbuf(g_out, nullptr, _IOFBF, 1 << 16);
    char rep[MAX_PATH * 3] = "", mod[64] = "";
    WideCharToMultiByte(CP_UTF8, 0, g_sessionReplay, -1, rep, sizeof(rep), nullptr, nullptr);
    WideCharToMultiByte(CP_UTF8, 0, g_modName, -1, mod, sizeof(mod), nullptr, nullptr);
    char repJ[sizeof(rep)]; SafeJsonStr(rep, repJ, sizeof(repJ));
    Out("{\"t\":\"meta\",\"v\":1,\"replay\":\"%s\",\"mod\":\"%s\",\"tps\":8,\"tick\":%d}\n", repJ, mod, tick);
    char pathU8[MAX_PATH * 3]; WideCharToMultiByte(CP_UTF8, 0, path, -1, pathU8, sizeof(pathU8), nullptr, nullptr);
    Log("SESSION open %s tick=%d\n", pathU8, tick);
}

// ---------------------------------------------------------------- sonda ekonomii (launcher --eco, DOWREC_ECO)
// Silnik nie eksportuje odczytu zasobów (SimEngine: tylko GetID/GetName gracza), a obiekt gracza to podklasa z modu.
// Co 5 s zapisujemy surową pamięć obiektu gracza i obiektów, na które wskazuje (pierwszy poziom), do pliku .bin;
// analysis/eco_scan.py szuka w nich liczb rosnących jak zebrane zasoby. Format (little endian):
//   rekord: "ECO1" | tick i32 | pid u32 | obj u64 | n u32 | obj[n] | k u32 | k x (off u32 | ptr u64 | 256 B)
static FILE* g_eco;
static const size_t kEcoObj = 0x2000, kEcoPtrScan = 0x800, kEcoSub = 0x100;

static void SafeCopy(const void* src, unsigned char* dst, size_t n)
{
    for (size_t i = 0; i < n; i += 0x40) {  // kawałkami – niedostępna końcówka obiektu nie psuje reszty
        size_t m = n - i < 0x40 ? n - i : 0x40;
        __try { memcpy(dst + i, (const char*)src + i, m); }
        __except (EXCEPTION_EXECUTE_HANDLER) { memset(dst + i, 0, m); }
    }
}

static void LogRttiName(unsigned long pid, uintptr_t obj)
{
    // MSVC x64 RTTI: [obj] = vtable, [vtable-8] = CompleteObjectLocator {sig, off, cdOff, typeRVA, classRVA, selfRVA}
    uintptr_t vt = 0, col = 0;
    if (!SafeReadPtr((void*)obj, &vt) || !SafeReadPtr((void*)(vt - 8), &col)) return;
    __try {
        const unsigned* c = (const unsigned*)col;
        uintptr_t base = col - c[5];
        const char* name = (const char*)(base + c[3] + 0x10);
        char safe[128]; SafeJsonStr(name, safe, sizeof(safe));
        Log("ECO gracz %lu obiekt %p klasa %s vtable +0x%llx\n", pid, (void*)obj, safe, (unsigned long long)(vt - base));
    } __except (EXCEPTION_EXECUTE_HANDLER) { Log("ECO gracz %lu obiekt %p (bez RTTI)\n", pid, (void*)obj); }
}

static void* SafePlayerFromId(uintptr_t world, unsigned long id)
{
    __try { return pPlayerFromId((void*)world, id); } __except (EXCEPTION_EXECUTE_HANDLER) { return nullptr; }
}

// gracze z sesji (z walk/zaznaczenia) + ze świata (ID 1000..1007), także ci, którzy jeszcze nie walczyli
static void GatherPlayers(std::vector<std::pair<unsigned long, uintptr_t>>& players)
{
    AcquireSRWLockExclusive(&g_lock);
    players.assign(g_playerObj->begin(), g_playerObj->end());
    ReleaseSRWLockExclusive(&g_lock);
    uintptr_t w = 0;
    if (pPlayerFromId && g_worldGlobal && SafeReadPtr(g_worldGlobal, &w) && w)
        for (unsigned long id = 1000; id < 1008; ++id) {
            void* pl = SafePlayerFromId(w, id);
            bool known = false;
            for (auto& q : players) known |= q.first == id;
            if (pl && !known) players.push_back({id, (uintptr_t)pl});
        }
}

static void EcoDump(int tick)
{
    if (!g_eco || tick <= 0) return;
    std::vector<std::pair<unsigned long, uintptr_t>> players;
    GatherPlayers(players);
    static std::unordered_set<unsigned long> named;
    static std::vector<unsigned char> buf(kEcoObj), sub(kEcoSub);
    for (auto& [pid, obj] : players) {
        if (named.insert(pid).second) LogRttiName(pid, obj);
        SafeCopy((void*)obj, buf.data(), kEcoObj);
        unsigned n = (unsigned)kEcoObj;
        unsigned long long o = obj;
        fwrite("ECO1", 1, 4, g_eco); fwrite(&tick, 4, 1, g_eco); fwrite(&pid, 4, 1, g_eco);
        fwrite(&o, 8, 1, g_eco); fwrite(&n, 4, 1, g_eco); fwrite(buf.data(), 1, kEcoObj, g_eco);
        std::vector<std::pair<unsigned, uintptr_t>> ptrs;
        for (unsigned off = 0; off < kEcoPtrScan; off += 8) {
            uintptr_t p = *(uintptr_t*)(buf.data() + off);
            if (p > 0x10000 && p < 0x7FFFFFFFFFFFull && (p & 7) == 0) ptrs.push_back({off, p});
        }
        unsigned k = (unsigned)ptrs.size();
        fwrite(&k, 4, 1, g_eco);
        for (auto& [off, p] : ptrs) {
            SafeCopy((void*)p, sub.data(), kEcoSub);
            unsigned long long pp = p;
            fwrite(&off, 4, 1, g_eco); fwrite(&pp, 8, 1, g_eco); fwrite(sub.data(), 1, kEcoSub, g_eco);
        }
    }
    fflush(g_eco);
}

// ---------------------------------------------------------------- ekonomia (rekord "eco" co 1 s)
// Ustalone sondą (NOTES.md, 2026-10-19): obiekt gracza = SigmaPlayer (DXP3Mod), float +0x3f8 rekwizycja,
// +0x3fc energia (stan konta), +0x410 / +0x414 dochód rekwizycji / energii na tick. Inna klasa (inny mod, wersja
// gry) -> nie zapisujemy nic, zamiast zapisywać śmieci.
static bool RttiNameContains(uintptr_t obj, const char* what)
{
    uintptr_t vt = 0, col = 0;
    if (!SafeReadPtr((void*)obj, &vt) || !SafeReadPtr((void*)(vt - 8), &col)) return false;
    __try {
        const unsigned* c = (const unsigned*)col;
        const char* name = (const char*)(col - c[5] + c[3] + 0x10);
        return strstr(name, what) != nullptr;
    } __except (EXCEPTION_EXECUTE_HANDLER) { return false; }
}

static bool ReadEco(uintptr_t obj, float out[4])
{
    __try {
        const char* b = (const char*)obj;
        out[0] = *(const float*)(b + 0x3f8); out[1] = *(const float*)(b + 0x3fc);
        out[2] = *(const float*)(b + 0x410); out[3] = *(const float*)(b + 0x414);
    } __except (EXCEPTION_EXECUTE_HANDLER) { return false; }
    for (int i = 0; i < 4; ++i) if (!(out[i] >= 0.0f && out[i] < 1e7f)) return false;  // NaN / śmieci
    return true;
}

static void DescribePlayer(uintptr_t owner, unsigned long pid);

// ---------------------------------------------------------------- ukończone badania (rekord "res")
// SigmaPlayer::Load (DXP3 0x199d0a..) wczytuje tablice badań (std::vector<ResearchInfo*>) do pól +0x2a8 i +0x2c0
// (+0x290 to inny loader – typy postawionych budynków). POTWIERDZONE 2026-10-19 (Battle Marshes, Orkowie): +0x2a8
// rośnie w chwili UKOŃCZENIA badania, nazwa = *(char**)element: ork_research_grot_infiltrate tick 750 (1:33),
// ork_research_eavy_armor_boyz 3137 (6:32), ork_research_burna 3377 (7:02) – zgodne z ekranem gry.
static bool ResearchName(uintptr_t item, char* out, size_t cap)
{
    uintptr_t p = 0;
    if (!SafeReadPtr((void*)item, &p) || p < 0x10000) return false;
    __try {
        const unsigned char* s = (const unsigned char*)p;
        size_t i = 0;
        for (; i + 1 < cap && s[i]; ++i)
            if (!((s[i] >= 'a' && s[i] <= 'z') || (s[i] >= 'A' && s[i] <= 'Z') || (s[i] >= '0' && s[i] <= '9') || s[i] == '_'))
                return false;
        if (i < 3) return false;
        memcpy(out, s, i); out[i] = 0;
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) { return false; }
}

// dopisuje do buf rekordy "res" dla badań ukończonych od poprzedniego wywołania (pole +0x2a8 gracza)
static void ResearchRecords(unsigned long pid, uintptr_t obj, int tick, char* buf, size_t cap, size_t& len)
{
    static std::unordered_map<uintptr_t, size_t> seen;  // obiekt gracza -> znana liczba ukończonych badań
    uintptr_t beg = 0, end = 0;
    if (!SafeReadPtr((void*)(obj + 0x2a8), &beg) || !SafeReadPtr((void*)(obj + 0x2b0), &end) || end < beg) return;
    size_t n = (end - beg) / 8;
    if (n > 512) return;
    size_t& known = seen[obj];
    for (size_t i = known; i < n; ++i) {
        uintptr_t item = 0;
        char name[96];
        if (!SafeReadPtr((void*)(beg + i * 8), &item) || !item || !ResearchName(item, name, sizeof(name))) continue;
        len += _snprintf_s(buf + len, cap - len, _TRUNCATE, "{\"t\":\"res\",\"tick\":%d,\"pid\":%lu,\"name\":\"%s\"}\n",
                           tick, pid, name);
    }
    if (n < known) Log("RES gracz %lu: lista badan skrocila sie %zu -> %zu\n", pid, known, n);
    known = n;
}

static void EcoRecord(int tick)
{
    std::vector<std::pair<unsigned long, uintptr_t>> players;
    GatherPlayers(players);
    static std::unordered_map<uintptr_t, bool> sigma;  // obiekt -> czy to SigmaPlayer (sprawdzane raz)
    char line[2048]; size_t len = 0;
    char res[2048]; size_t rlen = 0;
    std::vector<std::pair<unsigned long, uintptr_t>> ok;
    for (auto& [pid, obj] : players) {
        auto it = sigma.find(obj);
        bool isSigma = it != sigma.end() ? it->second : (sigma[obj] = RttiNameContains(obj, "SigmaPlayer"));
        float v[4];
        if (!isSigma || !ReadEco(obj, v)) continue;
        ResearchRecords(pid, obj, tick, res, sizeof(res), rlen);
        len += _snprintf_s(line + len, sizeof(line) - len, _TRUNCATE,
                           "{\"t\":\"eco\",\"tick\":%d,\"pid\":%lu,\"req\":%.2f,\"pow\":%.2f,\"ir\":%.4f,\"ip\":%.4f}\n",
                           tick, pid, v[0], v[1], v[2], v[3]);
        ok.push_back({pid, obj});
    }
    if (!len) return;
    AcquireSRWLockExclusive(&g_lock);
    if (g_out) {
        for (auto& [pid, obj] : ok) DescribePlayer(obj, pid);  // nazwa gracza, który jeszcze nie walczył
        Out("%s", line);
        if (rlen) Out("%s", res);
    }
    ReleaseSRWLockExclusive(&g_lock);
}

static void DescribePlayer(uintptr_t owner, unsigned long pid)
{
    if (owner && g_playerObj && !g_playerObj->count(pid)) (*g_playerObj)[pid] = owner;
    if (!owner || !g_players->insert(pid).second) return;
    char name[256] = "";
    __try {
        const wchar_t* w = pPlayerName ? pPlayerName((void*)owner) : nullptr;
        if (w) {
            char u8[256]; WideCharToMultiByte(CP_UTF8, 0, w, -1, u8, sizeof(u8), nullptr, nullptr);
            // UTF-8 zostawiamy (polskie znaki w nickach), usuwamy tylko znaki łamiące JSON
            size_t j = 0;
            for (size_t i = 0; u8[i] && j + 1 < sizeof(name); ++i)
                name[j++] = ((unsigned char)u8[i] < 32 || u8[i] == '"' || u8[i] == '\\') ? '_' : u8[i];
            name[j] = 0;
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {}
    Out("{\"t\":\"player\",\"pid\":%lu,\"name\":\"%s\"}\n", pid, name);
}

static void DescribeEnt(const Ent& e)
{
    if (!e.ok || !e.p) return;
    auto it = g_entSquad->find(e.id);
    if (it != g_entSquad->end() && it->second == e.sq) return;
    (*g_entSquad)[e.id] = e.sq;
    DescribePlayer(e.owner, e.pid);
    char bp[160] = "", sqbp[160] = "";
    __try {
        SafeJsonStr(e.bp, bp, sizeof(bp));
        SafeJsonStr(e.sqbp, sqbp, sizeof(sqbp));
    } __except (EXCEPTION_EXECUTE_HANDLER) {}
    Out("{\"t\":\"ent\",\"id\":%lu,\"bp\":\"%s\",\"sq\":%lu,\"sqbp\":\"%s\",\"pid\":%lu}\n", e.id, bp, e.sq, sqbp, e.pid);
}

static void DescribeWeapon(int wid, const char* name, bool melee)
{
    if (wid < 0 || !g_weapons->insert(wid).second) return;
    Out("{\"t\":\"wpn\",\"wid\":%d,\"name\":\"%s\",\"melee\":%s}\n", wid, name, melee ? "true" : "false");
}

// ---------------------------------------------------------------- detoury
struct AppCtx { float hpLoss; int nDeaths; uintptr_t deaths[4]; AppCtx* prev; };
static thread_local AppCtx* t_app;

static uintptr_t g_selfBase, g_selfSize; // rejestrator (pomijany w śladach stosu)

// do 3 adresów powrotu z DLL moda jako "M+rva>M+rva>..." – identyfikuje ścieżkę kodu (np. konkretną zdolność)
static void CallerChain(char* out, size_t cap)
{
    void* fr[12];
    USHORT n = RtlCaptureStackBackTrace(1, 12, fr, nullptr);
    size_t len = 0; int k = 0;
    out[0] = 0;
    for (USHORT i = 0; i < n && k < 3; ++i) {
        uintptr_t a = (uintptr_t)fr[i];
        if (a >= g_selfBase && a < g_selfBase + g_selfSize) continue;
        if (a < g_modBase || a >= g_modBase + g_modSize) continue;
        len += _snprintf_s(out + len, cap - len, _TRUNCATE, k++ ? ">M+%llx" : "M+%llx", (unsigned long long)(a - g_modBase));
    }
}

// Źródło obrażeń: r8 wskazuje strukturę obszaru rażenia (r8 = rsi+8 w 0xafd50/0xa6f60), która jest POLEM obiektu
// źródła (dla broni r8 = WeaponInfo+0x288). Obiekty tworzone z danych gry trzymają ścieżkę swojego pliku
// ("data:attrib\weapon\x.rgd", "data:attrib\abilities\y.rgd"...). HIPOTEZA: najbliższa taka ścieżka WSTECZ od r8
// należy do obiektu-kontenera, czyli identyfikuje źródło (broń, zdolność, atak specjalny) dla każdej rasy.
static const int kSrcScanBack = 0x800, kSrcScanFwd = 0x200;

static bool ReadAttribPath(uintptr_t at, char* out, size_t cap)
{
    __try {
        const char* s = *(const char**)at;
        if ((uintptr_t)s < 0x10000 || (uintptr_t)s > 0x7FFFFFFFFFFF || strncmp(s, "data:attrib\\", 12) != 0) return false;
        // kopia z zachowaniem '\' (potrzebne do rozbicia ścieżki); do JSON trafiają dopiero części po SplitAttribPath
        size_t i = 0;
        for (; i + 1 < cap && s[i]; ++i) out[i] = (s[i] < 32 || s[i] > 126 || s[i] == '"') ? '_' : s[i];
        out[i] = 0;
        return i > 12;
    } __except (EXCEPTION_EXECUTE_HANDLER) { return false; }
}

// najbliższa ścieżka wstecz od r8; zwraca offset (<= 0) albo 1, gdy nie znaleziono
static int SourcePath(void* r8, char* path, size_t cap)
{
    path[0] = 0;
    if (!r8) return 1;
    for (int off = 0; off >= -kSrcScanBack; off -= 8)
        if (ReadAttribPath((uintptr_t)r8 + off, path, cap)) return off;
    return 1;
}

// "data:attrib\abilities\eldar_psychic_storm.rgd" -> folder "abilities", nazwa "eldar_psychic_storm"
static void SplitAttribPath(const char* path, char* folder, size_t fcap, char* name, size_t ncap)
{
    folder[0] = name[0] = 0;
    const char* p = path + 12;                       // za "data:attrib\"
    const char* last = strrchr(p, '\\');
    if (last) {
        size_t n = min((size_t)(last - p), fcap - 1); memcpy(folder, p, n); folder[n] = 0;
        for (char* c = folder; *c; ++c) if (*c == '\\') *c = '/';   // podfoldery (JSON-bezpiecznie)
    }
    const char* base = last ? last + 1 : p;
    strncpy_s(name, ncap, base, _TRUNCATE);
    char* dot = strrchr(name, '.');
    if (dot && _stricmp(dot, ".rgd") == 0) *dot = 0;
}

// diagnostyka w dzienniku: raz na każdy nowy r8 – wszystkie ścieżki "data:attrib" w otoczeniu (weryfikacja hipotezy)
static void LogSourceOnce(void* r8, int wid, const char* wname, const Ent& a)
{
    static SRWLOCK lock = SRWLOCK_INIT;
    static std::unordered_set<uintptr_t>* seen = new std::unordered_set<uintptr_t>();
    AcquireSRWLockExclusive(&lock);
    bool isNew = r8 && seen->insert((uintptr_t)r8).second;
    ReleaseSRWLockExclusive(&lock);
    if (!isNew) return;
    char line[4096], p[200], bp[96] = "";
    SafeJsonStr(a.bp, bp, sizeof(bp)); // sama chroniona przez __try
    size_t len = _snprintf_s(line, sizeof(line), _TRUNCATE, "SRC r8=%p wid=%d w=%s att=%s:", r8, wid, wname, bp);
    for (int off = -kSrcScanBack; off <= kSrcScanFwd && len < sizeof(line) - 260; off += 8)
        if (ReadAttribPath((uintptr_t)r8 + off, p, sizeof(p)))
            len += _snprintf_s(line + len, sizeof(line) - len, _TRUNCATE, " %s0x%x=%s", off < 0 ? "-" : "+", off < 0 ? -off : off, p);
    Log("%s\n", line);
}

static void hkSetHealth(void* self, float value)
{
    if (g_armed) {
        LONG64 t0 = Qpc();
        float old = ReadHealth(self);
        if (t_app) {
            if (value < old) t_app->hpLoss += old - value;
        } else if (value < old) {
            // spadek HP poza ApplyDamage (np. zdolności, budowa) – atakujący nieznany, zapisujemy ścieżkę kodu
            Ent v; QueryEnt((void*)EntityFromHealthExt(self), &v);
            char src[96]; CallerChain(src, sizeof(src));
            int tick = GameTicks();
            AcquireSRWLockExclusive(&g_lock);
            EnsureSession(tick);
            DescribeEnt(v);
            Out("{\"t\":\"hp\",\"tick\":%d,\"v\":%lu,\"vs\":%lu,\"hp\":%.3f,\"src\":\"%s\"}\n", tick, v.id, v.sq, old - value, src);
            ReleaseSRWLockExclusive(&g_lock);
        }
        PerfAdd(Qpc() - t0);
    }
    oSetHealth(self, value);
}

static void EmitDeath(uintptr_t ent, const Ent* by)
{
    Ent v; QueryEnt((void*)ent, &v);
    int tick = GameTicks();
    AcquireSRWLockExclusive(&g_lock);
    EnsureSession(tick);
    DescribeEnt(v);
    if (by) DescribeEnt(*by);
    Out("{\"t\":\"die\",\"tick\":%d,\"v\":%lu,\"vs\":%lu,\"by\":%lu}\n", tick, v.id, v.sq, by ? by->id : 0UL);
    ++g_cntDie;
    ReleaseSRWLockExclusive(&g_lock);
}

static void hkDeath(void* self, uint64_t flag)
{
    if (g_armed) {
        LONG64 t0 = Qpc();
        uintptr_t ent = EntityFromHealthExt(self);
        if (t_app) { if (t_app->nDeaths < 4) t_app->deaths[t_app->nDeaths++] = ent; }
        else if (ent) EmitDeath(ent, nullptr);
        PerfAdd(Qpc() - t0);
    }
    oDeath(self, flag);
}

static float hkApplyDamage(void* victim, void* attacker, void* r8, void* r9, float f5, uint64_t b6)
{
    if (!g_armed) return oApplyDamage(victim, attacker, r8, r9, f5, b6);
    LONG64 t0 = Qpc();
    // Encje odczytujemy PRZED oryginałem: zabity model jest w jego trakcie usuwany z oddziału (sq=0).
    Ent v, a; QueryEnt(victim, &v); QueryEnt(attacker, &a);
    AppCtx ctx = { 0.f, 0, {}, t_app };
    t_app = &ctx;
    LONG64 tA = Qpc();
    float res = oApplyDamage(victim, attacker, r8, r9, f5, b6);
    LONG64 tB = Qpc();
    t_app = ctx.prev;
    if (res <= 0.f && ctx.hpLoss <= 0.f && ctx.nDeaths == 0) {  // szum (zerowe wywołania)
        PerfAdd((tA - t0) + (Qpc() - tB));
        return res;
    }

    int wid; char wname[160]; bool melee;
    WeaponInfoOf(r9, &wid, wname, sizeof(wname), &melee);
    int kill = 0;
    for (int i = 0; i < ctx.nDeaths; ++i) if (ctx.deaths[i] == (uintptr_t)victim) kill = 1;
    int tick = GameTicks();
    // bez WeaponInfo: źródło z najbliższej ścieżki danych gry (ab = nazwa pliku, abf = folder) + ścieżka kodu
    LogSourceOnce(r8, wid, wname, a);
    char extra[400] = "";
    int off = 1;
    if (wid < 0) {
        char src[96], path[200], folder[48], ab[128];
        CallerChain(src, sizeof(src));
        off = SourcePath(r8, path, sizeof(path));
        if (off <= 0) SplitAttribPath(path, folder, sizeof(folder), ab, sizeof(ab)); else folder[0] = ab[0] = 0;
        _snprintf_s(extra, sizeof(extra), _TRUNCATE, ",\"src\":\"%s\",\"ab\":\"%s\",\"abf\":\"%s\",\"abo\":%d",
                    src, ab, folder, off <= 0 ? -off : -1);
    }

    AcquireSRWLockExclusive(&g_lock);
    EnsureSession(tick);
    DescribeEnt(v); DescribeEnt(a);
    DescribeWeapon(wid, wname, melee);
    // Atak specjalny wręcz (2026-10-17): obszar rażenia tworzony w locie, bez pliku danych (abo=-1). HEURYSTYKA:
    // podpisujemy go ostatnią bronią wręcz atakującego ("sw"), bo salwy zbiegają się z walką tą bronią.
    if (wid >= 0 && melee) (*g_lastMelee)[a.id] = wid;
    else if (wid < 0 && off > 0) {
        auto it = g_lastMelee->find(a.id);
        size_t len = strlen(extra);
        _snprintf_s(extra + len, sizeof(extra) - len, _TRUNCATE, ",\"sw\":%d", it != g_lastMelee->end() ? it->second : -1);
    }
    Out("{\"t\":\"dmg\",\"tick\":%d,\"a\":%lu,\"as\":%lu,\"v\":%lu,\"vs\":%lu,\"w\":%d,\"hp\":%.3f,\"nom\":%.3f,\"k\":%d,\"ff\":%d%s}\n",
        tick, a.id, a.sq, v.id, v.sq, wid, ctx.hpLoss, res, kill, (a.ok && v.ok && a.owner == v.owner) ? 1 : 0, extra);
    ++g_cntDmg;
    ReleaseSRWLockExclusive(&g_lock);

    // zgony innych encji wywołane tym trafieniem (np. odbicie obrażeń) – rzadkie
    for (int i = 0; i < ctx.nDeaths; ++i) if (ctx.deaths[i] && ctx.deaths[i] != (uintptr_t)victim) EmitDeath(ctx.deaths[i], &a);
    PerfAdd((tA - t0) + (Qpc() - tB));  // bez czasu oryginału (w nim są nasze SetHealth/Death – liczone osobno)
    return res;
}

// ---------------------------------------------------------------- bezpiecznik
static void SetGameHooks(bool on)
{
    void* t[] = { g_tSetHealth, g_tDeath, g_tApplyDamage };
    for (void* x : t) if (x) on ? MH_EnableHook(x) : MH_DisableHook(x);
}

static NTSTATUS NTAPI hkNtCreateFile(PHANDLE h, ACCESS_MASK access, POBJECT_ATTRIBUTES oa, PIO_STATUS_BLOCK io,
                                     PLARGE_INTEGER alloc, ULONG attrs, ULONG share, ULONG disp, ULONG opts, PVOID ea, ULONG eal)
{
    NTSTATUS st = oNtCreateFile(h, access, oa, io, alloc, attrs, share, disp, opts, ea, eal);
    __try {
        const UNICODE_STRING* s = oa ? oa->ObjectName : nullptr;
        if (st >= 0 && s && s->Buffer && s->Length >= 8 && _wcsnicmp(s->Buffer + s->Length / 2 - 4, L".rec", 4) == 0) {
            bool write = (access & (GENERIC_WRITE | FILE_WRITE_DATA | FILE_APPEND_DATA)) != 0;
            static ULONGLONG lastReadMs;
            ULONGLONG now = GetTickCount64();
            // nazwa pliku bez ścieżki
            size_t n = s->Length / 2, b = n;
            while (b > 0 && s->Buffer[b - 1] != L'\\') --b;
            if (!write) {
                lastReadMs = now;
                AcquireSRWLockExclusive(&g_lock);
                wcsncpy_s(g_replayName, MAX_PATH, s->Buffer + b, min(n - b, (size_t)MAX_PATH - 1));
                ReleaseSRWLockExclusive(&g_lock);
            } else if (lastReadMs && now - lastReadMs < 30000) {
                __leave; // gra tworzy temp.rec przy starcie odtwarzania – to nadal powtórka
            }
            LONG want = write ? 0 : 1;
            if (InterlockedExchange(&g_armed, want) != want) {
                Log("GUARD %s\n", want ? "odczyt .rec - rejestrator WLACZONY" : "zapis .rec (gra na zywo?) - rejestrator WYLACZONY");
                SetEvent(g_armEvent);
            }
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {}
    return st;
}

// ---------------------------------------------------------------- wyszukiwanie adresów (jak w sondzie)
static uintptr_t ModuleSize(uintptr_t base)
{
    return ((IMAGE_NT_HEADERS64*)(base + ((IMAGE_DOS_HEADER*)base)->e_lfanew))->OptionalHeader.SizeOfImage;
}

// skanuje sekcje wykonywalne; maska: '?' = dowolny bajt. Zwraca adres tylko przy jednoznacznym trafieniu.
static uintptr_t FindBytes(const uint8_t* pat, const char* mask, size_t n, bool (*accept)(uintptr_t), int* hitsOut)
{
    auto nt = (IMAGE_NT_HEADERS64*)(g_modBase + ((IMAGE_DOS_HEADER*)g_modBase)->e_lfanew);
    auto sec = IMAGE_FIRST_SECTION(nt);
    uintptr_t hit = 0; int hits = 0;
    for (WORD i = 0; i < nt->FileHeader.NumberOfSections; ++i, ++sec) {
        if (!(sec->Characteristics & IMAGE_SCN_MEM_EXECUTE)) continue;
        uint8_t* s = (uint8_t*)(g_modBase + sec->VirtualAddress);
        for (size_t k = 0; k + n <= sec->Misc.VirtualSize; ++k) {
            size_t j = 0;
            while (j < n && (mask[j] == '?' || s[k + j] == pat[j])) ++j;
            if (j == n && (!accept || accept((uintptr_t)(s + k)))) { if (!hits++) hit = (uintptr_t)(s + k); }
        }
    }
    if (hitsOut) *hitsOut = hits;
    return hits == 1 ? hit : 0;
}

static uintptr_t CallTarget(uintptr_t e8) { return e8 + 5 + *(int32_t*)(e8 + 1); }

static uintptr_t CallAfter(uintptr_t from, const uint8_t* pat, size_t n, size_t limit)
{
    if (!from) return 0;
    for (size_t k = 0; k + n + 4 <= limit; ++k)
        if (memcmp((void*)(from + k), pat, n) == 0) return CallTarget(from + k + n - 1);
    return 0;
}

static uintptr_t FunctionStart(uintptr_t addr)
{
    DWORD64 img = 0;
    PRUNTIME_FUNCTION rf = RtlLookupFunctionEntry(addr, &img, nullptr);
    while (rf) {
        uint8_t* ui = (uint8_t*)(img + rf->UnwindData);
        if (!((ui[0] >> 3) & UNW_FLAG_CHAININFO)) return (uintptr_t)(img + rf->BeginAddress);
        rf = (PRUNTIME_FUNCTION)(ui + 4 + ((ui[2] + 1) & ~1) * 2);
    }
    return 0;
}

static uintptr_t g_takeDamage;
static bool CallsTakeDamage(uintptr_t at) { return CallTarget(at + 9) == g_takeDamage; }

static bool Resolve(uintptr_t* setHealth, uintptr_t* death, uintptr_t* apply)
{
    // TakeDamage: 40 53 48 83 EC 30 0F 29 74 24 20 0F 28 F1 48 8B D9 45 84 C0 74 ?? E8
    static const uint8_t tdPat[] = { 0x40,0x53,0x48,0x83,0xEC,0x30,0x0F,0x29,0x74,0x24,0x20,0x0F,0x28,0xF1,0x48,0x8B,0xD9,0x45,0x84,0xC0,0x74,0x00,0xE8 };
    static const char    tdMask[] = "xxxxxxxxxxxxxxxxxxxxx?x";
    static const uint8_t wPat[] = { 0x48,0x8B,0x0D,0,0,0,0,0xC7,0x44,0x24,0x40,0x58,0x54,0x4C,0x48 }; // mov rcx,[rip+X]; 'XTLH'
    static const char    wMask[] = "xxx????xxxxxxxx";
    static const uint8_t shCall[] = { 0xF3,0x0F,0x5C,0xC8,0x48,0x8B,0xCB,0xE8 };
    static const uint8_t deCall[] = { 0x33,0xD2,0x48,0x8B,0xCB,0xE8 };
    static const uint8_t apPat[] = { 0x41,0xB0,0x01,0x0F,0x28,0xCF,0x48,0x8B,0xCF,0xE8 };

    g_takeDamage = FindBytes(tdPat, tdMask, sizeof(tdPat), nullptr, nullptr);
    uintptr_t w = FindBytes(wPat, wMask, sizeof(wPat), nullptr, nullptr);
    if (w) g_worldGlobal = (void**)(w + 7 + *(int32_t*)(w + 3));
    *setHealth = CallAfter(g_takeDamage, shCall, sizeof(shCall), 0x100);
    *death     = CallAfter(*setHealth, deCall, sizeof(deCall), 0x140);
    int hits = 0;
    uintptr_t call = g_takeDamage ? FindBytes(apPat, "xxxxxxxxxx", sizeof(apPat), CallsTakeDamage, &hits) : 0;
    *apply = call ? FunctionStart(call) : 0;
    Log("RESOLVE TakeDamage=M+%llx SetHealth=M+%llx Death=M+%llx ApplyDamage=M+%llx (wywolan %d) World=M+%llx\n",
        (unsigned long long)(g_takeDamage ? g_takeDamage - g_modBase : 0), (unsigned long long)(*setHealth ? *setHealth - g_modBase : 0),
        (unsigned long long)(*death ? *death - g_modBase : 0), (unsigned long long)(*apply ? *apply - g_modBase : 0), hits,
        (unsigned long long)(g_worldGlobal ? (uintptr_t)g_worldGlobal - g_modBase : 0));
    return *setHealth && *death && *apply && g_worldGlobal;
}

static bool ResolveSimEngine()
{
    HMODULE s = GetModuleHandleW(L"SimEngine.dll");
    if (!s) return false;
    pEntGetBp    = (FnGetBp)     GetProcAddress(s, "?GetBlueprintName@Entity@@QEBAPEBDXZ");
    pSquadGetBp  = (FnGetBp)     GetProcAddress(s, "?GetBlueprintName@Squad@@QEBAPEBDXZ");
    pEntGetId    = (FnGetId)     GetProcAddress(s, "?GetID@Entity@@QEBAKXZ");
    pSquadGetId  = (FnGetId)     GetProcAddress(s, "?GetID@Squad@@QEBAKXZ");
    pPlayerGetId = (FnGetId)     GetProcAddress(s, "?GetID@Player@@UEBAKXZ");
    pPlayerName  = (FnPlayerName)GetProcAddress(s, "?GetName@Player@@QEBAPEB_WXZ");
    pEntGetSquad = (FnGetPtr)    GetProcAddress(s, "?GetSquad@Entity@@QEAAPEAVSquad@@XZ");
    pEntGetOwner = (FnGetPtr)    GetProcAddress(s, "?GetOwner@Entity@@QEAAPEAVPlayer@@XZ");
    pWorldTicks  = (FnWorldTicks)GetProcAddress(s, "?GetGameTicks@World@@QEBAJXZ");
    pPlayerFromId = (FnPlayerFromId)GetProcAddress(s, "?GetPlayerFromID@World@@QEAAPEAVPlayer@@K@Z");
    return pEntGetBp && pSquadGetBp && pEntGetId && pSquadGetId && pEntGetSquad && pEntGetOwner && pWorldTicks;
}

// ---------------------------------------------------------------- zaznaczenie gracza (W40k.exe)
// Misc_GetSelectedSquads (SCAR, W40k.exe 0xd4f480 w buildzie 2.10.3.1): app = f1(); ui = f2(app); sel = f3(ui);
// grp = sel->vtbl[1](sel) -> EntityHolderGroup zaznaczonych encji; encja+0x20 = oddział. Adresy f1..f3 wyznaczamy
// z kodu funkcji obsługi, którą znajdujemy po rejestracji napisu "Misc_GetSelectedSquads".
typedef void* (*FnGetter)(void*);
typedef void* const* (*FnGroupIter)(const void*);
static FnGetter    pSelApp, pSelUi, pSelMgr;
static FnGroupIter pGrpBegin, pGrpEnd;

static uintptr_t FindInImage(uintptr_t base, const void* pat, size_t n, bool exec)
{
    auto nt = (IMAGE_NT_HEADERS64*)(base + ((IMAGE_DOS_HEADER*)base)->e_lfanew);
    auto sec = IMAGE_FIRST_SECTION(nt);
    for (WORD i = 0; i < nt->FileHeader.NumberOfSections; ++i, ++sec) {
        if (((sec->Characteristics & IMAGE_SCN_MEM_EXECUTE) != 0) != exec) continue;
        uint8_t* s = (uint8_t*)(base + sec->VirtualAddress);
        for (size_t k = 0; k + n <= sec->Misc.VirtualSize; ++k)
            if (memcmp(s + k, pat, n) == 0) return (uintptr_t)(s + k);
    }
    return 0;
}

static bool ResolveSelection()
{
    uintptr_t exe = (uintptr_t)GetModuleHandleW(nullptr);
    static const char name[] = "Misc_GetSelectedSquads";
    uintptr_t str = FindInImage(exe, name, sizeof(name), false);  // z '\0' na końcu
    if (!str) { Log("WARN zaznaczenie: brak napisu Misc_GetSelectedSquads\n"); return false; }
    // lea r8, [rip+str] (4C 8D 05 rel32) w kodzie rejestracji funkcji SCAR
    auto nt = (IMAGE_NT_HEADERS64*)(exe + ((IMAGE_DOS_HEADER*)exe)->e_lfanew);
    auto sec = IMAGE_FIRST_SECTION(nt);
    uintptr_t reg = 0;
    for (WORD i = 0; i < nt->FileHeader.NumberOfSections && !reg; ++i, ++sec) {
        if (!(sec->Characteristics & IMAGE_SCN_MEM_EXECUTE)) continue;
        uint8_t* s = (uint8_t*)(exe + sec->VirtualAddress);
        for (size_t k = 0; k + 7 <= sec->Misc.VirtualSize; ++k)
            if (s[k] == 0x4C && s[k + 1] == 0x8D && s[k + 2] == 0x05 && (uintptr_t)(s + k + 7) + *(int32_t*)(s + k + 3) == str) {
                reg = (uintptr_t)(s + k); break;
            }
    }
    // dalej: lea rax,[rip+handler] (48 8D 05) ; mov [rsi+0x20],rax (48 89 46 20)
    uintptr_t handler = 0;
    for (size_t k = 0; reg && k < 0x40 && !handler; ++k) {
        uint8_t* p = (uint8_t*)reg + k;
        if (p[0] == 0x48 && p[1] == 0x8D && p[2] == 0x05 && p[7] == 0x48 && p[8] == 0x89 && p[9] == 0x46 && p[10] == 0x20)
            handler = (uintptr_t)(p + 7) + *(int32_t*)(p + 3);
    }
    if (!handler) { Log("WARN zaznaczenie: nie znaleziono funkcji obslugi\n"); return false; }
    // w funkcji obsługi: call [rip] (SGroup::Clear), potem trzy call rel32 = f1, f2, f3,
    // a za nimi: mov rcx,rax ; mov rdx,[rax] ; call [rdx+8]
    uintptr_t calls[3]; int nc = 0;
    uint8_t* p = (uint8_t*)handler;
    size_t k = 0;
    while (k < 0x30 && !(p[k] == 0xFF && p[k + 1] == 0x15)) ++k;
    for (k += 6; k < 0x60 && nc < 3; ++k)
        if (p[k] == 0xE8) { calls[nc++] = (uintptr_t)(p + k + 5) + *(int32_t*)(p + k + 1); k += 4; }
    static const uint8_t tail[] = { 0x48, 0x8B, 0xC8, 0x48, 0x8B, 0x10, 0xFF, 0x52, 0x08 };
    if (nc != 3 || memcmp(p + k, tail, sizeof(tail)) != 0) {  // k = bajt za trzecim wywołaniem
        Log("WARN zaznaczenie: nieoczekiwany kod funkcji obslugi (nc=%d) - wylaczone\n", nc);
        return false;
    }
    pSelApp = (FnGetter)calls[0]; pSelUi = (FnGetter)calls[1]; pSelMgr = (FnGetter)calls[2];
    HMODULE s = GetModuleHandleW(L"SimEngine.dll");
    pGrpBegin = (FnGroupIter)GetProcAddress(s, "?begin@?$EntityHolderGroup@VEntityHolderNonConst@@@@QEBAPEBQEAVEntity@@XZ");
    pGrpEnd   = (FnGroupIter)GetProcAddress(s, "?end@?$EntityHolderGroup@VEntityHolderNonConst@@@@QEBAPEBQEAVEntity@@XZ");
    Log("INFO zaznaczenie: obsluga=E+%llx f1=E+%llx f2=E+%llx f3=E+%llx\n", (unsigned long long)(handler - exe),
        (unsigned long long)(calls[0] - exe), (unsigned long long)(calls[1] - exe), (unsigned long long)(calls[2] - exe));
    return pGrpBegin && pGrpEnd;
}

// Odczyt z wątku roboczego (nie z wątku gry) – tylko gettery i odczyt listy, całość w __try; w najgorszym razie
// zwraca chwilowo nieaktualne zaznaczenie. sq = id oddziałów, en = id encji bez oddziału (budynki).
static bool ReadSelection(unsigned long* sq, int* nsq, unsigned long* en, int* nen, int cap, void** ents, int* nents)
{
    *nsq = *nen = *nents = 0;
    if (!pSelApp) return false;
    __try {
        void* mgr = pSelMgr(pSelUi(pSelApp(nullptr)));
        if (!mgr) return true;
        void* grp = ((FnGetter)(*(void***)mgr)[1])(mgr);
        if (!grp) return true;
        void* const* b = pGrpBegin(grp);
        void* const* e = pGrpEnd(grp);
        for (int i = 0; b + i < e && i < 64; ++i) {
            void* ent = b[i];
            if (!ent) continue;
            if (*nents < cap) ents[(*nents)++] = ent;   // do opisu encji (rekord 'ent') w podglądzie
            void* s = pEntGetSquad(ent);
            if (s) {
                unsigned long id = pSquadGetId(s);
                bool dup = false;
                for (int j = 0; j < *nsq; ++j) dup |= sq[j] == id;
                if (!dup && *nsq < cap) sq[(*nsq)++] = id;
            } else if (*nen < cap) en[(*nen)++] = pEntGetId(ent);
        }
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) { *nsq = *nen = 0; return false; }
}

// wołane co ~0,1 s z wątku roboczego; rekord "sel" tylko przy zmianie (i na początku każdej sesji)
static void PollSelection(int tick)
{
    static char last[512];
    static FILE* lastOut;
    unsigned long sq[16], en[16]; int nsq, nen, nents;
    void* ents[16];
    if (!ReadSelection(sq, &nsq, en, &nen, 16, ents, &nents)) return;
    char rec[512]; size_t len = _snprintf_s(rec, sizeof(rec), _TRUNCATE, "\"sq\":[");
    for (int i = 0; i < nsq; ++i) len += _snprintf_s(rec + len, sizeof(rec) - len, _TRUNCATE, i ? ",%lu" : "%lu", sq[i]);
    len += _snprintf_s(rec + len, sizeof(rec) - len, _TRUNCATE, "],\"e\":[");
    for (int i = 0; i < nen; ++i) len += _snprintf_s(rec + len, sizeof(rec) - len, _TRUNCATE, i ? ",%lu" : "%lu", en[i]);
    _snprintf_s(rec + len, sizeof(rec) - len, _TRUNCATE, "]");
    AcquireSRWLockExclusive(&g_lock);
    if (g_out && (g_out != lastOut || strcmp(rec, last) != 0)) {
        // oddział mógł jeszcze nie walczyć – opisujemy zaznaczone encje, żeby podgląd znał nazwę i gracza
        for (int i = 0; i < nents; ++i) { Ent e; QueryEnt(ents[i], &e); DescribeEnt(e); }
        Out("{\"t\":\"sel\",\"tick\":%d,%s}\n", tick, rec);
        strcpy_s(last, rec); lastOut = g_out;
        fflush(g_out);  // zaznaczenie ma być widoczne w podglądzie od razu
    }
    ReleaseSRWLockExclusive(&g_lock);
}

static bool HookAt(uintptr_t target, void* detour, void** orig, void** save, const char* name)
{
    MH_STATUS st = MH_CreateHook((void*)target, detour, orig);
    Log("HOOK %s M+%llx status=%d\n", name, (unsigned long long)(target - g_modBase), (int)st);
    if (st != MH_OK) return false;
    *save = (void*)target;
    return true;
}

static DWORD WINAPI InitThread(LPVOID)
{
    static const wchar_t* mods[] = { L"DXP3Mod.dll", L"DXP2Mod.dll", L"WXPMod.dll", L"W40kMod.dll" };
    HMODULE mod = nullptr;
    while (!mod) {
        for (const wchar_t* n : mods) if ((mod = GetModuleHandleW(n)) != nullptr) { g_modName = n; break; }
        if (!mod) Sleep(250);
    }
    Sleep(500);
    g_modBase = (uintptr_t)mod; g_modSize = ModuleSize(g_modBase);
    Log("INFO mod=%ls\n", g_modName);

    uintptr_t sh, de, ap;
    if (!ResolveSimEngine()) { Log("ERR brak eksportow SimEngine - rejestrator nieaktywny\n"); return 0; }
    if (!Resolve(&sh, &de, &ap)) { Log("ERR nie znaleziono wszystkich funkcji (np. W40kMod/WXPMod nie sa obslugiwane) - rejestrator nieaktywny\n"); return 0; }
    if (MH_Initialize() != MH_OK) { Log("ERR MH_Initialize\n"); return 0; }
    bool ok = HookAt(sh, (void*)hkSetHealth, (void**)&oSetHealth, &g_tSetHealth, "SetHealth")
           && HookAt(de, (void*)hkDeath, (void**)&oDeath, &g_tDeath, "Death")
           && HookAt(ap, (void*)hkApplyDamage, (void**)&oApplyDamage, &g_tApplyDamage, "ApplyDamage");
    if (!ok) { Log("ERR zakladanie hookow nie powiodlo sie - rejestrator nieaktywny\n"); return 0; }

    void* ntc = (void*)GetProcAddress(GetModuleHandleW(L"ntdll.dll"), "NtCreateFile");
    if (!ntc || MH_CreateHook(ntc, (void*)hkNtCreateFile, (void**)&oNtCreateFile) != MH_OK || MH_EnableHook(ntc) != MH_OK) {
        Log("ERR bezpiecznik NtCreateFile - rejestrator nieaktywny\n"); return 0;
    }
    bool selection = ResolveSelection();
    Log("INFO gotowy; czekam na otwarcie powtorki\n");

    LONG applied = 0;
    for (unsigned iter = 0;; ++iter) {
        // co 0,1 s zaznaczenie gracza (v1.2; było 0,2 s); co 1 s zegar i zrzut buforów
        DWORD w = WaitForSingleObject(g_armEvent, 100);
        if (w == WAIT_TIMEOUT && g_armed && selection) {
            LONG64 t0 = Qpc();
            PollSelection(GameTicks());
            InterlockedAdd64(&g_selTicks, Qpc() - t0);
        }
        if (w == WAIT_TIMEOUT && iter % 100 == 0 && g_armed) {  // co 10 s: narzut w ms na sekundę czasu rzeczywistego
            static LONG64 lastT, lastTicks, lastCalls, lastSel;
            LARGE_INTEGER f; QueryPerformanceFrequency(&f);
            LONG64 now = Qpc(), ticks = g_perfTicks, calls = g_perfCalls, sel = g_selTicks;
            if (lastT) {
                double sec = double(now - lastT) / f.QuadPart;
                Log("PERF hooki: %.3f ms/s (%.0f wywolan/s, max %.1f us) | zaznaczenie: %.3f ms/s\n",
                    (ticks - lastTicks) * 1000.0 / f.QuadPart / sec, (calls - lastCalls) / sec,
                    g_perfMax * 1e6 / f.QuadPart, (sel - lastSel) * 1000.0 / f.QuadPart / sec);
                g_perfMax = 0;
            }
            lastT = now; lastTicks = ticks; lastCalls = calls; lastSel = sel;
        }
        if (w == WAIT_TIMEOUT && iter % 10 != 0) continue;
        LONG want = g_armed;
        if (want != applied) {
            SetGameHooks(want != 0); applied = want;
            if (!want) { AcquireSRWLockExclusive(&g_lock); CloseSession(); ReleaseSRWLockExclusive(&g_lock); }
        }
        if (w == WAIT_TIMEOUT) { // co sekundę: zegar + zrzut buforów, żeby podgląd mógł czytać plik na bieżąco
            static int prevTick = -1;
            int tick = g_armed ? GameTicks() : -1;
            // Sesję otwieramy już od startu powtórki (nie dopiero przy pierwszym trafieniu), ale tylko gdy symulacja
            // faktycznie biegnie (tick rośnie) – w menu World może wskazywać na starą, zatrzymaną grę.
            bool running = tick > 0 && prevTick >= 0 && tick > prevTick;
            prevTick = tick;
            AcquireSRWLockExclusive(&g_lock);
            if (running) EnsureSession(tick); // nowa sesja przy innej powtórce lub cofnięciu ticka
            if (g_out && tick > g_lastTick) g_lastTick = tick;
            if (g_out && running) Out("{\"t\":\"clock\",\"tick\":%d}\n", tick);
            if (g_out) fflush(g_out);
            ReleaseSRWLockExclusive(&g_lock);
            if (running) EcoRecord(tick);                            // ekonomia graczy: co 1 s
            if (g_eco && running && iter % 50 == 0) EcoDump(tick);  // sonda ekonomii: co 5 s
            AcquireSRWLockExclusive(&g_logLock);
            if (g_log) fflush(g_log);
            ReleaseSRWLockExclusive(&g_logLock);
        }
    }
}

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID)
{
    if (reason != DLL_PROCESS_ATTACH) return TRUE;
    DisableThreadLibraryCalls(inst);
    g_selfBase = (uintptr_t)inst; g_selfSize = ModuleSize(g_selfBase);
    wchar_t flag[16] = {0}, logPath[MAX_PATH] = {0};
    if (!GetEnvironmentVariableW(L"DOWPROBE_LAUNCHER", flag, 16) || wcscmp(flag, L"1") != 0) return TRUE;
    if (!GetEnvironmentVariableW(L"DOWREC_OUT", g_outDir, MAX_PATH)) return TRUE;
    if (!GetEnvironmentVariableW(L"DOWPROBE_LOG", logPath, MAX_PATH)) return TRUE;
    CreateDirectoryW(g_outDir, nullptr);
    g_log = _wfsopen(logPath, L"wb", _SH_DENYWR);
    if (!g_log) return TRUE;
    g_entSquad = new std::unordered_map<unsigned long, unsigned long>();
    g_players  = new std::unordered_set<unsigned long>();
    g_playerObj = new std::unordered_map<unsigned long, uintptr_t>();
    wchar_t ecoPath[MAX_PATH] = {0};
    if (GetEnvironmentVariableW(L"DOWREC_ECO", ecoPath, MAX_PATH)) g_eco = _wfsopen(ecoPath, L"wb", _SH_DENYWR);
    g_weapons  = new std::unordered_set<int>();
    g_lastMelee = new std::unordered_map<unsigned long, int>();
    g_armEvent = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    Log("# dowrec v1 pid=%lu\n", GetCurrentProcessId());
    CloseHandle(CreateThread(nullptr, 0, InitThread, nullptr, 0, nullptr));
    return TRUE;
}
