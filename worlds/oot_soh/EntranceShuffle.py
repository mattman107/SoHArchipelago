"""Entrance Randomizer (Archipelago side).

This owns the *logic and randomization* of entrance shuffle. It shuffles the
shufflable entrances in the AP region graph (guaranteeing the seed stays
beatable) and emits the resulting pairs into slot data in the format Ship's
``EntranceShuffler::ParseJson`` already understands.

See ``ER_AP_00_SHARED_CONTRACT.md`` for the slot-data contract and
``ER_AP_01_ARCHIPELAGO_apworld.md`` for the apworld build plan.

Pools implemented (all coupled / two-way):
  * dungeon entrances (+ optionally Ganon's Castle)
  * boss-room entrances (child + adult bosses, age-aware)
  * interior entrances (the "simple" tier; special interiors are excluded)
  * grotto + grave entrances (dead-end grottos and graves)

Blue warps are intentionally NOT emitted yet: Ship leaves any un-overridden
entrance vanilla, so a shuffled boss/dungeon simply blue-warps to its *original*
overworld spot (cosmetic only; the seed stays beatable). Emitting blue-warp
overrides is a planned fast-follow.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .Enums import Regions, Ages, Events
from rule_builder.rules import True_
from BaseClasses import CollectionState

if TYPE_CHECKING:
    from . import SohWorld
    from BaseClasses import Entrance, Region

import logging
logger = logging.getLogger("SOH_OOT.ER")


# Ship's `EntranceType` enum values (soh `enum class EntranceType`, entrance.h).
# Emitted as the `type` field. Ship's ApplyEntranceOverrides() rewires purely by
# index -> override and ignores `type`, but the entrance tracker/hints read it,
# so we send the true values rather than a placeholder.
ENTRANCE_TYPE_DUNGEON = 5
ENTRANCE_TYPE_GANON_DUNGEON = 6
ENTRANCE_TYPE_CHILD_BOSS = 10
ENTRANCE_TYPE_ADULT_BOSS = 12
ENTRANCE_TYPE_INTERIOR = 15
ENTRANCE_TYPE_GROTTO_GRAVE = 20

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

# How a pool's reverse (inside -> outside) edges are handled in the AP graph:
#   "couple"  - reconnect them so they mirror the forward shuffle (true two-way).
#   "deadend" - disconnect them entirely; the target region is reachable only via
#               the forward edge. Used for boss rooms, whose only logical content
#               is the boss reward (reached via the forward door) and whose
#               vanilla reverse edges would otherwise create phantom paths.
REVERSE_COUPLE = "couple"
REVERSE_DEADEND = "deadend"


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
    are required for ``REVERSE_COUPLE`` pools and optional for ``REVERSE_DEADEND``
    pools (where they merely identify a real reverse edge to disconnect).
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


# Boss-room entrances. Forward edge is "*_BOSS_ENTRYWAY" -> "*_BOSS_ROOM"
# (ENTR_*_BOSS_ENTRANCE). The reverse (ENTR_*_BOSS_DOOR) is index-only here: boss
# rooms are treated as forward-only dead-ends (see REVERSE_DEADEND). We still name
# the reverse AP edge for Deku/Dodongo because theirs is a real ``True_()`` edge
# that must be disconnected to avoid phantom cross-dungeon paths; the adult bosses'
# reverse edges are ``False_()`` and Jabu's is absent, so they need no handling.
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
                0x301, 0x407, ENTRANCE_TYPE_CHILD_BOSS),
    EntranceDef("Phantom Ganon (Forest Temple)",
                Regions.FOREST_TEMPLE_BOSS_ENTRYWAY,
                Regions.FOREST_TEMPLE_BOSS_ROOM,
                0x00C, 0x24E, ENTRANCE_TYPE_ADULT_BOSS),
    EntranceDef("Volvagia (Fire Temple)",
                Regions.FIRE_TEMPLE_BOSS_ENTRYWAY, Regions.FIRE_TEMPLE_BOSS_ROOM,
                0x305, 0x175, ENTRANCE_TYPE_ADULT_BOSS),
    EntranceDef("Morpha (Water Temple)",
                Regions.WATER_TEMPLE_BOSS_ENTRYWAY, Regions.WATER_TEMPLE_BOSS_ROOM,
                0x417, 0x423, ENTRANCE_TYPE_ADULT_BOSS),
    EntranceDef("Twinrova (Spirit Temple)",
                Regions.SPIRIT_TEMPLE_BOSS_ENTRYWAY,
                Regions.SPIRIT_TEMPLE_BOSS_ROOM,
                0x08D, 0x2F5, ENTRANCE_TYPE_ADULT_BOSS),
    EntranceDef("Bongo Bongo (Shadow Temple)",
                Regions.SHADOW_TEMPLE_BOSS_ENTRYWAY,
                Regions.SHADOW_TEMPLE_BOSS_ROOM,
                0x413, 0x2B2, ENTRANCE_TYPE_ADULT_BOSS),
]


# The reverse AP edge defaults to the mirror (interior -> overworld); ``rev_child``
# overrides it for the asymmetric cases (where the exit lands in a different region
# than the entrance came from).
def _i(name: str, parent: Regions, child: Regions, fwd_index: int, rev_index: int,
       rev_child: "Regions | None" = None) -> EntranceDef:
    return EntranceDef(name, parent, child, fwd_index, rev_index,
                       ENTRANCE_TYPE_INTERIOR, child, rev_child or parent)


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
# (SpecialInterior) and not handled yet. The Market back-alley Dog Lady house is
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


class _Edge:
    """One coupled entrance in a shuffle pool, bound to its AP ``Entrance``(s)."""
    __slots__ = ("name", "ship_type", "fwd_index", "rev_index",
                 "fwd_entrance", "rev_entrance",
                 "fwd_original_region", "rev_original_region")

    def __init__(self, d: EntranceDef, fwd_entrance: "Entrance",
                 rev_entrance: "Entrance | None"):
        self.name = d.name
        self.ship_type = d.ship_type
        self.fwd_index = d.fwd_index
        self.rev_index = d.rev_index
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
    state = world.get_pre_fill_state()
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


def _reachable_location_names(world: "SohWorld") -> set[str]:
    state = world.get_pre_fill_state()
    return {loc.name for loc in world.get_locations() if loc.can_reach(state)}


def _probe_interior(world: "SohWorld", fwd: "_Edge",
                    source: Regions) -> set[str]:
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
    temp = world.create_entrance(src_region, interior, True_())
    try:
        return _reachable_location_names(world)
    finally:
        if temp in src_region.exits:
            src_region.exits.remove(temp)
        if temp in interior.entrances:
            interior.entrances.remove(temp)
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
        temps = [world.create_entrance(src_region, interior, True_())
                 for interior in interiors]
        try:
            state = world.get_pre_fill_state()
            return {name for name in owner if loc_by_name[name].can_reach(state)}
        finally:
            for interior, temp in zip(interiors, temps):
                if temp in src_region.exits:
                    src_region.exits.remove(temp)
                if temp in interior.entrances:
                    interior.entrances.remove(temp)

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
    def compatible(doorway: "_Edge", target: "_Edge") -> bool:
        cap = caps[doorway]
        return (needs[target] <= cap
                and (target not in forbidden or forbidden[target] not in cap))

    # Candidate targets per doorway, each list shuffled for a randomized matching.
    adj: dict[_Edge, list[_Edge]] = {}
    for doorway in forwards:
        cands = [t for t in forwards if compatible(doorway, t)]
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
    reachable, never more -- so it can never miss a genuine wrong-age access."""
    player = world.player
    for region, forbidden_age in _FORBIDDEN_AGE_EXITS:
        if state._soh_can_reach_as_age(region, forbidden_age, player):
            return False
    return True


