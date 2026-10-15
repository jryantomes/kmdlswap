// hcw_work.nss - Ebon Hawk Crew at Work (tools/hawk_crew; a package of its own, not part of any
// companion mod). Run as the Hawk loads - every boarding and every save loaded aboard - by the
// Module Load Scripts patch for Kotor Patch Manager (its modloadscripts.2da row ebo_m12aa -> hcw_work):
// a module.ifo hook would not reach a save that has already been aboard. User, 2026-10-07: "To make the ship feel more alive, I want to have the crew on
// the Ebon Hawk look like they are doing different tasks when you get on the ship".
//
// Each crew member standing aboard (not in the party) has a short routine of stations near their
// own spot (the module's pebn_* waypoint): walk there, face the console, bed or bench, and work at
// it a while - a looping animation that holds for its whole length on a crew member (harness
// crewanim, 2026-10-07: 40 s held) - then on to the next. On boarding they are put straight into
// their first task while the Hawk loads, unseen; after that every change is walked.
//
// Never in anyone's way:
//   * nothing is cleared: tasks are only queued behind whatever the crew member is doing, and
//     only when the last one has run its length;
//   * not while any conversation is open, nor in combat;
//   * only while they are in their own part of the ship (within 2 m of their waypoint or a
//     station): a scene that walks or jumps them elsewhere has them left alone until they are
//     back;
//   * party members walk with you and are left alone.
//
// One set of loops at a time: a module keeps its pending DelayCommands when the player leaves it
// (the saves' EventQueue, 2026-10-08: the Hawk held three of these loops in a save made on another
// planet), so the loops of the last visit wake up again with the next. Each run takes a new
// generation (global HCW_GEN) and every loop of an older one ends at its next turn.

// ANIMATION_LOOPING_*
int CW_PAUSE = 0;
int CW_PAUSE2 = 1;
int CW_LISTEN = 2;
int CW_MEDITATE = 3;
int CW_GET_LOW = 10;
int CW_GET_MID = 11;
int CW_TIRED = 12;
// Jolee lying back on the medical bed: an animation of his own, "hcw_bedlie" in his body models
// (jolee_bed.py), and a row the installer adds to animations.2da. The Animation Rows patch for Kotor
// Patch Manager plays it as 20000 + row. The installer writes the row into CW_BEDLIE_RAW's constant
// (HoloPatcher HACKList; install.py the same) - 0x12340000 is only the placeholder it looks for. An
// installer that writes 32 bits there leaves the row; one that writes 16 (TSLPatcher's way) leaves
// row * 65536 over the placeholder's zero low half - so both are read back the same. Unwritten, it is
// row 4660, which no table has: nothing plays. Until 2026-10-08 the pose was "dance" (16) on the
// shared male bodies, which the Star Forge easter egg plays on the player.
// (A function, not a global initialised by calling one: a global set from a function call kept
// hcw_work from running at all - harness crewpad, 2026-10-08.)
int CW_BEDLIE_RAW = 305397760;
// And sitting down onto the bed's foot first, "hcw_bedsit" (user, 2026-10-15: "he needs a sitting
// animation before laying so it doesn't look so jarring"): played once, then the lying pose blends in
// as he leans back. Its row the same way, placeholder 0x12350000.
int CW_BEDSIT_RAW = 305463296;
int CW_AnimRow(int v)
{
    if (v >= 65536) v = v / 65536;
    return 20000 + v;
}
int CW_OnBed()
{
    return CW_AnimRow(CW_BEDLIE_RAW);
}
int CW_SitBed()
{
    return CW_AnimRow(CW_BEDSIT_RAW);
}
int CW_COMPUTER = 15;
int CW_WELD = 25;
int CW_TREAT = 29;

int CW_CREW = 9;
string CW_GEN = "HCW_GEN";

string CW_Tag(int i)
{
    switch (i)
    {
        case 0: return "Carth";
        case 1: return "Bastila";
        case 2: return "Jolee";
        case 3: return "Cand";
        case 4: return "HK47";
        case 5: return "T3M4";
        case 6: return "Zaalbar";
        case 7: return "Juhani";
        case 8: return "Mission";
    }
    return "";
}

string CW_Home(int i)
{
    switch (i)
    {
        case 0: return "pebn_carth";
        case 1: return "pebn_bastila";
        case 2: return "pebn_jolee";
        case 3: return "pebn_canderous";
        case 4: return "pebn_hk47";
        case 5: return "pebn_t3m4";
        case 6: return "pebn_zaalbar";
        case 7: return "pebn_juhani";
        case 8: return "pebn_mission";
    }
    return "";
}

