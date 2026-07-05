"""Entrance Randomizer (Archipelago side).

This owns the *logic and randomization* of entrance shuffle. It shuffles the
shufflable entrances in the AP region graph (guaranteeing the seed stays
beatable) and emits the resulting pairs into slot data in the format Ship's
``EntranceShuffler::ParseJson`` already understands.

Coupled (two-way) pools:
  * dungeon entrances (+ optionally Ganon's Castle)
  * boss-room entrances (child + adult bosses, age-aware)
  * interior entrances ("simple" tier, or "all" to mix in the special/linked
    interiors: Temple of Time, Link's house, the windmill, the Kak potion shop)
  * grotto + grave entrances (dead-end grottos and graves)

One-way pools (a single source edge repointed, no reverse):
  * overworld spawns (child / adult start positions)
  * warp songs (the six song destinations)
  * owl drops (Lake Hylia / Death Mountain Trail owl flights)

Blue warps are *derived* from the boss/dungeon placement rather than shuffled, and
are emitted whenever either of those pools is shuffled.

All pools use a custom age-aware matcher + a full-accessibility validation gate
(see ``_seed_is_valid``); the Archipelago Generic Entrance Randomizer is not used
(its greedy staged placement deadlocks on this graph's age scarcity).
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .Enums import Regions, Ages, TimeOfDay
from rule_builder.rules import True_, False_
from BaseClasses import CollectionState
from Fill import fill_restrictive

if TYPE_CHECKING:
    from . import SohWorld
    from BaseClasses import Entrance, Location, Region

import logging
logger = logging.getLogger("SOH_OOT.ER")


# ===========================================================================
# AP-VS-SHIP DIVERGENCES
# ===========================================================================
# This module is a port of Ship of Harkinian's entrance shuffle (the upstream
# C++ in ``soh/soh/Enhancements/randomizer/entrance.cpp`` +
# ``soh/include/tables/entrance_table.h``). The points below are every place this
# AP port deliberately diverges from upstream, or depends on something that
# upstream might change. When re-syncing this apworld's logic to a newer Ship,
# re-verify each one. Individual code sites are tagged ``DIVERGENCE #N``.
#
# #1  SLOT-DATA CONTRACT IS THE ONLY THING SHIP CONSUMES.
#     We emit ``{type, index, destination, override, overrideDestination}`` per
#     entrance; Ship's ``EntranceShuffler::ParseEntrances`` -> ``ApplyEntranceOverrides``
#     reads them. ApplyEntranceOverrides rewires purely by ``index`` -> ``override``
#     (connecting ``index`` to override's *original* connected region) and IGNORES
#     ``type``/``destination``/``overrideDestination`` -- EXCEPT the all-zero "null
#     override" skip (see #2). The ``ENTR_*`` index numbers are the real contract;
#     keep them in sync with entrance_table.h. AP region names below matter only
#     for locating local ``Entrance`` objects + reachability, never for Ship.
#
# #2  ONE-WAY ENTRANCES EMIT destination = overrideDestination = -1, NOT 0.
#     (spawns / warp songs / owl drops / blue warps -- ``_ONE_WAY_NO_DEST``.) Ship's
#     CreateEntranceOverrides emits -1 for entrances with no reverse; and 0 is unsafe
#     because (a) an all-zero override is treated as "unshuffled" and skipped, and
#     (b) 0 is a real index (ENTR_DEKU_TREE_ENTRANCE == 0x000). Two-way pools emit
#     the real reverse indices.
#
# #4  AP REGION-GRAPH COLLAPSES / RENAMES some Ship transition regions, so our
#     entrance endpoints differ from Ship's ``RR_*`` even though the ``ENTR_*`` index
#     is identical. Re-verify if upstream restructures regions OR if this apworld's
#     location_access graph is re-synced to upstream names. Known cases:
#       - Dungeon sides: Fire=DMC_CENTRAL_LOCAL, Water=LH_FROM_WATER_TEMPLE,
#         BotW=KAK_WELL, Ice=ZF_LEDGE, GTG=GF_TO_GTG/GF_EXITING_GTG (see DUNGEON_ENTRANCES).
#       - Link's House porch (RR_KF_LINKS_PORCH) collapsed into KOKIRI_FOREST.
#       - Overworld buffers collapsed: KF_OUTSIDE_LOST_WOODS -> KOKIRI_FOREST,
#         HF_TO_LAKE_HYLIA -> HYRULE_FIELD. DMC "pots/upper entry" buffers are absent;
#         AP uses asymmetric DMC_*_LOCAL (forward) / DMC_*_NEARBY (reverse). See the
#         per-row notes in OVERWORLD_ENTRANCES and the ``_ow`` docstring.
#
# #TH THIEVES' HIDEOUT LOCATIONS are UNIONED where Ship splits them across cells: the
#     carpenter-rescue locations collapse into THIEVES_HIDEOUT_RESCUE_CARPENTERS and the
#     kitchen pots into THIEVES_HIDEOUT_KITCHEN_POTS. Those union regions are internal
#     (not shuffled). The entrance GRAPH matches Ship 1:1 (fwd + rev pairs), so the
#     hideout shuffles / mixes / decouples like the other coupled pools.
#
# #5  PRIORITY ENTRANCES DIFFER. Ship uses a static glitchless "priority entrances"
#     list (Bolero/Nocturne/Requiem); this port instead does per-seed dynamic detection
#     of load-bearing one-way landings (`_one_way_requirements`), which subsumes that
#     list. Re-verify if upstream changes how priority entrances are chosen. See the
#     one-way section.
#
# #6  PLACEMENT ALGORITHM DIFFERS (but the *result* is contract-compatible). Ship
#     uses incremental assumed-fill placement with per-entrance reachability checks;
#     we use a custom age-aware matcher (Kuhn) + a full re-validation gate with retry
#     (``_seed_is_valid`` / ``_find_matching``), and -- when that fast path can't find
#     a valid layout by luck -- a guaranteed-convergent validated random walk
#     (``_walk_shuffle``: start from valid vanilla, keep only validated swaps). The
#     Archipelago Generic Entrance Randomizer is NOT used (it deadlocks on this graph's
#     age scarcity). One consequence with no Ship analogue: pool ORDER matters for our
#     convergence -- the overworld backbone must be shuffled before interiors/grottos
#     (see ``shuffle_entrances``).
#
# #7  VALIDATION GATE ports Ship's ``ValidateWorld`` / ``ValidateEntrances``
#     (entrance.cpp:796 / 3drando/fill.cpp:606). ``_age_exits_are_safe`` is Ship's
#     child/adultForbidden hard-check. ``_world_age_invariants_hold`` (gated by
#     ``check_other_access``) is Ship's ``checkOtherEntranceAccess`` "sphere-zero"
#     requirement: a valid start area is reachable, time passes as both ages, and ToT
#     is reachable as the other age. The start-area check is item-less (true sphere
#     zero); the time-pass/ToT checks use the all-items pre-fill state so that a
#     closed/song-only Door of Time (other age gated behind Song of Time) or a closed
#     forest (leaving Kokiri gated behind sword+shield) is not a false positive (the
#     items satisfy those gates). FULL ENTRANCE CONNECTIVITY (every region reachable
#     with all items) is required for ALL pools regardless of AP's ``accessibility``
#     option: Ship's entrance generator always requires it, and AP's accessibility
#     governs item placement, not the entrance graph. Without this, an earlier pool can
#     strand a region under ``minimal`` and a later pool's doorway there gets an empty
#     age-cap -> matcher infeasible (see ``_seed_is_valid``).
#
# #8  ITEM-FILLABILITY GATE. The per-pool checks are all all-items (optimistic): they
#     grant every item at once, so they miss a *progressive* fill deadlock -- a layout
#     reachable only when you already hold everything (a pre-filled item whose RESTRICTED
#     home location, e.g. a dungeon reward / song / small key, is stranded; a shuffled
#     spawn stranding the start age under closed/song Door of Time). Such layouts pass
#     every per-pool check yet make real fill raise. Ship never hits this because it
#     assumed-fills items and entrances together; our pools run before fill. So
#     ``shuffle_entrances`` snapshots the vanilla graph, runs all pools, then trial-runs
#     the real pre_fill + an assumed fill (``_trial_fill_accessible``); on failure it
#     restores the graph and re-rolls the whole shuffle. Only the check_other_access
#     pools can trigger this, so plain dead-end shuffles skip the gate. The trial is
#     fully undone, so the pipeline's own later pre_fill is unaffected. The gate accepts
#     via the multiworld's own ``fulfills_accessibility``, so it honours each seed's
#     accessibility (under ``minimal`` only the goal must be reachable). A per-pool
#     progressive *heuristic* was tried and removed: a bootstrap deadlock is a property
#     of the whole layout, so a single pool can't fix one a prior pool created, and the
#     capacity estimate produced false negatives -> spurious hard fails. This accurate
#     global trial supersedes it.
# ===========================================================================


# Ship's `EntranceType` enum values (soh `enum class EntranceType`, entrance.h).
# Emitted as the `type` field. Ship's ApplyEntranceOverrides() rewires purely by
# index -> override and ignores `type`, but the entrance tracker/hints read it,
# so we send the true values rather than a placeholder.
ENTRANCE_TYPE_OWL_DROP = 1
ENTRANCE_TYPE_SPAWN = 2
ENTRANCE_TYPE_WARP_SONG = 3
ENTRANCE_TYPE_BLUE_WARP = 4
ENTRANCE_TYPE_DUNGEON = 5
ENTRANCE_TYPE_GANON_DUNGEON = 6
ENTRANCE_TYPE_CHILD_BOSS = 10
ENTRANCE_TYPE_ADULT_BOSS = 12
ENTRANCE_TYPE_GANON_TOWER = 14
ENTRANCE_TYPE_INTERIOR = 15
ENTRANCE_TYPE_SPECIAL_INTERIOR = 17
ENTRANCE_TYPE_THIEVES_HIDEOUT = 18
ENTRANCE_TYPE_GROTTO_GRAVE = 20
ENTRANCE_TYPE_OVERWORLD = 22

# Types whose target region is a forward-only dead end (a boss room / Ganon's Tower
# climb): their reverse edge is disconnected before a coupled shuffle so it can't create
# a phantom cross-area path. See ``_Edge.dead_end`` and the reverse-mode note above.
_DEAD_END_TYPES = frozenset((ENTRANCE_TYPE_CHILD_BOSS, ENTRANCE_TYPE_ADULT_BOSS,
                             ENTRANCE_TYPE_GANON_TOWER))

# Grotto indices are computed from a base + offset (soh randomizerTypes.h).
_GROTTO_LOAD_START = 0x0700
_GROTTO_EXIT_START = 0x0800


def _grotto_load(offset: int) -> int:
    return _GROTTO_LOAD_START + offset


def _grotto_exit(offset: int) -> int:
    return _GROTTO_EXIT_START + offset


# Number of constrained matchings to try per pool before giving up. The
# age-compatibility constraints already guarantee full reachability, so the final
# validation is a safety net and this is essentially never exhausted.
MAX_SHUFFLE_ATTEMPTS = 50


class _OneWayInfeasible(RuntimeError):
    """A one-way (spawn/warp/owl) layout can't be satisfied for the *current* coupled
    layout -- a load-bearing landing has no deliverable cover, or no source is left to
    cover a required landing. Raised by the one-way pool and caught by ``shuffle_entrances``
    as a signal to re-roll the WHOLE shuffle (a fresh coupled layout typically lifts the
    dependency), rather than hard-failing generation."""


# How a pool's reverse (inside -> outside) edges are handled in the AP graph:
#   "couple"  - reconnect them so they mirror the forward shuffle (true two-way).
#   "keep"    - leave the opposite-direction AP edges untouched (don't repoint or
#               disconnect); permute only this pool's own direction. Used by the
#               decoupled single-direction passes (`_shuffle_decoupled` and the
#               decoupled overworld/mixed pools), where the forward and reverse
#               directions are shuffled as separate one-directional pools and each
#               pass emits its own forward-only (-1-destination) overrides.
# Orthogonally, an individual edge may be a DEAD END (``_Edge.dead_end``): its target
# region is a forward-only sink (a boss room / Ganon's Tower climb), so its reverse is
# disconnected before shuffling -- the boss reward is reached via the forward door and
# the exit is the derived blue warp, and a live vanilla reverse would otherwise create a
# phantom cross-area path. This is per-EDGE, not per-pool, so a coupled pool (including
# the mixed pool) can hold both dead-end (boss) and coupled members: the coupling step
# simply skips a dead-end target (its ``rev_entrance`` is None after the disconnect).
REVERSE_COUPLE = "couple"
REVERSE_KEEP = "keep"


@dataclass(frozen=True)
class EntranceDef:
    """One coupled, shufflable entrance, described in both repos' terms.

    The AP region graph creates an ``Entrance`` named ``"{parent} -> {child}"``
    for every ``connect_regions`` edge (the StrEnum *values* are the region
    names). We manipulate the *forward* edge (``fwd_parent -> fwd_child``, i.e.
    outside -> inside) in the graph; the reverse edge is handled per the pool's
    reverse mode.

    ``fwd_index`` / ``rev_index`` are Ship's ``ENTR_*`` table indices (the hex
    values from soh/include/tables/entrance_table.h, or the computed grotto
    load/exit values). They are what we send to Ship; the AP region members are
    only used to locate the local ``Entrance`` objects to shuffle.

    ``rev_parent`` / ``rev_child`` give the reverse AP edge when one exists. They
    are required for ``REVERSE_COUPLE`` pools; for a dead-end edge (``_Edge.dead_end``)
    they merely identify the real reverse edge to disconnect.
    """
    name: str
    fwd_parent: Regions
    fwd_child: Regions
    fwd_index: int
    rev_index: int
    ship_type: int
    rev_parent: "Regions | None" = None
    rev_child: "Regions | None" = None


# ---------------------------------------------------------------------------
# Bridge tables
# ---------------------------------------------------------------------------
#
# AP region members verified against this apworld's location_access graph; Ship
# indices verified against entrance_table.h / entrance.cpp's entranceShuffleTable.

# Dungeon entrances. Forward edge is overworld -> "*_ENTRYWAY" buffer; reverse is
# the buffer back out to the overworld (== forward parent except for the handful
# the graph models asymmetrically: Spirit, GTG, Ganon).
DUNGEON_ENTRANCES: list[EntranceDef] = [
    EntranceDef("Deku Tree",
                Regions.KF_OUTSIDE_DEKU_TREE, Regions.DEKU_TREE_ENTRYWAY,
                0x000, 0x209, ENTRANCE_TYPE_DUNGEON,
                Regions.DEKU_TREE_ENTRYWAY, Regions.KF_OUTSIDE_DEKU_TREE),
    EntranceDef("Dodongos Cavern",
                Regions.DEATH_MOUNTAIN_TRAIL, Regions.DODONGOS_CAVERN_ENTRYWAY,
                0x004, 0x242, ENTRANCE_TYPE_DUNGEON,
                Regions.DODONGOS_CAVERN_ENTRYWAY, Regions.DEATH_MOUNTAIN_TRAIL),
    EntranceDef("Jabu Jabus Belly",
                Regions.ZORAS_FOUNTAIN, Regions.JABU_JABUS_BELLY_ENTRYWAY,
                0x028, 0x221, ENTRANCE_TYPE_DUNGEON,
                Regions.JABU_JABUS_BELLY_ENTRYWAY, Regions.ZORAS_FOUNTAIN),
    EntranceDef("Forest Temple",
                Regions.SACRED_FOREST_MEADOW, Regions.FOREST_TEMPLE_ENTRYWAY,
                0x169, 0x215, ENTRANCE_TYPE_DUNGEON,
                Regions.FOREST_TEMPLE_ENTRYWAY, Regions.SACRED_FOREST_MEADOW),
    EntranceDef("Fire Temple",
                Regions.DMC_CENTRAL_LOCAL, Regions.FIRE_TEMPLE_ENTRYWAY,
                0x165, 0x24A, ENTRANCE_TYPE_DUNGEON,
                Regions.FIRE_TEMPLE_ENTRYWAY, Regions.DMC_CENTRAL_LOCAL),
    EntranceDef("Water Temple",
                Regions.LH_FROM_WATER_TEMPLE, Regions.WATER_TEMPLE_ENTRYWAY,
                0x010, 0x21D, ENTRANCE_TYPE_DUNGEON,
                Regions.WATER_TEMPLE_ENTRYWAY, Regions.LH_FROM_WATER_TEMPLE),
    EntranceDef("Spirit Temple",
                Regions.DESERT_COLOSSUS, Regions.SPIRIT_TEMPLE_ENTRYWAY,
                0x082, 0x1E1, ENTRANCE_TYPE_DUNGEON,
                Regions.SPIRIT_TEMPLE_ENTRYWAY,
                Regions.DESERT_COLOSSUS_OUTSIDE_TEMPLE),
    EntranceDef("Shadow Temple",
                Regions.GRAVEYARD_WARP_PAD_REGION, Regions.SHADOW_TEMPLE_ENTRYWAY,
                0x037, 0x205, ENTRANCE_TYPE_DUNGEON,
                Regions.SHADOW_TEMPLE_ENTRYWAY, Regions.GRAVEYARD_WARP_PAD_REGION),
    EntranceDef("Bottom of the Well",
                Regions.KAK_WELL, Regions.BOTTOM_OF_THE_WELL_ENTRYWAY,
                0x098, 0x2A6, ENTRANCE_TYPE_DUNGEON,
                Regions.BOTTOM_OF_THE_WELL_ENTRYWAY, Regions.KAK_WELL),
    EntranceDef("Ice Cavern",
                Regions.ZF_LEDGE, Regions.ICE_CAVERN_ENTRYWAY,
                0x088, 0x3D4, ENTRANCE_TYPE_DUNGEON,
                Regions.ICE_CAVERN_ENTRYWAY, Regions.ZF_LEDGE),
    EntranceDef("Gerudo Training Ground",
                Regions.GF_TO_GTG, Regions.GERUDO_TRAINING_GROUND_ENTRYWAY,
                0x008, 0x3A8, ENTRANCE_TYPE_DUNGEON,
                Regions.GERUDO_TRAINING_GROUND_ENTRYWAY, Regions.GF_EXITING_GTG),
]

GANON_ENTRANCE = EntranceDef(
    "Ganons Castle",
    Regions.GANONS_CASTLE_LEDGE, Regions.GANONS_CASTLE_ENTRYWAY,
    0x467, 0x23D, ENTRANCE_TYPE_GANON_DUNGEON,
    Regions.GANONS_CASTLE_ENTRYWAY, Regions.CASTLE_GROUNDS_FROM_GANONS_CASTLE)

# Ganon's Tower entrance (Ship EntranceType::GanonTower, ENTR_GANONS_TOWER_0 / rev
# ENTR_INSIDE_GANONS_CASTLE_1). The forward edge is the ungated loading zone
# GANONS_TOWER_ENTRYWAY -> GANONS_TOWER_FLOOR_1 (AP's FLOOR_1 == Ship's STAIRS_1);
# the Ganon's-Trials gate lives on the *approach* (GANONS_CASTLE_LOBBY ->
# GANONS_TOWER_ENTRYWAY), so shuffling this edge does not move the trials
# requirement -- matching Ship (ganons_castle.cpp: LOBBY->ENTRYWAY gated,
# ENTRYWAY->STAIRS_1 true). Treated as a boss and a dead-end edge (``_Edge.dead_end``):
# FLOOR_1 climbs to Ganon and ends the game, so it is a forward-only dead end and its
# reverse (FLOOR_1 -> ENTRYWAY) is disconnected once shuffled (coupled/mixed). Only
# shuffled when boss entrances are shuffled AND ShuffleGanonsTower is on (Ship
# entrance.cpp:1248/1260).
GANON_TOWER_ENTRANCE = EntranceDef(
    "Ganons Tower",
    Regions.GANONS_TOWER_ENTRYWAY, Regions.GANONS_TOWER_FLOOR_1,
    0x41B, 0x534, ENTRANCE_TYPE_GANON_TOWER,
    Regions.GANONS_TOWER_FLOOR_1, Regions.GANONS_TOWER_ENTRYWAY)


# Boss-room entrances. Forward edge is "*_BOSS_ENTRYWAY" -> "*_BOSS_ROOM"
# (ENTR_*_BOSS_ENTRANCE); reverse (ENTR_*_BOSS_DOOR) is "*_BOSS_ROOM" -> the exit
# region. Every boss now names its reverse AP edge, matching Ship's boss entrance
# pairs 1:1 (entrance.cpp entranceShuffleTable):
#   - Child bosses (Deku/Dodongo/Jabu) exit to a dedicated ``*_BOSS_EXIT`` region
#     that leads back into the dungeon. Deku/Dodongo's boss-room->exit edge is a real
#     ``True_()``; Jabu's is ``False_()`` (Ship marks it so -- the exit region exists
#     only to host the reverse shuffle unit; the blue warp is Jabu's logical exit).
#   - Adult bosses exit back to ``*_BOSS_ENTRYWAY``; those edges are ``False_()`` in
#     both repos (you can't walk back out of an adult boss room in vanilla).
# The ``False_()`` reverses (adult bosses + Jabu) aren't materialized by the rule
# builder (AutoWorld.create_entrance drops always-false edges), so ``shuffle_entrances``
# force-creates them via ``_ensure_reverse_edges`` when boss shuffle is on. In a coupled
# or mixed pool each boss edge is a dead end (``_Edge.dead_end``), so its reverse is
# disconnected (the real Deku/Dodongo ones to avoid phantom cross-dungeon paths, the
# ``False_()`` ones harmlessly); decoupled shuffles the reverse pool independently.
# Naming + materializing them makes the AP graph match Ship's topology 1:1.
BOSS_ENTRANCES: list[EntranceDef] = [
    EntranceDef("Gohma (Deku Tree)",
                Regions.DEKU_TREE_BOSS_ENTRYWAY, Regions.DEKU_TREE_BOSS_ROOM,
                0x40F, 0x252, ENTRANCE_TYPE_CHILD_BOSS,
                Regions.DEKU_TREE_BOSS_ROOM, Regions.DEKU_TREE_BOSS_EXIT),
    EntranceDef("King Dodongo (Dodongos Cavern)",
                Regions.DODONGOS_CAVERN_BOSS_ENTRYWAY,
                Regions.DODONGOS_CAVERN_BOSS_ROOM,
                0x40B, 0x0C5, ENTRANCE_TYPE_CHILD_BOSS,
                Regions.DODONGOS_CAVERN_BOSS_ROOM,
                Regions.DODONGOS_CAVERN_BOSS_EXIT),
    EntranceDef("Barinade (Jabu Jabus Belly)",
                Regions.JABU_JABUS_BELLY_BOSS_ENTRYWAY,
                Regions.JABU_JABUS_BELLY_BOSS_ROOM,
                0x301, 0x407, ENTRANCE_TYPE_CHILD_BOSS,
                Regions.JABU_JABUS_BELLY_BOSS_ROOM,
                Regions.JABU_JABUS_BELLY_BOSS_EXIT),
    EntranceDef("Phantom Ganon (Forest Temple)",
                Regions.FOREST_TEMPLE_BOSS_ENTRYWAY,
                Regions.FOREST_TEMPLE_BOSS_ROOM,
                0x00C, 0x24E, ENTRANCE_TYPE_ADULT_BOSS,
                Regions.FOREST_TEMPLE_BOSS_ROOM,
                Regions.FOREST_TEMPLE_BOSS_ENTRYWAY),
    EntranceDef("Volvagia (Fire Temple)",
                Regions.FIRE_TEMPLE_BOSS_ENTRYWAY, Regions.FIRE_TEMPLE_BOSS_ROOM,
                0x305, 0x175, ENTRANCE_TYPE_ADULT_BOSS,
                Regions.FIRE_TEMPLE_BOSS_ROOM, Regions.FIRE_TEMPLE_BOSS_ENTRYWAY),
    EntranceDef("Morpha (Water Temple)",
                Regions.WATER_TEMPLE_BOSS_ENTRYWAY, Regions.WATER_TEMPLE_BOSS_ROOM,
                0x417, 0x423, ENTRANCE_TYPE_ADULT_BOSS,
                Regions.WATER_TEMPLE_BOSS_ROOM, Regions.WATER_TEMPLE_BOSS_ENTRYWAY),
    EntranceDef("Twinrova (Spirit Temple)",
                Regions.SPIRIT_TEMPLE_BOSS_ENTRYWAY,
                Regions.SPIRIT_TEMPLE_BOSS_ROOM,
                0x08D, 0x2F5, ENTRANCE_TYPE_ADULT_BOSS,
                Regions.SPIRIT_TEMPLE_BOSS_ROOM,
                Regions.SPIRIT_TEMPLE_BOSS_ENTRYWAY),
    EntranceDef("Bongo Bongo (Shadow Temple)",
                Regions.SHADOW_TEMPLE_BOSS_ENTRYWAY,
                Regions.SHADOW_TEMPLE_BOSS_ROOM,
                0x413, 0x2B2, ENTRANCE_TYPE_ADULT_BOSS,
                Regions.SHADOW_TEMPLE_BOSS_ROOM,
                Regions.SHADOW_TEMPLE_BOSS_ENTRYWAY),
]


# The reverse AP edge defaults to the mirror (interior -> overworld); ``rev_child``
# overrides it for the asymmetric cases (where the exit lands in a different region
# than the entrance came from).
def _i(name: str, parent: Regions, child: Regions, fwd_index: int, rev_index: int,
       rev_child: "Regions | None" = None) -> EntranceDef:
    return EntranceDef(name, parent, child, fwd_index, rev_index,
                       ENTRANCE_TYPE_INTERIOR, child, rev_child or parent)


def _si(name: str, parent: Regions, child: Regions, fwd_index: int, rev_index: int,
        rev_child: "Regions | None" = None) -> EntranceDef:
    return EntranceDef(name, parent, child, fwd_index, rev_index,
                       ENTRANCE_TYPE_SPECIAL_INTERIOR, child, rev_child or parent)


def _g(name: str, parent: Regions, child: Regions, offset: int,
       rev_child: "Regions | None" = None) -> EntranceDef:
    return EntranceDef(name, parent, child,
                       _grotto_load(offset), _grotto_exit(offset),
                       ENTRANCE_TYPE_GROTTO_GRAVE, child, rev_child or parent)


def _grave(name: str, child: Regions, fwd_index: int,
           rev_index: int) -> EntranceDef:
    return EntranceDef(name, Regions.THE_GRAVEYARD, child, fwd_index, rev_index,
                       ENTRANCE_TYPE_GROTTO_GRAVE, child, Regions.THE_GRAVEYARD)


# Interior entrances (the "simple" tier; Ship EntranceType::Interior). Matches
# Ship's Interior pool exactly. Special interiors (Temple of Time, Link's house,
# the windmill, the linked Kak potion shop) are a separate Ship type
# (SpecialInterior), handled below as SPECIAL_INTERIOR_ENTRANCES and mixed in only
# under interior "All". The Market back-alley Dog Lady house is
# not in Ship's shuffle table at all. Impa's House front + back are dead-ends (the
# shared cow cage they both reach has no exit), so they are safe to include.
INTERIOR_ENTRANCES: list[EntranceDef] = [
    _i("Mido's House", Regions.KOKIRI_FOREST, Regions.KF_MIDOS_HOUSE, 0x433, 0x443),
    _i("Saria's House", Regions.KOKIRI_FOREST, Regions.KF_SARIAS_HOUSE, 0x437, 0x447),
    _i("House of Twins", Regions.KOKIRI_FOREST, Regions.KF_HOUSE_OF_TWINS, 0x09C, 0x33C),
    _i("Know-It-All House", Regions.KOKIRI_FOREST, Regions.KF_KNOW_IT_ALL_HOUSE, 0x0C9, 0x26A),
    _i("Kokiri Shop", Regions.KOKIRI_FOREST, Regions.KF_KOKIRI_SHOP, 0x0C1, 0x266),
    _i("Lakeside Laboratory", Regions.LAKE_HYLIA, Regions.LH_LAB, 0x043, 0x3CC),
    _i("Fishing Pond", Regions.LH_FISHING_ISLAND, Regions.LH_FISHING_HOLE, 0x45F, 0x309),
    _i("Carpenter's Tent", Regions.GV_FORTRESS_SIDE, Regions.GV_CARPENTER_TENT, 0x3A0, 0x3D0),
    _i("Market Guard House", Regions.MARKET_ENTRANCE, Regions.MARKET_GUARD_HOUSE, 0x07E, 0x26E),
    _i("Happy Mask Shop", Regions.MARKET, Regions.MARKET_MASK_SHOP, 0x530, 0x1D1),
    _i("Bombchu Bowling Alley", Regions.MARKET, Regions.MARKET_BOMBCHU_BOWLING, 0x507, 0x3BC),
    _i("Market Potion Shop", Regions.MARKET, Regions.MARKET_POTION_SHOP, 0x388, 0x2A2),
    _i("Treasure Box Shop", Regions.MARKET, Regions.MARKET_TREASURE_CHEST_GAME, 0x063, 0x1D5),
    _i("Bombchu Shop", Regions.MARKET_BACK_ALLEY, Regions.MARKET_BOMBCHU_SHOP, 0x528, 0x3C0),
    _i("Man in Green House", Regions.MARKET_BACK_ALLEY, Regions.MARKET_MAN_IN_GREEN_HOUSE, 0x43B, 0x067),
    _i("Kak Guest House", Regions.KAKARIKO_VILLAGE, Regions.KAK_CARPENTER_BOSS_HOUSE, 0x2FD, 0x349),
    _i("House of Skulltula", Regions.KAKARIKO_VILLAGE, Regions.KAK_HOUSE_OF_SKULLTULA, 0x550, 0x4EE),
    _i("Impa's House (Front)", Regions.KAKARIKO_VILLAGE, Regions.KAK_IMPAS_HOUSE, 0x39C, 0x345),
    _i("Impa's House (Back)", Regions.KAK_IMPAS_LEDGE, Regions.KAK_IMPAS_HOUSE_BACK, 0x5C8, 0x5DC),
    _i("Granny's Potion Shop", Regions.KAK_BACKYARD, Regions.KAK_GRANNYS_POTION_SHOP, 0x072, 0x34D),
    _i("Gravekeeper's Hut", Regions.THE_GRAVEYARD, Regions.GRAVEYARD_DAMPES_HOUSE, 0x30D, 0x355),
    _i("Goron Shop", Regions.GORON_CITY, Regions.GC_SHOP, 0x37C, 0x3FC),
    _i("Zora Shop", Regions.ZORAS_DOMAIN, Regions.ZD_SHOP, 0x380, 0x3C4),
    _i("Talon's House", Regions.LON_LON_RANCH, Regions.LLR_TALONS_HOUSE, 0x04F, 0x378),
    _i("Lon Lon Stables", Regions.LON_LON_RANCH, Regions.LLR_STABLES, 0x2F9, 0x42F),
    _i("Lon Lon Tower", Regions.LON_LON_RANCH, Regions.LLR_TOWER, 0x5D0, 0x5D4),
    _i("Market Bazaar", Regions.MARKET, Regions.MARKET_BAZAAR, 0x52C, 0x3B8),
    _i("Market Shooting Gallery", Regions.MARKET, Regions.MARKET_SHOOTING_GALLERY, 0x16D, 0x1CD),
    _i("Kak Bazaar", Regions.KAKARIKO_VILLAGE, Regions.KAK_BAZAAR, 0x0B7, 0x201),
    _i("Kak Shooting Gallery", Regions.KAKARIKO_VILLAGE, Regions.KAK_SHOOTING_GALLERY, 0x03B, 0x463),
    _i("Colossus Great Fairy", Regions.DESERT_COLOSSUS, Regions.COLOSSUS_GREAT_FAIRY_FOUNTAIN, 0x588, 0x57C),
    _i("HC Great Fairy", Regions.HYRULE_CASTLE_GROUNDS, Regions.HC_GREAT_FAIRY_FOUNTAIN,
       0x578, 0x340, rev_child=Regions.CASTLE_GROUNDS),
    _i("OGC Great Fairy", Regions.GANONS_CASTLE_GROUNDS, Regions.OGC_GREAT_FAIRY_FOUNTAIN,
       0x4C2, 0x3E8, rev_child=Regions.CASTLE_GROUNDS),
    _i("DMC Great Fairy", Regions.DMC_LOWER_NEARBY, Regions.DMC_GREAT_FAIRY_FOUNTAIN,
       0x4BE, 0x482, rev_child=Regions.DMC_LOWER_LOCAL),
    _i("DMT Great Fairy", Regions.DEATH_MOUNTAIN_SUMMIT, Regions.DMT_GREAT_FAIRY_FOUNTAIN, 0x315, 0x45B),
    _i("ZF Great Fairy", Regions.ZORAS_FOUNTAIN, Regions.ZF_GREAT_FAIRY_FOUNTAIN, 0x371, 0x394),
]


# Special/linked interiors (Ship EntranceType::SpecialInterior). Added to the
# interior pool only on the "All" setting (Ship mixes them in -- entrance.cpp:1295).
# Unlike the simple tier these are mostly NOT dead ends: Temple of Time leads on to
# the Door of Time (gating the adult game), the Kak potion shop's two doors are a
# pass-through (Front <-> Back, adult-gated), and the windmill links Kakariko to the
# graveyard via Dampe's grave. So this pool is shuffled with per-edge needs and the
# global age/time invariants enabled (check_other_access) -- the validation gate
# absorbs the cap-stability slack the pass-throughs introduce. Ship models Link's
# House behind a porch region (RR_KF_LINKS_PORCH) that this apworld collapses into
# the Kokiri Forest doorway, so the forward edge is Kokiri Forest -> KF Link's House.
SPECIAL_INTERIOR_ENTRANCES: list[EntranceDef] = [
    _si("Link's House", Regions.KOKIRI_FOREST, Regions.KF_LINKS_HOUSE, 0x272, 0x211),
    _si("Temple of Time", Regions.TOT_ENTRANCE, Regions.TEMPLE_OF_TIME, 0x053, 0x472),
    _si("Windmill", Regions.KAKARIKO_VILLAGE, Regions.KAK_WINDMILL, 0x453, 0x351),
    _si("Kak Potion Shop Front", Regions.KAKARIKO_VILLAGE, Regions.KAK_POTION_SHOP_FRONT, 0x384, 0x44B),
    _si("Kak Potion Shop Back", Regions.KAK_BACKYARD, Regions.KAK_POTION_SHOP_BACK, 0x3EC, 0x4FF),
]


# Grotto + grave entrances (Ship EntranceType::GrottoGrave). Matches Ship's pool.
# Grotto indices are load/exit = 0x0700/0x0800 + offset. HC Storms Grotto and
# Dampe's Grave each add a redundant shortcut (to Castle Grounds / the windmill);
# everything they reach is reachable independently, so the final full-accessibility
# validation (with retry) covers the slight cap-stability imperfection.
GROTTO_ENTRANCES: list[EntranceDef] = [
    _g("Colossus Grotto", Regions.DESERT_COLOSSUS, Regions.COLOSSUS_GROTTO, 0x00),
    _g("LH Grotto", Regions.LAKE_HYLIA, Regions.LH_GROTTO, 0x01),
    _g("ZR Storms Grotto", Regions.ZORA_RIVER, Regions.ZR_STORMS_GROTTO, 0x02),
    _g("ZR Fairy Grotto", Regions.ZORA_RIVER, Regions.ZR_FAIRY_GROTTO, 0x03),
    _g("ZR Open Grotto", Regions.ZORA_RIVER, Regions.ZR_OPEN_GROTTO, 0x04),
    _g("DMC Hammer Grotto", Regions.DMC_LOWER_NEARBY, Regions.DMC_HAMMER_GROTTO, 0x05,
       rev_child=Regions.DMC_LOWER_LOCAL),
    _g("DMC Upper Grotto", Regions.DMC_UPPER_NEARBY, Regions.DMC_UPPER_GROTTO, 0x06,
       rev_child=Regions.DMC_UPPER_LOCAL),
    _g("GC Grotto", Regions.GC_GROTTO_PLATFORM, Regions.GC_GROTTO, 0x07),
    _g("DMT Storms Grotto", Regions.DEATH_MOUNTAIN_TRAIL, Regions.DMT_STORMS_GROTTO, 0x08),
    _g("DMT Cow Grotto", Regions.DEATH_MOUNTAIN_SUMMIT, Regions.DMT_COW_GROTTO, 0x09),
    _g("Kak Open Grotto", Regions.KAK_BACKYARD, Regions.KAK_OPEN_GROTTO, 0x0A),
    _g("Kak Redead Grotto", Regions.KAKARIKO_VILLAGE, Regions.KAK_REDEAD_GROTTO, 0x0B),
    _g("HC Storms Grotto", Regions.HYRULE_CASTLE_GROUNDS, Regions.HC_STORMS_GROTTO, 0x0C,
       rev_child=Regions.CASTLE_GROUNDS),
    _g("HF Tektite Grotto", Regions.HYRULE_FIELD, Regions.HF_TEKTITE_GROTTO, 0x0D),
    _g("HF Near Kak Grotto", Regions.HYRULE_FIELD, Regions.HF_NEAR_KAK_GROTTO, 0x0E),
    _g("HF Fairy Grotto", Regions.HYRULE_FIELD, Regions.HF_FAIRY_GROTTO, 0x0F),
    _g("HF Near Market Grotto", Regions.HYRULE_FIELD, Regions.HF_NEAR_MARKET_GROTTO, 0x10),
    _g("HF Cow Grotto", Regions.HYRULE_FIELD, Regions.HF_COW_GROTTO, 0x11),
    _g("HF Inside Fence Grotto", Regions.HYRULE_FIELD, Regions.HF_INSIDE_FENCE_GROTTO, 0x12),
    _g("HF Open Grotto", Regions.HYRULE_FIELD, Regions.HF_OPEN_GROTTO, 0x13),
    _g("HF Southeast Grotto", Regions.HYRULE_FIELD, Regions.HF_SOUTHEAST_GROTTO, 0x14),
    _g("LLR Grotto", Regions.LON_LON_RANCH, Regions.LLR_GROTTO, 0x15),
    _g("SFM Wolfos Grotto", Regions.SFM_ENTRYWAY, Regions.SFM_WOLFOS_GROTTO, 0x16),
    _g("SFM Storms Grotto", Regions.SACRED_FOREST_MEADOW, Regions.SFM_STORMS_GROTTO, 0x17),
    _g("SFM Fairy Grotto", Regions.SACRED_FOREST_MEADOW, Regions.SFM_FAIRY_GROTTO, 0x18),
    _g("LW Scrubs Grotto", Regions.LW_BEYOND_MIDO, Regions.LW_SCRUBS_GROTTO, 0x19),
    _g("LW Near Shortcuts Grotto", Regions.LOST_WOODS, Regions.LW_NEAR_SHORTCUTS_GROTTO, 0x1A),
    _g("KF Storms Grotto", Regions.KOKIRI_FOREST, Regions.KF_STORMS_GROTTO, 0x1B),
    _g("ZD Storms Grotto", Regions.ZORAS_DOMAIN_ISLAND, Regions.ZD_STORMS_GROTTO, 0x1C),
    _g("GF Storms Grotto", Regions.GF_NEAR_GROTTO, Regions.GF_STORMS_GROTTO, 0x1D),
    _g("GV Storms Grotto", Regions.GV_FORTRESS_SIDE, Regions.GV_STORMS_GROTTO, 0x1E),
    _g("GV Octorok Grotto", Regions.GV_GROTTO_LEDGE, Regions.GV_OCTOROK_GROTTO, 0x1F),
    _g("Deku Theater Grotto", Regions.LW_BEYOND_MIDO, Regions.DEKU_THEATER, 0x20,
       rev_child=Regions.LOST_WOODS),
    _grave("Shield Grave", Regions.GRAVEYARD_SHIELD_GRAVE, 0x04B, 0x35D),
    _grave("Heart Piece Grave", Regions.GRAVEYARD_HEART_PIECE_GRAVE, 0x31C, 0x361),
    _grave("Composers Grave", Regions.GRAVEYARD_COMPOSERS_GRAVE, 0x02D, 0x50B),
    _grave("Dampe's Grave", Regions.GRAVEYARD_DAMPES_GRAVE, 0x44F, 0x359),
]


def _ow(name: str, fwd_parent: Regions, fwd_child: Regions, fwd_index: int,
        rev_parent: Regions, rev_child: Regions, rev_index: int) -> EntranceDef:
    """Build a two-way Overworld entrance pair.

    Overworld rows are frequently *asymmetric* in this apworld: ``fwd_child`` (the
    region the forward edge leads to) often differs from ``rev_parent`` (the region
    the reverse edge departs from), because AP collapses Ship's transition buffer
    regions differently per direction. So every endpoint is given explicitly rather
    than mirrored. See AP-VS-SHIP DIVERGENCES #4 at the top of the module."""
    return EntranceDef(name, fwd_parent, fwd_child, fwd_index, rev_index,
                       ENTRANCE_TYPE_OVERWORLD, rev_parent, rev_child)