def _item_less_state(world: "SohWorld") -> "CollectionState":
    """An empty state with events swept in (no progression items collected).

    Mirrors the "no items" basis Ship uses for its start-of-seed guarantees: the
    invariants below must hold with nothing in the inventory, so the player is never
    stranded at the very start. Sweeping picks up item-independent events such as the
    CHILD/ADULT_CAN_PASS_TIME flags."""
    state = CollectionState(world.multiworld)
    state.sweep_for_advancements(list(world.multiworld.get_locations(world.player)))
    return state


def _world_age_invariants_hold(world: "SohWorld") -> bool:
    """Global age/time guarantees Ship enforces once spawns, the overworld, or
    special interiors get shuffled (entrance.cpp:873-898).

    Dormant for the current coupled dead-end pools (they never move spawns or the
    overworld, so these always hold); callers opt in via ``check_other_access``. The
    upcoming GER-backed pass-through / overworld / spawn pools are what will turn it
    on. All checks use an item-less state -- the guarantees must hold with no items.

    NOTE (refine with the GER work): the Temple-of-Time-after-time-travel check
    assumes the Door of Time can be opened item-less (true with the default open
    door). With a closed Door of Time -- where the seed is forced to a child start --
    reaching ToT as adult needs Song of Time + stones, which an item-less state lacks.
    Ship's own search handles this via its settings; pin the exact semantics down when
    wiring GER, which owns the validation search."""
    player = world.player
    state = _item_less_state(world)

    # 1) A valid starting overworld (Kokiri or Kakariko) reachable with no items.
    starts = (Regions.KOKIRI_FOREST, Regions.KAKARIKO_VILLAGE)
    if not any(state._soh_can_reach_as_age(r, age, player)
               for r in starts for age in (Ages.CHILD, Ages.ADULT)):
        return False

    # 2) Time must be passable as BOTH ages with no items, or day/night-gated checks
    #    could become permanently inaccessible.
    if not (state.has(str(Events.CHILD_CAN_PASS_TIME), player)
            and state.has(str(Events.ADULT_CAN_PASS_TIME), player)):
        return False

    # 3) After going through time, the Temple of Time must remain reachable as the
    #    *other* age, so the player never loses pedestal access.
    starting_child = world.options.starting_age.value == world.options.starting_age.option_child
    other_age = Ages.ADULT if starting_child else Ages.CHILD
    if not state._soh_can_reach_as_age(Regions.TEMPLE_OF_TIME, other_age, player):
        return False

    return True