int CW_Steps(int i)
{
    // Bastila meditates and Jolee lies back on the medical bed, the whole visit (user, 2026-10-07)
    if (i == 1 || i == 2) return 1;
    return 2;
}

// a station: x, y (0.0 = the home waypoint itself), facing, animation, shortest and longest stay
// (one routine per crew member: case 10 * i + k)
vector CW_Spot(int i, int k)
{
    switch (10 * i + k)
    {
        case 0:  return Vector(50.80, 79.50, 1.80);   // Carth: the console on the pilot's side (the seats block the front)
        case 11: return Vector(54.80, 79.50, 1.80);   // Bastila: the console on the co-pilot's side
        case 20: return Vector(44.03, 36.00, 1.80);   // Jolee: at the medical bed's foot, lying back onto it
        case 30: return Vector(58.90, 36.60, 1.80);   // Canderous: the workbench
        case 41: return Vector(63.60, 27.20, 1.80);   // HK-47: by the swoop bike
        case 50: return Vector(50.05, 43.95, 1.80);   // T3-M4: the holotable's base
        case 51: return Vector(47.50, 47.20, 1.80);   // T3-M4: the holotable's west panel
        case 80: return Vector(77.60, 47.80, 1.80);   // Mission: the lit panel on the starboard quarters' inner wall
        // Zaalbar: the wall console on the main hold's starboard curve (the holotable's east panel had
        // no console at his height: "zaalbar looks like he's typing in air" - user, 2026-10-15; harness zaalconsole)
        case 60: return Vector(56.80, 48.20, 1.80);
    }
    return GetPosition(GetWaypointByTag(CW_Home(i)));
}

float CW_Face(int i, int k)
{
    switch (10 * i + k)
    {
        case 0:  return 100.0;
        case 1:  return 90.0;      // Carth: out of the viewport
        case 10: return 90.0;
        case 11: return 80.0;
        case 20: return 270.0;     // facing away from the bed: 'prone' lays him back along it
        case 30: return 80.0;
        case 41: return 20.0;
        case 50: return 88.0;
        case 51: return 350.0;
        case 80: return 180.0;
        case 60: return 50.0;
    }
    return GetFacing(GetWaypointByTag(CW_Home(i)));
}

int CW_Anim(int i, int k)
{
    switch (10 * i + k)
    {
        case 0:  return CW_COMPUTER;
        case 1:  return CW_PAUSE;
        case 10: return CW_MEDITATE;
        case 11: return CW_COMPUTER;
        case 20: return CW_OnBed();
        case 21: return CW_TIRED;
        case 30: return CW_COMPUTER;
        case 31: return CW_PAUSE;
        case 40: return CW_PAUSE2;
        case 41: return CW_LISTEN;
        case 50: return CW_WELD;
        case 51: return CW_COMPUTER;
        case 60: return CW_COMPUTER;
        case 61: return CW_PAUSE;
        case 70: return CW_MEDITATE;
        case 71: return CW_PAUSE;
        case 80: return CW_COMPUTER;
        case 81: return CW_TIRED;
    }
    return CW_PAUSE;
}

// the stay, seconds: the first step of each routine is the long one, the work
float CW_Stay(int i, int k)
{
    if (CW_Steps(i) == 1) return 60.0 + IntToFloat(Random(31));
    if (k == 0) return 30.0 + IntToFloat(Random(21));
    return 12.0 + IntToFloat(Random(13));
}

// the crew member with this tag standing aboard (not walking with you)
object CW_Find(string sTag)
{
    int n = 0;
    object o = GetObjectByTag(sTag, n);
    while (GetIsObjectValid(o))
    {
        if (!IsObjectPartyMember(o)) return o;
        n++;
        o = GetObjectByTag(sTag, n);
    }
    return OBJECT_INVALID;
}

// in their own part of the ship: by their waypoint or one of their stations
int CW_InPlace(object o, int i)
{
    vector v = GetPosition(o);
    vector h = GetPosition(GetWaypointByTag(CW_Home(i)));
    if (VectorMagnitude(Vector(v.x - h.x, v.y - h.y, 0.0)) < 2.0) return TRUE;
    int k;
    for (k = 0; k < CW_Steps(i); k++)
    {
        vector s = CW_Spot(i, k);
        if (VectorMagnitude(Vector(v.x - s.x, v.y - s.y, 0.0)) < 2.0) return TRUE;
    }
    return FALSE;
}

