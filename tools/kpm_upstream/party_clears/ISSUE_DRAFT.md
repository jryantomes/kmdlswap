> **Posted 2026-10-10:** https://github.com/LaneDibello/Kotor-Patch-Manager/issues/330

**Title:** Party Roster Limit 32 (K1): companions in slots 9 to 31 stay in the party when a script clears it

**Version:** 0.7.3 release and current master. KotOR 1.03 (GOG identical exe), Windows.

**What happens:** a companion in one of the new slots (9 to 31) is never removed when the game clears the party. Boarding the Ebon Hawk is the easiest place to see it: everyone else goes to their station, and the companion in slot 10 is still following you around the ship. The same happens at the Leviathan capture, the Taris dueling ring, the Manaan arrest, Korriban, the Unknown World and so on.

**Why:** the game clears the party with loops over slots 0 to 8. Most use `UT_ClearAllPartyMembers` from k_inc_utility:

```c
for(nCnt; nCnt <= 8; nCnt++)
{
    if(IsNPCPartyMember(nCnt))
    {
        RemovePartyMember(nCnt);
    }
}
```

and others have their own copy of that loop. I scanned every compiled script on my install (vanilla plus K1CP and a few other mods, 9,981 scripts) and found 61 that clear the party this way, many of them inside .mod files, so a fix through Override files can't reach them. Three Star Forge scripts (k_psta_door, k_psta_mlkparty, k_psta_pc_j) list slots 0 to 8 one by one instead.

**What I did on my side:** a small patch that requires Party Roster Limit 32. It hooks `CVirtualMachineInternal::InitializeScript` (0x005D16F0) and, as each script loads, widens a loop's bound from 8 to 31 when that loop removes party members by a computed slot (`CONSTI 8; LEQII` followed by a body with `RemovePartyMember` on a non constant argument). Loops that only check or count members are left alone. I checked the matching offline against all 9,981 scripts (every clearing loop matched, nothing else did) and in game: with a companion in slot 10 and Juhani in the party, the game's own clear loop removed only Juhani without the patch, and both with it.

It's here if it's useful, or if you'd rather handle it inside the roster patch itself:
https://github.com/jryantomes/kmdlswap/tree/claude/kmdlswap-droid-editing-pt3u7r/tools/kpm_patches/PartyClearsAllSlotsK1

I think it belongs with the roster patch, since anyone using a companion in the new slots will hit this. Happy to help test either way.
