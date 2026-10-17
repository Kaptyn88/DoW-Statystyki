// dowprobe.dll – sonda obrażeń dla Dawn of War: Definitive Edition (tylko do powtórek offline).
//
// Hooki (adresy znajdowane sygnaturami w DLL aktywnego moda: W40kMod/WXPMod/DXP2Mod/DXP3Mod):
//   SetHealth  (HealthExt::SetHealth core, rcx=this, xmm1=nowe zdrowie bezwzględne)
//   TakeDamage (rcx=this, xmm1=kwota, r8b=flaga)
//   Death      (ścieżka śmierci, rcx=this, dl=flaga)
// Plus NtCreateFile (ntdll) jako bezpiecznik: hooki gry są włączane dopiero po otwarciu pliku .rec do odczytu,
// a wyłączane na stałe, gdy gra otworzy .rec do zapisu (czyli nagrywa rozgrywkę na żywo).
//
// DLL nic nie robi, jeśli nie została załadowana przez dowprobe_launcher.exe (zmienna środowiskowa DOWPROBE_LAUNCHER).

#include <windows.h>
#include <winternl.h>
#include <intrin.h>
#include <stdio.h>
#include <share.h>
#include <stdint.h>
#include <string.h>
#include <wchar.h>
#include <unordered_set>
#include "MinHook.h"

#pragma intrinsic(_AddressOfReturnAddress)

// ---------------------------------------------------------------- konfiguracja
static const int   kStackFrames   = 14;      // ile adresów powrotu zapisywać
static const DWORD kStackScanBytes = 0x1000; // ile bajtów stosu przeszukiwać pod kątem wskaźników do znanych encji

// ---------------------------------------------------------------- stan globalny
static FILE*        g_log;
static SRWLOCK      g_logLock = SRWLOCK_INIT;
static SRWLOCK      g_entLock = SRWLOCK_INIT;
static std::unordered_set<uintptr_t>* g_entities; // znane wskaźniki Entity*
static uintptr_t    g_modBase, g_modSize;         // DLL aktywnego moda
static uintptr_t    g_simBase, g_simSize;         // SimEngine.dll
static void**       g_worldGlobal;                // &World* w DLL moda
static void*        g_tSetHealth, *g_tTakeDamage, *g_tDeath, *g_tNtCreateFile;
static volatile LONG g_armed;      // 1 = detoury logują (ustawiane przez bezpiecznik)
static HANDLE       g_armEvent;    // sygnał dla wątku roboczego: zmienił się stan uzbrojenia
static uintptr_t    g_selfBase, g_selfSize; // dowprobe.dll (do pomijania własnych ramek)
static volatile LONG64 g_seq;
static volatile LONG64 g_cntSet, g_cntDmg, g_cntDeath, g_cntHeal;

// eksporty SimEngine.dll
typedef const char* (*FnEntGetBp)(const void*);
typedef unsigned long (*FnEntGetId)(const void*);
typedef void* (*FnEntGetPtr)(void*);
typedef int   (*FnWorldTicks)(const void*);
typedef float (*FnWorldTime)(const void*);
static FnEntGetBp  pEntGetBp, pSquadGetBp;
static FnEntGetId  pEntGetId, pSquadGetId;
static FnEntGetPtr pEntGetSquad, pEntGetOwner;
static FnWorldTicks pWorldTicks;
static FnWorldTime  pWorldTime;

// oryginały. Konwencja x64 MS: arg1=rcx, arg2 float=xmm1, arg3 int=r8, arg2 int=rdx – zgodnie z deasemblacją.
typedef void (*FnSetHealth)(void* self, float value);                 // rcx, xmm1
typedef void (*FnTakeDamage)(void* self, float amount, uint64_t flag); // rcx, xmm1, r8b
typedef void (*FnDeath)(void* self, uint64_t flag);                    // rcx, dl
static FnSetHealth  oSetHealth;
static FnTakeDamage oTakeDamage;
static FnDeath      oDeath;
typedef NTSTATUS (NTAPI* FnNtCreateFile)(PHANDLE, ACCESS_MASK, POBJECT_ATTRIBUTES, PIO_STATUS_BLOCK, PLARGE_INTEGER,
                                         ULONG, ULONG, ULONG, ULONG, PVOID, ULONG);
static FnNtCreateFile oNtCreateFile;


// ---------------------------------------------------------------- logowanie
static void Log(const char* fmt, ...)
{
    if (!g_log) return;
    char buf[2048];
    va_list ap; va_start(ap, fmt);
    int n = _vsnprintf_s(buf, sizeof(buf), _TRUNCATE, fmt, ap);
    va_end(ap);
    if (n < 0) n = (int)strlen(buf);
    AcquireSRWLockExclusive(&g_logLock);
    fwrite(buf, 1, (size_t)n, g_log);
    ReleaseSRWLockExclusive(&g_logLock);
}

static DWORD WINAPI FlushThread(LPVOID)
{
    for (;;) {
        Sleep(1000);
        AcquireSRWLockExclusive(&g_logLock);
        if (g_log) fflush(g_log);
        ReleaseSRWLockExclusive(&g_logLock);
    }
}

