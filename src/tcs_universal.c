/*
 * TCS Universal Patch - a dinput8.dll proxy for LEGO Star Wars: The Complete Saga (PC).
 *
 * Turns several identity-hardcoded behaviours into opt-in character-file keywords and an INI section.
 * Nothing changes unless a character file uses one of the new keywords or the INI enables a feature.
 *
 *   behaviour="jedi"        which native behaviour routine (and AI routine) the character runs
 *   bullet="ewokpebble"     which projectile type the character fires (name or number)
 *   pull_levers / pull_levers off   allow or forbid pulling levers, whatever the categories say
 *   [arena] in TCSUniversal.ini     which Jedi the Geonosis arena spawns, and how many at once
 *   [characters] in TCSUniversal.ini   the same keywords by character name, without editing game files
 *
 * Supported build: the Steam executable (SteamStub 2.1, sha256 085688e7...) and its unwrapped image
 * (sha256 6c9c2b35...). Both share the image timestamp 0x4AC4A20B. Every patch site is compared with
 * the expected bytes first; any mismatch disables that patch and is written to TCSUniversal.log.
 *
 * Licence: MIT. Credit: Gibby.
 */
#define _CRT_SECURE_NO_WARNINGS
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdarg.h>

/* ------------------------------------------------------------------ game addresses (image base 0x400000) */
#define EXE_TIMESTAMP      0x4AC4A20Bu
#define IAT_GETCOMMANDLINEA 0x00751178u

#define G_DEF_A_ARRAY   (*(char **)0x0093B274)   /* character definition A, stride 0x4C, flags at +4  */
#define G_DEF_COUNT     (*(int *)0x0093B278)
#define G_DEF_B_ARRAY   (*(char **)0x0093B284)   /* character definition B, stride 0x120             */
#define G_PARSE_INDEX   (*(short *)0x0095441C)   /* index of the definition being parsed             */
#define G_FREEPLAY      (*(int *)0x0093B2A4)
#define DEF_A(i)        (G_DEF_A_ARRAY + (i) * 0x4C)
#define DEF_B(i)        (G_DEF_B_ARRAY + (i) * 0x120)
#define CHAR_ID(c)      (*(short *)((char *)(c) + 0x1064))
#define TOKEN(ctx)      (*(char **)((char *)(ctx) + 0x510))

typedef int   (__cdecl *fn_next_token)(void *ctx);
typedef int   (__cdecl *fn_read_int)(void *ctx);
typedef short (__cdecl *fn_char_index)(const char *name);
typedef float (__cdecl *fn_randf)(void);
typedef void  (__cdecl *fn_void)(void);
static const fn_next_token next_token = (fn_next_token)0x004F7FB0;
static const fn_read_int   read_int   = (fn_read_int)0x004F9E70;
static const fn_char_index char_index = (fn_char_index)0x0055B1C0;
static const fn_randf      randf      = (fn_randf)0x005B9DD0;
static const fn_void       assign_behaviours = (fn_void)0x00414400;

#define KEYWORD_TABLE      0x00804248u   /* {name, handler} pairs, 207 entries, {0,0} ends it */
#define KEYWORD_TABLE_PUSH 0x005896D6u   /* push imm32 of the table in the character loader   */
#define ASSIGN_CALL        0x0048ABFDu   /* call FUN_00414400 after the definitions are read   */
#define BULLET_PICKER      0x00407E40u
#define LEVER_RULE         0x0055E470u
#define LEVER_RULE_2       0x0055F360u
#define ARENA_PICK         0x004DE2A0u
#define ARENA_CALL_1       0x004DEABDu
#define ARENA_CALL_2       0x004DF8B9u
#define BULLET_TABLE       0x007EF388u   /* 0xA4 bytes per type, name first */
#define BULLET_COUNT       0x2C

#define MAX_DEFS 512

/* ------------------------------------------------------------------ state */
static signed char g_behaviour[MAX_DEFS];
static short       g_bullet[MAX_DEFS];
static signed char g_levers[MAX_DEFS];
static FILE *g_log;
static int g_patched;
static FARPROC g_real_GetCommandLineA;

static struct {
    int enabled, max_at_once, respawn, freeplay;
    char names[16][64];
    int count;
    short ids[16];
    int resolved;
    unsigned used_mask;
    int next;
} g_arena;