# Overworld entrances (Ship EntranceType::Overworld). 26 two-way pairs; indices
# verified against entrance_table.h, region pairs verified against this apworld's
# location_access graph. The forward index is Ship's "exit A->B", the reverse is
# "exit B->A". Several rows are asymmetric or route through a region AP names
# differently than Ship -- each such row is annotated; see the AP-VS-SHIP
# DIVERGENCES note for the general pattern.
#
# Ship's GV Lower Stream -> Lake Hylia overworld entrance (ENTR 0x219) is one-way and
# is only shuffled when decoupled entrances are on, so it lives in its own
# OVERWORLD_ONE_WAY_ENTRANCES list (below) rather than this two-way table.
OVERWORLD_ENTRANCES: list[EntranceDef] = [
    # AP collapses Ship's KF_OUTSIDE_LOST_WOODS buffer into Kokiri Forest, so the
    # Kokiri<->Lost-Woods rows depart from KOKIRI_FOREST and the bridge row lands
    # on the LW_BRIDGE_FROM_FOREST buffer (forward) but returns from LW_BRIDGE.
    _ow("KF/LW Bridge", Regions.KOKIRI_FOREST, Regions.LW_BRIDGE_FROM_FOREST, 0x5E0,
        Regions.LW_BRIDGE, Regions.KOKIRI_FOREST, 0x20D),
    _ow("KF/Lost Woods", Regions.KOKIRI_FOREST, Regions.LOST_WOODS, 0x11E,
        Regions.LW_FOREST_EXIT, Regions.KOKIRI_FOREST, 0x286),
    _ow("Lost Woods/GC Woods Warp", Regions.LOST_WOODS, Regions.GC_WOODS_WARP, 0x4E2,
        Regions.GC_WOODS_WARP, Regions.LOST_WOODS, 0x4D6),
    _ow("Lost Woods/ZR Shortcut", Regions.LOST_WOODS, Regions.ZR_FROM_SHORTCUT, 0x1DD,
        Regions.ZR_FROM_SHORTCUT, Regions.LOST_WOODS, 0x4DA),
    _ow("LW Beyond Mido/SFM", Regions.LW_BEYOND_MIDO, Regions.SFM_ENTRYWAY, 0x0FC,
        Regions.SFM_ENTRYWAY, Regions.LW_BEYOND_MIDO, 0x1A9),
    _ow("LW Bridge/Hyrule Field", Regions.LW_BRIDGE, Regions.HYRULE_FIELD, 0x185,
        Regions.HYRULE_FIELD, Regions.LW_BRIDGE, 0x4DE),
    # AP collapses Ship's HF_TO_LAKE_HYLIA buffer into Hyrule Field.
    _ow("Hyrule Field/Lake Hylia", Regions.HYRULE_FIELD, Regions.LAKE_HYLIA, 0x102,
        Regions.LAKE_HYLIA, Regions.HYRULE_FIELD, 0x189),
    _ow("Hyrule Field/Gerudo Valley", Regions.HYRULE_FIELD, Regions.GERUDO_VALLEY, 0x117,
        Regions.GERUDO_VALLEY, Regions.HYRULE_FIELD, 0x18D),
    _ow("Hyrule Field/Market Entrance", Regions.HYRULE_FIELD, Regions.MARKET_ENTRANCE, 0x276,
        Regions.MARKET_ENTRANCE, Regions.HYRULE_FIELD, 0x1FD),
    _ow("Hyrule Field/Kakariko", Regions.HYRULE_FIELD, Regions.KAKARIKO_VILLAGE, 0x0DB,
        Regions.KAKARIKO_VILLAGE, Regions.HYRULE_FIELD, 0x17D),
    _ow("Hyrule Field/Zora's River", Regions.HYRULE_FIELD, Regions.ZR_FRONT, 0x0EA,
        Regions.ZR_FRONT, Regions.HYRULE_FIELD, 0x181),
    _ow("Hyrule Field/Lon Lon Ranch", Regions.HYRULE_FIELD, Regions.LON_LON_RANCH, 0x157,
        Regions.LON_LON_RANCH, Regions.HYRULE_FIELD, 0x1F9),
    _ow("LH Shortcut/Zora's Domain", Regions.LH_FROM_SHORTCUT, Regions.ZORAS_DOMAIN, 0x328,
        Regions.ZORAS_DOMAIN, Regions.LH_FROM_SHORTCUT, 0x560),
    _ow("Gerudo Valley/GF Outskirts", Regions.GV_FORTRESS_SIDE, Regions.GERUDO_FORTRESS_OUTSKIRTS, 0x129,
        Regions.GERUDO_FORTRESS_OUTSKIRTS, Regions.GV_FORTRESS_SIDE, 0x22D),
    _ow("GF Gate/Haunted Wasteland", Regions.GF_OUTSIDE_GATE, Regions.WASTELAND_NEAR_FORTRESS, 0x130,
        Regions.WASTELAND_NEAR_FORTRESS, Regions.GF_OUTSIDE_GATE, 0x3AC),
    _ow("Wasteland/Desert Colossus", Regions.WASTELAND_NEAR_COLOSSUS, Regions.DESERT_COLOSSUS, 0x123,
        Regions.DESERT_COLOSSUS, Regions.WASTELAND_NEAR_COLOSSUS, 0x365),
    _ow("Market Entrance/Market", Regions.MARKET_ENTRANCE, Regions.MARKET, 0x0B1,
        Regions.MARKET, Regions.MARKET_ENTRANCE, 0x033),
    _ow("Market/Castle Grounds", Regions.MARKET, Regions.CASTLE_GROUNDS, 0x138,
        Regions.CASTLE_GROUNDS, Regions.MARKET, 0x25A),
    _ow("Market/Temple of Time", Regions.MARKET, Regions.TOT_ENTRANCE, 0x171,
        Regions.TOT_ENTRANCE, Regions.MARKET, 0x25E),
    _ow("Kakariko/Graveyard", Regions.KAKARIKO_VILLAGE, Regions.THE_GRAVEYARD, 0x0E4,
        Regions.THE_GRAVEYARD, Regions.KAKARIKO_VILLAGE, 0x195),
    _ow("Kak Behind Gate/DM Trail", Regions.KAK_BEHIND_GATE, Regions.DEATH_MOUNTAIN_TRAIL, 0x13D,
        Regions.DEATH_MOUNTAIN_TRAIL, Regions.KAK_BEHIND_GATE, 0x191),
    _ow("DM Trail/Goron City", Regions.DEATH_MOUNTAIN_TRAIL, Regions.GORON_CITY, 0x14D,
        Regions.GORON_CITY, Regions.DEATH_MOUNTAIN_TRAIL, 0x1B9),
    # Asymmetric: AP has no DMC "pots entry" buffer -- the forward lands in
    # DMC_LOWER_LOCAL but the reverse departs from DMC_LOWER_NEARBY.
    _ow("Goron City/DMC (Darunia)", Regions.GC_DARUNIAS_CHAMBER, Regions.DMC_LOWER_LOCAL, 0x246,
        Regions.DMC_LOWER_NEARBY, Regions.GC_DARUNIAS_CHAMBER, 0x1C1),
    # Asymmetric: forward lands in DMC_UPPER_LOCAL, reverse departs DMC_UPPER_NEARBY.
    _ow("DM Summit/DMC (Upper)", Regions.DEATH_MOUNTAIN_SUMMIT, Regions.DMC_UPPER_LOCAL, 0x147,
        Regions.DMC_UPPER_NEARBY, Regions.DEATH_MOUNTAIN_SUMMIT, 0x1BD),
    _ow("Zora's River/Zora's Domain", Regions.ZR_BEHIND_WATERFALL, Regions.ZORAS_DOMAIN, 0x108,
        Regions.ZORAS_DOMAIN, Regions.ZR_BEHIND_WATERFALL, 0x19D),
    _ow("Zora's Domain/Zora's Fountain", Regions.ZD_BEHIND_KING_ZORA, Regions.ZORAS_FOUNTAIN, 0x225,
        Regions.ZORAS_FOUNTAIN, Regions.ZD_BEHIND_KING_ZORA, 0x1A1),
]

