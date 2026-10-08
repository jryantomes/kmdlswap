// Module Load Scripts, for KotOR I 1.03 - a Kotor Patch Manager patch of its own (not part of any mod).
//
// A module's load script (module.ifo Mod_OnModLoad) is the one place a mod can run code every time a
// module loads - and a mod cannot give a module a new one for games already under way: a save keeps
// each visited module's module.ifo, and a module loaded from a save runs the saved copy's script, not
// the installed .mod's (harness ifoprobe, 2026-10-08: the Ebon Hawk's Mod_OnModLoad changed in its .mod
// never ran on a save that had been aboard). And a module has one load script, so two mods that both
// want it overwrite each other.
//
// This runs, after a module's own load script, every script modloadscripts.2da names for that module:
//
//     module      script
//     ebo_m12aa   hcw_work        <- one row per script; any mod adds its own (HoloPatcher AddRow)
//     all         some_script     <- "all": every module
//
// (not "*": K1 reads a 2DA cell that starts with '*' as blank - the "****" convention - harness 2026-10-08)
//
// each with the module as OBJECT_SELF, as the game runs the module's own. In every save, old or new.
//
// The hook replaces the module load case of CSWSModule::EventHandler (0x004c5215, event 0x11: load
// the module's object id, point at script_on_module_load, then RunScript at 0x004c5408): this runs
// that script itself, exactly so, then the table's, and goes on at 0x004c5417 - where the game's own
// RunScript returns to, with the stack as it was here.

#include <windows.h>
#include <string>
#include <cctype>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include "Common.h"
#include "GameAPI/GameVersion.h"
#include "GameAPI/CExoString.h"
#include "GameAPI/C2DA.h"
#include "GameAPI/CVirtualMachine.h"

static const int MODULE_OBJECT_ID = 0x20;    // CSWSModule.game_object_id
static const int MODULE_ON_LOAD = 0xC0;      // CSWSModule.script_on_module_load (a CExoString)
static const int MODULE_NAME = 0x5C;         // the string CSWSModule::GetModuleResourceName reads ("...:name")
static const int C2DA_ROW_COUNT = 0x24;      // C2DA.row_count (its getters' own bound)
static const int MAX_ROWS = 2000;

// Every line goes to the debug output (DebugView) and, if a file modloadscripts.log is beside the
// game's exe, to that too - a modder creates the empty file to see what ran (the debug output drops
// lines when other programs flood it).
static void Log(const char* format, ...)
{
    char line[512];
    va_list args;
    va_start(args, format);
    vsnprintf_s(line, sizeof(line), _TRUNCATE, format, args);
    va_end(args);
    OutputDebugStringA(line);
    char path[MAX_PATH];
    const DWORD n = GetModuleFileNameA(nullptr, path, MAX_PATH);
    if (n == 0 || n >= MAX_PATH) return;
    char* slash = strrchr(path, '\\');
    if (!slash || (slash - path) + 20 >= MAX_PATH) return;
    strcpy_s(slash + 1, MAX_PATH - (slash + 1 - path), "modloadscripts.log");
    if (GetFileAttributesA(path) == INVALID_FILE_ATTRIBUTES) return;
    FILE* f = nullptr;
    if (fopen_s(&f, path, "a") == 0 && f) {
        fputs(line, f);
        fclose(f);
    }
}

// A CExoString's text up to its first null: the game's length can count the terminator (a 2DA cell
// "all" reads back with length 4), and ToStdString keeps every counted byte - "all\0" != "all"
static std::string Text(CExoString& s)
{
    const char* text = s.GetCStr();
    const DWORD length = s.GetLength();
    if (!text || length == 0 || length > 4096) return std::string();
    return std::string(text, strnlen(text, length));
}

static std::string Lower(std::string s)
{
    for (char& c : s) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    return s;
}

static std::string ModuleName(void* module)
{
    CExoString name(static_cast<BYTE*>(module) + MODULE_NAME);
    std::string s = Text(name);
    const size_t colon = s.rfind(':');
    if (colon != std::string::npos) s = s.substr(colon + 1);
    return Lower(s);
}

extern "C" int __cdecl RunModuleLoadScripts(void* module)
{
    if (!module) return 0;                    // not consumed: the game's own path runs
    CVirtualMachine* vm = CVirtualMachine::GetInstance();
    if (!vm) return 0;
    const DWORD self = *reinterpret_cast<DWORD*>(static_cast<BYTE*>(module) + MODULE_OBJECT_ID);

    const std::string here = ModuleName(module);

    // the module's own load script, as the game runs it
    CExoString own(static_cast<BYTE*>(module) + MODULE_ON_LOAD);
    if (own.GetLength() > 0) {
        const bool ran = vm->RunScript(&own, self, 1);
        Log("[ModuleLoadScripts] %s: own %s (%d)\n", here.c_str(), Text(own).c_str(), ran ? 1 : 0);
    }

    // then the table's, for this module and for every module. A blank cell reads as false: skipped
    C2DA table("modloadscripts");
    if (table.GetPtr()) {
        const int rows = *reinterpret_cast<int*>(static_cast<BYTE*>(table.GetPtr()) + C2DA_ROW_COUNT);
        Log("[ModuleLoadScripts] %s: modloadscripts.2da, %d rows\n", here.c_str(), rows);
        CExoString colModule(const_cast<char*>("module"));
        CExoString colScript(const_cast<char*>("script"));
        for (int row = 0; row < rows && row < MAX_ROWS; ++row) {
            CExoString forModule;
            if (!table.GetCExoStringEntry(row, &colModule, &forModule)) {
                Log("[ModuleLoadScripts] row %d: blank module cell, skipped\n", row);
                continue;
            }
            const std::string m = Lower(Text(forModule));
            if (m != here && m != "all") continue;
            CExoString script;
            if (!table.GetCExoStringEntry(row, &colScript, &script) || script.GetLength() == 0) continue;
            const bool ran = vm->RunScript(&script, self, 1);
            Log("[ModuleLoadScripts] %s: row %d '%s' -> %s (%d)\n", here.c_str(), row, m.c_str(),
                Text(script).c_str(), ran ? 1 : 0);
        }
    }
    delete vm;
    return 1;                                 // consumed: on at 0x004c5417, the script already run
}

BOOL WINAPI DllMain(HINSTANCE, DWORD reason, LPVOID)
{
    if (reason == DLL_PROCESS_ATTACH) {
        if (!GameVersion::Initialize()) {
            Log("[ModuleLoadScripts] ERROR: GameVersion::Initialize() failed\n");
            return FALSE;
        }
        Log("[ModuleLoadScripts] ready\n");
    } else if (reason == DLL_PROCESS_DETACH) {
        GameVersion::Reset();
    }
    return TRUE;
}
