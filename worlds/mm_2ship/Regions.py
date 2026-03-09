from __future__ import annotations

from typing import TYPE_CHECKING

from BaseClasses import MultiWorld, Region

from .Enums import Regions as RegionsEnum, Locations
from .Locations import MM2ShipLocation, location_data_table
from .LocationData import LOCATION_RCTYPE
from .LocationFilter import location_should_be_included  # noqa: F401 — re-exported
from .RegionData import REGIONS, START_REGION

if TYPE_CHECKING:
    from . import MM2ShipWorld


class MM2ShipRegion(Region):
    game = "2 Ship 2 Harkinian (MM)"

    def __init__(self, name: str, player: int, multiworld: MultiWorld, hint: str | None = None):
        super().__init__(name, player, multiworld, hint)


def _ap_region_name(rr_key: str) -> str:
    """RR_* id -> AP region display name. The start region is AP's Menu."""
    if rr_key == START_REGION:
        return "Menu"
    return RegionsEnum[rr_key[3:]].value


# RC_* -> owning RR_* (first region defining the check, in sorted RR order).
# A check can appear in several regions (e.g. shared enemy drops); reachability
# is still exact because the location rule asks the solver, which ORs over all
# of them. The owner only decides which AP region the location displays under.
_CHECK_OWNER: dict[str, str] = {}
for _rid, _spec in REGIONS.items():
    for _rc, _rule, _src in _spec.checks:
        _CHECK_OWNER.setdefault(_rc, _rid)


def create_regions_and_locations(world: "MM2ShipWorld") -> None:
    player = world.player
    multiworld = world.multiworld

    # One AP region per RandoRegion; the start region (RR_MAX) becomes Menu.
    ap_regions: dict[str, MM2ShipRegion] = {}
    for rr_key in REGIONS:
        region = MM2ShipRegion(_ap_region_name(rr_key), player, multiworld)
        ap_regions[rr_key] = region
        multiworld.regions.append(region)

    menu = ap_regions[START_REGION]

    # Star topology with always-open entrances: reachability is enforced
    # entirely by per-location rules (the solver already accounts for region
    # access), so entrances only provide structure for spoilers/trackers.
    for rr_key, region in ap_regions.items():
        if rr_key != START_REGION:
            menu.connect(region, f"Menu -> {region.name}")

    use_logic = world.use_logic()

    # Create locations, filtering by options. Inactive locations are skipped
    # entirely — no AP item is placed there and they won't appear in the
    # spoiler log. The C++ resync loop applies the same filter so it never
    # sends a location ID the server doesn't know about.
    # NOTE: Map/compass locations are always created even when
    # starting_maps_and_compasses is ON — items are removed from the pool,
    # not the locations.
    from .VanillaItems import vanilla_items

    for loc in Locations:
        if loc == Locations.VICTORY:
            continue
        if not location_should_be_included(world, loc):
            continue

        rc_key = f"RC_{loc.name}"
        owner = _CHECK_OWNER.get(rc_key, START_REGION)
        parent = ap_regions[owner]

        address = location_data_table[loc]
        loc_obj = MM2ShipLocation(player, loc.value, address, parent)
        parent.locations.append(loc_obj)

        if use_logic:
            loc_obj.access_rule = (
                lambda state, rc=rc_key: world.logic.check_reachable(state, rc)
            )

        # Boss warp locations are always created. When not shuffled, pre-fill
        # with the vanilla item so the player receives it from the server on check.
        if LOCATION_RCTYPE.get(loc.name) == "RCTYPE_REMAINS" and not world.options.shuffle_boss_remains.value:
            vanilla_item = vanilla_items.get(loc)
            if vanilla_item is not None:
                loc_obj.place_locked_item(world.create_item(vanilla_item.value))

    # Victory event: beating Majora (or the triforce goal, which the C++
    # completes automatically on collecting the required pieces).
    majora_region = ap_regions.get("RR_MOON_MAJORAS_LAIR", menu)
    victory = MM2ShipLocation(player, Locations.VICTORY.value, None, majora_region)
    majora_region.locations.append(victory)
    victory.place_locked_item(world.create_item("Victory", create_as_event=True))
    if use_logic:
        victory.access_rule = lambda state: world.victory_reachable(state)