# Ship's GV Lower Stream -> Lake Hylia overworld exit (ENTR 0x219) is one-way
# (NO_RETURN) and is shuffled ONLY when decoupled entrances are on (entrance.cpp:1335);
# in coupled mode it is filtered out and stays vanilla. It has no reverse, so
# ``rev_parent``/``rev_child`` are left None (``_decoupled_pool_edges`` skips one-way
# edges when building the reverse side). The rev_index is -1 (``_ONE_WAY_NO_DEST``);
# it is never emitted since decoupled slot data uses -1 destinations. The AP edge
# exists (gerudo_valley.py: GV_LOWER_STREAM -> LAKE_HYLIA).
OVERWORLD_ONE_WAY_ENTRANCES: list[EntranceDef] = [
    EntranceDef("GV Lower Stream to Lake Hylia", Regions.GV_LOWER_STREAM,
                Regions.LAKE_HYLIA, 0x219, -1, ENTRANCE_TYPE_OVERWORLD),
]


def _th(name: str, fortress: Regions, cell: Regions,
        fwd_index: int, rev_index: int) -> EntranceDef:
    """Build a Thieves' Hideout entrance (fortress doorway -> hideout cell).

    The reverse edge is the exact mirror ``cell -> fortress`` (rev_parent=cell,
    rev_child=fortress), matching Ship's ENTR_GERUDOS_FORTRESS_* reverse pairs 1:1 now
    that the AP hideout graph is rewired to mirror them. Shuffled REVERSE_COUPLE like
    the other coupled pools (rev = ENTR_GERUDOS_FORTRESS_*)."""
    return EntranceDef(name, fortress, cell, fwd_index, rev_index,
                       ENTRANCE_TYPE_THIEVES_HIDEOUT, cell, fortress)


# Thieves' Hideout entrances (Ship EntranceType::ThievesHideout). 13 fortress->cell
# doorways, each a coupled two-way pair; ENTR indices verified against entrance_table.h,
# both directions verified present in the AP graph. Each cell's reverse edges mirror
# Ship's ENTR_GERUDOS_FORTRESS_* pairs 1:1, so this pool shuffles REVERSE_COUPLE like
# dungeons/interiors. fwd = ENTR_THIEVES_HIDEOUT_*, rev = ENTR_GERUDOS_FORTRESS_*.
THIEVES_HIDEOUT_ENTRANCES: list[EntranceDef] = [
    _th("Hideout 1 Torch (Outskirts)", Regions.GERUDO_FORTRESS_OUTSKIRTS, Regions.THIEVES_HIDEOUT_1_TORCH_CELL, 0x486, 0x231),
    _th("Hideout 1 Torch (Near Grotto)", Regions.GF_NEAR_GROTTO, Regions.THIEVES_HIDEOUT_1_TORCH_CELL, 0x48A, 0x235),
    _th("Hideout Kitchen Corridor (Near Grotto)", Regions.GF_NEAR_GROTTO, Regions.THIEVES_HIDEOUT_KITCHEN_CORRIDOR, 0x48E, 0x239),
    _th("Hideout Kitchen Corridor (Above GTG)", Regions.GF_ABOVE_GTG, Regions.THIEVES_HIDEOUT_KITCHEN_CORRIDOR, 0x492, 0x2AA),
    _th("Hideout Steep Slope (Near Grotto)", Regions.GF_NEAR_GROTTO, Regions.THIEVES_HIDEOUT_STEEP_SLOPE_CELL, 0x496, 0x2BA),
    _th("Hideout Steep Slope (Lower Vines)", Regions.GF_BOTTOM_OF_LOWER_VINES, Regions.THIEVES_HIDEOUT_STEEP_SLOPE_CELL, 0x49A, 0x2BE),
    _th("Hideout Double Cell (Above GTG)", Regions.GF_ABOVE_GTG, Regions.THIEVES_HIDEOUT_DOUBLE_CELL, 0x49E, 0x2C2),
    _th("Hideout Double Cell (Lower Vines)", Regions.GF_TOP_OF_LOWER_VINES, Regions.THIEVES_HIDEOUT_DOUBLE_CELL, 0x4A2, 0x2C6),
    _th("Hideout Kitchen Top (Lower Vines)", Regions.GF_TOP_OF_LOWER_VINES, Regions.THIEVES_HIDEOUT_KITCHEN_BY_CORRIDOR, 0x4A6, 0x2D2),
    _th("Hideout Kitchen Top (Near GS)", Regions.GF_NEAR_GS, Regions.THIEVES_HIDEOUT_KITCHEN_OPPOSITE_CORRIDOR, 0x4AA, 0x2D6),
    _th("Hideout Break Room (Below Chest)", Regions.GF_BELOW_CHEST, Regions.THIEVES_HIDEOUT_BREAK_ROOM, 0x4AE, 0x2DA),
    _th("Hideout Break Room Corridor (Above Jail)", Regions.GF_ABOVE_JAIL, Regions.THIEVES_HIDEOUT_BREAK_ROOM_CORRIDOR, 0x4B2, 0x2DE),
    _th("Hideout Dead End (Below GS)", Regions.GF_BELOW_GS, Regions.THIEVES_HIDEOUT_DEAD_END_CELL, 0x570, 0x3A4),
]


class _Edge:
    """One coupled entrance in a shuffle pool, bound to its AP ``Entrance``(s)."""
    __slots__ = ("name", "ship_type", "fwd_index", "rev_index", "dead_end",
                 "fwd_entrance", "rev_entrance",
                 "fwd_original_region", "rev_original_region")

    def __init__(self, d: EntranceDef, fwd_entrance: "Entrance",
                 rev_entrance: "Entrance | None"):
        self.name = d.name
        self.ship_type = d.ship_type
        self.fwd_index = d.fwd_index
        self.rev_index = d.rev_index
        # Target is a forward-only dead end (boss room / tower climb) -> its reverse is
        # disconnected before a coupled shuffle (per-edge, so it works inside a mix).
        self.dead_end = d.ship_type in _DEAD_END_TYPES
        self.fwd_entrance = fwd_entrance
        self.rev_entrance = rev_entrance
        # The regions these edges led to before any shuffling. Ship reconnects an
        # entrance to its replacement's *original* connected region, so we mirror
        # that here.
        self.fwd_original_region: "Region" = fwd_entrance.connected_region
        self.rev_original_region: "Region | None" = (
            rev_entrance.connected_region if rev_entrance is not None else None)


def _entrance_name(parent: Regions, child: Regions) -> str:
    return f"{parent} -> {child}"


def _reconnect(entrance: "Entrance", new_region: "Region") -> None:
    """Repoint an entrance at ``new_region``, keeping the .entrances lists sane.

    Works from whatever the entrance is currently connected to (so it is safe to
    call repeatedly across retry attempts)."""
    old_region = entrance.connected_region
    if old_region is not None and entrance in old_region.entrances:
        old_region.entrances.remove(entrance)
    entrance.connected_region = new_region
    if entrance not in new_region.entrances:
        new_region.entrances.append(entrance)


def _disconnect(entrance: "Entrance") -> None:
    """Remove an entrance from the graph entirely (parent.exits + child.entrances).

    Used to turn a pool's targets into forward-only dead-ends."""
    parent = entrance.parent_region
    child = entrance.connected_region
    if parent is not None and entrance in parent.exits:
        parent.exits.remove(entrance)
    if child is not None and entrance in child.entrances:
        child.entrances.remove(entrance)
    entrance.connected_region = None


def _ensure_reverse_edges(world: "SohWorld", entries: list[EntranceDef]) -> None:
    """Force-create the reverse edges that the rule builder skips as statically False.

    Ship models every boss as a forward+reverse Entrance pair, but AP's rule builder
    omits an Entrance whose rule resolves to ``False`` (AutoWorld.create_entrance skips
    it unless ``force_creation``). So the adult bosses' ``BOSS_ROOM -> BOSS_ENTRYWAY``
    and Jabu's ``BOSS_ROOM -> BOSS_EXIT`` -- all ``False_()``, matching Ship -- never
    become real objects. Force-create the missing ones with their ``False_()`` rule so
    they exist as shuffle units the boss pool can locate and repoint, while staying
    non-traversable (the blue warp remains the logical exit). Edges that already exist
    (Deku/Dodongo's real ``True_()`` reverses) are left untouched. Idempotent: run once
    before the graph snapshot so re-rolls and _restore_graph preserve them."""
    for d in entries:
        if d.rev_parent is None or d.rev_child is None:
            continue
        name = _entrance_name(d.rev_parent, d.rev_child)
        try:
            world.get_entrance(name)
            continue  # already materialized
        except KeyError:
            pass
        world.create_entrance(world.get_region(str(d.rev_parent)),
                              world.get_region(str(d.rev_child)),
                              False_(), name=name, force_creation=True)


def _remove_probe_edge(temp: "Entrance") -> None:
    """Detach a temporary probe/cover entrance (the inverse of ``create_entrance``).

    Unlike ``_disconnect`` this takes the endpoints from the entrance itself and does
    not null ``connected_region`` -- the temp object is thrown away right after. Used
    by the reachability probes that wire a throwaway ``source -> interior`` edge."""
    if temp.parent_region is not None and temp in temp.parent_region.exits:
        temp.parent_region.exits.remove(temp)
    if temp.connected_region is not None and temp in temp.connected_region.entrances:
        temp.connected_region.entrances.remove(temp)


def _build_pool(world: "SohWorld",
                entries: list[EntranceDef]) -> list[_Edge] | None:
    """Resolve a pool's defs into bound ``_Edge``s.

    Returns the list of edges, or ``None`` if any expected forward entrance is
    missing from the graph (surfaced as a warning so a graph/naming regression is
    caught rather than silently dropping an entrance)."""
    edges: list[_Edge] = []
    for d in entries:
        fwd_name = _entrance_name(d.fwd_parent, d.fwd_child)
        try:
            fwd_entrance = world.get_entrance(fwd_name)
        except KeyError:
            logger.warning(
                "ER: could not find forward entrance for %s ('%s'); aborting "
                "this pool's shuffle.", d.name, fwd_name)
            return None

        rev_entrance = None
        if d.rev_parent is not None and d.rev_child is not None:
            rev_name = _entrance_name(d.rev_parent, d.rev_child)
            try:
                rev_entrance = world.get_entrance(rev_name)
            except KeyError:
                logger.warning(
                    "ER: reverse entrance for %s ('%s') not found; treating it "
                    "as absent.", d.name, rev_name)

        edges.append(_Edge(d, fwd_entrance, rev_entrance))

    return edges


def _reverse_def(d: EntranceDef) -> EntranceDef:
    """A synthetic def that treats an entrance's REVERSE direction as a forward edge.

    Under decoupled entrances the two directions of a two-way entrance are shuffled
    independently (Ship builds a separate ``<Type>Reverse`` pool). We model that pool
    by swapping each def's forward/reverse fields, so ``_build_pool`` binds the reverse
    AP entrance as the ``_Edge``'s forward and the existing coupled machinery permutes
    the reverse edges among themselves. Only valid for pools whose defs carry a real
    reverse (``rev_parent``/``rev_child`` set)."""
    return EntranceDef(f"{d.name} (reverse)", d.rev_parent, d.rev_child,
                       d.rev_index, d.fwd_index, d.ship_type,
                       d.fwd_parent, d.fwd_child)


def _apply(forwards: list[_Edge], targets: list[_Edge],
           reverse_mode: str) -> None:
    """Apply a coupled pairing to the graph.

    ``targets[i]`` is the entrance whose interior now sits behind ``forwards[i]``'s
    doorway. For a coupled placement of doorway S onto target T: S leads into T's
    interior, and (couple mode) T's reverse leads back out to where S came from."""
    for src, tgt in zip(forwards, targets):
        _reconnect(src.fwd_entrance, tgt.fwd_original_region)
    if reverse_mode == REVERSE_COUPLE:
        for src, tgt in zip(forwards, targets):
            if tgt.rev_entrance is not None and src.rev_original_region is not None:
                _reconnect(tgt.rev_entrance, src.rev_original_region)


def _restore_forwards(forwards: list[_Edge], reverse_mode: str) -> None:
    """Restore a pool's forward (and, in couple mode, reverse) edges to vanilla."""
    for edge in forwards:
        _reconnect(edge.fwd_entrance, edge.fwd_original_region)
    if reverse_mode == REVERSE_COUPLE:
        for edge in forwards:
            if edge.rev_entrance is not None and edge.rev_original_region is not None:
                _reconnect(edge.rev_entrance, edge.rev_original_region)


# --- Age-aware reachability analysis -----------------------------------------
#
# A target's interior locations may require reaching its doorway as a specific age
# (e.g. Bottom of the Well is child-only, Fire Temple is adult-only). The overworld
# doorways are themselves age-restricted. A random pairing almost never lines these
# up, which breaks `full` accessibility. So, with all items collected, we compute:
#   * cap(doorway)  = the ages that can actually use that doorway, and
#   * need(target)  = the ages a target's interior strictly requires,
# then only pair a doorway with a target when need(target) ⊆ cap(doorway).
#
# Because targets are dead ends, a doorway's reachable ages do not depend on which
# target sits behind it (in the all-items state), so these profiles are stable.


def _compute_caps(world: "SohWorld",
                  forwards: list[_Edge]) -> dict[_Edge, frozenset]:
    """For each doorway, the set of ages that can reach its (current) interior."""
    state = _er_pre_fill_state(world)
    caps: dict[_Edge, frozenset] = {}
    for fwd in forwards:
        region_enum = Regions(fwd.fwd_original_region.name)
        ages = set()
        if state._soh_can_reach_as_age(region_enum, Ages.CHILD, world.player):
            ages.add(Ages.CHILD)
        if state._soh_can_reach_as_age(region_enum, Ages.ADULT, world.player):
            ages.add(Ages.ADULT)
        caps[fwd] = frozenset(ages)
        if not ages:
            logger.warning("ER: doorway '%s' is unreachable as either age.",
                           fwd.name)
    return caps


def _sever_target(fwd: "_Edge") -> tuple["Region | None", "Region | None"]:
    """Isolate a target's interior as a pure sink: drop its forward doorway and its
    reverse exit so the interior is reachable only via an injected source edge and
    can't leak back into the overworld. Returns the regions to restore later.

    Mirrors the manual rewiring style of the rest of the module: the edges stay in
    their parent ``.exits`` (with ``connected_region = None``, so the graph search
    skips them) and are only pulled from the child ``.entrances`` list."""
    interior = fwd.fwd_original_region
    fe = fwd.fwd_entrance
    fwd_conn = fe.connected_region
    if fwd_conn is not None and fe in fwd_conn.entrances:
        fwd_conn.entrances.remove(fe)
    fe.connected_region = None

    re = fwd.rev_entrance
    rev_conn = re.connected_region if re is not None else None
    if re is not None and rev_conn is not None and re in rev_conn.entrances:
        rev_conn.entrances.remove(re)
    if re is not None:
        re.connected_region = None
    return fwd_conn, rev_conn


def _restore_target(fwd: "_Edge", fwd_conn: "Region | None",
                    rev_conn: "Region | None") -> None:
    """Undo :func:`_sever_target`."""
    fe = fwd.fwd_entrance
    fe.connected_region = fwd_conn
    if fwd_conn is not None and fe not in fwd_conn.entrances:
        fwd_conn.entrances.append(fe)
    re = fwd.rev_entrance
    if re is not None:
        re.connected_region = rev_conn
        if rev_conn is not None and re not in rev_conn.entrances:
            rev_conn.entrances.append(re)


def _interior_location_names(interior: "Region") -> set[str]:
    """Location names physically inside an interior's subgraph.

    Walks forward exits from the interior region; call only while the interior is
    severed (:func:`_sever_target`) so the walk can't leak out into the overworld.
    Handles multi-room interiors and never includes independently-reachable regions
    behind a non-dead-end exit (that exit is severed)."""
    seen = {interior}
    stack = [interior]
    names: set[str] = set()
    while stack:
        region = stack.pop()
        for loc in region.locations:
            names.add(loc.name)
        for ex in region.exits:
            nxt = ex.connected_region
            if nxt is not None and nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return names


# Prefix for the throwaway "source -> interior" edges the needs-probes inject. A
# plain "{source} -> {interior}" name collides with real entrances when the interior
# is also a spawn target (Link's House is the child spawn, Temple of Time the adult
# spawn), so probe edges get a unique, non-colliding name.
_PROBE_PREFIX = "__er_probe__ "


def _probe_entrance_name(src_region: "Region", interior: "Region") -> str:
    return f"{_PROBE_PREFIX}{src_region.name} -> {interior.name}"