static void tlog(const char *fmt, ...)
{
    va_list ap;
    if (!g_log) return;
    va_start(ap, fmt);
    vfprintf(g_log, fmt, ap);
    va_end(ap);
    fputc('\n', g_log);
    fflush(g_log);
}

/* ------------------------------------------------------------------ behaviours (from FUN_00414400) */
typedef struct { const char *name; DWORD update, ai, extra; } Behaviour;
static const Behaviour BEHAVIOURS[] = {
    { "standard",         0x004B4AC0, 0x004A8F20, 0 },  /* default for unmatched characters: jump, vehicles, levers */
    { "jedi",             0x004B3390, 0x004A9B80, 0 },  /* jedi flag; MagnaGuard and Royal Guard by identity        */
    { "droid",            0x004B5EF0, 0x004A8F20, 0 },  /* droid without bounty_hunter: no jump, no vehicles         */
    { "protocol",         0x004B5EF0, 0x004AA2C0, 0 },
    { "astromech",        0x004B5EF0, 0x004A9E40, 0x004A9F60 },
    { "beast",            0x004B3000, 0x004A9800, 0 },
    { "winged",           0x004B65F0, 0x004AB100, 0 },  /* hover_wings (Geonosians)                                   */
    { "superbattledroid", 0x004B5E10, 0x004AA670, 0 },
    { "droideka",         0x004B6520, 0x004AB010, 0 },
    { "jawa",             0x004B3B80, 0,          0 },  /* jawa and ugnaught keep their AI                            */
    { "variant0",         0x004B5820, 0x004A9940, 0 },  /* routine of variant 0 characters                           */
};
#define BEHAVIOUR_COUNT (sizeof(BEHAVIOURS) / sizeof(BEHAVIOURS[0]))

/* ------------------------------------------------------------------ helpers */
static void unquote(const char *in, char *out, size_t n)
{
    size_t len;
    if (!in) { out[0] = 0; return; }
    while (*in == '"' || *in == '=' || *in == ' ') in++;
    strncpy(out, in, n - 1);
    out[n - 1] = 0;
    len = strlen(out);
    while (len && (out[len - 1] == '"' || out[len - 1] == ' ')) out[--len] = 0;
}

static int write_code(DWORD addr, const void *bytes, size_t n)
{
    DWORD old;
    if (!VirtualProtect((void *)addr, n, PAGE_EXECUTE_READWRITE, &old)) return 0;
    memcpy((void *)addr, bytes, n);
    VirtualProtect((void *)addr, n, old, &old);
    FlushInstructionCache(GetCurrentProcess(), (void *)addr, n);
    return 1;
}