// ---------------------------------------------------------------- bezpieczne odczyty (SEH, bez obiektów C++)
static bool SafeReadPtr(const void* p, uintptr_t* out)
{
    __try { *out = *(const uintptr_t*)p; return true; }
    __except (EXCEPTION_EXECUTE_HANDLER) { return false; }
}

static bool SafeCopyStr(const char* s, char* out, size_t cap)
{
    __try {
        size_t i = 0;
        for (; i + 1 < cap && s[i]; ++i) out[i] = (s[i] >= 32 && s[i] < 127) ? s[i] : '?';
        out[i] = 0;
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) { out[0] = 0; return false; }
}

struct EntInfo {
    uintptr_t ent, owner, squad;
    unsigned long id, squadId;
    char bp[160], squadBp[160];
    bool ok;
};

static void QueryEntity(uintptr_t ent, EntInfo* e)
{
    memset(e, 0, sizeof(*e));
    e->ent = ent;
    if (!ent) return;
    __try {
        e->id = pEntGetId ? pEntGetId((void*)ent) : 0;
        const char* bp = pEntGetBp ? pEntGetBp((void*)ent) : nullptr;
        if (bp) SafeCopyStr(bp, e->bp, sizeof(e->bp));
        e->owner = pEntGetOwner ? (uintptr_t)pEntGetOwner((void*)ent) : 0;
        e->squad = pEntGetSquad ? (uintptr_t)pEntGetSquad((void*)ent) : 0;
        if (e->squad) {
            e->squadId = pSquadGetId ? pSquadGetId((void*)e->squad) : 0;
            const char* sbp = pSquadGetBp ? pSquadGetBp((void*)e->squad) : nullptr;
            if (sbp) SafeCopyStr(sbp, e->squadBp, sizeof(e->squadBp));
        }
        e->ok = true;
    } __except (EXCEPTION_EXECUTE_HANDLER) { e->ok = false; }
}

// HIPOTEZA (do weryfikacji sondą): Entity* = [[HealthExt+8]+0x10]
static uintptr_t EntityFromHealthExt(void* hx)
{
    uintptr_t a = 0, ent = 0;
    if (!SafeReadPtr((char*)hx + 8, &a) || !a) return 0;
    if (!SafeReadPtr((char*)a + 0x10, &ent)) return 0;
    return ent;
}

static void GameTime(int* ticks, float* secs)
{
    *ticks = -1; *secs = -1.f;
    uintptr_t w = 0;
    if (!g_worldGlobal || !SafeReadPtr(g_worldGlobal, &w) || !w) return;
    __try {
        if (pWorldTicks) *ticks = pWorldTicks((void*)w);
        if (pWorldTime)  *secs  = pWorldTime((void*)w);
    } __except (EXCEPTION_EXECUTE_HANDLER) {}
}

static bool RememberEntity(uintptr_t ent) // true = nowa
{
    AcquireSRWLockExclusive(&g_entLock);
    bool isNew = g_entities->insert(ent).second;
    ReleaseSRWLockExclusive(&g_entLock);
    return isNew;
}

static bool KnownEntity(uintptr_t p)
{
    AcquireSRWLockShared(&g_entLock);
    bool k = g_entities->count(p) != 0;
    ReleaseSRWLockShared(&g_entLock);
    return k;
}

// zapisuje linię "E" przy pierwszym zobaczeniu encji
static void DescribeEntityOnce(uintptr_t ent)
{
    if (!ent || !RememberEntity(ent)) return;
    EntInfo e; QueryEntity(ent, &e);
    Log("E ent=%p ok=%d id=%lu owner=%p squad=%p squadId=%lu bp=%s squadBp=%s\n",
        (void*)ent, e.ok, e.id, (void*)e.owner, (void*)e.squad, e.squadId, e.bp, e.squadBp);
}

static void FormatAddr(uintptr_t a, char* out, size_t cap)
{
    if (a >= g_modBase && a < g_modBase + g_modSize)      _snprintf_s(out, cap, _TRUNCATE, "M+%llx", (unsigned long long)(a - g_modBase));
    else if (a >= g_simBase && a < g_simBase + g_simSize) _snprintf_s(out, cap, _TRUNCATE, "S+%llx", (unsigned long long)(a - g_simBase));
    else {
        HMODULE h = nullptr; char name[MAX_PATH] = "?";
        if (GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT, (LPCSTR)a, &h) && h) {
            char full[MAX_PATH]; GetModuleFileNameA(h, full, MAX_PATH);
            const char* b = strrchr(full, '\\'); strncpy_s(name, b ? b + 1 : full, _TRUNCATE);
            _snprintf_s(out, cap, _TRUNCATE, "%s+%llx", name, (unsigned long long)(a - (uintptr_t)h));
        } else _snprintf_s(out, cap, _TRUNCATE, "%p", (void*)a);
    }
}