def _er_pre_fill_state(world: "SohWorld") -> "CollectionState":
    """``world.get_pre_fill_state()`` for the current graph, reusing a cached base.

    The collected-item half of ``get_pre_fill_state`` (collect every pool item, ~700)
    is identical no matter how the entrance graph is wired -- only the sweep depends on
    topology. Entrance shuffling probes reachability hundreds of times (per-edge needs,
    every ``_seed_is_valid``/one-way/cap call), so re-collecting the pool each time is
    ER's single dominant cost. We build an UNSWEPT all-items base once per
    ``shuffle_entrances`` (item_pool/pre_fill_pool are stable throughout -- the trial fill
    mutates them but restores before any further reachability call) and copy+sweep it.
    Verified to give reachability identical to a fresh ``get_pre_fill_state`` even under a
    rewired probe graph: the base is unswept, so it carries no topology-specific (stale)
    rule cache, and the per-copy sweep re-derives reachability for whatever graph is live.
    Falls back to a fresh build if no cache is active (e.g. called outside shuffling)."""
    base = getattr(world, "_er_base_state", None)
    if base is None:
        return world.get_pre_fill_state()
    state = base.copy()
    state.sweep_for_advancements(world._er_locations)
    return state


def _er_begin_cache(world: "SohWorld") -> None:
    """Build the cached all-items base + location list for the shuffle (see
    :func:`_er_pre_fill_state`). Idempotent within one shuffle."""
    state = CollectionState(world.multiworld)
    for item in world.item_pool:
        state.collect(item, True)
    for name in world.pre_fill_pool:
        state.collect(world.create_item(name), True)
    world._er_base_state = state
    world._er_locations = list(world.multiworld.get_locations(world.player))


def _er_end_cache(world: "SohWorld") -> None:
    """Drop the cached base so a later genuine ``get_pre_fill_state`` (real fill) is fresh."""
    world.__dict__.pop("_er_base_state", None)
    world.__dict__.pop("_er_locations", None)


def _probe_interior(world: "SohWorld", fwd: "_Edge", source: Regions) -> set[str]:
    """Reachable locations when ``fwd``'s interior is entered only via ``source``.

    Temporarily disconnects the doorway and wires ``source -> interior`` (with a
    free rule), so a single-age ``source`` (CHILD_SPAWN / ADULT_SPAWN) isolates
    which interior locations that age can reach. Restores the graph afterwards.
    """
    interior = fwd.fwd_original_region
    entrance = fwd.fwd_entrance
    saved = entrance.connected_region
    if entrance in interior.entrances:
        interior.entrances.remove(entrance)
    entrance.connected_region = None

    src_region = world.get_region(source)
    temp = world.create_entrance(src_region, interior, True_(),
                                 name=_probe_entrance_name(src_region, interior))
    try:
        state = _er_pre_fill_state(world)
        return {loc.name for loc in world.get_locations() if loc.can_reach(state)}
    finally:
        _remove_probe_edge(temp)
        entrance.connected_region = saved
        interior.entrances.append(entrance)


def _needs_from_sets(child: set[str], adult: set[str],
                     both: set[str]) -> frozenset:
    """Derive the required-ages set from per-source reachable-location sets."""
    both_only = both - child - adult  # needs both ages available at once
    required = set()
    if (child - adult) or both_only:
        required.add(Ages.CHILD)
    if (adult - child) or both_only:
        required.add(Ages.ADULT)
    return frozenset(required)


def _compute_needs_per_edge(world: "SohWorld",
                            forwards: list[_Edge]) -> dict[_Edge, frozenset]:
    """Whole-world per-target needs (three sweeps per target).

    Used for non-dead-end pools (dungeons, bosses) whose contents gate *other*
    regions: a target is probed in isolation while the rest of the graph stays
    connected, so the world-reachability difference captures those downstream
    effects. Dead-end pools use the much cheaper :func:`_compute_needs`."""
    needs: dict[_Edge, frozenset] = {}
    for fwd in forwards:
        child = _probe_interior(world, fwd, Regions.CHILD_SPAWN)
        adult = _probe_interior(world, fwd, Regions.ADULT_SPAWN)
        both = _probe_interior(world, fwd, Regions.ROOT)
        needs[fwd] = _needs_from_sets(child, adult, both)
    return needs


def _compute_needs(world: "SohWorld",
                   forwards: list[_Edge]) -> dict[_Edge, frozenset]:
    """For each dead-end target, the ages its interior strictly requires.

    A location reachable only when entering as child contributes CHILD; only as
    adult contributes ADULT; reachable only when *both* ages are available at once
    contributes both. Locations reachable as either age impose no constraint.

    All targets are severed and probed together: one reachability sweep per
    age-source (3 total) instead of three per target. Valid only for dead-end pools
    (interiors, grottos, graves) -- because every doorway is severed and the targets
    gate nothing beyond themselves, a location's reachability under a given source is
    governed solely by the interior that owns it, matching the per-target probe at a
    fraction of the sweeps (the sweep dominates ER's cost). Non-dead-end pools must
    use :func:`_compute_needs_per_edge`."""
    # Sever every target, then attribute each interior's own locations.
    severed: list[tuple[_Edge, "Region | None", "Region | None"]] = []
    owner: dict[str, _Edge] = {}
    for fwd in forwards:
        fwd_conn, rev_conn = _sever_target(fwd)
        severed.append((fwd, fwd_conn, rev_conn))
        for name in _interior_location_names(fwd.fwd_original_region):
            owner.setdefault(name, fwd)

    interiors = [fwd.fwd_original_region for fwd in forwards]
    loc_by_name = {loc.name: loc for loc in world.get_locations()}

    def reachable_owned(source: Regions) -> set[str]:
        src_region = world.get_region(source)
        temps = [world.create_entrance(src_region, interior, True_(),
                                       name=_probe_entrance_name(src_region, interior))
                 for interior in interiors]
        try:
            state = _er_pre_fill_state(world)
            return {name for name in owner if loc_by_name[name].can_reach(state)}
        finally:
            for temp in temps:
                _remove_probe_edge(temp)

    try:
        child = reachable_owned(Regions.CHILD_SPAWN)
        adult = reachable_owned(Regions.ADULT_SPAWN)
        both = reachable_owned(Regions.ROOT)
    finally:
        for fwd, fwd_conn, rev_conn in severed:
            _restore_target(fwd, fwd_conn, rev_conn)

    # Bucket reachable locations back to their owning target, then derive needs.
    per: dict[_Edge, list[set[str]]] = {fwd: [set(), set(), set()] for fwd in forwards}
    for idx, names in enumerate((child, adult, both)):
        for name in names:
            per[owner[name]][idx].add(name)
    return {fwd: _needs_from_sets(*per[fwd]) for fwd in forwards}


def _age_compatible(caps: dict[_Edge, frozenset], needs: dict[_Edge, frozenset],
                    forbidden: dict[_Edge, Ages],
                    doorway: "_Edge", target: "_Edge") -> bool:
    """The core placement rule shared by the matcher and the walk fallback: the
    target's interior is reachable as every age it needs, and the doorway's cap
    excludes any age the target forbids (see ``_find_matching`` / ``_FORBIDDEN_AGE_EXITS``)."""
    cap = caps[doorway]
    return (needs[target] <= cap
            and (target not in forbidden or forbidden[target] not in cap))


def _find_matching(world: "SohWorld", forwards: list[_Edge],
                   caps: dict[_Edge, frozenset],
                   needs: dict[_Edge, frozenset],
                   forbidden: dict[_Edge, Ages]) -> list[_Edge] | None:
    """Randomized backtracking bijection of doorways -> targets respecting ages.

    Returns ``targets`` where ``targets[i]`` is the target for ``forwards[i]``,
    or ``None`` if no age-compatible perfect matching exists.

    Constraints per (doorway, target):
      * ``needs[target] <= caps[doorway]`` -- the target's interior is reachable as
        every age it requires; and
      * if the target is a wrong-age-exit interior, the forbidden age is *not* in the
        doorway's cap, so the player can never be routed in as that age (see
        ``_FORBIDDEN_AGE_EXITS``). Enforcing this here -- rather than only in the
        final validation -- is what keeps the search converging: a random placement
        almost never satisfies it by luck.

    Uses Kuhn's augmenting-path algorithm (O(V*E)) rather than plain DFS
    backtracking: with 36-37 edges per pool the naive backtracker can explode
    exponentially when an early assignment paints the search into a corner, whereas
    augmenting paths repair such conflicts in polynomial time. Randomness (a fresh
    bijection each call, so the retry loop explores different seeds) comes from
    shuffling both the doorway processing order and each doorway's candidate list."""
    # Candidate targets per doorway, each list shuffled for a randomized matching.
    adj: dict[_Edge, list[_Edge]] = {}
    for doorway in forwards:
        cands = [t for t in forwards
                 if _age_compatible(caps, needs, forbidden, doorway, t)]
        world.random.shuffle(cands)
        adj[doorway] = cands

    # Process the most constrained doorways first; randomize ties for variety.
    order = list(forwards)
    world.random.shuffle(order)
    order.sort(key=lambda d: len(adj[d]))

    match_doorway: dict[_Edge, _Edge] = {}  # target -> doorway it is assigned to

    def augment(doorway: "_Edge", visited: set["_Edge"]) -> bool:
        for target in adj[doorway]:
            if target in visited:
                continue
            visited.add(target)
            holder = match_doorway.get(target)
            if holder is None or augment(holder, visited):
                match_doorway[target] = doorway
                return True
        return False

    for doorway in order:
        if not augment(doorway, set()):
            return None  # no perfect matching exists

    target_of = {doorway: target for target, doorway in match_doorway.items()}
    return [target_of[f] for f in forwards]


# --- World-validity guards beyond plain location reachability -----------------
#
# Ports of Ship's ValidateWorld checks (entrance.cpp:796-905). These guard against
# states that are "logically beatable" (every item still obtainable) yet strand the
# player in-game -- e.g. exiting an interior into a region that only exists for the
# other age. Our location-reachability check cannot see these, because nothing
# becomes *unreachable*; the danger is wrong-age *access*, which is a separate axis.

# Interiors that must never be reachable as the listed age. Ported from Ship's
# childForbidden / adultForbidden lists (entrance.cpp:828-832), keyed by the
# interior region behind each forbidden exit: if that interior is reachable as the
# forbidden age, the player can be dumped out its exit into a region that only
# exists for the other age (Castle Grounds / GV Fortress Side), soft-locking.
_FORBIDDEN_AGE_EXITS: tuple[tuple[Regions, Ages], ...] = (
    (Regions.OGC_GREAT_FAIRY_FOUNTAIN, Ages.CHILD),
    (Regions.GV_CARPENTER_TENT, Ages.CHILD),
    (Regions.GANONS_CASTLE_ENTRYWAY, Ages.CHILD),
    (Regions.HC_GREAT_FAIRY_FOUNTAIN, Ages.ADULT),
    (Regions.HC_STORMS_GROTTO, Ages.ADULT),
)
_FORBIDDEN_BY_REGION: dict[Regions, Ages] = dict(_FORBIDDEN_AGE_EXITS)


def _forbidden_age(edge: "_Edge") -> "Ages | None":
    """The age (if any) a target's interior must never be reachable as."""
    try:
        return _FORBIDDEN_BY_REGION.get(Regions(edge.fwd_original_region.name))
    except ValueError:
        return None


def _age_exits_are_safe(world: "SohWorld", state: "CollectionState") -> bool:
    """No interior is reachable as an age that would strand the player on exit.

    Ship enforces this topologically via EntranceUnreachableAs while excluding each
    interior's own door (entrance.cpp:822-870). We use the all-items age-reachability
    state instead, which is equivalent for coupled pools: after a coupled shuffle a
    forbidden interior's only doorway is whichever doorway was routed onto it, so
    "reachable as the forbidden age" == "a wrong-age doorway leads here". Vanilla
    connectivity never reaches any of these as the forbidden age (verified), so the
    check is safe to run unconditionally and needs no per-pool gating. Using the
    all-items state is conservative -- fewer items could only make a region *less*
    reachable, never more -- so it can never miss a genuine wrong-age access.

    Skipped entirely when entrances are decoupled (Ship, entrance.cpp:822): with the
    two directions shuffled independently the player can always take the correct return
    direction, so the coupled "a wrong-age doorway strands you inside" reasoning no
    longer applies."""
    if world.options.decouple_entrances.value:
        return True
    player = world.player
    for region, forbidden_age in _FORBIDDEN_AGE_EXITS:
        if state._soh_can_reach_as_age(region, forbidden_age, player):
            return False
    return True


def _item_less_state(world: "SohWorld") -> "CollectionState":
    """An empty state with events swept in (no progression items collected).

    Mirrors the "no items" basis Ship uses for its start-of-seed guarantees: the
    invariants below must hold with nothing in the inventory, so the player is never
    stranded at the very start. Sweeping picks up item-independent events."""
    state = CollectionState(world.multiworld)
    state.sweep_for_advancements(list(world.multiworld.get_locations(world.player)))
    return state


def _has_time_pass_access(state: "CollectionState", world: "SohWorld", age: Ages) -> bool:
    """Ship's ``HasTimePassAccess`` (location_access.cpp:1128): some time-passing
    region is reachable as ``age``. Because reaching any ``provides_time`` region
    as an age grants both day and night everywhere reachable as that age, this is
    the guarantee that day/night-gated checks can never be permanently lost."""
    player = world.player
    stored_age = state._soh_age[player]  # type: ignore
    state._soh_age[player] = age  # type: ignore
    try:
        return any(region.can_reach(state)
                   for region in world.multiworld.get_regions(player)
                   if getattr(region, "provides_time", TimeOfDay.NONE))
    finally:
        state._soh_age[player] = stored_age  # type: ignore


def _world_age_invariants_hold(world: "SohWorld", state: "CollectionState") -> bool:
    """Global age/time guarantees Ship enforces once spawns, the overworld, or
    special interiors get shuffled (entrance.cpp:873-898).

    Dormant for the coupled dead-end pools (they never move spawns or the overworld,
    so these always hold); callers opt in via ``check_other_access``. The "all"
    interior pool, the overworld/mixed pools and the one-way pools turn it on.

    Two bases are used deliberately (DIVERGENCE #7):

    * Condition 1 -- a valid starting overworld is reachable with NO items -- is the
      true sphere-zero guard: it catches an entrance/spawn arrangement that leaves the
      player unable to leave the start at all.

    * Conditions 2-3 (both ages can pass time; the Temple of Time is reachable as the
      *other* age) are checked against the FULL item state, not item-less -- the
      caller's ``state`` (the graph is unchanged, so it needs no rebuild). With a
      closed/song-only Door of Time the other age is only reachable via the Song of
      Time, and with a closed forest leaving Kokiri needs the sword + shield -- both
      items -- so an item-less check there is a false positive (the seed is perfectly
      winnable; Ship's own progressive search collects those along the way). Checking
      with items still rejects an arrangement that severs time-pass or pedestal access
      outright. For an OPEN Door of Time both ages are reachable item-less anyway, so
      this is behaviourally identical to the original item-less check there."""
    player = world.player

    # 1) A valid starting overworld (Kokiri or Kakariko) reachable with no items.
    bootstrap = _item_less_state(world)
    starts = (Regions.KOKIRI_FOREST, Regions.KAKARIKO_VILLAGE)
    if not any(bootstrap._soh_can_reach_as_age(r, age, player)
               for r in starts for age in (Ages.CHILD, Ages.ADULT)):
        return False

    # 2) Time must be passable as BOTH ages (with the items the player will collect),
    #    or day/night-gated checks could become permanently inaccessible. A
    #    time-passing region must be reachable as each age (Ship's HasTimePassAccess,
    #    location_access.cpp:1128).
    if not (_has_time_pass_access(state, world, Ages.CHILD)
            and _has_time_pass_access(state, world, Ages.ADULT)):
        return False

    # 3) After going through time, the Temple of Time must remain reachable as the
    #    *other* age, so the player never loses pedestal access.
    starting_child = world.options.starting_age.value == world.options.starting_age.option_child
    other_age = Ages.ADULT if starting_child else Ages.CHILD
    if not state._soh_can_reach_as_age(Regions.TEMPLE_OF_TIME, other_age, player):
        return False

    return True


def _seed_is_valid(world: "SohWorld", check_other_access: bool = False) -> bool:
    """Validate the shuffled graph for entrance connectivity.

    Always enforces the wrong-age exit guard (a soft-lock guard, independent of
    accessibility). ``check_other_access`` additionally enforces the global age/time
    invariants -- left off for the current coupled dead-end pools and turned on by the
    future pools that move spawns / the overworld / special interiors (mirroring
    Ship's ``checkOtherEntranceAccess``).

    Full entrance connectivity is required regardless of AP's ``accessibility``
    option. AP's accessibility (``minimal`` = only the goal need be reachable) governs
    *item placement*, not the entrance graph: Ship's own entrance generator
    (3drando ValidateEntrances) always requires every shuffled entrance reachable, so
    a faithful port must too. Without this, an earlier pool can strand a region under
    ``minimal`` (the goal stays reachable some other way), and a later pool's doorway
    that lives in the stranded region then has an empty age-cap, making the matcher
    infeasible or the validated walk unable to start. Probing with the all-items
    pre-fill state, ``all(loc.can_reach)`` is the region-connectivity proxy: OoT's
    glitchless logic reaches every location with full items (tricks only add routes),
    so a failure here means a region is genuinely unreachable, not merely item-gated.
    This is identical to the long-validated former ``full``/``items`` path -- it now
    just runs for ``minimal`` too."""
    completion = world.multiworld.completion_condition.get(world.player)
    if completion is None:
        # true_no_logic (or no goal set): logic is bypassed, nothing to verify.
        return True
    state = _er_pre_fill_state(world)
    if not completion(state):
        return False
    if not _age_exits_are_safe(world, state):
        return False
    if check_other_access and not _world_age_invariants_hold(world, state):
        return False
    # Entrance connectivity: every location reachable with all items (see docstring).
    if not all(loc.can_reach(state) for loc in world.get_locations()):
        return False
    # NOTE: progressive (assumed-fill) BOOTSTRAP soundness -- that an item collection
    # order exists out of the start under closed/song Door of Time -- is NOT checked
    # here. It is a property of the whole layout, not of any single pool, so a per-pool
    # heuristic both rejected valid layouts (a cumulative deadlock a later pool cannot
    # fix -> hard fail) and was redundant with the accurate global gate. The real
    # `world.pre_fill()` + assumed fill in `_trial_fill_accessible` (run once per
    # candidate layout in `shuffle_entrances`, with a global re-roll) is the sound,
    # non-heuristic bootstrap check.
    return True


def _build_slot_data(forwards: list[_Edge], targets: list[_Edge],
                     decoupled: bool = False) -> list[dict[str, int]]:
    """Convert a pairing into the contract's ``entrances`` elements.

    Each shuffled direction is its own element (forward and reverse are separate),
    matching what Ship's CreateEntranceOverrides()/ParseJson() exchange.

    Coupled (default): a placement of doorway S onto target T emits BOTH directions
    as a mirrored pair -- S's forward adopts T's forward, and T's reverse adopts S's
    reverse -- carrying the paired reverse indices in ``destination`` /
    ``overrideDestination``.

    Decoupled: this pool is a single independent direction (a forward pool or a
    ``_reverse_def`` reverse pool), so each edge emits ONE element with the destination
    fields set to ``_ONE_WAY_NO_DEST`` -- Ship's decoupled emission leaves them -1 and
    rewires purely by ``index -> override`` (entrance.cpp:1652)."""
    entrances: list[dict[str, int]] = []
    for src, tgt in zip(forwards, targets):
        entrances.append({
            "type": src.ship_type,
            "index": src.fwd_index,
            "destination": _ONE_WAY_NO_DEST if decoupled else src.rev_index,
            "override": tgt.fwd_index,
            "overrideDestination": _ONE_WAY_NO_DEST if decoupled else tgt.rev_index,
        })
        if not decoupled:
            entrances.append({
                "type": tgt.ship_type,
                "index": tgt.rev_index,
                "destination": tgt.fwd_index,
                "override": src.rev_index,
                "overrideDestination": src.fwd_index,
            })
    return entrances


def _walk_shuffle(world: "SohWorld", forwards: list[_Edge],
                  caps: dict[_Edge, frozenset], needs: dict[_Edge, frozenset],
                  forbidden: dict[_Edge, Ages], reverse_mode: str,
                  check_other_access: bool) -> list[_Edge] | None:
    """Validated random-walk shuffle: a guaranteed-convergent fallback for pools the
    fast matching path can't satisfy by luck.

    Starts from the vanilla (identity) pairing -- which is valid, since every prior
    pool left the graph valid and this pool hasn't moved yet -- and repeatedly swaps
    two doorways' targets, keeping a swap only if the world stays fully valid. Because
    it never leaves a valid state, it cannot end invalid; because one swap perturbs
    far less than a full re-roll, most swaps are accepted, so it mixes well. The
    age-compat pre-check just skips obviously-bad swaps; ``_seed_is_valid`` is the real
    gate, so approximate caps can't let an invalid layout through.

    Returns the ``targets`` list (aligned with ``forwards``) with the graph left in
    that state, or ``None`` if even vanilla is invalid (a prior-pool bug; let the
    caller raise)."""
    if len(forwards) < 2:
        return None

    targets: dict[_Edge, _Edge] = {e: e for e in forwards}

    def apply_current() -> None:
        _apply(forwards, [targets[e] for e in forwards], reverse_mode)

    apply_current()
    if not _seed_is_valid(world, check_other_access):
        return None

    # Enough attempted swaps to thoroughly mix n edges (~n*ln n successful swaps);
    # bounded so the largest (mixed) pool can't run away.
    budget = min(12 * len(forwards), 1500)
    made = 0
    for _ in range(budget):
        a, b = world.random.sample(forwards, 2)
        if not (_age_compatible(caps, needs, forbidden, a, targets[b])
                and _age_compatible(caps, needs, forbidden, b, targets[a])):
            continue
        targets[a], targets[b] = targets[b], targets[a]
        apply_current()
        if _seed_is_valid(world, check_other_access):
            made += 1
        else:
            targets[a], targets[b] = targets[b], targets[a]  # revert
            apply_current()
    logger.debug("ER: random walk accepted %d swaps over %d edges", made,
                 len(forwards))
    return [targets[e] for e in forwards]


