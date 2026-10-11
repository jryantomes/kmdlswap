// Party Silhouettes, for KotOR I 1.03 - a Kotor Patch Manager patch of its own (not part of any mod).
// Requires Party Roster Limit 32. A stopgap until that patch has this itself
// (LaneDibello/Kotor-Patch-Manager#331).
//
// Every vanilla companion has a silhouette on the party screen while they aren't available. A
// companion a mod adds in slots 9 to 31 has none: Party Roster Limit 32 shows the silhouette label
// only for slots 0-8 (its layout's LBL_NA9-31 all carry Bastila's), so the slot is an empty box.
//
// Mods register a silhouette in partysilhouettes.2da (Override; this patch's additional file):
//
//     slot   slotglobal         silhouette
//     12     ****               po_pmycomp2      <- a fixed slot
//     ****   MYMOD_PARTY_SLOT   po_pother2       <- a slot kept in a global number (Party Slots)
//
// The hook is CSWGuiPanel::AddControl. Party Roster Limit 32 builds a page of the party screen in
// the game's own slot records (CSWGuiPartySelectionData): it sets every record up, adds each
// record's button to the panel, and then adds each record's silhouette label if that label is
// visible. So when a slot's button is added to the party screen - the record already final - an
// unavailable slot 9-31 with a registered silhouette has its label given that texture and made
// visible, and the roster patch then adds it as it does for slots 0-8. Every page is rebuilt this
// way, so the second page's slots get their own.

#include <windows.h>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <string>
#include "Common.h"
#include "GameAPI/GameVersion.h"
#include "GameAPI/CExoString.h"
#include "GameAPI/C2DA.h"
#include "GameAPI/CServerExoApp.h"

namespace {

const DWORD PARTY_SELECTION_VTABLE = 0x00756D28;   // CSWGuiPartySelection
const DWORD SLOT_BUTTON_VTABLE = 0x00756BB8;       // CSWGuiPartySelectionButton
const int RECORD_LABEL = 0x1C8;                    // CSWGuiPartySelectionData.portrait_label (LBL_NA)
const int RECORD_FLAGS = 0x448;                    // the roster patch's slot flags: 1 = available
const int RECORD_SLOT = 0x450;                     // .npc_index: the logical slot
const int LABEL_FILL_PARAMS = 0x70;                // CSWGuiLabel.border (0x5C) + its border params (0x14)
const int CONTROL_BIT_FLAGS = 0x44;                // CSWGuiControl.bit_flags; bit 1 = shown
const int C2DA_ROW_COUNT = 0x24;
const int MAX_ROWS = 256;

typedef void(__thiscall* SetFillImageFn)(void* borderParams, void* resref, int forceUpdate);
typedef int(__thiscall* GetValueNumberFn)(void* table, void* name, signed char* value);
const SetFillImageFn SetFillImage = reinterpret_cast<SetFillImageFn>(0x00414C00);
const GetValueNumberFn GetValueNumber = reinterpret_cast<GetValueNumberFn>(0x00529240);

struct ResRef { char name[16]; };

void Log(const char* format, ...)
{
    char line[256];
    va_list args;
    va_start(args, format);
    vsnprintf_s(line, sizeof(line), _TRUNCATE, format, args);
    va_end(args);
    OutputDebugStringA(line);
}

// a CExoString's text up to its first null (a 2DA cell's length can count the terminator)
std::string Text(CExoString& s)
{
    const char* text = s.GetCStr();
    const DWORD length = s.GetLength();
    if (!text || length == 0 || length > 64) return std::string();
    return std::string(text, strnlen(text, length));
}

int GlobalNumber(const std::string& name)
{
    CServerExoApp* server = CServerExoApp::GetInstance();
    if (!server) return -1;
    void* table = server->GetGlobalVariableTable();
    delete server;
    if (!table) return -1;
    CExoString exo(const_cast<char*>(name.c_str()));
    // the engine writes ONE byte: it zeroes it, then copies the global's value (K1's numbers are
    // signed bytes) - and its return value is not a found/not-found flag (read in its code, after
    // the first build read an int and missed: harness silhouettes, 2026-10-10)
    signed char value = 0;
    GetValueNumber(table, exo.GetPtr(), &value);
    return value;
}

// the silhouette registered for a slot, or empty
std::string SilhouetteFor(int slot)
{
    C2DA table("partysilhouettes");
    if (!table.GetPtr()) return std::string();
    const int rows = *reinterpret_cast<int*>(static_cast<BYTE*>(table.GetPtr()) + C2DA_ROW_COUNT);
    CExoString colSlot(const_cast<char*>("slot"));
    CExoString colGlobal(const_cast<char*>("slotglobal"));
    CExoString colSilhouette(const_cast<char*>("silhouette"));
    for (int row = 0; row < rows && row < MAX_ROWS; ++row)
    {
        int rowSlot = -1;
        if (!table.GetINTEntry(row, &colSlot, &rowSlot))
        {
            CExoString global;
            if (table.GetCExoStringEntry(row, &colGlobal, &global))
            {
                const std::string name = Text(global);
                if (!name.empty()) rowSlot = GlobalNumber(name);
            }
        }
        if (rowSlot != slot) continue;
        CExoString silhouette;
        if (table.GetCExoStringEntry(row, &colSilhouette, &silhouette)) return Text(silhouette);
    }
    return std::string();
}

}

namespace {

void AddSilhouette(void* panel, void* control)
{
    if (!panel || !control) return;
    if (*static_cast<DWORD*>(panel) != PARTY_SELECTION_VTABLE) return;
    if (*static_cast<DWORD*>(control) != SLOT_BUTTON_VTABLE) return;
    BYTE* record = static_cast<BYTE*>(control);            // a slot's button is the start of its record
    const int slot = *reinterpret_cast<int*>(record + RECORD_SLOT);
    if (slot < 9 || slot > 31) return;
    if (*reinterpret_cast<DWORD*>(record + RECORD_FLAGS) & 1) return;   // available: its portrait shows
    const std::string texture = SilhouetteFor(slot);
    if (texture.empty() || texture.size() > 16) return;
    ResRef image = {};
    memcpy(image.name, texture.data(), texture.size());
    BYTE* label = record + RECORD_LABEL;
    SetFillImage(label + LABEL_FILL_PARAMS, &image, 1);
    *reinterpret_cast<int*>(label + CONTROL_BIT_FLAGS) |= 1 << 1;
}

}

extern "C" void __cdecl AddPartySilhouette(void* panel, void* control)
{
    __try
    {
        AddSilhouette(panel, control);
    }
    __except (EXCEPTION_EXECUTE_HANDLER)
    {
        Log("[PartySilhouettes] could not set a silhouette\n");
    }
}

BOOL WINAPI DllMain(HINSTANCE, DWORD reason, LPVOID)
{
    if (reason == DLL_PROCESS_ATTACH)
    {
        if (!GameVersion::Initialize())
        {
            Log("[PartySilhouettes] ERROR: GameVersion::Initialize() failed\n");
            return FALSE;
        }
    }
    return TRUE;
}