static void AppendStack(char* line, size_t cap)
{
    void* frames[kStackFrames + 8];
    USHORT n = RtlCaptureStackBackTrace(0, kStackFrames + 8, frames, nullptr);
    size_t len = strlen(line);
    _snprintf_s(line + len, cap - len, _TRUNCATE, " stk=");
    int out = 0;
    for (USHORT i = 0; i < n && out < kStackFrames; ++i) {
        uintptr_t a = (uintptr_t)frames[i];
        if (a >= g_selfBase && a < g_selfBase + g_selfSize) continue; // własne ramki sondy
        char s[96]; FormatAddr(a, s, sizeof(s));
        len = strlen(line);
        _snprintf_s(line + len, cap - len, _TRUNCATE, out++ ? ",%s" : "%s", s);
    }
}

// przeszukuje stos nad ramką detoura w poszukiwaniu wskaźników do znanych encji (innych niż ofiara)
static void AppendStackEntities(char* line, size_t cap, const void* from, uintptr_t victim)
{
    ULONG_PTR lo = 0, hi = 0; GetCurrentThreadStackLimits(&lo, &hi);
    uintptr_t p = (uintptr_t)from & ~(uintptr_t)7, end = p + kStackScanBytes;
    if (end > hi) end = hi;
    size_t len = strlen(line);
    _snprintf_s(line + len, cap - len, _TRUNCATE, " sent=");
    int found = 0;
    for (; p < end && found < 12; p += 8) {
        uintptr_t v = *(uintptr_t*)p;
        if (v && v != victim && KnownEntity(v)) {
            unsigned long id = 0;
            __try { id = pEntGetId ? pEntGetId((void*)v) : 0; } __except (EXCEPTION_EXECUTE_HANDLER) {}
            len = strlen(line);
            _snprintf_s(line + len, cap - len, _TRUNCATE, "%s+%llx:%lu", found ? "," : "",
                        (unsigned long long)(p - (uintptr_t)from), id);
            ++found;
        }
    }
}

// kontekst bieżącego wywołania ApplyDamage w tym wątku (zagnieżdżenia łączone listą)
struct AppCtx { long long seq; float hpLoss; int deaths; int sets; AppCtx* prev; };
static thread_local AppCtx* t_app;

static void EmitEvent(const char* kind, void* hx, float a, float b, float c, uint64_t flag, const void* stackFrom)
{
    if (t_app) {
        if (kind[0] == 'S') { t_app->hpLoss += a - b; t_app->sets++; }
        else if (kind[0] == 'D' && kind[1] == 'I') t_app->deaths++;
    }
    uintptr_t ent = EntityFromHealthExt(hx);
    DescribeEntityOnce(ent);
    unsigned long id = 0;
    if (ent) { __try { id = pEntGetId ? pEntGetId((void*)ent) : 0; } __except (EXCEPTION_EXECUTE_HANDLER) {} }
    int ticks; float secs; GameTime(&ticks, &secs);
    char line[3072];
    _snprintf_s(line, sizeof(line), _TRUNCATE, "%s seq=%lld tid=%lu tick=%d t=%.3f hx=%p ent=%p id=%lu a=%.4f b=%.4f c=%.4f f=%llu",
                kind, (long long)InterlockedIncrement64(&g_seq), GetCurrentThreadId(), ticks, secs, hx, (void*)ent, id,
                a, b, c, (unsigned long long)flag);
    size_t len = strlen(line);
    _snprintf_s(line + len, sizeof(line) - len, _TRUNCATE, " app=%lld", t_app ? t_app->seq : 0LL);
    AppendStack(line, sizeof(line));
    AppendStackEntities(line, sizeof(line), stackFrom, ent);
    len = strlen(line);
    _snprintf_s(line + len, sizeof(line) - len, _TRUNCATE, "\n");
    Log("%s", line);
}

// ---------------------------------------------------------------- detoury
static float ReadHealth(void* hx, float* maxOut)
{
    float frac = 0, mx = 0;
    __try { frac = *(float*)((char*)hx + 0x28); mx = *(float*)((char*)hx + 0x2c); } __except (EXCEPTION_EXECUTE_HANDLER) {}
    *maxOut = mx; return frac * mx;
}

static void hkSetHealth(void* self, float value)
{
    if (g_armed) {
        float mx; float old = ReadHealth(self, &mx);
        if (value < old - 1e-4f) { InterlockedIncrement64(&g_cntSet); EmitEvent("SET", self, old, value, mx, 0, _AddressOfReturnAddress()); }
        else if (value > old + 1e-4f) InterlockedIncrement64(&g_cntHeal); // leczenie/regeneracja – tylko licznik
    }
    oSetHealth(self, value);
}

static void hkTakeDamage(void* self, float amount, uint64_t flag)
{
    if (g_armed) {
        float mx; float old = ReadHealth(self, &mx);
        InterlockedIncrement64(&g_cntDmg);
        EmitEvent("DMG", self, amount, old, mx, flag & 0xff, _AddressOfReturnAddress());
    }
    oTakeDamage(self, amount, flag);
}