def _seed_is_valid(world: "SohWorld", check_other_access: bool = False) -> bool:
    """Validate the shuffled graph against the world's accessibility setting.

    Always enforces the wrong-age exit guard (a soft-lock guard, independent of
    accessibility). ``check_other_access`` additionally enforces the global age/time
    invariants -- left off for the current coupled dead-end pools and turned on by the
    future pools that move spawns / the overworld / special interiors (mirroring
    Ship's ``checkOtherEntranceAccess``)."""
    completion = world.multiworld.completion_condition.get(world.player)
    if completion is None:
        # true_no_logic (or no goal set): logic is bypassed, nothing to verify.
        return True
    state = world.get_pre_fill_state()
    if not completion(state):
        return False
    if not _age_exits_are_safe(world, state):
        return False
    if check_other_access and not _world_age_invariants_hold(world):
        return False
    if world.options.accessibility == "minimal":
        return True
    # full / items accessibility: every location must be reachable.
    return all(loc.can_reach(state) for loc in world.get_locations())


def _build_slot_data(forwards: list[_Edge],
                     targets: list[_Edge]) -> list[dict[str, int]]:
    """Convert a coupled pairing into the contract's ``entrances`` elements.

    Each shuffled direction is its own element (forward and reverse are separate),
    matching what Ship's CreateEntranceOverrides()/ParseJson() exchange. For a
    placement of doorway S onto target T: S's forward adopts T's forward, and T's
    reverse adopts S's reverse."""
    entrances: list[dict[str, int]] = []
    for src, tgt in zip(forwards, targets):
        entrances.append({
            "type": src.ship_type,
            "index": src.fwd_index,
            "destination": src.rev_index,
            "override": tgt.fwd_index,
            "overrideDestination": tgt.rev_index,
        })
        entrances.append({
            "type": tgt.ship_type,
            "index": tgt.rev_index,
            "destination": tgt.fwd_index,
            "override": src.rev_index,
            "overrideDestination": src.fwd_index,
        })
    return entrances