static int hexval(char c)
{
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static int expect(DWORD addr, const char *hex, const char *what)
{
    unsigned char want[32];
    size_t n = 0;
    while (*hex && n < sizeof want) {
        int hi, lo;
        while (*hex == ' ') hex++;
        hi = hexval(hex[0]);
        lo = hex[0] ? hexval(hex[1]) : -1;
        if (hi < 0 || lo < 0) break;
        want[n++] = (unsigned char)(hi * 16 + lo);
        hex += 2;
    }
    if (memcmp((void *)addr, want, n) != 0) {
        tlog("SKIP %s: bytes at %08X do not match this build", what, addr);
        return 0;
    }
    return 1;
}

static int write_call(DWORD at, void *target)
{
    unsigned char b[5];
    DWORD rel = (DWORD)target - (at + 5);
    b[0] = 0xE8;
    memcpy(b + 1, &rel, 4);
    return write_code(at, b, 5);
}

static int write_jmp(DWORD at, void *target)
{
    unsigned char b[5];
    DWORD rel = (DWORD)target - (at + 5);
    b[0] = 0xE9;
    memcpy(b + 1, &rel, 4);
    return write_code(at, b, 5);
}

/* ------------------------------------------------------------------ keyword handlers */
static int parse_index(void)
{
    int i = G_PARSE_INDEX;
    return (i >= 0 && i < MAX_DEFS) ? i : -1;
}

static void __cdecl kw_behaviour(void *ctx)
{
    char name[64];
    int i = parse_index(), b;
    if (i < 0 || !next_token(ctx)) return;
    unquote(TOKEN(ctx), name, sizeof name);
    for (b = 0; b < (int)BEHAVIOUR_COUNT; b++)
        if (!_stricmp(name, BEHAVIOURS[b].name)) { g_behaviour[i] = (signed char)b; return; }
    tlog("character %d: unknown behaviour \"%s\"", i, name);
}

static int bullet_from_name(const char *name)
{
    int t, v = 0;
    const char *c = name;
    while (*c >= '0' && *c <= '9') v = v * 10 + (*c++ - '0');
    if (*name && !*c) return v < BULLET_COUNT ? v : -1;
    for (t = 0; t < BULLET_COUNT; t++)
        if (!_stricmp(name, (const char *)(BULLET_TABLE + t * 0xA4))) return t;
    return -1;
}

static void __cdecl kw_bullet(void *ctx)
{
    char name[64];
    int i = parse_index(), t;
    if (i < 0 || !next_token(ctx)) return;
    unquote(TOKEN(ctx), name, sizeof name);
    t = bullet_from_name(name);
    if (t < 0) { tlog("character %d: unknown bullet \"%s\"", i, name); return; }
    g_bullet[i] = (short)t;
}

static void __cdecl kw_pull_levers(void *ctx)
{
    char word[16];
    int i = parse_index();
    if (i < 0) return;
    g_levers[i] = 1;
    if (next_token(ctx)) {
        unquote(TOKEN(ctx), word, sizeof word);
        if (!_stricmp(word, "off")) g_levers[i] = 0;
    }
}

/* the original table plus ours; built at patch time */
static DWORD g_keywords[2 * 260];

/* ------------------------------------------------------------------ behaviour assignment */
static char g_ini[MAX_PATH];

static void apply_value(int i, const char *key, const char *val)
{
    int b, t;
    if (!_stricmp(key, "behaviour") || !_stricmp(key, "behavior")) {
        for (b = 0; b < (int)BEHAVIOUR_COUNT; b++)
            if (!_stricmp(val, BEHAVIOURS[b].name)) { g_behaviour[i] = (signed char)b; return; }
        tlog("ini: unknown behaviour \"%s\"", val);
    } else if (!_stricmp(key, "bullet")) {
        if ((t = bullet_from_name(val)) >= 0) g_bullet[i] = (short)t;
        else tlog("ini: unknown bullet \"%s\"", val);
    } else if (!_stricmp(key, "pull_levers")) {
        g_levers[i] = (char)(_stricmp(val, "off") != 0);
    } else tlog("ini: unknown setting \"%s\"", key);
}

/* [characters]  name = behaviour=standard bullet=ewokpebble pull_levers=on */
static void apply_ini_characters(void)
{
    static char keys[8192];
    char *k;
    DWORD got = GetPrivateProfileStringA("characters", NULL, "", keys, sizeof keys, g_ini);
    for (k = keys; got && *k; k += strlen(k) + 1) {
        char line[512], *tok, *ctx = NULL;
        int i = char_index(k);
        if (i < 0 || i >= MAX_DEFS) { tlog("ini: no character \"%s\"", k); continue; }
        GetPrivateProfileStringA("characters", k, "", line, sizeof line, g_ini);
        for (tok = strtok_s(line, " \t", &ctx); tok; tok = strtok_s(NULL, " \t", &ctx)) {
            char *eq = strchr(tok, '=');
            char val[64];
            if (!eq) { apply_value(i, tok, "on"); continue; }
            *eq = 0;
            unquote(eq + 1, val, sizeof val);
            apply_value(i, tok, val);
        }
    }
}

static void __cdecl assign_wrapper(void)
{
    int i, n;
    assign_behaviours();
    apply_ini_characters();
    n = G_DEF_COUNT < MAX_DEFS ? G_DEF_COUNT : MAX_DEFS;
    for (i = 0; i < n; i++) {
        const Behaviour *b;
        if (g_behaviour[i] < 0) continue;
        b = &BEHAVIOURS[g_behaviour[i]];
        *(DWORD *)(DEF_A(i) + 0x18) = b->update;
        if (b->ai) *(DWORD *)(DEF_A(i) + 0x1C) = b->ai;
        if (b->extra) *(DWORD *)(DEF_A(i) + 0x20) = b->extra;
        tlog("character %d (%s): behaviour %s", i, *(char **)(DEF_A(i) + 0x0C), b->name);
    }
}

/* ------------------------------------------------------------------ projectile picker */
/* original first instruction is call 0x0055F450 (5 bytes); the trampoline replays it */
static __declspec(naked) int __cdecl bullet_original(void *chr, int deflt)
{
    __asm {
        mov eax, 0x0055F450
        call eax
        mov ecx, BULLET_PICKER + 5
        jmp ecx
    }
}

static int __cdecl bullet_hook(void *chr, int deflt)
{
    if (chr) {
        int id = CHAR_ID(chr);
        if (id >= 0 && id < MAX_DEFS && g_bullet[id] >= 0) return g_bullet[id];
    }
    return bullet_original(chr, deflt);
}

/* ------------------------------------------------------------------ lever rule */
static int __cdecl lever_rule(int id)
{
    unsigned flags;
    if (id >= 0 && id < MAX_DEFS && g_levers[id] >= 0) return g_levers[id];
    flags = *(unsigned *)(DEF_A(id) + 4);
    if ((flags & 0x1000010) == 0x1000010) return 0;   /* droid AND bounty hunter */
    return (flags & 0x40088) != 0;                      /* jedi, blaster or teleport */
}

static int __cdecl lever_rule_2(int id)
{
    if (id >= 0 && id < MAX_DEFS && g_levers[id] >= 0) return g_levers[id];
    if (*(unsigned char *)(DEF_B(id) + 0x90) & 0x10) return 0;
    return lever_rule(id);
}

/* ------------------------------------------------------------------ arena */
#define ARENA_SLOT_TYPE(s)  (*(int *)((char *)(s) + 0x10))
#define ARENA_SLOT_FLAGS(s) (*(unsigned *)((char *)(s) + 0x5C))
#define ARENA_SLOTS         ((char *)0x00882BD0)
#define ARENA_SLOT_COUNT    (*(short *)0x00888ED0)
#define ARENA_ONCE_BITS     (*(unsigned *)0x00888FB8)
#define ID_GEONOSIAN        (*(short *)0x007F18DC)
#define ID_BDROID_GEONOSIAN (*(short *)0x007F1890)
#define ID_BOB              (*(short *)0x007F19DC)

static void arena_resolve(void)
{
    int k;
    if (g_arena.resolved) return;
    for (k = 0; k < g_arena.count; k++) {
        g_arena.ids[k] = char_index(g_arena.names[k]);
        tlog("arena jedi %s -> %d", g_arena.names[k], g_arena.ids[k]);
    }
    g_arena.resolved = 1;
}

static int arena_is_jedi(int type)
{
    int k;
    for (k = 0; k < g_arena.count; k++)
        if (g_arena.ids[k] != -1 && g_arena.ids[k] == type) return k;
    return -1;
}

static void arena_set(char *slot, int type)
{
    ARENA_SLOT_FLAGS(slot) &= 0xFFFFFFE3;
    ARENA_SLOT_TYPE(slot) = type;
    *(int *)(slot + 0x58) = 0;
}

static void __cdecl arena_pick(char *slot)
{
    int i, k, live = 0;
    if (!slot) return;
    if (!(ARENA_SLOT_FLAGS(slot) & 2)) { arena_set(slot, ID_BOB); return; }
    arena_resolve();
    if (!(ARENA_ONCE_BITS & 1)) g_arena.used_mask = 0;  /* the level reset clears the stock bits */
    if (!G_FREEPLAY || g_arena.freeplay) {
        for (i = 0; i < ARENA_SLOT_COUNT; i++) {
            char *s = ARENA_SLOTS + i * 0x60;
            if (s != slot && arena_is_jedi(ARENA_SLOT_TYPE(s)) >= 0) live++;
        }
        if (live < g_arena.max_at_once && g_arena.count > 0) {
            for (k = 0; k < g_arena.count; k++) {
                int j = (g_arena.next + k) % g_arena.count;
                if (g_arena.ids[j] == -1) continue;
                if (!g_arena.respawn && (g_arena.used_mask & (1u << j))) continue;
                g_arena.next = j + 1;
                g_arena.used_mask |= 1u << j;
                ARENA_ONCE_BITS |= 1;
                arena_set(slot, g_arena.ids[j]);
                return;
            }
        }
    }
    arena_set(slot, randf() < 0.5f ? ID_BDROID_GEONOSIAN : ID_GEONOSIAN);
}

/* original convention: slot in ESI, no stack arguments */
static __declspec(naked) void arena_stub(void)
{
    __asm {
        push ecx
        push edx
        push esi
        call arena_pick
        add esp, 4
        pop edx
        pop ecx
        ret
    }
}

/* ------------------------------------------------------------------ config */
static void load_config(const char *dir)
{
    char ini[MAX_PATH], list[1024], *tok, *ctx = NULL;
    strcpy(ini, dir);
    strcat(ini, "\\TCSUniversal.ini");
    strcpy(g_ini, ini);
    g_arena.enabled     = GetPrivateProfileIntA("arena", "enabled", 0, ini);
    g_arena.max_at_once = GetPrivateProfileIntA("arena", "max_jedi_at_once", 2, ini);
    g_arena.respawn     = GetPrivateProfileIntA("arena", "respawn", 0, ini);
    g_arena.freeplay    = GetPrivateProfileIntA("arena", "in_freeplay", 0, ini);
    GetPrivateProfileStringA("arena", "jedi", "luminara,shaakti", list, sizeof list, ini);
    for (tok = strtok_s(list, ", ", &ctx); tok && g_arena.count < 16; tok = strtok_s(NULL, ", ", &ctx)) {
        strncpy(g_arena.names[g_arena.count], tok, 63);
        g_arena.count++;
    }
}

/* ------------------------------------------------------------------ patching */
static int code_is_decrypted(void)
{
    /* first bytes of the keyword table reference; encrypted text never matches */
    return memcmp((void *)KEYWORD_TABLE_PUSH, "\x68\x48\x42\x80\x00", 5) == 0;
}

static void apply_patches(void)
{
    int n = 0, k;
    DWORD imm;

    /* keyword table */
    while (((DWORD *)KEYWORD_TABLE)[2 * n]) n++;
    if (n == 207 && expect(KEYWORD_TABLE_PUSH, "68 48 42 80 00", "keywords")) {
        static const struct { const char *name; void *fn; } mine[] = {
            { "behaviour", kw_behaviour }, { "behavior", kw_behaviour },
            { "bullet", kw_bullet }, { "pull_levers", kw_pull_levers },
        };
        memcpy(g_keywords, (void *)KEYWORD_TABLE, n * 8);
        for (k = 0; k < 4; k++) {
            g_keywords[2 * (n + k)] = (DWORD)mine[k].name;
            g_keywords[2 * (n + k) + 1] = (DWORD)mine[k].fn;
        }
        imm = (DWORD)g_keywords;
        if (write_code(KEYWORD_TABLE_PUSH + 1, &imm, 4)) tlog("OK keywords (%d stock + 4)", n);
    } else if (n != 207) tlog("SKIP keywords: table has %d entries, expected 207", n);

    if (expect(ASSIGN_CALL, "e8 fe 97 f8 ff", "behaviour assignment") && write_call(ASSIGN_CALL, assign_wrapper))
        tlog("OK behaviour assignment");

    if (expect(BULLET_PICKER, "e8 0b 76 15 00 8b 4c 24 04 85", "bullet picker") && write_jmp(BULLET_PICKER, bullet_hook))
        tlog("OK bullet picker");

    if (expect(LEVER_RULE, "8b 44 24 04 8b 0d 74 b2 93 00 6b c0 4c", "lever rule") && write_jmp(LEVER_RULE, lever_rule))
        tlog("OK lever rule");
    if (expect(LEVER_RULE_2, "8b 44 24 04 8b 15 84 b2 93 00 8d 0c c0", "lever rule 2") && write_jmp(LEVER_RULE_2, lever_rule_2))
        tlog("OK lever rule 2");

    if (g_arena.enabled) {
        if (expect(ARENA_CALL_1, "e8 de f7 ff ff", "arena 1") && expect(ARENA_CALL_2, "e8 e2 e9 ff ff", "arena 2") &&
            expect(ARENA_PICK, "85 f6 0f 84 b0 00 00 00", "arena pick") &&
            write_call(ARENA_CALL_1, arena_stub) && write_call(ARENA_CALL_2, arena_stub))
            tlog("OK arena (%d jedi listed, %d at once, respawn %d, freeplay %d)",
                 g_arena.count, g_arena.max_at_once, g_arena.respawn, g_arena.freeplay);
    }
}

static LPSTR WINAPI hook_GetCommandLineA(void)
{
    if (!g_patched && code_is_decrypted()) {
        DWORD old;
        g_patched = 1;
        apply_patches();
        VirtualProtect((void *)IAT_GETCOMMANDLINEA, 4, PAGE_READWRITE, &old);
        *(FARPROC *)IAT_GETCOMMANDLINEA = g_real_GetCommandLineA;
        VirtualProtect((void *)IAT_GETCOMMANDLINEA, 4, old, &old);
    }
    return ((LPSTR(WINAPI *)(void))g_real_GetCommandLineA)();
}

static void reset_state(const char *dir)
{
    int i;
    memset(g_behaviour, -1, sizeof g_behaviour);
    memset(g_levers, -1, sizeof g_levers);
    for (i = 0; i < MAX_DEFS; i++) g_bullet[i] = -1;
    memset(&g_arena, 0, sizeof g_arena);
    g_patched = 0;
    load_config(dir);
}

/* checks the build and redirects the game's GetCommandLineA import; 1 when installed */
static int hook_import(void)
{
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)GetModuleHandleA(NULL);
    IMAGE_NT_HEADERS *nt = (IMAGE_NT_HEADERS *)((char *)dos + dos->e_lfanew);
    DWORD old;
    if ((DWORD)dos != 0x400000 || nt->FileHeader.TimeDateStamp != EXE_TIMESTAMP) {
        tlog("Not the supported LEGO Star Wars: The Complete Saga build (timestamp %08X); nothing patched.",
             nt->FileHeader.TimeDateStamp);
        return 0;
    }
    g_real_GetCommandLineA = GetProcAddress(GetModuleHandleA("kernel32.dll"), "GetCommandLineA");
    if (*(FARPROC *)IAT_GETCOMMANDLINEA != g_real_GetCommandLineA) {
        tlog("Unexpected import table entry for GetCommandLineA; nothing patched.");
        return 0;
    }
    VirtualProtect((void *)IAT_GETCOMMANDLINEA, 4, PAGE_READWRITE, &old);
    *(FARPROC *)IAT_GETCOMMANDLINEA = (FARPROC)hook_GetCommandLineA;
    VirtualProtect((void *)IAT_GETCOMMANDLINEA, 4, old, &old);
    tlog("TCS Universal Patch loaded; waiting for the game's start-up code.");
    return 1;
}