static void hkDeath(void* self, uint64_t flag)
{
    if (g_armed) {
        float mx; float old = ReadHealth(self, &mx);
        InterlockedIncrement64(&g_cntDeath);
        EmitEvent("DIE", self, old, 0, mx, flag & 0xff, _AddressOfReturnAddress());
    }
    oDeath(self, flag);
}

// ---------------------------------------------------------------- ApplyDamage (sonda v2)
// HIPOTEZA z analizy statycznej DXP3Mod 0x15fbc0:
//   float ApplyDamage(Entity* victim, Entity* attacker, ? r8, WeaponInfo? r9, float f5, byte b6) -> zadane obrażenia
typedef float (*FnApplyDamage)(void* victim, void* attacker, void* r8, void* r9, float f5, uint64_t b6);
static FnApplyDamage oApplyDamage;
static void* g_tApplyDamage;
static volatile LONG64 g_cntApp;

// nazwa klasy z RTTI MSVC x64 (obj -> vtable -> CompleteObjectLocator -> TypeDescriptor)
static bool RttiName(uintptr_t obj, char* out, size_t cap)
{
    out[0] = 0;
    __try {
        uintptr_t vt = *(uintptr_t*)obj;
        uintptr_t col = *(uintptr_t*)(vt - 8);
        if (*(uint32_t*)col != 1) return false;                 // signature x64
        uintptr_t img = col - *(uint32_t*)(col + 0x14);         // pSelf RVA
        const char* nm = (const char*)(img + *(uint32_t*)(col + 0xC) + 0x10);
        if (nm[0] == '.' && nm[1] == '?') nm += 4;              // ".?AV"
        size_t i = 0;
        for (; i + 1 < cap && nm[i] && !(nm[i] == '@' && nm[i + 1] == '@'); ++i) out[i] = nm[i];
        out[i] = 0;
        return true;
    } __except (EXCEPTION_EXECUTE_HANDLER) { out[0] = 0; return false; }
}

// MSVC std::string: dane inline (<16) albo wskaźnik; [+0x10]=size, [+0x18]=capacity
static void ReadStdString(uintptr_t s, char* out, size_t cap)
{
    out[0] = 0;
    __try {
        size_t size = *(size_t*)(s + 0x10), capy = *(size_t*)(s + 0x18);
        if (size > 512 || capy < size) return;
        const char* p = capy > 15 ? *(const char**)s : (const char*)s;
        size_t i = 0;
        for (; i + 1 < cap && i < size; ++i) out[i] = (p[i] > 32 && p[i] < 127) ? p[i] : '_';
        out[i] = 0;
    } __except (EXCEPTION_EXECUTE_HANDLER) { out[0] = 0; }
}

// czy pod p jest czytelny napis ASCII (>= 4 znaki); kopiuje do out
static bool ProbeCStr(uintptr_t p, char* out, size_t cap)
{
    __try {
        const char* s = (const char*)p; size_t i = 0;
        for (; i + 1 < cap && s[i]; ++i) { if (s[i] < 32 || s[i] > 126) return false; out[i] = s[i]; }
        out[i] = 0;
        return i >= 4 && s[i] == 0;
    } __except (EXCEPTION_EXECUTE_HANDLER) { return false; }
}

// jednorazowy zrzut napisów osiągalnych z obiektu: char* na offsetach, std::string inline/heap, i 1 poziom głębiej
static void DumpStrings(const char* tag, uintptr_t obj, const char* idText)
{
    static SRWLOCK lock = SRWLOCK_INIT;
    static std::unordered_set<uintptr_t>* seen = new std::unordered_set<uintptr_t>();
    AcquireSRWLockExclusive(&lock);
    bool isNew = seen->insert(obj).second;
    ReleaseSRWLockExclusive(&lock);
    if (!isNew || !obj) return;
    char line[4096]; size_t len = 0;
    len += _snprintf_s(line, sizeof(line), _TRUNCATE, "%s obj=%p id=%s:", tag, (void*)obj, idText);
    for (uintptr_t off = 0; off < 0x400 && len < sizeof(line) - 300; off += 8) {
        uintptr_t q = 0; char s[120];
        if (!SafeReadPtr((void*)(obj + off), &q)) break;
        if (ProbeCStr(obj + off, s, sizeof(s)) && strlen(s) >= 4) { // inline (np. SSO std::string)
            len += _snprintf_s(line + len, sizeof(line) - len, _TRUNCATE, " +%llx=in'%s'", (unsigned long long)off, s);
            continue;
        }
        if (q < 0x10000 || q > 0x7FFFFFFFFFFF) continue;
        if (ProbeCStr(q, s, sizeof(s))) {
            len += _snprintf_s(line + len, sizeof(line) - len, _TRUNCATE, " +%llx='%s'", (unsigned long long)off, s);
            continue;
        }
        for (uintptr_t o2 = 0; o2 < 0x60; o2 += 8) { // jeden poziom głębiej
            uintptr_t q2 = 0;
            if (!SafeReadPtr((void*)(q + o2), &q2) || q2 < 0x10000 || q2 > 0x7FFFFFFFFFFF) continue;
            if (ProbeCStr(q2, s, sizeof(s))) {
                len += _snprintf_s(line + len, sizeof(line) - len, _TRUNCATE, " +%llx->+%llx='%s'",
                                   (unsigned long long)off, (unsigned long long)o2, s);
                break;
            }
        }
    }
    _snprintf_s(line + len, sizeof(line) - len, _TRUNCATE, "\n");
    Log("%s", line);
}