def _shuffle_pool(world: "SohWorld", label: str, entries: list[EntranceDef],
                  reverse_mode: str, dead_end_targets: bool,
                  check_other_access: bool = False,
                  decoupled: bool = False) -> list[dict[str, int]]:
    """Shuffle one pool in place on the graph; return its slot-data elements.

    Pools are applied cumulatively (not restored between pools): a later pool's
    age-caps are computed against the graph left by the earlier pools, which is
    what makes e.g. boss reachability reflect the dungeon placement.

    ``dead_end_targets`` selects the fast batched needs computation (valid only when
    each target gates nothing beyond itself -- interiors, grottos, graves); pools
    whose targets gate other regions (dungeons, bosses) must pass ``False``.

    ``check_other_access`` is forwarded to validation; pools that move spawns, the
    overworld, or special interiors should set it so the global age/time invariants
    are enforced (mirrors Ship's ``checkOtherEntranceAccess``).

    ``decoupled`` marks a single-direction pool (a forward pool, or a ``_reverse_def``
    reverse pool, shuffled independently of its opposite direction). It only changes
    slot-data emission (one ``-1``-destination element per edge) and drops the
    wrong-age forbidden constraint: Ship skips that check entirely when decoupled
    (entrance.cpp:822), because with independent directions the player can always take
    the correct return, so a forbidden interior can no longer be entered as the wrong
    age via a mirrored doorway. Callers pass ``REVERSE_KEEP`` so the opposite direction
    (shuffled by its own pass) is left untouched here."""
    forwards = _build_pool(world, entries)
    if not forwards:
        return []

    # Dead-end edges (boss rooms / tower climb): make the target a forward-only sink so a
    # vanilla reverse edge can't create a phantom cross-area path once the forward moves.
    # Per-edge, so a coupled pool (incl. the mix) can hold both dead-end and coupled
    # members -- the coupling step skips a dead-end target (rev_entrance is None below).
    # Skipped when decoupled: there the reverse is a real shuffle unit (its own pass /
    # _reverse_def edge in the mix), so it must stay live to be permuted, not disconnected.
    if not decoupled:
        for edge in forwards:
            if edge.dead_end and edge.rev_entrance is not None:
                _disconnect(edge.rev_entrance)
                edge.rev_entrance = None

    caps = _compute_caps(world, forwards)
    needs = (_compute_needs(world, forwards) if dead_end_targets
             else _compute_needs_per_edge(world, forwards))
    forbidden = ({} if decoupled else
                 {edge: age for edge in forwards
                  if (age := _forbidden_age(edge)) is not None})

    # A target can never be *required* as the very age it forbids: the matcher only
    # ever routes it through a doorway whose cap excludes that age, so the player never
    # enters it as that age, and any interior location that needs it is unreachable by
    # design (the same in vanilla -- e.g. HC Storms Grotto is adult-forbidden, yet its
    # contents are child-reachable through the grotto's CASTLE_GROUNDS exit, which the
    # severed dead-end needs-probe cannot see and so mis-attributes to ADULT). Keeping
    # the forbidden age in `needs` makes `needs[t] <= cap` and `forbidden ∉ cap`
    # contradictory -> a spurious "no matching exists". Clamp it; genuine unreachability
    # of forbidden-age-only content is still caught by the full-accessibility gate.
    for edge, age in forbidden.items():
        if age in needs[edge]:
            needs[edge] = needs[edge] - {age}

    for _ in range(MAX_SHUFFLE_ATTEMPTS):
        targets = _find_matching(world, forwards, caps, needs, forbidden)
        if targets is None:
            # No perfect bijection under the caps/needs model. That model is SOUND
            # (never accepts an invalid layout) but not COMPLETE: it can reject a
            # layout that is actually valid, because `needs` is probed by force-
            # injecting each interior from a spawn -- so a location reachable only as
            # child through that injection marks the interior CHILD-needed even when
            # its vanilla doorway is adult-only and the game reaches that content as
            # adult (e.g. Kak Bazaar / Shooting Gallery / Granny's, DMC Great Fairy).
            # Such interiors make `needs > own cap`, so even the identity (vanilla)
            # pairing fails the model; when enough of them coincide the bipartite
            # matching has no solution at all (a Hall deficit) and returns None. Since
            # infeasibility is a property of caps/needs (retrying only reshuffles the
            # candidate order, never the feasibility), don't retry and don't hard-fail
            # -- fall through to the validated random walk below, which starts from the
            # genuinely-valid vanilla layout and gates on _seed_is_valid rather than the
            # approximate model.
            _restore_forwards(forwards, reverse_mode)
            break
        _apply(forwards, targets, reverse_mode)
        if _seed_is_valid(world, check_other_access):
            logger.debug("ER: shuffled %d %s entrances for player %d",
                         len(forwards), label, world.player)
            return _build_slot_data(forwards, targets, decoupled)
        _restore_forwards(forwards, reverse_mode)

    # Fast path exhausted (or infeasible under the model -- see the break above). A fresh random bijection rewires every edge at once, so
    # one constraint violation anywhere fails the whole attempt -- yield collapses
    # for tightly-constrained layouts (e.g. a particular dungeon shuffle leaving the
    # overworld little room to keep the item-less Temple-of-Time/time-pass backbone
    # reachable as both ages). Fall back to a validated random walk: start from the
    # already-valid vanilla layout and apply only swaps that keep the world valid, so
    # it can never end invalid. A single swap is a small perturbation that stays valid
    # far more often than a full re-roll, so this mixes well and is guaranteed to
    # converge (worst case it returns vanilla). Rescues the unlucky tail instead of
    # hard-failing; the fast path still handles the common case (and its variety).
    targets = _walk_shuffle(world, forwards, caps, needs, forbidden,
                            reverse_mode, check_other_access)
    if targets is not None:
        logger.debug("ER: shuffled %d %s entrances for player %d via random walk",
                     len(forwards), label, world.player)
        return _build_slot_data(forwards, targets, decoupled)

    _restore_forwards(forwards, reverse_mode)
    raise RuntimeError(
        f"SoH ER: could not find a valid {label} entrance shuffle for player "
        f"{world.player} after {MAX_SHUFFLE_ATTEMPTS} attempts + random walk.")


def _decoupled_pool_edges(entries: list[EntranceDef]) -> list[EntranceDef]:
    """Both independent directions of every def in a decoupled pool, as one flat list.

    Two-way defs contribute their forward edge plus a :func:`_reverse_def` reverse
    edge; one-way defs (no ``rev_parent``/``rev_child`` -- e.g. GV Lower Stream ->
    Lake Hylia) contribute only their forward. Used where a decoupled pool is shuffled
    as a SINGLE combined matching (the overworld pool and the mixed pool), matching
    Ship, which folds both directions of the overworld entrances into one pool rather
    than a separate ``OverworldReverse`` pool."""
    out = list(entries)
    out += [_reverse_def(d) for d in entries
            if d.rev_parent is not None and d.rev_child is not None]
    return out


def _shuffle_decoupled(world: "SohWorld", label: str,
                       entries: list[EntranceDef]) -> list[dict[str, int]]:
    """Shuffle a coupled two-way pool as two INDEPENDENT one-directional pools.

    Ship's decoupled mode (entrance.cpp builds a separate ``<Type>Reverse`` pool):
    the forward edges are permuted among themselves, then the reverse edges -- treated
    as forwards via :func:`_reverse_def` -- are permuted among themselves, with no
    round-trip link between the two directions. Each pass runs forward-only
    (``REVERSE_KEEP`` leaves the opposite direction for its own pass) and emits its
    own ``-1``-destination overrides (``decoupled=True``).

    Order matters: the forward pass runs first so the reverse pass's reachability is
    computed against the placed dungeon interiors. ``check_other_access`` is set on
    both because the reverse pass relocates where dungeon exits deposit the player in
    the overworld, which can move age/time access."""
    out = _shuffle_pool(world, f"{label} (fwd)", entries, REVERSE_KEEP,
                        dead_end_targets=False, check_other_access=True, decoupled=True)
    out += _shuffle_pool(world, f"{label} (rev)", [_reverse_def(d) for d in entries],
                         REVERSE_KEEP, dead_end_targets=False, check_other_access=True,
                         decoupled=True)
    return out


# --- Blue warps --------------------------------------------------------------
#
# A dungeon boss's blue warp ejects the player from the boss room to an overworld
# spot. Blue warps are not shuffled themselves; they are *derived* from the boss
# AND dungeon-entrance placement, so defeating a boss drops you at the overworld of
# whichever entrance slot led you to that room -- not its vanilla home. We port
# Ship's resolution (entrance.cpp:1525-1607, non-decoupled), keyed by the boss ROOM
# (not the boss doorway): whatever doorway now leads into the room, chase backward
# through the placement until we reach the overworld, and eject there. Keying by the
# room is what makes it correct under a *mixed* pool, where a boss room can sit behind
# a dungeon/interior/overworld doorway (not just a boss doorway) and a boss doorway
# can lead to something that is not a boss room. See ``_resolve_blue_warp_eject`` for
# the chase and ``_blue_warp_overrides`` / ``_rewire_blue_warp_logic`` for the
# game-side and logic-graph applications, which share it so overrides and graph agree.

# Blue-warp ENTR indices keyed by the boss room they eject from (entrance.cpp
# BlueWarp table + entrance_table.h).
_BLUE_WARP_BY_BOSS_ROOM: dict[Regions, int] = {
    Regions.DEKU_TREE_BOSS_ROOM: 0x457,
    Regions.DODONGOS_CAVERN_BOSS_ROOM: 0x47A,
    Regions.JABU_JABUS_BELLY_BOSS_ROOM: 0x10E,
    Regions.FOREST_TEMPLE_BOSS_ROOM: 0x608,
    Regions.FIRE_TEMPLE_BOSS_ROOM: 0x564,
    Regions.WATER_TEMPLE_BOSS_ROOM: 0x60C,
    Regions.SPIRIT_TEMPLE_BOSS_ROOM: 0x610,
    Regions.SHADOW_TEMPLE_BOSS_ROOM: 0x580,
    # Ganon's Tower, when it joins the boss pool (ShuffleGanonsTower). FLOOR_1 is
    # AP's analog of Ship's STAIRS_1; its "blue warp" ejects to Castle Grounds.
    Regions.GANONS_TOWER_FLOOR_1: 0x23F,
}
# Ganon's Tower blue warp (Castle Grounds). Emitted as identity for the dungeon
# "on + Ganon" shuffle when the tower entrance itself is NOT shuffled; when the
# tower joins the boss pool it is resolved through the boss-slot loop instead.
_GANON_BLUE_WARP_INDEX = 0x23F

# The overworld region each boss room's blue warp ejects to in vanilla. These are
# the static ``BOSS_ROOM -> overworld`` edges authored in the dungeon
# location_access files (gated on that dungeon's completion event). Under a boss
# shuffle the destination must follow the *slot*, not the boss room, so this map
# both identifies each blue-warp edge (by its vanilla name) and supplies the
# per-slot destination -- see ``_rewire_blue_warp_logic``.
_BLUE_WARP_DEST_BY_BOSS_ROOM: dict[Regions, Regions] = {
    Regions.DEKU_TREE_BOSS_ROOM: Regions.KF_OUTSIDE_DEKU_TREE,
    Regions.DODONGOS_CAVERN_BOSS_ROOM: Regions.DEATH_MOUNTAIN_TRAIL,
    Regions.JABU_JABUS_BELLY_BOSS_ROOM: Regions.ZORAS_FOUNTAIN,
    Regions.FOREST_TEMPLE_BOSS_ROOM: Regions.SACRED_FOREST_MEADOW,
    Regions.FIRE_TEMPLE_BOSS_ROOM: Regions.DMC_CENTRAL_LOCAL,
    Regions.WATER_TEMPLE_BOSS_ROOM: Regions.LAKE_HYLIA,
    Regions.SPIRIT_TEMPLE_BOSS_ROOM: Regions.DESERT_COLOSSUS,
    Regions.SHADOW_TEMPLE_BOSS_ROOM: Regions.GRAVEYARD_WARP_PAD_REGION,
    # Tower: no such static edge exists in AP (FLOOR_1 climbs to Ganon and the game
    # ends -- no blue-warp-out edge), so _rewire_blue_warp_logic finds nothing to
    # repoint for the tower slot. Present for symmetry with the override loop.
    Regions.GANONS_TOWER_FLOOR_1: Regions.CASTLE_GROUNDS_FROM_GANONS_CASTLE,
}

# Ship's blue-warp derivation chains through the *dungeon-entrance* shuffle as well
# as the boss shuffle (entrance.cpp:1591-1607, gated on non-decoupled): the blue
# warp ejects to the overworld exit of whichever dungeon-entrance *slot* the boss's
# dungeon now occupies. To resolve that we need, per boss slot, that slot's dungeon
# overworld entryway (whose relocation we follow)...
_BOSS_ROOM_TO_DUNGEON_ENTRYWAY: dict[Regions, Regions] = {
    Regions.DEKU_TREE_BOSS_ROOM: Regions.DEKU_TREE_ENTRYWAY,
    Regions.DODONGOS_CAVERN_BOSS_ROOM: Regions.DODONGOS_CAVERN_ENTRYWAY,
    Regions.JABU_JABUS_BELLY_BOSS_ROOM: Regions.JABU_JABUS_BELLY_ENTRYWAY,
    Regions.FOREST_TEMPLE_BOSS_ROOM: Regions.FOREST_TEMPLE_ENTRYWAY,
    Regions.FIRE_TEMPLE_BOSS_ROOM: Regions.FIRE_TEMPLE_ENTRYWAY,
    Regions.WATER_TEMPLE_BOSS_ROOM: Regions.WATER_TEMPLE_ENTRYWAY,
    Regions.SPIRIT_TEMPLE_BOSS_ROOM: Regions.SPIRIT_TEMPLE_ENTRYWAY,
    Regions.SHADOW_TEMPLE_BOSS_ROOM: Regions.SHADOW_TEMPLE_ENTRYWAY,
    # Tower: its "dungeon" is Ganon's Castle, so its blue warp chains through the
    # Ganon's Castle entrance shuffle (dungeon "on + Ganon"); identity otherwise.
    Regions.GANONS_TOWER_FLOOR_1: Regions.GANONS_CASTLE_ENTRYWAY,
}
# ...and, per dungeon-entrance slot (keyed by its vanilla entryway), where that
# slot's blue warp lands: (overworld region for the logic graph, ENTR index for the
# game override). Boss dungeons eject to their boss room's blue-warp pad (Ship's
# ``dungeonExits``); the non-boss dungeons and Ganon's Castle have no blue-warp pad,
# so they eject to their dungeon entrance's overworld side (the plain reverse), using
# that reverse's ENTR. Every index verified against Ship's entrance_table.h.
_DUNGEON_SLOT_BLUE_WARP: dict[Regions, tuple[Regions, int]] = {
    Regions.DEKU_TREE_ENTRYWAY: (Regions.KF_OUTSIDE_DEKU_TREE, 0x457),
    Regions.DODONGOS_CAVERN_ENTRYWAY: (Regions.DEATH_MOUNTAIN_TRAIL, 0x47A),
    Regions.JABU_JABUS_BELLY_ENTRYWAY: (Regions.ZORAS_FOUNTAIN, 0x10E),
    Regions.FOREST_TEMPLE_ENTRYWAY: (Regions.SACRED_FOREST_MEADOW, 0x608),
    Regions.FIRE_TEMPLE_ENTRYWAY: (Regions.DMC_CENTRAL_LOCAL, 0x564),
    Regions.WATER_TEMPLE_ENTRYWAY: (Regions.LAKE_HYLIA, 0x60C),
    Regions.SPIRIT_TEMPLE_ENTRYWAY: (Regions.DESERT_COLOSSUS, 0x610),
    Regions.SHADOW_TEMPLE_ENTRYWAY: (Regions.GRAVEYARD_WARP_PAD_REGION, 0x580),
    Regions.BOTTOM_OF_THE_WELL_ENTRYWAY: (Regions.KAK_WELL, 0x2A6),
    Regions.ICE_CAVERN_ENTRYWAY: (Regions.ZF_LEDGE, 0x3D4),
    Regions.GERUDO_TRAINING_GROUND_ENTRYWAY: (Regions.GF_EXITING_GTG, 0x3A8),
    Regions.GANONS_CASTLE_ENTRYWAY: (Regions.CASTLE_GROUNDS_FROM_GANONS_CASTLE,
                                     _GANON_BLUE_WARP_INDEX),
}

# Drift guard: for every boss room that maps to a dungeon slot, the per-boss-room maps
# and the per-slot table must agree on that slot's (overworld dest, ENTR index) -- these
# are hand-verified against Ship's entrance_table.h, so a lone edit to one table would
# otherwise diverge silently.
for _room, _entryway in _BOSS_ROOM_TO_DUNGEON_ENTRYWAY.items():
    assert _DUNGEON_SLOT_BLUE_WARP[_entryway] == (
        _BLUE_WARP_DEST_BY_BOSS_ROOM[_room], _BLUE_WARP_BY_BOSS_ROOM[_room]), (
        f"blue-warp table mismatch for {_room}")

# The eight dungeon boss rooms (in boss-pool order). The tower's FLOOR_1 is appended
# by the caller when ShuffleGanonsTower joins it to the boss pool. One blue warp is
# derived per room regardless of which doorway type now leads into it.
_BOSS_ROOMS: list[Regions] = [d.fwd_child for d in BOSS_ENTRANCES]

# Every coupled doorway that can host a boss room or dungeon entryway as its
# destination (all of them, once mixing is on). ``_build_doorway_index`` reads each
# one's current forward destination to answer "which doorway now leads into region R?"
# -- the backbone of the blue-warp chase.
def _all_doorway_defs() -> list[EntranceDef]:
    return [*DUNGEON_ENTRANCES, GANON_ENTRANCE, *BOSS_ENTRANCES, GANON_TOWER_ENTRANCE,
            *INTERIOR_ENTRANCES, *SPECIAL_INTERIOR_ENTRANCES, *GROTTO_ENTRANCES,
            *OVERWORLD_ENTRANCES, *THIEVES_HIDEOUT_ENTRANCES]


def _build_doorway_index(world: "SohWorld") -> dict[Regions, EntranceDef]:
    """Map each region to the coupled doorway whose forward edge currently leads into
    it. Built from the live graph (pre-rename, so vanilla names still resolve); edges
    the rule builder never materialized are simply absent. Keys we actually query --
    boss rooms and dungeon entryways -- have a single incoming doorway, so first-writer
    wins is deterministic and unambiguous."""
    idx: dict[Regions, EntranceDef] = {}
    for d in _all_doorway_defs():
        try:
            ent = world.get_entrance(_entrance_name(d.fwd_parent, d.fwd_child))
        except KeyError:
            continue
        conn = ent.connected_region
        if conn is None:
            continue
        try:
            idx.setdefault(Regions(conn.name), d)
        except ValueError:
            continue
    return idx


def _resolve_blue_warp_eject(world: "SohWorld", boss_room: Regions,
                             doorway_by_dest: dict[Regions, EntranceDef],
                             ) -> "tuple[Regions, int] | None":
    """Chase the placement backward from ``boss_room`` to the overworld its blue warp
    ejects to. AP-native analog of Ship's bossExits/dungeonExits walk (entrance.cpp
    1591-1607, non-decoupled): follow the doorway now entering the room, and

      * a *dungeon* doorway -> eject at that dungeon's own overworld pad;
      * a *boss* doorway -> hop to its dungeon's entryway and keep chasing (the room
        sits deeper inside a dungeon whose entrance may itself be relocated);
      * any *other* doorway (interior/overworld/grotto/thieves, only under a full mix)
        -> eject via that doorway's own reverse edge;
      * nothing shuffled leading here -> the room/dungeon is in its vanilla slot.

    Returns ``(overworld region, blue-warp ENTR index)`` or ``None``. The loop is
    bounded by the index size purely as a cycle guard."""
    region = boss_room
    for _ in range(len(doorway_by_dest) + 2):
        d = doorway_by_dest.get(region)
        if d is None:
            slot = _DUNGEON_SLOT_BLUE_WARP.get(region)
            if slot is not None:
                return slot
            own = _BOSS_ROOM_TO_DUNGEON_ENTRYWAY.get(region)
            return _DUNGEON_SLOT_BLUE_WARP.get(own) if own is not None else None
        if d.fwd_child in _DUNGEON_SLOT_BLUE_WARP:
            return _DUNGEON_SLOT_BLUE_WARP[d.fwd_child]
        nxt = _BOSS_ROOM_TO_DUNGEON_ENTRYWAY.get(d.fwd_child)
        if nxt is not None:
            region = nxt
            continue
        if d.rev_child is None or d.rev_index == _ONE_WAY_NO_DEST:
            return None
        return (d.rev_child, d.rev_index)
    return None


def _blue_warp_overrides(world: "SohWorld", boss_rooms: list[Regions],
                         include_ganon: bool) -> list[dict[str, int]]:
    """Derive BlueWarp (type 4) override elements from the current placement.

    Call after the boss/dungeon pools have been applied. One element per boss room:
    ``index = blue_warp(room)`` (fixed per room) and ``override = blue_warp(resolved
    ejection slot)`` from ``_resolve_blue_warp_eject``. One-way, so the destination
    fields are ``-1`` (see ``_ONE_WAY_NO_DEST``).

    Keying by the room (not the doorway) is correct even when a mixed pool puts a boss
    room behind a non-boss doorway. Decoupled: exits are independent of entrances and
    the chain is skipped (Ship entrance.cpp:1594), so each room ejects at its OWN
    vanilla pad (identity).

    ``boss_rooms`` is the eight dungeon boss rooms plus Ganon's Tower FLOOR_1 when it
    joins the boss pool (see ``_run_entrance_pools``); FLOOR_1's blue warp is ``0x23F``
    (Castle Grounds), so it takes the place of the standalone Ganon identity warp."""
    decoupled = world.options.decouple_entrances.value
    index = None if decoupled else _build_doorway_index(world)
    out: list[dict[str, int]] = []
    for room in boss_rooms:
        bw_index = _BLUE_WARP_BY_BOSS_ROOM[room]
        if decoupled:
            eject: "tuple[Regions, int] | None" = (
                _BLUE_WARP_DEST_BY_BOSS_ROOM[room], bw_index)
        else:
            eject = _resolve_blue_warp_eject(world, room, index)
        if eject is None:
            continue
        out.append({"type": ENTRANCE_TYPE_BLUE_WARP, "index": bw_index,
                    "destination": _ONE_WAY_NO_DEST, "override": eject[1],
                    "overrideDestination": _ONE_WAY_NO_DEST})
    # Emit the standalone Ganon identity warp only if 0x23F was not already emitted by
    # the loop -- when the tower is in ``boss_rooms``, FLOOR_1 already produced index
    # 0x23F, so a second element would duplicate it.
    if include_ganon and not any(o["index"] == _GANON_BLUE_WARP_INDEX for o in out):
        out.append({"type": ENTRANCE_TYPE_BLUE_WARP,
                    "index": _GANON_BLUE_WARP_INDEX, "destination": _ONE_WAY_NO_DEST,
                    "override": _GANON_BLUE_WARP_INDEX,
                    "overrideDestination": _ONE_WAY_NO_DEST})
    return out