// bLead: the last task queued is still playing and ends about a second from now, so one queued now
// follows it without a break (Bastila and Jolee hold their one task the whole visit, never standing up between)
void CW_Tick(int i, int k, int bBoarding, int bLead, int nGen)
{
    if (nGen != GetGlobalNumber(CW_GEN)) return;      // an older visit's loop
    object o = CW_Find(CW_Tag(i));
    // not aboard: looked for again now and then (a companion mod may make one a little later)
    if (!GetIsObjectValid(o))
    {
        if (bBoarding) DelayCommand(4.0, CW_Tick(i, k, FALSE, FALSE, nGen));
        else DelayCommand(15.0, CW_Tick(i, k, FALSE, FALSE, nGen));
        return;
    }
    // the player's fight only: Jolee lying on the bed reads as in combat (harness crewpad, 2026-10-07)
    if (GetIsConversationActive() || GetIsInCombat(GetFirstPC()) || !CW_InPlace(o, i))
    {
        DelayCommand(5.0, CW_Tick(i, k, FALSE, FALSE, nGen));
        return;
    }
    vector vAt = CW_Spot(i, k);
    float fFace = CW_Face(i, k);
    float fStay = CW_Stay(i, k);
    vector vNow = GetPosition(o);
    float fWalk = VectorMagnitude(Vector(vAt.x - vNow.x, vAt.y - vNow.y, 0.0));
    location lAt = Location(vAt, fFace);
    if (bBoarding)
    {
        AssignCommand(o, JumpToLocation(lAt));    // while the Hawk loads: unseen
        fWalk = 0.0;
    }
    else if (fWalk > 0.6)
        AssignCommand(o, ActionMoveToLocation(lAt, FALSE));
    AssignCommand(o, ActionDoCommand(SetFacing(fFace)));
    // Jolee sits on the bed before lying back - not when put there unseen, nor between loops (already lying)
    if (i == 2 && !bBoarding && !bLead) AssignCommand(o, ActionPlayAnimation(CW_SitBed(), 1.0, 0.0));
    AssignCommand(o, ActionPlayAnimation(CW_Anim(i, k), 1.0, fStay));
    int kNext = (k + 1) % CW_Steps(i);
    if (bBoarding || fWalk <= 0.6)
    {
        // no walk: the next task is queued a second before this one ends (this one starts at once, or
        // a second from now behind the last)
        if (bLead) DelayCommand(fStay, CW_Tick(i, kNext, FALSE, TRUE, nGen));
        else DelayCommand(fStay - 1.0, CW_Tick(i, kNext, FALSE, TRUE, nGen));
    }
    else   // walking pace is about 1.7 m/s; a second spare for the turn
        DelayCommand(fWalk / 1.5 + fStay + 1.0, CW_Tick(i, kNext, FALSE, FALSE, nGen));
}

// Jolee's Datapad (jolee_bed.py: hcw_jolee_pad, a Consular-only stun baton modelled as a datapad
// in the fist - user, 2026-10-07: "For fun, make a datapad equipable for Jolee and equip it to that
// hand"). In his right hand while he lies on the bed with the party leader within 20 m. A crew member's
// equipment aboard goes back into the party table when the ship is left (harness equipsync, 2026-10-07:
// a stun baton put in Carth's hand aboard was in it when he was spawned off the ship), so his own weapon
// - which waits in his inventory meanwhile, upgrades and all - is back in his hand whenever the leader
// is further off: the exit ramp is 25 m from the bed, the galaxy map 38 m.
string CW_PAD_ITEM = "hcw_jolee_pad";
string CW_PAD_OLD = "rfk_jdpad_i";    // its first tag, when it shipped inside a companion mod
float CW_PAD_NEAR = 20.0;

int CW_IsPad(object oItem)
{
    return GetIsObjectValid(oItem) && (GetTag(oItem) == CW_PAD_ITEM || GetTag(oItem) == CW_PAD_OLD);
}

void CW_DropPad(object oJ)
{
    if (CW_IsPad(GetItemInSlot(INVENTORY_SLOT_RIGHTWEAPON, oJ))) return;
    object oPad = GetItemPossessedBy(oJ, CW_PAD_ITEM);
    if (GetIsObjectValid(oPad)) DestroyObject(oPad);
    oPad = GetItemPossessedBy(oJ, CW_PAD_OLD);
    if (GetIsObjectValid(oPad)) DestroyObject(oPad);
}