static void EntShort(uintptr_t ent, char* out, size_t cap)
{
    if (!ent) { _snprintf_s(out, cap, _TRUNCATE, "0"); return; }
    DescribeEntityOnce(ent);
    EntInfo e; QueryEntity(ent, &e);
    _snprintf_s(out, cap, _TRUNCATE, "%lu:%s:sq%lu:own%p", e.id, e.ok ? e.bp : "?", e.squadId, (void*)e.owner);
}

static float hkApplyDamage(void* victim, void* attacker, void* r8, void* r9, float f5, uint64_t b6)
{
    if (!g_armed) return oApplyDamage(victim, attacker, r8, r9, f5, b6);
    AppCtx ctx = { InterlockedIncrement64(&g_seq), 0.f, 0, 0, t_app };
    t_app = &ctx;
    float res = oApplyDamage(victim, attacker, r8, r9, f5, b6);
    t_app = ctx.prev;
    InterlockedIncrement64(&g_cntApp);

    char v[256], a[256], c8[96], c9[96], wname[160] = "", wid[32] = "?";
    EntShort((uintptr_t)victim, v, sizeof(v));
    EntShort((uintptr_t)attacker, a, sizeof(a));
    if (r8) RttiName((uintptr_t)r8, c8, sizeof(c8)); else c8[0] = 0;
    if (r9) {
        RttiName((uintptr_t)r9, c9, sizeof(c9));
        ReadStdString((uintptr_t)r9 + 0x120, wname, sizeof(wname));
        __try { _snprintf_s(wid, sizeof(wid), _TRUNCATE, "%d/%u", *(int*)((char*)r9 + 0x10), *(uint8_t*)((char*)r9 + 0x5e)); }
        __except (EXCEPTION_EXECUTE_HANDLER) {}
    } else c9[0] = 0;
    if (r9) DumpStrings("WI", (uintptr_t)r9, wid);
    if (r8) DumpStrings("R8", (uintptr_t)r8, wid);
    int ticks; float secs; GameTime(&ticks, &secs);
    char stk[512] = "";
    AppendStack(stk, sizeof(stk));
    Log("APP seq=%lld tick=%d t=%.3f victim=%s attacker=%s res=%.4f hpLoss=%.4f sets=%d deaths=%d f5=%.4f b6=%u "
        "r8=%p(%s) r9=%p(%s) w=%s wid=%s%s\n",
        ctx.seq, ticks, secs, v, a, res, ctx.hpLoss, ctx.sets, ctx.deaths, f5, (unsigned)(b6 & 0xff),
        r8, c8, r9, c9, wname, wid, stk);
    return res;
}

// początek funkcji zawierającej adres (podąża za łańcuchem UNW_FLAG_CHAININFO)
static uintptr_t FunctionStart(uintptr_t addr)
{
    DWORD64 img = 0;
    PRUNTIME_FUNCTION rf = RtlLookupFunctionEntry(addr, &img, nullptr);
    while (rf) {
        uint8_t* ui = (uint8_t*)(img + rf->UnwindData);
        if (!((ui[0] >> 3) & UNW_FLAG_CHAININFO)) return (uintptr_t)(img + rf->BeginAddress);
        uint8_t count = ui[2];
        rf = (PRUNTIME_FUNCTION)(ui + 4 + ((count + 1) & ~1) * 2);
    }
    return 0;
}

// ---------------------------------------------------------------- bezpiecznik: NtCreateFile
static void SetGameHooks(bool on)
{
    void* t[] = { g_tSetHealth, g_tTakeDamage, g_tDeath, g_tApplyDamage };
    for (void* x : t) if (x) on ? MH_EnableHook(x) : MH_DisableHook(x);
}

static bool EndsWithRec(const UNICODE_STRING* s)
{
    if (!s || !s->Buffer || s->Length < 8) return false;
    size_t n = s->Length / 2;
    const wchar_t* e = s->Buffer + n - 4;
    return _wcsnicmp(e, L".rec", 4) == 0;
}