def _rewire_blue_warp_logic(world: "SohWorld", boss_rooms: list[Regions]) -> None:
    """Repoint each boss room's blue-warp *logic* edge to follow the placement.

    ``_blue_warp_overrides`` fixes the game side; this fixes the region graph. The
    ``BOSS_ROOM -> overworld`` edges are authored statically per boss room, so under
    an entrance shuffle logic would still credit a relocated room with its *vanilla*
    overworld exit -- e.g. defeating a boss placed behind Jabu Jabu could "reach" its
    vanilla pad, when the warp actually ejects you outside Jabu. Mirror of the override
    loop and share its chain (``_resolve_blue_warp_eject``), so logic and the emitted
    overrides agree.

    Call after the boss/dungeon pools have been applied; gated the same as the
    overrides (dungeon or boss shuffle on). Re-roll-safe: each edge is looked up by
    its (stable) vanilla name and repointed from wherever it currently sits, and
    ``_restore_graph`` resets it between attempts. The completion-event gate on the
    edge is left untouched -- you trigger the warp by beating whichever boss is there.

    ``boss_rooms`` matches ``_blue_warp_overrides``. Decoupled leaves every edge at its
    vanilla destination (identity). The tower's FLOOR_1 has no blue-warp-out edge in AP
    (beating Ganon ends the game), so it is silently skipped."""
    if world.options.decouple_entrances.value:
        return
    index = _build_doorway_index(world)
    for room in boss_rooms:
        room_vanilla_dest = _BLUE_WARP_DEST_BY_BOSS_ROOM.get(room)
        if room_vanilla_dest is None:
            continue
        try:
            blue_warp = world.get_entrance(_entrance_name(room, room_vanilla_dest))
        except KeyError:
            continue
        eject = _resolve_blue_warp_eject(world, room, index)
        if eject is None:
            continue
        _reconnect(blue_warp, world.get_region(str(eject[0])))


# --- One-way entrances (spawns, warp songs, owl drops) -----------------------
#
# Unlike the coupled pools, these are one-way: a single source edge gets
# repointed to a new landing region, with no reverse. Ship models them as
# entrances with no return (``NO_RETURN_ENTRANCE``); the override JSON sets both
# ``destination`` and ``overrideDestination`` to ``-1`` (see ``_ONE_WAY_NO_DEST``).
#
# Ship draws one-way targets from the full static entrance table (entrance.cpp
# BuildOneWayTargets): every *directed* entrance of a set of valid target types is
# a candidate landing, consumed at most once across all one-way pools. We mirror
# that -- ``_ONE_WAY_TARGET_SPECS`` enumerates both directions of every overworld /
# interior / special-interior / grotto pair plus the one-way landings themselves,
# regardless of which pools are actually shuffled (Ship builds the target set from
# the static table, not the shuffled pools). A one-way override always lands the
# player at the *original* (vanilla) region behind the target's index -- Ship's
# ApplyEntranceOverrides connects via ``GetOriginalConnectedRegionKey`` -- so the
# coupled pools' own shuffling never changes where a one-way deposits you, which is
# why building targets from vanilla landings stays correct even when those pools
# are shuffled too.
#
# The valid target *types* differ by source (``_ONE_WAY_TARGET_TYPES_BY_SOURCE``):
# owl drops are physically overworld flights, so they may only land at overworld-
# style targets (warp / owl / overworld) and never inside an interior or grotto;
# spawns and warp songs may also land inside interiors and grottos. Ship also
# excludes the Prelude-of-Light -> Temple-of-Time landing from owl targets
# specifically (``_OWL_EXCLUDED_TARGET_INDICES``). EntranceType::Extra has no rows
# in Ship's table, so it contributes nothing and is omitted.
#
# Ship's static glitchless "priority entrances" (Bolero/Nocturne/Requiem) force a
# one-way *into* a few hard-to-reach regions up front so they never strand. We do the
# same job per seed and more generally: ``_one_way_requirements`` detects which one-way
# landings are actually load-bearing for THIS seed's (already-shuffled) graph and
# ``_place_priorities`` force-covers each before the rest is filled. See DIVERGENCE #5.
#
# A one-way edge moves a single source edge to a landing; it can strand the player only
# by (a) delivering them to a region as an age that has no way out, or (b) vacating a
# landing that was the region's sole access. ``delivers`` captures which ages a source
# can deposit the player as (a faithful port of Ship's ``EntranceUnreachableAs``: owl
# drops + child spawn are child-only, adult spawn is adult-only, warp songs are usable
# as both ages); ``_one_way_compatible`` refuses any landing whose forbidden age the
# source can deliver, the requirements machinery handles (b), and a final full
# validation guards the assembled result.

# Sentinel for the destination / overrideDestination fields of a one-way override.
# Must be -1, not 0: Ship treats an all-zero override as "unshuffled", and 0 is a
# real entrance index (ENTR_DEKU_TREE_ENTRANCE == 0x000).
_ONE_WAY_NO_DEST = -1


@dataclass(frozen=True)
class OneWayDef:
    """One one-way entrance: a source edge ``parent -> dest`` and its ENTR index.

    ``delivers`` is the set of ages the source can deposit the player at its
    landing as (Ship's ``EntranceUnreachableAs``). It serves as both the source's
    cap (when this def is shuffled) and is irrelevant when it is used only as a
    target (a landing is reached as whatever age the *source* delivers)."""
    name: str
    parent: Regions
    dest: Regions
    index: int
    ship_type: int
    delivers: frozenset


_BOTH_AGES = frozenset((Ages.CHILD, Ages.ADULT))
_CHILD_ONLY = frozenset((Ages.CHILD,))
_ADULT_ONLY = frozenset((Ages.ADULT,))


SPAWN_ENTRANCES: list[OneWayDef] = [
    OneWayDef("Child Spawn", Regions.CHILD_SPAWN, Regions.KF_LINKS_HOUSE,
              0x0BB, ENTRANCE_TYPE_SPAWN, _CHILD_ONLY),
    OneWayDef("Adult Spawn", Regions.ADULT_SPAWN, Regions.TEMPLE_OF_TIME,
              0x282, ENTRANCE_TYPE_SPAWN, _ADULT_ONLY),
]

WARP_SONG_ENTRANCES: list[OneWayDef] = [
    OneWayDef("Minuet of Forest Warp", Regions.MINUET_OF_FOREST_WARP,
              Regions.SACRED_FOREST_MEADOW, 0x600, ENTRANCE_TYPE_WARP_SONG, _BOTH_AGES),
    OneWayDef("Bolero of Fire Warp", Regions.BOLERO_OF_FIRE_WARP,
              Regions.DMC_CENTRAL_LOCAL, 0x4F6, ENTRANCE_TYPE_WARP_SONG, _BOTH_AGES),
    OneWayDef("Serenade of Water Warp", Regions.SERENADE_OF_WATER_WARP,
              Regions.LAKE_HYLIA, 0x604, ENTRANCE_TYPE_WARP_SONG, _BOTH_AGES),
    OneWayDef("Requiem of Spirit Warp", Regions.REQUIEM_OF_SPIRIT_WARP,
              Regions.DESERT_COLOSSUS, 0x1F1, ENTRANCE_TYPE_WARP_SONG, _BOTH_AGES),
    OneWayDef("Nocturne of Shadow Warp", Regions.NOCTURNE_OF_SHADOW_WARP,
              Regions.GRAVEYARD_WARP_PAD_REGION, 0x568, ENTRANCE_TYPE_WARP_SONG, _BOTH_AGES),
    OneWayDef("Prelude of Light Warp", Regions.PRELUDE_OF_LIGHT_WARP,
              Regions.TEMPLE_OF_TIME, 0x5F4, ENTRANCE_TYPE_WARP_SONG, _BOTH_AGES),
]

OWL_DROP_ENTRANCES: list[OneWayDef] = [
    OneWayDef("LH Owl Flight", Regions.LH_OWL_FLIGHT, Regions.HYRULE_FIELD,
              0x27E, ENTRANCE_TYPE_OWL_DROP, _CHILD_ONLY),
    OneWayDef("DMT Owl Flight", Regions.DMT_OWL_FLIGHT, Regions.KAK_IMPAS_ROOFTOP,
              0x554, ENTRANCE_TYPE_OWL_DROP, _CHILD_ONLY),
]

# Which target entrance types each one-way SOURCE type may be sent to (Ship's
# BuildOneWayTargets validTargetTypes). Owl drops never land inside interiors or
# grottos; spawns and warp songs may.
_OWL_TARGET_TYPES = frozenset((
    ENTRANCE_TYPE_WARP_SONG, ENTRANCE_TYPE_OWL_DROP, ENTRANCE_TYPE_OVERWORLD))
_SPAWN_WARP_TARGET_TYPES = frozenset((
    ENTRANCE_TYPE_SPAWN, ENTRANCE_TYPE_WARP_SONG, ENTRANCE_TYPE_OWL_DROP,
    ENTRANCE_TYPE_OVERWORLD, ENTRANCE_TYPE_INTERIOR,
    ENTRANCE_TYPE_SPECIAL_INTERIOR, ENTRANCE_TYPE_GROTTO_GRAVE))
_ONE_WAY_TARGET_TYPES_BY_SOURCE: dict[int, frozenset] = {
    ENTRANCE_TYPE_OWL_DROP: _OWL_TARGET_TYPES,
    ENTRANCE_TYPE_SPAWN: _SPAWN_WARP_TARGET_TYPES,
    ENTRANCE_TYPE_WARP_SONG: _SPAWN_WARP_TARGET_TYPES,
}

# Targets excluded from owl drops specifically (Ship's BuildOneWayTargets exclude
# pair for OwlDrop). 0x5F4 is the Prelude of Light -> Temple of Time warp landing.
_OWL_EXCLUDED_TARGET_INDICES = frozenset((0x5F4,))


def _all_one_way_target_specs() -> list[tuple[str, int, Regions, int]]:
    """Every candidate one-way landing as ``(name, index, region, pool_type)``.

    The one-way landings contribute a single directed edge each; the coupled
    overworld / interior / special-interior / grotto pairs contribute *both*
    directions (Ship's ``GetShuffleableEntrances`` returns both, and each becomes a
    target). ``region`` is the vanilla landing region behind ``index``."""
    specs: list[tuple[str, int, Regions, int]] = []
    for d in (*SPAWN_ENTRANCES, *WARP_SONG_ENTRANCES, *OWL_DROP_ENTRANCES):
        specs.append((d.name, d.index, d.dest, d.ship_type))
    for table in (OVERWORLD_ENTRANCES, INTERIOR_ENTRANCES,
                  SPECIAL_INTERIOR_ENTRANCES, GROTTO_ENTRANCES):
        for e in table:
            specs.append((f"{e.name} (fwd)", e.fwd_index, e.fwd_child, e.ship_type))
            specs.append((f"{e.name} (rev)", e.rev_index, e.rev_child, e.ship_type))
    return specs


_ONE_WAY_TARGET_SPECS: list[tuple[str, int, Regions, int]] = _all_one_way_target_specs()


class _OneWaySource:
    """A one-way source bound to its AP ``Entrance``, with its original landing."""
    __slots__ = ("name", "ship_type", "index", "delivers", "entrance",
                 "original_region")

    def __init__(self, d: OneWayDef, entrance: "Entrance"):
        self.name = d.name
        self.ship_type = d.ship_type
        self.index = d.index
        self.delivers = d.delivers
        self.entrance = entrance
        self.original_region: "Region" = entrance.connected_region


class _OneWayTarget:
    """A candidate landing: a region, the ENTR index that owns it, and the entrance
    type of the directed edge it was built from (for per-source type filtering)."""
    __slots__ = ("name", "index", "region", "pool_type", "forbidden")

    def __init__(self, name: str, index: int, region: "Region",
                 pool_type: int, forbidden: "Ages | None"):
        self.name = name
        self.index = index
        self.region = region
        self.pool_type = pool_type
        self.forbidden = forbidden


def _build_one_way_sources(world: "SohWorld",
                           entries: list[OneWayDef]) -> list[_OneWaySource] | None:
    sources: list[_OneWaySource] = []
    for d in entries:
        name = _entrance_name(d.parent, d.dest)
        try:
            entrance = world.get_entrance(name)
        except KeyError:
            logger.warning("ER: one-way source '%s' ('%s') not found; aborting "
                           "one-way shuffle.", d.name, name)
            return None
        sources.append(_OneWaySource(d, entrance))
    return sources


def _build_one_way_targets(world: "SohWorld") -> list[_OneWayTarget]:
    targets: list[_OneWayTarget] = []
    for name, index, region_name, pool_type in _ONE_WAY_TARGET_SPECS:
        try:
            region = world.get_region(region_name)
        except KeyError:
            # Landing region not present in this world's graph; skip it rather than
            # crash, so a graph trim can't break the whole one-way shuffle.
            logger.warning("ER: one-way target region '%s' (index 0x%X) not found; "
                           "skipping.", region_name, index)
            continue
        forbidden = _FORBIDDEN_BY_REGION.get(region_name)
        targets.append(_OneWayTarget(name, index, region, pool_type, forbidden))
    return targets


def _one_way_compatible(src: "_OneWaySource", tgt: "_OneWayTarget") -> bool:
    """Whether one-way source ``src`` may be sent to landing ``tgt``: the target's
    entrance type must be valid for the source, the target must not be on the
    source's exclusion list, and the source must never deliver the player there as
    the target's forbidden age."""
    if tgt.pool_type not in _ONE_WAY_TARGET_TYPES_BY_SOURCE[src.ship_type]:
        return False
    if (src.ship_type == ENTRANCE_TYPE_OWL_DROP
            and tgt.index in _OWL_EXCLUDED_TARGET_INDICES):
        return False
    return tgt.forbidden is None or tgt.forbidden not in src.delivers


@dataclass(frozen=True)
class _OneWayRequirement:
    """A landing region that must receive a one-way edge delivering the given ages,
    or it (and everything downstream) would be unreachable after the shuffle."""
    region: Regions
    ages: frozenset


def _one_way_requirements(world: "SohWorld",
                          sources: list[_OneWaySource]) -> list[_OneWayRequirement]:
    """Detect the load-bearing one-way landings for this seed.

    Ship shuffles every entrance in one integrated assumed-fill, so a coupled pool
    never silently leans on a vanilla one-way edge. This port shuffles pools
    *sequentially* -- the coupled pools are validated with the one-way edges still at
    vanilla, then the one-way pool runs last -- so a shuffled overworld/dungeon
    layout can come to rely on a vanilla warp. (Desert Colossus, DMC and the
    Graveyard warp pad have no non-warp access at all in this apworld's glitchless
    logic; a shuffled overworld can route still more regions behind a warp.)

    Rather than port Ship's static Bolero/Nocturne/Requiem priority table, we detect
    the dependency directly and per seed: a landing that is reachable now (one-ways at
    vanilla) but becomes unreachable, as an age it currently supports, once the
    shuffled access-adding sources are detached, must be re-covered by the shuffle.
    This subsumes Ship's three static priorities and also catches whatever extra
    regions the coupled layout happened to route behind a warp. See DIVERGENCE #5.

    The detection is a *cascade-aware fixpoint*, not a one-shot detach-all-and-list:
    detaching every mover at once strands the whole warp-network cluster, so listing
    each stranded region independently over-counts wildly (e.g. flags all 8 landings
    as both-age requirements when only 6 both-age sources -- the warp songs -- exist,
    making placement impossible). But covering one upstream landing restores the others
    downstream of it (DMC, once a warp lands there, re-opens everything reachable from
    DMC), so most stranded regions are not *independently* required. We therefore repeat
    a max-cover step: among the regions still missing an age, simulate covering each
    (a virtual root/spawn edge supplying exactly the lost ages) and keep the one that
    restores the most others; commit it and recompute, until nothing is left missing.
    The committed set is the minimal-ish set of landings that genuinely need a direct
    source, and is bounded well under the source count.

    Spawns are excluded from the analysis: they are the *start* edges (root reaches
    the world through them), so detaching them would make everything unreachable, and
    they only relocate the start -- whose validity is enforced by the age/time
    invariants, not by landing coverage. Spawns are still eligible to *satisfy* a
    requirement during placement."""
    player = world.player
    movers = [s for s in sources if s.ship_type != ENTRANCE_TYPE_SPAWN]
    dests = {Regions(s.original_region.name) for s in movers}
    if not dests:
        return []

    both = _BOTH_AGES
    # A region that supplies exactly the given lost ages, to simulate coverage so the
    # cascade through the overworld is captured (root supplies both ages; the single-age
    # spawns supply one). Probing with only the lost ages avoids over-restoring.
    cover_source = {
        both: world.get_region(Regions.ROOT),
        _CHILD_ONLY: world.get_region(Regions.CHILD_SPAWN),
        _ADULT_ONLY: world.get_region(Regions.ADULT_SPAWN),
    }

    def reach_all() -> "dict[Regions, frozenset]":
        st = _er_pre_fill_state(world)
        return {reg: frozenset(a for a in (Ages.CHILD, Ages.ADULT)
                               if st._soh_can_reach_as_age(reg, a, player))
                for reg in dests}

    def add_cover(reg: Regions, ages: frozenset) -> "Entrance":
        src = cover_source[ages]
        region = world.get_region(reg)
        return world.create_entrance(
            src, region, True_(),
            name=f"{_PROBE_PREFIX}cover {src.name} -> {region.name}")

    before = reach_all()
    for s in movers:                        # detach (self-loop adds no access)
        _reconnect(s.entrance, s.entrance.parent_region)

    # Smallest cover-age-sets first: delivering a single age can be enough even when
    # both were lost, because the cascade restores the rest (e.g. dropping CHILD onto a
    # landing that gates the child route to the Temple of Time re-enables time travel, so
    # ADULT comes back globally). A requirement should therefore demand only the age(s)
    # that must be delivered DIRECTLY -- a single age a real owl/spawn can supply -- not
    # the raw lost set, which would force a both-age warp where none is needed (or exists).
    cover_choices = (_CHILD_ONLY, _ADULT_ONLY, both)

    # A cover is only useful if some actual source can deliver it: owls/single spawns
    # supply one age, warp songs both. Requiring (or scoring) an age-set no source can
    # deliver -- e.g. a both-age cover with no warp enabled -- makes the matcher hard-fail
    # on a landing that a *deliverable* cover elsewhere would have fixed via cascade (a
    # landing reachable as both ages only because a single load-bearing owl also gated the
    # child->Temple-of-Time time-travel chain: cover the gateway as CHILD and ADULT returns
    # everywhere, including that landing, by the normal age route).
    deliver_caps = [s.delivers for s in sources]

    def deliverable(ages: frozenset) -> bool:
        return any(ages <= cap for cap in deliver_caps)

    def minimal_cover(reg: Regions):
        """Smallest DELIVERABLE cover that fully restores ``reg`` (cascade included), with
        the reachability it yields, or ``(None, None)`` if no deliverable cover restores it
        (it must instead be fixed by covering another region whose cascade reaches it)."""
        for ages in cover_choices:
            if not deliverable(ages):
                continue
            temp = add_cover(reg, ages)
            trial = reach_all()
            _remove_probe_edge(temp)
            if not (before[reg] - trial[reg]):
                return ages, trial
        return None, None

    reqs: list[_OneWayRequirement] = []
    committed: list["Entrance"] = []
    try:
        while True:
            now = reach_all()
            missing = {reg: lost for reg in dests
                       if (lost := before[reg] - now[reg])}
            if not missing:
                break
            # Max-cover: for each still-missing region compute its minimal deliverable
            # cover, then keep the one that (re)satisfies the most missing regions,
            # breaking ties toward the smaller cover. Stable order for determinism. A
            # region with no deliverable cover is skipped here -- covering another region
            # (committed below) may restore it by cascade on a later pass.
            best = None  # (satisfied, -cover_size, name, reg, ages)
            for cand in sorted(missing, key=lambda r: r.name):
                ages, trial = minimal_cover(cand)
                if ages is None:
                    continue
                satisfied = sum(1 for reg in missing if not (before[reg] - trial[reg]))
                key = (satisfied, -len(ages), cand.name)
                if best is None or key > best[0]:
                    best = (key, cand, ages)
            if best is None:
                # Regions still missing but none has a deliverable cover and no cascade
                # reaches them: this coupled (overworld/dungeon) layout can't be made
                # consistent with the available one-way sources. Re-roll the whole shuffle.
                raise _OneWayInfeasible(
                    f"one-way landings {[r.name for r in missing]} have no deliverable "
                    f"cover for player {world.player}")
            _, best_reg, best_ages = best
            reqs.append(_OneWayRequirement(best_reg, best_ages))
            committed.append(add_cover(best_reg, best_ages))
    finally:
        for temp in committed:
            _remove_probe_edge(temp)
        for s in movers:                    # restore to vanilla
            _reconnect(s.entrance, s.original_region)
    return reqs


