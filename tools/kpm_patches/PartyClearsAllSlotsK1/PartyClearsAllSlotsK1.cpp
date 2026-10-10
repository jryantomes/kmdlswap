// Party Clears Reach All Slots, for KotOR I 1.03 - a Kotor Patch Manager patch of its own (not part of
// any mod). Requires Party Roster Limit 32.
//
// The game clears the party - boarding the Ebon Hawk, the Leviathan capture, the dueling ring, the
// Manaan arrest - with loops over party slots 0-8: k_inc_utility's UT_ClearAllPartyMembers
// ("for (n = 0; n <= 8; n++) if (IsNPCPartyMember(n)) RemovePartyMember(n);") and scripts' own
// versions of it. With the roster patch a companion in slots 9-31 is never reached, and stays in the
// party (audit 2026-10-10: 61 scripts on one install, the game's and mods', many inside .mod files no
// Override file can replace).
//
// So, as each script loads, its party-clearing loops are widened to 31: the loop's bound
// "CONSTI 8; LEQII" (n <= 8) becomes 31 when the loop's body removes a party member by a computed
// slot (RemovePartyMember, action 575, with an argument that is not a constant). Loops that only check
// or count members remove no one and are left alone; so are removals of one named slot. Every family
// of these loops found on the install has its bound in that form: the condition, a few stack/logic
// instructions (for "n <= 8 && !bDone", with its short-circuit JZ), then the JZ that leaves the loop.
// Checked offline against all 9,981 scripts of one install (widen_sim.py): every party-clearing
// loop matched, and nothing else.
//
// The hook is CVirtualMachineInternal::InitializeScript's entry: the bytecode it is given is copied
// into the script's own buffer right after, so the change is made in the code it copies. Code already
// widened has no "CONSTI 8; LEQII" left there, so a second pass changes nothing.

#include <windows.h>
#include <cstdarg>
#include <cstdio>
#include <cstring>

namespace {

const int MAX_CODE = 4 * 1024 * 1024;
const int CONDITION_SPAN = 96;          // from the bound to the loop's JZ, at most

int BigInt(const unsigned char* p)
{
    return (int)((unsigned)p[0] << 24 | (unsigned)p[1] << 16 | (unsigned)p[2] << 8 | (unsigned)p[3]);
}

// The size of the instruction at p, for the few that sit between a loop's bound and its JZ;
// 0 for anything else (then the loop is not touched).
int ConditionInstructionSize(const unsigned char* p, const unsigned char* end)
{
    const ptrdiff_t left = end - p;
    if (left < 2) return 0;
    switch (p[0])
    {
    case 0x03: return left >= 8 ? 8 : 0;                        // CPTOPSP
    case 0x27: return left >= 8 ? 8 : 0;                        // CPTOPBP
    case 0x04: return (p[1] == 0x03 && left >= 6) ? 6 : 0;      // CONSTI
    case 0x05: return left >= 5 ? 5 : 0;                        // ACTION
    case 0x06: case 0x07: case 0x08: case 0x09: case 0x0A:      // LOGAND, LOGOR, INCOR, EXCOR, BOOLAND
    case 0x0B: case 0x0C: case 0x0D: case 0x0E: case 0x0F: case 0x10:   // comparisons
    case 0x22:                                                  // NOTI
        return p[1] == 0x24 ? 0 : 2;                            // not a structure comparison
    default: return 0;
    }
}

bool RemovesByComputedSlot(const unsigned char* body, const unsigned char* bodyEnd, const unsigned char* code)
{
    static const unsigned char REMOVE[] = {0x05, 0x00, 0x02, 0x3F, 0x01};   // ACTION RemovePartyMember, 1 arg
    for (const unsigned char* p = body; p + 5 <= bodyEnd; ++p)
    {
        if (memcmp(p, REMOVE, 5) != 0) continue;
        if (p - code >= 6 && p[-6] == 0x04 && p[-5] == 0x03) continue;     // a named slot
        return true;
    }
    return false;
}

void Log(const char* format, ...)
{
    char line[256];
    va_list args;
    va_start(args, format);
    vsnprintf_s(line, sizeof(line), _TRUNCATE, format, args);
    va_end(args);
    OutputDebugStringA(line);
}

int Widen(unsigned char* code, int size)
{
    static const unsigned char BOUND[] = {0x04, 0x03, 0x00, 0x00, 0x00, 0x08, 0x10, 0x20};   // CONSTI 8; LEQII
    const unsigned char* end = code + size;
    int widened = 0;
    for (unsigned char* p = code; p + sizeof(BOUND) <= end; ++p)
    {
        if (memcmp(p, BOUND, sizeof(BOUND)) != 0) continue;
        // the rest of the condition, up to the JZ that leaves the loop
        const unsigned char* q = p + sizeof(BOUND);
        const unsigned char* jz = nullptr;
        while (q < end && q - p < CONDITION_SPAN)
        {
            if (end - q >= 6 && q[0] == 0x1F && q[1] == 0x00)
            {
                // "n <= 8 && !bDone" compiles a short-circuit JZ that lands just past the LOGAND
                // further on in the condition - not the loop's exit: step over it
                const unsigned char* t = q + BigInt(q + 2);
                if (t > q + 6 && t <= q + 64 && t <= end && (t[-2] == 0x06 || t[-2] == 0x07) && t[-1] == 0x20)
                {
                    q += 6;
                    continue;
                }
                jz = q;
                break;
            }
            const int n = ConditionInstructionSize(q, end);
            if (n == 0) break;
            q += n;
        }
        if (jz == nullptr) continue;
        const int jump = BigInt(jz + 2);
        if (jump <= 6 || (jz - code) + jump > size) continue;
        if (!RemovesByComputedSlot(jz + 6, jz + jump, code)) continue;
        p[5] = 0x1F;                                            // n <= 31
        ++widened;
    }
    return widened;
}

}

extern "C" void __cdecl WidenPartyClears(unsigned char* code, int size)
{
    if (code == nullptr || size < 16 || size > MAX_CODE) return;
    int widened = 0;
    __try
    {
        widened = Widen(code, size);
    }
    __except (EXCEPTION_EXECUTE_HANDLER)
    {
        Log("[PartyClearsAllSlots] could not read a script's code (%d bytes)\n", size);
        return;
    }
    if (widened)
        Log("[PartyClearsAllSlots] %d party-clearing loop(s) widened to slot 31 (%d bytes of code)\n", widened, size);
}