static NTSTATUS NTAPI hkNtCreateFile(PHANDLE h, ACCESS_MASK access, POBJECT_ATTRIBUTES oa, PIO_STATUS_BLOCK io,
                                     PLARGE_INTEGER alloc, ULONG attrs, ULONG share, ULONG disp, ULONG opts, PVOID ea, ULONG eal)
{
    NTSTATUS st = oNtCreateFile(h, access, oa, io, alloc, attrs, share, disp, opts, ea, eal);
    __try {
        if (oa && EndsWithRec(oa->ObjectName)) {
            bool write = (access & (GENERIC_WRITE | FILE_WRITE_DATA | FILE_APPEND_DATA)) != 0;
            char path[600] = {0};
            WideCharToMultiByte(CP_UTF8, 0, oa->ObjectName->Buffer, oa->ObjectName->Length / 2, path, sizeof(path) - 1, nullptr, nullptr);
            Log("FILE rec %s access=0x%lx disp=%lu status=0x%lx path=%s\n", write ? "WRITE" : "READ", access, disp, (unsigned long)st, path);
            // Reguła:
            //   odczyt .rec                          => odtwarzanie powtórki => sonda włączona
            //   zapis .rec do 30 s po odczycie .rec  => to samo odtwarzanie (gra przy starcie powtórki tworzy temp.rec,
            //                                           potwierdzone logiem 2026-10-17) => bez zmian
            //   inny zapis .rec                      => gra na żywo nagrywa temp.rec => sonda wyłączona (hooki zdjęte)
            // Hooki zakłada/zdejmuje wątek roboczy (nie robimy tego wewnątrz NtCreateFile).
            static ULONGLONG lastReadMs;
            if (st >= 0) {
                ULONGLONG now = GetTickCount64();
                if (!write) lastReadMs = now;
                else if (lastReadMs && now - lastReadMs < 30000) {
                    Log("GUARD: zapis .rec %llu ms po odczycie powtorki - traktuje jako czesc odtwarzania\n", now - lastReadMs);
                    __leave;
                }
                LONG want = write ? 0 : 1;
                if (InterlockedExchange(&g_armed, want) != want) {
                    Log("GUARD: %s\n", want ? "otwarto .rec do odczytu - sonda WLACZONA" : "zapis .rec (gra na zywo?) - sonda WYLACZONA");
                    SetEvent(g_armEvent);
                }
            }
        }
    } __except (EXCEPTION_EXECUTE_HANDLER) {}
    return st;
}

// ---------------------------------------------------------------- skanowanie sygnatur
static uintptr_t FindPattern(uintptr_t base, const char* sig)
{
    auto dos = (IMAGE_DOS_HEADER*)base;
    auto nt  = (IMAGE_NT_HEADERS64*)(base + dos->e_lfanew);
    auto sec = IMAGE_FIRST_SECTION(nt);
    uint8_t pat[128]; bool wild[128]; int n = 0;
    for (const char* p = sig; *p && n < 128;) {
        while (*p == ' ') ++p;
        if (!*p) break;
        if (p[0] == '?') { wild[n] = true; pat[n++] = 0; p += (p[1] == '?') ? 2 : 1; }
        else { wild[n] = false; pat[n++] = (uint8_t)strtoul(p, nullptr, 16); p += 2; }
    }
    uintptr_t hit = 0; int hits = 0;
    for (WORD i = 0; i < nt->FileHeader.NumberOfSections; ++i, ++sec) {
        if (!(sec->Characteristics & IMAGE_SCN_MEM_EXECUTE)) continue;
        uint8_t* s = (uint8_t*)(base + sec->VirtualAddress);
        size_t sz = sec->Misc.VirtualSize;
        for (size_t k = 0; k + n <= sz; ++k) {
            int j = 0;
            while (j < n && (wild[j] || s[k + j] == pat[j])) ++j;
            if (j == n) { if (!hits++) hit = (uintptr_t)(s + k); }
        }
    }
    return hits == 1 ? hit : 0; // tylko jednoznaczne trafienie
}

// Sygnatura TakeDamage pasuje we wszystkich czterech modach (W40k/WXP/DXP2/DXP3). SetHealth i Death wyznaczamy
// z wywołań wewnątrz łańcucha, bo ich prologi różnią się między modami (zob. analysis/resolve_chain.py).
static const char* SIG_TAKEDAMAGE = "40 53 48 83 EC 30 0F 29 74 24 20 0F 28 F1 48 8B D9 45 84 C0 74 ?? E8";
static const char* SIG_WORLDREF   = "48 8B 0D ?? ?? ?? ?? C7 44 24 40 58 54 4C 48"; // mov rcx,[rip+X] ; 'XTLH'
static const uint8_t CALL_SETHEALTH[] = { 0xF3, 0x0F, 0x5C, 0xC8, 0x48, 0x8B, 0xCB, 0xE8 }; // subss xmm1,xmm0; mov rcx,rbx; call
static const uint8_t CALL_DEATH[]     = { 0x33, 0xD2, 0x48, 0x8B, 0xCB, 0xE8 };             // xor edx,edx; mov rcx,rbx; call

// cel pierwszego wywołania poprzedzonego wzorcem w zakresie [from, from+limit)
static uintptr_t CallAfter(uintptr_t from, const uint8_t* pat, size_t n, size_t limit)
{
    if (!from) return 0;
    for (size_t k = 0; k + n + 4 <= limit; ++k) {
        if (memcmp((void*)(from + k), pat, n) == 0) {
            uintptr_t e8 = from + k + n - 1;
            return e8 + 5 + *(int32_t*)(e8 + 1);
        }
    }
    return 0;
}