def _place_priorities(world: "SohWorld", sources: list[_OneWaySource],
                      targets: list[_OneWayTarget],
                      requirements: list[_OneWayRequirement],
                      ) -> "dict[_OneWaySource, _OneWayTarget] | None":
    """Force a source that delivers the required ages into each load-bearing landing
    (our analogue of Ship's ``PlaceOneWayPriorityEntrance``). Returns the forced
    source->target map, or ``None`` if a requirement can't be satisfied with the
    available sources (the caller re-rolls)."""
    forced: dict[_OneWaySource, _OneWayTarget] = {}
    used_indices: set[int] = set()
    # Prefer warp songs to satisfy a requirement, then owl drops, then spawns last:
    # a warp gives safe both-age access, an owl is pure access (a flight), but a spawn
    # *relocates the start* to that region -- forcing e.g. the child spawn onto DMC
    # Central would make the player start there and fail the start invariants, which
    # would then reject every other placement. Hardest (both-age) requirements first.
    _src_pref = {ENTRANCE_TYPE_WARP_SONG: 0, ENTRANCE_TYPE_OWL_DROP: 1,
                 ENTRANCE_TYPE_SPAWN: 2}
    for req in sorted(requirements, key=lambda r: -len(r.ages)):
        cand_sources = [s for s in sources
                        if s not in forced and req.ages <= s.delivers]
        world.random.shuffle(cand_sources)
        cand_sources.sort(key=lambda s: _src_pref[s.ship_type])
        placed = False
        for src in cand_sources:
            cand_targets = [t for t in targets
                            if t.index not in used_indices
                            and t.region.name == req.region.value
                            and _one_way_compatible(src, t)]
            if cand_targets:
                tgt = world.random.choice(cand_targets)
                forced[src] = tgt
                used_indices.add(tgt.index)
                placed = True
                break
        if not placed:
            return None
    return forced


def _shuffle_one_way(world: "SohWorld",
                     entries: list[OneWayDef]) -> list[dict[str, int]]:
    """Shuffle the given one-way sources onto unique landings; return overrides.

    All enabled one-way pools are shuffled together (one landing is consumed at most
    once across them, mirroring Ship's cross-pool target consumption). Each attempt
    forces the load-bearing landings first (see ``_place_priorities``), then places
    the remaining sources greedily with a per-placement reachability check -- like
    Ship's assumed-reachability fill, this prunes a bad branch (e.g. a spawn dropped
    somewhere the start invariants fail) the moment it is taken, instead of rolling a
    whole matching and discovering the failure only at the end. A final full
    validation (global age/time invariants on) guards the assembled result."""
    sources = _build_one_way_sources(world, entries)
    if not sources:
        return []
    targets = _build_one_way_targets(world)
    requirements = _one_way_requirements(world, sources)

    def restore() -> None:
        for src in sources:
            _reconnect(src.entrance, src.original_region)

    for _ in range(MAX_SHUFFLE_ATTEMPTS):
        forced = _place_priorities(world, sources, targets, requirements)
        if forced is None:
            restore()
            raise _OneWayInfeasible(
                f"SoH ER: cannot satisfy a required one-way landing for player "
                f"{world.player} (no eligible source).")

        placement = dict(forced)
        used_indices = {t.index for t in forced.values()}
        for src, tgt in forced.items():
            _reconnect(src.entrance, tgt.region)

        # Greedily place the rest: for each source, take the first random candidate
        # landing that keeps the world valid (other unplaced sources sit at vanilla,
        # so the graph stays complete and the check is real at every step).
        rest = [s for s in sources if s not in forced]
        world.random.shuffle(rest)
        stuck = False
        for src in rest:
            cands = [t for t in targets if t.index not in used_indices
                     and _one_way_compatible(src, t)]
            world.random.shuffle(cands)
            chosen = None
            for tgt in cands:
                _reconnect(src.entrance, tgt.region)
                if _seed_is_valid(world, check_other_access=True):
                    chosen = tgt
                    break
            if chosen is None:
                _reconnect(src.entrance, src.original_region)
                stuck = True
                break
            placement[src] = chosen
            used_indices.add(chosen.index)

        if not stuck and _seed_is_valid(world, check_other_access=True):
            logger.debug("ER: shuffled %d one-way entrances for player %d",
                         len(sources), world.player)
            return [{
                "type": src.ship_type,
                "index": src.index,
                "destination": _ONE_WAY_NO_DEST,
                "override": tgt.index,
                "overrideDestination": _ONE_WAY_NO_DEST,
            } for src, tgt in placement.items()]
        restore()

    raise RuntimeError(
        f"SoH ER: could not find a valid one-way entrance shuffle for player "
        f"{world.player} after {MAX_SHUFFLE_ATTEMPTS} attempts.")


# Global re-roll budget for the item-fillability gate (see shuffle_entrances). A whole
# re-shuffle is cheap relative to a failed Generate, and fillable layouts dominate, so a
# small budget suffices; exceeding it raises rather than emitting an unfillable layout.
MAX_FILL_REROLLS = 12

# A single trial fill is RNG-flaky: pre_fill and the assumed fill both draw randomly, so a
# layout that is only *occasionally* fillable can pass one trial by luck and then fail the
# real (single-draw) fill -- the exact greedy-fill gap that let unfillable layouts ship.
# Requiring N independent trial passes (short-circuited on the first failure) makes the gate
# accept only ROBUSTLY-fillable layouts: a layout fillable with probability p passes only
# p**N of the time, so fragile layouts are re-rolled away while a solidly-fillable one (p~1)
# still passes cheaply. Higher N -> lower residual fail rate, at ~N trial fills per shipped
# layout. (Re-rolled candidates usually fail the FIRST trial, so they stay cheap.)
TRIAL_FILL_CONFIRMATIONS = 2


def _snapshot_graph(world: "SohWorld") -> list[tuple["Entrance", "Region | None"]]:
    """Record every entrance's vanilla connection so the whole shuffle can be undone.

    Taken before any pool runs (so every entrance is still in its parent's ``exits``);
    pools repoint ``connected_region``, move entrances between ``entrances`` lists and
    ``_disconnect`` boss reverses out of ``exits`` entirely -- :func:`_restore_graph`
    reverses all three."""
    return [(ent, ent.connected_region)
            for region in world.multiworld.get_regions(world.player)
            for ent in region.exits]


def _restore_graph(world: "SohWorld",
                   snapshot: list[tuple["Entrance", "Region | None"]]) -> None:
    """Reset the entrance graph to the vanilla connections captured by
    :func:`_snapshot_graph`, so a fresh re-shuffle starts from a clean slate."""
    for ent, conn in snapshot:
        cur = ent.connected_region
        if cur is not None and ent in cur.entrances:
            cur.entrances.remove(ent)
        ent.connected_region = conn
        if conn is not None and ent not in conn.entrances:
            conn.entrances.append(ent)
        if ent not in ent.parent_region.exits:   # boss reverse was _disconnect'd
            ent.parent_region.exits.append(ent)


def _player_fulfills_accessibility(world: "SohWorld") -> bool:
    """Per-player port of ``MultiWorld.fulfills_accessibility`` (BaseClasses.py:655).

    The multiworld version sweeps EVERY player's locations and requires the whole
    multiworld beatable. That is wrong for the ER trial: it runs during this
    player's ``connect_entrances``, before any other player has been filled, and
    only this player is trial-filled (``single_player_placement=True``). Other
    players are therefore structurally unbeatable, so the whole-multiworld check
    can never pass and every re-roll is spuriously rejected -- a deterministic
    generation failure for any 2+ SoH-player multiworld on a fill-gated pool.

    This scopes the identical sphere-sweep / accessibility logic to ``world.player``
    only, matching the trial's single-player fill and this function's documented
    single-player intent."""
    mw = world.multiworld
    player = world.player
    state = CollectionState(mw)
    acc = world.options.accessibility.current_key
    full = acc == "full"
    minimal = acc == "minimal"

    # A location must be reachable when the accessibility setting requires it:
    # `full` -> all of the player's locations; `items` -> those holding an item;
    # `minimal` -> none (only the goal, checked via has_beaten_game).
    def location_relevant(loc: "Location") -> bool:
        return full or loc.advancement

    def location_condition(loc: "Location") -> bool:
        return full or (loc.item is not None and not minimal)

    locations = [loc for loc in mw.get_locations(player) if location_relevant(loc)]
    while locations:
        sphere: list["Location"] = []
        for n in range(len(locations) - 1, -1, -1):
            if locations[n].can_reach(state):
                sphere.append(locations.pop(n))
        if not sphere:
            return False
        for loc in sphere:
            if loc.item:
                state.collect(loc.item, True, loc)
        if mw.has_beaten_game(state, player) and not any(location_condition(l) for l in locations):
            return True
    return False


def _trial_fill_accessible(world: "SohWorld") -> bool:
    """Whether this player's items can actually be filled into the shuffled graph: a
    throwaway run of the real pre_fill + an assumed fill of the rest, then fully undone.

    The all-items checks in :func:`_seed_is_valid` are optimistic -- they grant every
    item at once, so they cannot see a *progressive* fill deadlock: a layout reachable
    only when you already hold everything, e.g. a pre-filled item (a dungeon reward, a
    song, a small key) whose RESTRICTED home location is stranded, or a shuffled spawn
    that strands the starting age. Such layouts pass every cheap check yet make real fill
    raise (``Could not access required locations`` / ``No more spots to place items``).
    Ship avoids this by integrating entrance and item assumed-fill; our pools run before
    fill, so we predict it by actually filling once and re-rolling the whole shuffle on
    failure.

    Runs ``world.pre_fill`` (placing rewards/songs/keys/shop items with their real
    restrictions -- the cheaper variants of this check, which skip them or place them
    anywhere, both give wrong answers) then assumed-fills the remaining progression. It
    runs during ``connect_entrances``, BEFORE the pipeline's own ``pre_fill`` step, so
    this is pre_fill's first call; everything it mutates is snapshotted and restored, so
    the pipeline's later real pre_fill is unaffected (verified: trial-then-real is clean).
    Single-player because ER runs per player before the others have connected."""
    mw = world.multiworld
    player = world.player
    # Snapshot all fill-relevant state, then restore it in `finally`. We capture
    # `locked` as well as `item`: `world.pre_fill()` locks the locations it fills
    # (fill_restrictive(lock=True)), and if we only restored `item` those locations
    # would stay `locked` -- excluded from the next trial's candidate locations and,
    # worse, left locked-but-empty for the pipeline's real pre_fill/fill, which then
    # overflows. Locked state must be rewound exactly like item placement.
    saved_items = {loc: (loc.item, loc.locked) for loc in mw.get_locations(player)}
    saved_item_pool = list(world.item_pool)
    # `world.pre_fill()` -> fill_shop_items -> run_prefill can strand shop items it
    # cannot place (an unreachable shop slot under this layout) and dump them back via
    # add_items_to_item_pool_list, which appends to BOTH world.item_pool AND
    # mw.itempool. Restoring only world.item_pool would leave those stray shop items
    # (event items, code None) in the real fill's mw.itempool -> overflow and a shop
    # item placed at a non-shop location (write_multidata asserts code/address agree).
    saved_mw_itempool = list(mw.itempool)
    saved_pre_fill_pool = list(world.pre_fill_pool)
    saved_preplaced = list(world.preplaced_items)
    saved_reserved = list(world.reserved_pre_fill_locations)
    saved_completion = mw.completion_condition.get(player)
    try:
        world.pre_fill()
        locations = [loc for loc in mw.get_unfilled_locations(player) if not loc.locked]
        items = [it for it in world.item_pool if it.advancement]
        world.random.shuffle(locations)
        world.random.shuffle(items)
        fill_restrictive(mw, CollectionState(mw), locations, items,
                         single_player_placement=True, swap=True, allow_partial=True,
                         name="SOH_ER_trial")
        if items:
            return False  # overflow: some progression could not be placed
        # Accept iff the real fill's own gate would: this player beatable AND every
        # location this player's accessibility option requires is reachable. Scoped to
        # the current player (see _player_fulfills_accessibility): the multiworld-wide
        # MultiWorld.fulfills_accessibility would demand other, not-yet-filled players
        # be beatable too and so reject every layout in a 2+ SoH-player multiworld.
        # Faithful to each accessibility setting -- under `minimal` only the goal must
        # be reachable, so demanding every advancement location would spuriously reject
        # perfectly fillable minimal layouts.
        return _player_fulfills_accessibility(world)
    except Exception:
        return False
    finally:
        for loc, (item, locked) in saved_items.items():
            if loc.item is not item:
                if loc.item is not None:
                    loc.item.location = None
                loc.item = item
                if item is not None:
                    item.location = loc
            loc.locked = locked
        world.item_pool[:] = saved_item_pool
        mw.itempool[:] = saved_mw_itempool
        world.pre_fill_pool[:] = saved_pre_fill_pool
        world.preplaced_items[:] = saved_preplaced
        world.reserved_pre_fill_locations[:] = saved_reserved
        mw.completion_condition[player] = saved_completion


# --- Universal Tracker: replay a stored layout onto the graph ----------------
#
# When Universal Tracker re-generates a seed to rebuild the logic graph
# (``world.using_ut``), the entrance layout is already decided and recorded in slot
# data (``world.passthrough["entrances"]``, the very list ``fill_slot_data`` emits).
# Re-running the shuffle would be slow (re-rolls + trial fills) AND wrong -- a fresh
# RNG draw picks a different layout than the seed. Instead we replay each stored
# override as the same graph edit the live shuffle made, read back from slot data.
# The element's ship_type tells us how the live shuffle treated that edge's reverse:
#   * one-way (owl/spawn/warp) -> repoint the single source edge to the landing
#   * boss (child/adult)       -> reconnect the forward, disconnect the real reverse
#   * blue warp                -> repoint the boss room's static logic edge
#   * everything else (coupled + thieves forward) -> reconnect index -> override's child

_UT_BOSS_TYPES = frozenset((ENTRANCE_TYPE_CHILD_BOSS, ENTRANCE_TYPE_ADULT_BOSS,
                            ENTRANCE_TYPE_GANON_TOWER))
_UT_ONE_WAY_TYPES = frozenset((
    ENTRANCE_TYPE_OWL_DROP, ENTRANCE_TYPE_SPAWN, ENTRANCE_TYPE_WARP_SONG))

# Every two-way (coupled) EntranceDef the UT loader / label map iterate over. Shared
# so a new entrance is added in exactly one place. (Boss/Ganon-Tower reverses are
# forward-only dead-ends handled per their ship_type by the consumers; every def --
# including thieves -- names its reverse so both directions resolve.)
_COUPLED_ENTRANCES: list[EntranceDef] = [
    *DUNGEON_ENTRANCES, GANON_ENTRANCE, GANON_TOWER_ENTRANCE, *BOSS_ENTRANCES,
    *INTERIOR_ENTRANCES, *SPECIAL_INTERIOR_ENTRANCES, *GROTTO_ENTRANCES,
    *OVERWORLD_ENTRANCES, *THIEVES_HIDEOUT_ENTRANCES,
]


def _build_ut_direction_map() -> "dict[int, tuple[Regions, Regions, bool]]":
    """ENTR index -> ``(parent, child, is_reverse)`` for every coupled/boss/thieves
    edge direction that maps to a real AP entrance.

    Forward indices always resolve; a reverse index resolves only when its def names
    a reverse AP edge. Every coupled/boss/thieves def now names its reverse, so all
    resolve: coupled + thieves reverses get reconnected to the override target
    (REVERSE_COUPLE). In a coupled/mixed pool a boss reverse is a dead end and gets
    disconnected; under decoupled the reverse pool is shuffled independently, so its
    overrides are reconnected like any other reverse -- ``_load_entrances_from_slot_data``
    branches on the decoupled option to match whichever the live shuffle did."""
    out: "dict[int, tuple[Regions, Regions, bool]]" = {}
    for d in _COUPLED_ENTRANCES:
        out[d.fwd_index] = (d.fwd_parent, d.fwd_child, False)
        if d.rev_parent is not None and d.rev_child is not None:
            out[d.rev_index] = (d.rev_parent, d.rev_child, True)
    return out


_UT_DIRECTION_MAP = _build_ut_direction_map()

# One-way SOURCE ENTR index -> its vanilla ``(parent, dest)`` (to locate the AP edge).
_UT_ONE_WAY_SOURCE_MAP: "dict[int, tuple[Regions, Regions]]" = {
    d.index: (d.parent, d.dest)
    for d in (*SPAWN_ENTRANCES, *WARP_SONG_ENTRANCES, *OWL_DROP_ENTRANCES)
}
# One-way TARGET ENTR index -> its vanilla landing region (Ship lands you at the
# target index's original connected region, so this stays correct even when the
# target's own pool is shuffled -- mirrors ``_ONE_WAY_TARGET_SPECS``).
_UT_ONE_WAY_LANDING_MAP: "dict[int, Regions]" = {
    index: region for _name, index, region, _pool in _ONE_WAY_TARGET_SPECS
}
# Blue-warp reverse lookups: which boss room a blue-warp ENTR ejects from, and where
# a given override blue-warp ENTR lands (for the logic-graph edge). Ganon's blue warp
# (0x23F) has no boss room, so it never appears in the first map (identity, skipped).
_UT_BOSS_ROOM_BY_BLUE_WARP: "dict[int, Regions]" = {
    index: room for room, index in _BLUE_WARP_BY_BOSS_ROOM.items()
}
_UT_BLUE_WARP_DEST_BY_OVERRIDE: "dict[int, Regions]" = {
    index: dest for dest, index in _DUNGEON_SLOT_BLUE_WARP.values()
}
# Under a full mix a boss room can sit behind a non-dungeon doorway, so a blue warp's
# override may be that doorway's own reverse ENTR (the "arbitrary doorway" branch of
# ``_resolve_blue_warp_eject``) rather than a dungeon-slot warp. Map every doorway's
# reverse index to where it lands so UT replays those the same way.
for _d in _all_doorway_defs():
    if _d.rev_child is not None and _d.rev_index != _ONE_WAY_NO_DEST:
        _UT_BLUE_WARP_DEST_BY_OVERRIDE.setdefault(_d.rev_index, _d.rev_child)


def _build_entrance_label_map() -> "dict[str, str]":
    """Vanilla entrance name -> a human label describing that specific doorway.

    Used only to disambiguate the rare case where two distinct relocated edges resolve to
    the same ``"{source} -> {dest}"`` name (a destination region reached by more than one
    doorway from the same source -- e.g. a Thieves' Hideout cell with two doors, or an
    overworld region that also has a static internal edge to the same place). The label is
    the shuffle table's own name for the edge (``EntranceDef``/``OneWayDef`` ``name``), keyed
    by the edge's vanilla ``"{parent} -> {child}"`` (which is still the entrance's name when
    the rename pass runs). First writer wins (forward before reverse), so it is deterministic."""
    labels: "dict[str, str]" = {}
    for d in _COUPLED_ENTRANCES:
        labels.setdefault(_entrance_name(d.fwd_parent, d.fwd_child), d.name)
        if d.rev_parent is not None and d.rev_child is not None:
            labels.setdefault(_entrance_name(d.rev_parent, d.rev_child), d.name)
    for d in (*SPAWN_ENTRANCES, *WARP_SONG_ENTRANCES, *OWL_DROP_ENTRANCES):
        labels.setdefault(_entrance_name(d.parent, d.dest), d.name)
    return labels


_ENTRANCE_LABELS = _build_entrance_label_map()


def _ut_load_blue_warp(world: "SohWorld", index: int, override: int) -> None:
    """Replay one blue-warp *logic* edge from a stored override (the game side is moot
    under UT). Mirror of :func:`_rewire_blue_warp_logic`: repoint the boss room's static
    ``BOSS_ROOM -> overworld`` edge to where the override's slot lands. Ganon's blue
    warp has no boss room (identity) and is skipped."""
    boss_room = _UT_BOSS_ROOM_BY_BLUE_WARP.get(index)
    if boss_room is None:
        return
    vanilla_dest = _BLUE_WARP_DEST_BY_BOSS_ROOM.get(boss_room)
    slot_dest = _UT_BLUE_WARP_DEST_BY_OVERRIDE.get(override)
    if vanilla_dest is None or slot_dest is None:
        return
    try:
        blue_warp = world.get_entrance(_entrance_name(boss_room, vanilla_dest))
    except KeyError:
        return
    _reconnect(blue_warp, world.get_region(str(slot_dest)))


def _load_entrances_from_slot_data(world: "SohWorld") -> None:
    """Rebuild the entrance graph from the layout recorded in slot data, for UT.

    Replays each stored override element as the same graph edit the live shuffle made,
    keyed off the element's ship_type (see the module note above this function). Fast
    and deterministic -- no re-roll, no trial fill -- so the tracker's graph matches the
    seed exactly without paying the shuffle cost. Indices with no AP entrance to move
    (absent boss reverses, decoupled reverses that were never emitted, unrecognised
    entries from a newer seed) are skipped, leaving those edges vanilla, just as the
    live shuffle leaves them."""
    elements = (getattr(world, "passthrough", None) or {}).get("entrances") or []
    applied = 0
    for el in elements:
        stype = el.get("type")
        index = el.get("index")
        override = el.get("override")
        if index is None or override is None:
            continue

        if stype == ENTRANCE_TYPE_BLUE_WARP:
            _ut_load_blue_warp(world, index, override)
            continue

        if stype in _UT_ONE_WAY_TYPES:
            src = _UT_ONE_WAY_SOURCE_MAP.get(index)
            landing = _UT_ONE_WAY_LANDING_MAP.get(override)
            if src is None or landing is None:
                continue
            try:
                ent = world.get_entrance(_entrance_name(src[0], src[1]))
            except KeyError:
                continue
            _reconnect(ent, world.get_region(str(landing)))
            applied += 1
            continue

        info = _UT_DIRECTION_MAP.get(index)
        if info is None:
            continue  # absent boss reverse / unrecognised index -> left vanilla
        parent, child, is_reverse = info
        try:
            ent = world.get_entrance(_entrance_name(parent, child))
        except KeyError:
            continue
        if (stype in _UT_BOSS_TYPES and is_reverse
                and not world.options.decouple_entrances.value):
            _disconnect(ent)  # dead-end boss room: reverse disconnected (coupled/mixed)
            applied += 1
            continue
        tgt = _UT_DIRECTION_MAP.get(override)
        if tgt is None:
            continue
        _reconnect(ent, world.get_region(str(tgt[1])))
        applied += 1

    world.entrance_overrides = list(elements)
    _rename_shuffled_entrances(world)
    logger.debug("ER (UT): applied %d of %d stored entrance overrides for player %d",
                 applied, len(elements), world.player)