static void install(HMODULE self)
{
    char dir[MAX_PATH], path[MAX_PATH], *slash;
    GetModuleFileNameA(self, dir, sizeof dir);
    if ((slash = strrchr(dir, '\\')) != NULL) *slash = 0;
    strcpy(path, dir);
    strcat(path, "\\TCSUniversal.log");
    g_log = fopen(path, "w");
    reset_state(dir);
    hook_import();
}

#ifdef TCSU_TEST
/* entry points for the emulator tests (tests/emulate.py); not in the release build */
__declspec(dllexport) int __cdecl TCSU_TestInstall(const char *dir) { reset_state(dir); return hook_import(); }
__declspec(dllexport) void __cdecl TCSU_TestApply(void) { apply_patches(); }
#endif

/* ------------------------------------------------------------------ dinput8 proxy */
typedef HRESULT (WINAPI *fn_DirectInput8Create)(HINSTANCE, DWORD, REFIID, LPVOID *, LPVOID);
static fn_DirectInput8Create real_DirectInput8Create;

HRESULT WINAPI Proxy_DirectInput8Create(HINSTANCE inst, DWORD ver, REFIID riid, LPVOID *out, LPVOID outer)
{
    if (!real_DirectInput8Create) {
        char sys[MAX_PATH];
        GetSystemDirectoryA(sys, MAX_PATH);
        strcat_s(sys, MAX_PATH, "\\dinput8.dll");
        real_DirectInput8Create = (fn_DirectInput8Create)GetProcAddress(LoadLibraryA(sys), "DirectInput8Create");
        if (!real_DirectInput8Create) return E_FAIL;
    }
    return real_DirectInput8Create(inst, ver, riid, out, outer);
}
#pragma comment(linker, "/export:DirectInput8Create=_Proxy_DirectInput8Create@20")

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID reserved)
{
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(inst);
        install(inst);
    }
    return TRUE;
}