static const wchar_t* kModDlls[] = { L"DXP3Mod.dll", L"DXP2Mod.dll", L"WXPMod.dll", L"W40kMod.dll" };

static uintptr_t ModuleSize(uintptr_t base)
{
    auto nt = (IMAGE_NT_HEADERS64*)(base + ((IMAGE_DOS_HEADER*)base)->e_lfanew);
    return nt->OptionalHeader.SizeOfImage;
}

static void ResolveSimEngine()
{
    HMODULE s = GetModuleHandleW(L"SimEngine.dll");
    if (!s) return;
    g_simBase = (uintptr_t)s; g_simSize = ModuleSize(g_simBase);
    pEntGetBp    = (FnEntGetBp)  GetProcAddress(s, "?GetBlueprintName@Entity@@QEBAPEBDXZ");
    pSquadGetBp  = (FnEntGetBp)  GetProcAddress(s, "?GetBlueprintName@Squad@@QEBAPEBDXZ");
    pEntGetId    = (FnEntGetId)  GetProcAddress(s, "?GetID@Entity@@QEBAKXZ");
    pSquadGetId  = (FnEntGetId)  GetProcAddress(s, "?GetID@Squad@@QEBAKXZ");
    pEntGetSquad = (FnEntGetPtr) GetProcAddress(s, "?GetSquad@Entity@@QEAAPEAVSquad@@XZ");
    pEntGetOwner = (FnEntGetPtr) GetProcAddress(s, "?GetOwner@Entity@@QEAAPEAVPlayer@@XZ");
    pWorldTicks  = (FnWorldTicks)GetProcAddress(s, "?GetGameTicks@World@@QEBAJXZ");
    pWorldTime   = (FnWorldTime) GetProcAddress(s, "?GetGameTime@World@@QEBAMXZ");
    Log("INFO SimEngine=%p bp=%p sbp=%p id=%p sid=%p gsq=%p gown=%p ticks=%p time=%p\n", s, pEntGetBp, pSquadGetBp,
        pEntGetId, pSquadGetId, pEntGetSquad, pEntGetOwner, pWorldTicks, pWorldTime);
}

static bool HookAt(uintptr_t target, void* detour, void** orig, void** saveTarget, const char* name)
{
    if (!target) { Log("ERR sygnatura %s nie znaleziona (lub niejednoznaczna) – hook pominięty\n", name); return false; }
    MH_STATUS st = MH_CreateHook((void*)target, detour, orig);
    Log("HOOK %s at M+%llx status=%d\n", name, (unsigned long long)(target - g_modBase), (int)st);
    if (st != MH_OK) return false;
    *saveTarget = (void*)target;
    return true;
}