def _rename_shuffled_entrances(world: "SohWorld") -> None:
    """Rename every relocated entrance to reflect where it now leads.

    Entrance names are baked as ``"{parent} -> {vanilla child}"`` at graph-build time;
    the shuffle only repoints ``connected_region``, so an entrance keeps its vanilla name
    (e.g. ``Nocturne of Shadow Warp -> Graveyard Warp Pad Region`` even after it is
    repointed to Kak Open Grotto). Universal Tracker (and any name-based display) shows
    that stale name. Rewrite each moved edge to ``"{parent} -> {current destination}"``,
    matching AP's own ``Region.connect`` convention.

    Must run only once the layout is FINAL: the shuffle, its re-rolls, and the UT loader
    all look entrances up by their vanilla names, so renaming earlier would break those
    lookups. ``region.exits`` is an ``EntranceRegister`` whose ``entrance_cache`` is keyed
    by name, so we update that cache alongside ``ent.name`` (a later ``.exits`` mutation
    would otherwise ``del`` a stale key).

    Two-phase, because a pool's placement is a permutation: a 2-cycle swap has each edge's
    new name transiently held by the *other* edge that hasn't been renamed yet. So we first
    pull every moving edge out of the cache, then assign. Even after that, two *distinct*
    transitions can share a ``parent -> dest`` name (a destination region reached by more than
    one doorway from the same source -- a Thieves' Hideout cell with two doors, or an overworld
    region with a static internal edge to the same place). Leaving those
    with their stale vanilla name would defeat the point, so we disambiguate with the doorway's
    descriptive label (``_ENTRANCE_LABELS``), falling back to a numeric suffix. Both worlds walk
    the graph in the same order, so the same names come out for a normal gen and its UT re-gen."""
    cache = world.multiworld.regions.entrance_cache[world.player]
    moving: list[tuple["Entrance", str, "str | None"]] = []
    for region in world.multiworld.get_regions(world.player):
        for ent in region.exits:
            conn = ent.connected_region
            if conn is None or ent.parent_region is None:
                continue
            new_name = f"{ent.parent_region.name} -> {conn.name}"
            if new_name != ent.name:
                # ent.name is still the vanilla name here (phase 2 hasn't run) -> label lookup.
                moving.append((ent, new_name, _ENTRANCE_LABELS.get(ent.name)))

    for ent, _new_name, _label in moving:  # phase 1: vacate the old keys
        del cache[ent.name]

    for ent, new_name, label in moving:    # phase 2: claim the new keys
        if new_name not in cache:
            final = new_name
        else:
            # Collision: a distinct doorway already owns "{source} -> {dest}". Tag this one
            # with its descriptive label so both stay unique and readable.
            base = f"{new_name} [{label}]" if label else new_name
            final, n = base, 2
            while final in cache:
                final = f"{base} ({n})"
                n += 1
        ent.name = final
        cache[final] = ent
    if moving:
        logger.debug("ER: renamed %d relocated entrances for player %d",
                     len(moving), world.player)


def shuffle_entrances(world: "SohWorld") -> None:
    """Run every enabled entrance pool, re-rolling until the layout is item-fillable,
    and stash slot-data overrides on the world.

    Call this from ``connect_entrances`` (after the region graph, rules and item pool
    exist, before fill). When all pools are off this is a no-op and
    ``world.entrance_overrides`` stays empty.

    Pools that move the start / age access / pass-throughs (overworld, spawns, warps,
    owls, special interiors, the mixed pool, thieves) can produce a layout that passes
    every per-pool check yet has no valid item placement (see ``_trial_fill_accessible``).
    Those failures can originate in any pool, so a per-pool retry can't fix them; instead
    we snapshot the vanilla graph, run all pools, trial-fill once, and on failure restore
    and re-roll the whole shuffle (a fresh RNG draw). The cheaper dead-end-only pools
    (dungeon/boss/simple-interior/grotto) never hit this, so they skip the gate and run
    exactly once, unchanged.

    Under Universal Tracker (``world.using_ut``) the layout is already fixed and stored
    in slot data, so we replay it directly (:func:`_load_entrances_from_slot_data`)
    instead of re-shuffling: a fresh shuffle would be slow (re-rolls + trial fills) and,
    worse, would draw a *different* layout than the seed. See that function."""
    world.entrance_overrides = []
    # Materialize the boss reverse edges Ship carries but AP's rule builder drops as
    # statically False, so the boss pool (and UT replay) can locate them. Only needed
    # when boss entrances shuffle; harmless (inert False edges) otherwise.
    boss_opt = world.options.shuffle_boss_entrances
    if boss_opt.value != boss_opt.option_off:
        _ensure_reverse_edges(world, BOSS_ENTRANCES)
    if getattr(world, "using_ut", False):
        _load_entrances_from_slot_data(world)
        return
    opts = world.options
    interior_all = (opts.shuffle_interior_entrances.value
                    == opts.shuffle_interior_entrances.option_all)
    # Only the pools that set check_other_access can produce a non-item-fillable layout;
    # gate the (re-roll + trial-fill) on them so plain dead-end shuffles are untouched.
    fill_gate = (bool(opts.shuffle_overworld_entrances.value) or interior_all
                 or bool(opts.shuffle_overworld_spawns.value)
                 or bool(opts.shuffle_warp_songs.value)
                 or bool(opts.shuffle_owl_drops.value)
                 or bool(opts.shuffle_thieves_hideout_entrances.value)
                 or bool(opts.mixed_entrance_pools.value)
                 # Decoupled shuffling relocates reverse (exit) edges, which moves
                 # overworld access and so can affect item-fill accessibility.
                 or bool(opts.decouple_entrances.value))

    # Cache the all-items reachability base for the duration of the shuffle; every
    # per-pool reachability probe / validation copies+sweeps it instead of re-collecting
    # the whole item pool (see _er_pre_fill_state). Cleared in `finally` so the pipeline's
    # own later pre_fill/get_pre_fill_state are unaffected.
    _er_begin_cache(world)
    try:
        snapshot = _snapshot_graph(world) if fill_gate else None
        for attempt in range(MAX_FILL_REROLLS if fill_gate else 1):
            if attempt:
                _restore_graph(world, snapshot)
                logger.debug("ER: layout not item-fillable, re-rolling (attempt %d) for "
                             "player %d", attempt + 1, world.player)
            try:
                overrides = _run_entrance_pools(world)
            except _OneWayInfeasible as exc:
                # The coupled layout left a one-way landing uncoverable; a fresh whole-shuffle
                # re-roll almost always lifts the dependency. (fill_gate is always on when any
                # one-way pool runs, so we always have a snapshot to re-roll from.)
                if not fill_gate:
                    raise
                logger.debug("ER: %s; re-rolling (attempt %d) for player %d",
                             exc, attempt + 1, world.player)
                continue
            if (not fill_gate or not overrides
                    or all(_trial_fill_accessible(world)
                           for _ in range(TRIAL_FILL_CONFIRMATIONS))):
                world.entrance_overrides = overrides
                _rename_shuffled_entrances(world)
                return
        raise RuntimeError(
            f"SoH ER: could not find an item-fillable entrance layout for player "
            f"{world.player} after {MAX_FILL_REROLLS} re-rolls.")
    finally:
        _er_end_cache(world)


def compute_mixed_pools(world: "SohWorld") -> set[str]:
    """Return the set of entrance pools that combine into one mixed pool for the given
    options: a pool joins only if it is shuffled AND its mix flag is on (boss only in
    Full mode), and mixing self-disables below two pools. Shared by _run_entrance_pools
    and by SohWorld.generate_early's slot-data normalization so the two can't drift; the
    Ship applies the equivalent guard in ShuffleAllEntrances (entrance.cpp:1349-1360)."""
    opts = world.options
    if not opts.mixed_entrance_pools.value:
        return set()
    dungeon_on = opts.shuffle_dungeon_entrances.value != opts.shuffle_dungeon_entrances.option_off
    interior_on = (opts.shuffle_interior_entrances.value != opts.shuffle_interior_entrances.option_off
                   and bool(INTERIOR_ENTRANCES))
    overworld_on = bool(opts.shuffle_overworld_entrances.value) and bool(OVERWORLD_ENTRANCES)
    grotto_on = bool(opts.shuffle_grotto_entrances.value) and bool(GROTTO_ENTRANCES)
    thieves_on = (bool(opts.shuffle_thieves_hideout_entrances.value)
                  and bool(THIEVES_HIDEOUT_ENTRANCES))
    boss_full = opts.shuffle_boss_entrances.value == opts.shuffle_boss_entrances.option_full
    mixed: set[str] = set()
    if dungeon_on and opts.mix_dungeon_entrances.value:
        mixed.add("dungeon")
    if overworld_on and opts.mix_overworld_entrances.value:
        mixed.add("overworld")
    if interior_on and opts.mix_interior_entrances.value:
        mixed.add("interior")
    if grotto_on and opts.mix_grotto_entrances.value:
        mixed.add("grotto")
    if thieves_on and opts.mix_thieves_hideout_entrances.value:
        mixed.add("thieves")
    if boss_full and opts.mix_boss_entrances.value:
        mixed.add("boss")
    if len(mixed) < 2:
        mixed.clear()
    return mixed


def _run_entrance_pools(world: "SohWorld") -> list[dict[str, int]]:
    """Run every enabled entrance pool once on the current graph and return the
    accumulated slot-data overrides (see :func:`shuffle_entrances` for the gate/re-roll
    wrapper that calls this)."""
    overrides: list[dict[str, int]] = []
    opts = world.options

    # --- Resolve the coupled pools eligible for mixing (dungeon, overworld, interior,
    # grotto, Thieves' Hideout, and boss in Full mode). Boss rooms are per-edge dead-end
    # targets, so they combine into the coupled mix without disturbing the coupled members.
    dungeon_opt = opts.shuffle_dungeon_entrances.value
    dungeon_on = dungeon_opt != opts.shuffle_dungeon_entrances.option_off
    dungeon_table = list(DUNGEON_ENTRANCES) if dungeon_on else []
    if dungeon_on and dungeon_opt == opts.shuffle_dungeon_entrances.option_on_plus_ganon:
        dungeon_table.append(GANON_ENTRANCE)

    interior_opt = opts.shuffle_interior_entrances.value
    interior_on = (interior_opt != opts.shuffle_interior_entrances.option_off
                   and bool(INTERIOR_ENTRANCES))
    interior_all = interior_opt == opts.shuffle_interior_entrances.option_all
    interior_table = list(INTERIOR_ENTRANCES) if interior_on else []
    if interior_on and interior_all:
        interior_table += SPECIAL_INTERIOR_ENTRANCES

    overworld_on = bool(opts.shuffle_overworld_entrances.value) and bool(OVERWORLD_ENTRANCES)
    grotto_on = bool(opts.shuffle_grotto_entrances.value) and bool(GROTTO_ENTRANCES)
    thieves_on = (bool(opts.shuffle_thieves_hideout_entrances.value)
                  and bool(THIEVES_HIDEOUT_ENTRANCES))

    # Boss: Off / Age Restricted (child + adult pools separately) / Full (one pool).
    # Ganon's Tower joins the boss pool when ShuffleGanonsTower is on. Only Full is
    # mixable (Ship's Boss pool is empty under age-restricted, so MixBoss is a no-op
    # there -- entrance.cpp:1245/1370).
    boss_opt = opts.shuffle_boss_entrances
    boss_on = boss_opt.value != boss_opt.option_off
    boss_full = boss_opt.value == boss_opt.option_full
    tower_shuffled = boss_on and bool(opts.shuffle_ganons_tower.value)
    boss_pool = list(BOSS_ENTRANCES) + ([GANON_TOWER_ENTRANCE] if tower_shuffled else [])

    # Decoupled entrances (Ship's RSK_DECOUPLED_ENTRANCES): forward and reverse of each
    # two-way entrance are shuffled independently. Applies to every shuffled pool below.
    decoupled = bool(opts.decouple_entrances.value)

    # Which pools combine into the mixed pool. Shared with generate_early's slot-data
    # normalization (compute_mixed_pools) so the two can't disagree.
    mixed = compute_mixed_pools(world)

    # Pool order is chosen so the overworld backbone is placed before interior doors
    # (DIVERGENCE-free convergence rule: interior-"all" relocates the Temple of Time
    # door, and pinning it before the overworld layout deadlocks the matcher -- see
    # the overworld notes). Whether a pool is mixed or separate, overworld/the mix is
    # resolved before the separate interior pool; boss/thieves/one-way come last.

    # 1) Dungeon (separate). Dungeons gate other regions -> per-edge needs.
    if dungeon_on and "dungeon" not in mixed:
        if decoupled:
            overrides += _shuffle_decoupled(world, "dungeon", dungeon_table)
        else:
            overrides += _shuffle_pool(world, "dungeon", dungeon_table, REVERSE_COUPLE,
                                       dead_end_targets=False)

    # 2) Overworld (separate) -- the backbone, before interiors/grottos.
    if overworld_on and "overworld" not in mixed:
        if decoupled:
            # Ship pools BOTH overworld directions into the one Overworld pool (no
            # separate OverworldReverse), plus the decoupled-only GV Lower Stream ->
            # Lake Hylia one-way. So shuffle them as a single combined matching, not the
            # two-pass split used for dungeon/interior/grotto (whose reverses are their
            # own <Type>Reverse pools).
            ow_edges = _decoupled_pool_edges(
                list(OVERWORLD_ENTRANCES) + OVERWORLD_ONE_WAY_ENTRANCES)
            overrides += _shuffle_pool(world, "overworld", ow_edges, REVERSE_KEEP,
                                       dead_end_targets=False, check_other_access=True,
                                       decoupled=True)
        else:
            overrides += _shuffle_pool(world, "overworld", OVERWORLD_ENTRANCES,
                                       REVERSE_COUPLE, dead_end_targets=False,
                                       check_other_access=True)

    # 3) Mixed pool: the selected coupled pools shuffled together as one. The combined
    # pool uses per-edge needs and the global age/time invariants (superset of the
    # members' requirements).
    if mixed:
        combined: list[EntranceDef] = []
        if "dungeon" in mixed:
            combined += dungeon_table
        if "overworld" in mixed:
            combined += list(OVERWORLD_ENTRANCES)
            if decoupled:
                # The decoupled-only GV Lower Stream -> Lake Hylia one-way joins the mix
                # with the overworld pool (Ship keeps it in EntranceType::Overworld).
                combined += OVERWORLD_ONE_WAY_ENTRANCES
        if "interior" in mixed:
            combined += interior_table
        if "grotto" in mixed:
            combined += list(GROTTO_ENTRANCES)
        if "thieves" in mixed:
            combined += list(THIEVES_HIDEOUT_ENTRANCES)
        if "boss" in mixed:
            # Boss rooms are dead-end targets (per-edge _Edge.dead_end): in the coupled
            # mix their reverse is disconnected and coupling skips them; in the decoupled
            # mix their reverse joins as an independent (inert) edge.
            combined += boss_pool
        if decoupled:
            # Decoupled: every direction is an independent edge in the ONE mixed pool
            # (Ship folds each member's <Type>Reverse pool into the mix). A single
            # matching over forwards + reverse-as-forwards (one-way members contribute
            # only their forward), forward-only per edge.
            combined_all = _decoupled_pool_edges(combined)
            overrides += _shuffle_pool(world, "mixed", combined_all, REVERSE_KEEP,
                                       dead_end_targets=False, check_other_access=True,
                                       decoupled=True)
        else:
            # Coupled: members are REVERSE_COUPLE, each a mirrored two-way pair.
            overrides += _shuffle_pool(world, "mixed", combined, REVERSE_COUPLE,
                                       dead_end_targets=False, check_other_access=True)

    # 4) Interior (separate). "Simple" = dead-end houses/shops (fast batched needs);
    # "All" mixes in the special/linked interiors (pass-throughs -> per-edge needs +
    # invariants). Decoupled uses per-edge needs both ways (its reverse targets are
    # overworld regions, not dead-ends).
    if interior_on and "interior" not in mixed:
        if decoupled:
            overrides += _shuffle_decoupled(world, "interior", interior_table)
        elif interior_all:
            overrides += _shuffle_pool(world, "interior+special", interior_table,
                                       REVERSE_COUPLE, dead_end_targets=False,
                                       check_other_access=True)
        else:
            overrides += _shuffle_pool(world, "interior", interior_table,
                                       REVERSE_COUPLE, dead_end_targets=True)

    # 5) Grotto (separate).
    if grotto_on and "grotto" not in mixed:
        if decoupled:
            overrides += _shuffle_decoupled(world, "grotto", list(GROTTO_ENTRANCES))
        else:
            overrides += _shuffle_pool(world, "grotto", GROTTO_ENTRANCES,
                                       REVERSE_COUPLE, dead_end_targets=True)

    # 6) Boss (separate -- when not folded into the mix). Runs after dungeons so boss caps
    # reflect the final dungeon placement. Ship's three modes (entrance.cpp:1243): Off,
    # Age Restricted (child bosses among themselves, adult among themselves), Full (one
    # pool). Partitioning the pool is what enforces the age restriction -- the shared
    # caps/needs machinery is unchanged (need(boss) is empty; caps encode reach-the-door
    # age). Boss rooms are per-edge dead-end targets (_Edge.dead_end): coupled, the reverse
    # is disconnected; decoupled, the boss-room reverse pool is shuffled independently
    # (Ship's BossReverse) via _shuffle_decoupled -- the #5 force-created reverse edges make
    # that work (mostly inert False_ edges, so it is an override-table permutation).
    #
    # Ganon's Tower (ShuffleGanonsTower) joins the boss pool when boss shuffle is on (Ship
    # entrance.cpp:1248/1260): FULL takes it directly, AGE RESTRICTED puts it with the ADULT
    # bosses (reaching the tower entryway is adult-only). Its blue warp resolves via the
    # boss-slot loop below.
    if boss_full and "boss" not in mixed:
        if decoupled:
            overrides += _shuffle_decoupled(world, "boss", boss_pool)
        else:
            overrides += _shuffle_pool(world, "boss", boss_pool, REVERSE_COUPLE,
                                       dead_end_targets=False)
    elif boss_opt.value == boss_opt.option_age_restricted:
        child_bosses = [d for d in BOSS_ENTRANCES if d.ship_type == ENTRANCE_TYPE_CHILD_BOSS]
        adult_bosses = [d for d in BOSS_ENTRANCES if d.ship_type == ENTRANCE_TYPE_ADULT_BOSS]
        if tower_shuffled:
            adult_bosses.append(GANON_TOWER_ENTRANCE)
        if decoupled:
            overrides += _shuffle_decoupled(world, "child boss", child_bosses)
            overrides += _shuffle_decoupled(world, "adult boss", adult_bosses)
        else:
            overrides += _shuffle_pool(world, "child boss", child_bosses, REVERSE_COUPLE,
                                       dead_end_targets=False)
            overrides += _shuffle_pool(world, "adult boss", adult_bosses, REVERSE_COUPLE,
                                       dead_end_targets=False)

    # 7) Thieves' Hideout (separate -- when not folded into the mix). A true coupled
    # two-way shuffle (REVERSE_COUPLE): the AP hideout reverse edges mirror Ship's pairs
    # 1:1. Cells gate the carpenters -> Gerudo card -> wasteland/GTG, so they are NOT dead
    # ends. check_other_access=True mirrors Ship. Under decoupled the forward and reverse
    # doors shuffle independently (Ship's ThievesHideoutReverse pool), via the same
    # two-pass _shuffle_decoupled used for dungeon/interior/grotto.
    if thieves_on and "thieves" not in mixed:
        if decoupled:
            overrides += _shuffle_decoupled(world, "thieves hideout",
                                            list(THIEVES_HIDEOUT_ENTRANCES))
        else:
            overrides += _shuffle_pool(world, "thieves hideout", THIEVES_HIDEOUT_ENTRANCES,
                                       REVERSE_COUPLE, dead_end_targets=False,
                                       check_other_access=True)

    # One-way pools (spawns, warp songs, owl drops). Shuffled together as one
    # combined matching so a landing is consumed at most once across them. Run
    # after the coupled pools so it never perturbs their CHILD/ADULT_SPAWN probes.
    one_way: list[OneWayDef] = []
    if opts.shuffle_overworld_spawns.value:
        one_way += SPAWN_ENTRANCES
    if opts.shuffle_warp_songs.value:
        one_way += WARP_SONG_ENTRANCES
    if opts.shuffle_owl_drops.value:
        one_way += OWL_DROP_ENTRANCES
    if one_way:
        overrides += _shuffle_one_way(world, one_way)

    # Blue warps follow the boss/dungeon placement; emit them whenever either pool
    # is shuffled (Ship's includeBluewarps gate). Must run after the boss pool so
    # each boss slot's forward entrance reflects the boss now behind it.
    # Blue warps are derived (never shuffled themselves): whenever dungeons or bosses
    # move, a boss's blue warp ejects to the overworld of the dungeon-entrance slot
    # its dungeon now occupies (Ship's includeBluewarps gate + resolution chain). The
    # game-side overrides and the logic-graph rewiring share that chain so they agree.
    if dungeon_on or opts.shuffle_boss_entrances.value:
        include_ganon = (dungeon_opt
                         == opts.shuffle_dungeon_entrances.option_on_plus_ganon)
        # The tower joins the blue-warp resolution as a boss room when shuffled, so its
        # FLOOR_1 warp gets a correct ejection target (and the identity Ganon warp is
        # suppressed -- see above).
        boss_rooms = _BOSS_ROOMS + ([Regions.GANONS_TOWER_FLOOR_1] if tower_shuffled
                                    else [])
        overrides += _blue_warp_overrides(world, boss_rooms, include_ganon)
        _rewire_blue_warp_logic(world, boss_rooms)

    return overrides