def _shuffle_pool(world: "SohWorld", label: str, entries: list[EntranceDef],
                  reverse_mode: str, dead_end_targets: bool,
                  check_other_access: bool = False) -> list[dict[str, int]]:
    """Shuffle one pool in place on the graph; return its slot-data elements.

    Pools are applied cumulatively (not restored between pools): a later pool's
    age-caps are computed against the graph left by the earlier pools, which is
    what makes e.g. boss reachability reflect the dungeon placement.

    ``dead_end_targets`` selects the fast batched needs computation (valid only when
    each target gates nothing beyond itself -- interiors, grottos, graves); pools
    whose targets gate other regions (dungeons, bosses) must pass ``False``.

    ``check_other_access`` is forwarded to validation; pools that move spawns, the
    overworld, or special interiors should set it so the global age/time invariants
    are enforced (mirrors Ship's ``checkOtherEntranceAccess``)."""
    forwards = _build_pool(world, entries)
    if not forwards:
        return []

    # Boss-style pools: make targets forward-only dead-ends so a vanilla reverse
    # edge can't create a phantom cross-area path once the forward is shuffled.
    if reverse_mode == REVERSE_DEADEND:
        for edge in forwards:
            if edge.rev_entrance is not None:
                _disconnect(edge.rev_entrance)
                edge.rev_entrance = None

    caps = _compute_caps(world, forwards)
    needs = (_compute_needs(world, forwards) if dead_end_targets
             else _compute_needs_per_edge(world, forwards))
    forbidden = {edge: age for edge in forwards
                 if (age := _forbidden_age(edge)) is not None}

    for _ in range(MAX_SHUFFLE_ATTEMPTS):
        targets = _find_matching(world, forwards, caps, needs, forbidden)
        if targets is None:
            _restore_forwards(forwards, reverse_mode)
            raise RuntimeError(
                f"SoH ER: no age-compatible {label} entrance matching exists "
                f"for player {world.player}.")
        _apply(forwards, targets, reverse_mode)
        if _seed_is_valid(world, check_other_access):
            logger.debug("ER: shuffled %d %s entrances for player %d",
                         len(forwards), label, world.player)
            return _build_slot_data(forwards, targets)
        _restore_forwards(forwards, reverse_mode)

    raise RuntimeError(
        f"SoH ER: could not find a valid {label} entrance shuffle for player "
        f"{world.player} after {MAX_SHUFFLE_ATTEMPTS} attempts.")


def shuffle_entrances(world: "SohWorld") -> None:
    """Run every enabled entrance pool and stash slot-data overrides on the world.

    Call this from ``set_rules`` (after the region graph, rules and item pool
    exist, before fill). When all pools are off this is a no-op and
    ``world.entrance_overrides`` stays empty.
    """
    world.entrance_overrides = []
    overrides: list[dict[str, int]] = []
    opts = world.options

    dungeon_opt = opts.shuffle_dungeon_entrances.value
    if dungeon_opt != opts.shuffle_dungeon_entrances.option_off:
        table = list(DUNGEON_ENTRANCES)
        if dungeon_opt == opts.shuffle_dungeon_entrances.option_on_plus_ganon:
            table.append(GANON_ENTRANCE)
        # Dungeons/bosses gate other regions, so needs must be computed per-edge.
        overrides += _shuffle_pool(world, "dungeon", table, REVERSE_COUPLE,
                                   dead_end_targets=False)

    if opts.shuffle_boss_entrances.value:
        overrides += _shuffle_pool(world, "boss", BOSS_ENTRANCES, REVERSE_DEADEND,
                                   dead_end_targets=False)

    # Interiors/grottos/graves are dead ends -> fast batched needs computation.
    if opts.shuffle_interior_entrances.value and INTERIOR_ENTRANCES:
        overrides += _shuffle_pool(world, "interior", INTERIOR_ENTRANCES,
                                   REVERSE_COUPLE, dead_end_targets=True)

    if opts.shuffle_grotto_entrances.value and GROTTO_ENTRANCES:
        overrides += _shuffle_pool(world, "grotto", GROTTO_ENTRANCES,
                                   REVERSE_COUPLE, dead_end_targets=True)

    world.entrance_overrides = overrides