static DWORD WINAPI InitThread(LPVOID)
{
    // czekamy (bez limitu) na DLL aktywnego moda – ładuje się dopiero po ekranie startowym. "M+" w logu = RVA w tej DLL.
    Log("INFO czekam na DLL moda...\n");
    HMODULE mod = nullptr; const wchar_t* modName = nullptr;
    while (!mod) {
        for (const wchar_t* n : kModDlls) if ((mod = GetModuleHandleW(n)) != nullptr) { modName = n; break; }
        if (!mod) Sleep(250);
    }
    Sleep(500); // niech mod dokończy inicjalizację
    g_modBase = (uintptr_t)mod; g_modSize = ModuleSize(g_modBase);
    Log("INFO mod=%ls base=%p size=0x%llx (M+ = RVA w tej DLL)\n", modName, mod, (unsigned long long)g_modSize);
    ResolveSimEngine();

    uintptr_t wref = FindPattern(g_modBase, SIG_WORLDREF);
    if (wref) {
        g_worldGlobal = (void**)(wref + 7 + *(int32_t*)(wref + 3));
        Log("INFO World global at M+%llx\n", (unsigned long long)((uintptr_t)g_worldGlobal - g_modBase));
    } else Log("WARN brak sygnatury World – czas gry niedostępny\n");

    if (MH_Initialize() != MH_OK) { Log("ERR MH_Initialize\n"); return 0; }
    uintptr_t td = FindPattern(g_modBase, SIG_TAKEDAMAGE);
    uintptr_t sh = CallAfter(td, CALL_SETHEALTH, sizeof(CALL_SETHEALTH), 0x100);
    uintptr_t de = CallAfter(sh, CALL_DEATH, sizeof(CALL_DEATH), 0x140);
    HookAt(sh, (void*)hkSetHealth,  (void**)&oSetHealth,  &g_tSetHealth,  "SetHealth");
    HookAt(td, (void*)hkTakeDamage, (void**)&oTakeDamage, &g_tTakeDamage, "TakeDamage");
    HookAt(de, (void*)hkDeath,      (void**)&oDeath,      &g_tDeath,      "Death");

    // ApplyDamage: funkcja z wywołaniem "mov r8b,1; movaps xmm1,xmm7; mov rcx,rdi; call TakeDamage" (DXP3/DXP2)
    uintptr_t ap = 0; int apHits = 0;
    if (td) {
        auto nt = (IMAGE_NT_HEADERS64*)(g_modBase + ((IMAGE_DOS_HEADER*)g_modBase)->e_lfanew);
        auto sec = IMAGE_FIRST_SECTION(nt);
        for (WORD i = 0; i < nt->FileHeader.NumberOfSections; ++i, ++sec) {
            if (!(sec->Characteristics & IMAGE_SCN_MEM_EXECUTE)) continue;
            uint8_t* s = (uint8_t*)(g_modBase + sec->VirtualAddress);
            for (size_t k = 0; k + 14 <= sec->Misc.VirtualSize; ++k) {
                if (memcmp(s + k, "\x41\xB0\x01\x0F\x28\xCF\x48\x8B\xCF\xE8", 10) != 0) continue;
                uintptr_t e8 = (uintptr_t)(s + k + 9);
                if (e8 + 5 + *(int32_t*)(e8 + 1) != td) continue;
                uintptr_t f = FunctionStart(e8);
                if (f && f != ap) { ap = f; ++apHits; }
            }
        }
    }
    if (apHits == 1) HookAt(ap, (void*)hkApplyDamage, (void**)&oApplyDamage, &g_tApplyDamage, "ApplyDamage");
    else Log("ERR ApplyDamage: %d kandydatów – hook pominięty\n", apHits);

    void* ntc = (void*)GetProcAddress(GetModuleHandleW(L"ntdll.dll"), "NtCreateFile");
    if (ntc && MH_CreateHook(ntc, (void*)hkNtCreateFile, (void**)&oNtCreateFile) == MH_OK && MH_EnableHook(ntc) == MH_OK) {
        g_tNtCreateFile = ntc;
        Log("INFO bezpiecznik NtCreateFile aktywny; hooki gry czekają na otwarcie .rec do odczytu\n");
    } else {
        Log("ERR nie udało się założyć bezpiecznika NtCreateFile – hooki gry NIE zostaną włączone\n");
    }
    // Wątek roboczy: zakłada/zdejmuje hooki gry zgodnie z bezpiecznikiem, co 10 s zapisuje liczniki
    LONG applied = 0;
    for (;;) {
        DWORD w = WaitForSingleObject(g_armEvent, 10000);
        LONG want = g_armed;
        if (want != applied) { SetGameHooks(want != 0); applied = want; Log("HOOKS %s\n", want ? "ON" : "OFF"); }
        if (w == WAIT_TIMEOUT) {
            int ticks; float secs; GameTime(&ticks, &secs);
            AcquireSRWLockShared(&g_entLock); size_t ne = g_entities->size(); ReleaseSRWLockShared(&g_entLock);
            Log("STAT armed=%ld tick=%d t=%.1f set=%lld dmg=%lld die=%lld heal=%lld app=%lld ents=%zu\n", g_armed, ticks, secs,
                g_cntSet, g_cntDmg, g_cntDeath, g_cntHeal, g_cntApp, ne);
        }
    }
}

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID)
{
    if (reason != DLL_PROCESS_ATTACH) return TRUE;
    DisableThreadLibraryCalls(inst);

    // Zabezpieczenie: tylko przez dowprobe_launcher.exe
    wchar_t flag[16] = {0};
    if (!GetEnvironmentVariableW(L"DOWPROBE_LAUNCHER", flag, 16) || wcscmp(flag, L"1") != 0) return TRUE;

    wchar_t path[MAX_PATH] = {0};
    if (!GetEnvironmentVariableW(L"DOWPROBE_LOG", path, MAX_PATH)) return TRUE;
    g_log = _wfsopen(path, L"wb", _SH_DENYWR); // inne procesy mogą czytać log w trakcie
    if (!g_log) return TRUE;
    setvbuf(g_log, nullptr, _IOFBF, 1 << 20);
    g_selfBase = (uintptr_t)inst; g_selfSize = ModuleSize(g_selfBase);
    g_armEvent = CreateEventW(nullptr, FALSE, FALSE, nullptr);
    g_entities = new std::unordered_set<uintptr_t>();
    g_entities->reserve(1 << 14);
    Log("# dowprobe v2 pid=%lu\n# kolumny: KIND seq tid tick t hx ent id a b c f stk sent\n"
        "# SET: a=stare zdrowie b=nowe c=max | DMG: a=kwota b=zdrowie przed c=max f=r8b | DIE: a=zdrowie c=max f=dl\n"
        "# APP: victim/attacker = id:bp:sqSquadId:ownPlayer, res=zwrot (obrazenia), hpLoss/deaths = SET/DIE wewnatrz, w=std::string z [r9+0x120]\n"
        "# stk: M+rva = DLL moda (patrz INFO mod=), S+rva = SimEngine.dll | sent: offset_od_ramki:ID innej znanej encji na stosie\n",
        GetCurrentProcessId());
    CloseHandle(CreateThread(nullptr, 0, InitThread, nullptr, 0, nullptr));
    CloseHandle(CreateThread(nullptr, 0, FlushThread, nullptr, 0, nullptr));
    return TRUE;
}