// his own weapon back in his right hand (the one the datapad displaced: the only thing in his
// inventory), the datapad gone
void CW_GiveBack(object oJ)
{
    object oMine = OBJECT_INVALID;
    object o = GetFirstItemInInventory(oJ);
    while (GetIsObjectValid(o) && !GetIsObjectValid(oMine))
    {
        if (!CW_IsPad(o)) oMine = o;
        o = GetNextItemInInventory(oJ);
    }
    AssignCommand(oJ, ClearAllActions());
    if (GetIsObjectValid(oMine)) AssignCommand(oJ, ActionEquipItem(oMine, INVENTORY_SLOT_RIGHTWEAPON, TRUE));
    else AssignCommand(oJ, ActionUnequipItem(GetItemInSlot(INVENTORY_SLOT_RIGHTWEAPON, oJ), TRUE));
    DelayCommand(1.0, CW_DropPad(oJ));
}

void CW_GivePad(object oJ)
{
    object oPad = GetItemPossessedBy(oJ, CW_PAD_ITEM);
    if (!GetIsObjectValid(oPad)) oPad = CreateItemOnObject(CW_PAD_ITEM, oJ);
    AssignCommand(oJ, ClearAllActions());
    AssignCommand(oJ, ActionEquipItem(oPad, INVENTORY_SLOT_RIGHTWEAPON, TRUE));
}

void CW_LieBack(object oJ)
{
    AssignCommand(oJ, ActionDoCommand(SetFacing(CW_Face(2, 0))));
    AssignCommand(oJ, ActionPlayAnimation(CW_SitBed(), 1.0, 0.0));
    AssignCommand(oJ, ActionPlayAnimation(CW_OnBed(), 1.0, CW_Stay(2, 0)));
}

// every second: the datapad in or out of his hand; and after a conversation he lies straight back
// down rather than standing at the bed's foot until his next turn
void CW_JoleeWatch(int bWasTalking, int nGen)
{
    if (nGen != GetGlobalNumber(CW_GEN)) return;
    object oJ = CW_Find(CW_Tag(2));
    if (!GetIsObjectValid(oJ))
    {
        DelayCommand(5.0, CW_JoleeWatch(FALSE, nGen));
        return;
    }
    object oLead = GetPartyMemberByIndex(0);
    int bTalking = GetIsInConversation(oJ);
    vector vBed = CW_Spot(2, 0);
    vector vJ = GetPosition(oJ);
    int bThere = VectorMagnitude(Vector(vJ.x - vBed.x, vJ.y - vBed.y, 0.0)) < 0.6;
    int bNear = GetIsObjectValid(oLead) && GetArea(oLead) == GetArea(oJ) && GetDistanceBetween(oLead, oJ) < CW_PAD_NEAR;
    // the player's fight, not his: a Jolee made from his template reads as in combat while he lies there
    // (harness crewpad, 2026-10-07)
    int bFight = GetIsInCombat(GetFirstPC());
    int bHolding = CW_IsPad(GetItemInSlot(INVENTORY_SLOT_RIGHTWEAPON, oJ));
    if (bHolding && !bTalking && (!bNear || !bThere || bFight))
    {
        CW_GiveBack(oJ);
        if (bThere && !bFight) CW_LieBack(oJ);
    }
    else if (!bHolding && !bTalking && bNear && bThere && !bFight && !GetIsConversationActive())
    {
        CW_GivePad(oJ);
        CW_LieBack(oJ);
    }
    else if (bWasTalking && !bTalking && bThere && !GetIsConversationActive())
        CW_LieBack(oJ);
    else if (!bHolding)
        CW_DropPad(oJ);             // one left over from an earlier visit
    DelayCommand(1.0, CW_JoleeWatch(bTalking, nGen));
}
void main()
{
    int nGen = (GetGlobalNumber(CW_GEN) + 1) % 250;     // a global number holds a byte
    SetGlobalNumber(CW_GEN, nGen);
    DelayCommand(2.0, CW_JoleeWatch(FALSE, nGen));
    int i;
    for (i = 0; i < CW_CREW; i++)
        CW_Tick(i, Random(CW_Steps(i)), TRUE, FALSE, nGen);
}
