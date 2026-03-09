from __future__ import annotations

from typing import TYPE_CHECKING

from BaseClasses import CollectionState
from Fill import fill_restrictive

from .Enums import Locations
from .LocationData import LOCATION_DUNGEON

if TYPE_CHECKING:
    from . import MM2ShipWorld

# LOCATION_DUNGEON is keyed by the Locations enum's attribute name (e.g.
# "WOODFALL_TEMPLE_BOSS_KEY_CHEST"), but AP Location objects are named after the
# enum's display *value* (e.g. "Woodfall Temple Boss Key Chest") — see
# Regions.create_regions_and_locations(), which builds each MM2ShipLocation with
# loc_name = loc.value. Re-key by display value so lookups by Location.name work.
LOCATION_VALUE_TO_DUNGEON: dict[str, str] = {
    Locations[key].value: dungeon for key, dungeon in LOCATION_DUNGEON.items() if key in Locations.__members__
}

# Each dungeon's Small Key / Boss Key / Stray Fairy item by AP item name —
# generated from Rando::Logic::RandoItemIdToDungeon() (LogicHelpersGen).
from .LogicHelpersGen import DUNGEON_ITEMS as DUNGEON_ITEM_NAMES

# Maps each confined item type to the MM2ShipOptions attribute that controls its placement.
PLACEMENT_OPTION_BY_TYPE: dict[str, str] = {
    "small_key": "placement_small_keys",
    "boss_key": "placement_boss_keys",
    "stray_fairy": "placement_stray_fairies",
}

OWN_DUNGEON = 1  # RO_DUNGEON_ITEM_OWN_DUNGEON


def confine_dungeon_items(world: "MM2ShipWorld") -> None:
    """
    Pre-place dungeon items into their own dungeon's locations when the matching
    placement_* option is set to Own Dungeon, mirroring the confinement performed
    by PlacementConstraints.cpp's RandoItemIdToDungeon/IsItemAllowedAtCheck for the
    standalone (non-AP) randomizer.

    Must run from World.pre_fill(), after create_items() has populated
    multiworld.itempool and before the main fill consumes it.

    Note: Skeleton Key is intentionally excluded — it has no vanilla location and,
    per GiveItem.cpp, is a standalone item that instantly grants keys for every
    dungeon at once, so it is never confined to a single dungeon.
    """
    dungeon_locations: dict[str, list] = {}
    for location in world.multiworld.get_unfilled_locations(world.player):
        dungeon = LOCATION_VALUE_TO_DUNGEON.get(location.name)
        if dungeon:
            dungeon_locations.setdefault(dungeon, []).append(location)

    state = CollectionState(world.multiworld)
    state.sweep_for_advancements()

    for item_type, option_name in PLACEMENT_OPTION_BY_TYPE.items():
        if getattr(world.options, option_name).value != OWN_DUNGEON:
            continue

        for dungeon, item_names in DUNGEON_ITEM_NAMES.items():
            item_name = item_names[item_type]
            confined_items = [
                item for item in world.multiworld.itempool
                if item.player == world.player and item.name == item_name
            ]
            if not confined_items:
                continue

            locations = [loc for loc in dungeon_locations.get(dungeon, []) if loc.item is None]
            if not locations:
                continue

            for item in confined_items:
                world.multiworld.itempool.remove(item)

            world.random.shuffle(locations)

            # allow_partial: if a dungeon doesn't have enough room for its own
            # confined items (e.g. most of its locations were excluded by other
            # options), leftover items fall back to the unrestricted main pool
            # rather than failing generation outright.
            fill_restrictive(
                world.multiworld, state, locations, confined_items,
                single_player_placement=True, lock=True, allow_excluded=True,
                allow_partial=True, name=f"MM2Ship {dungeon} {item_type}",
            )

            if confined_items:
                world.multiworld.itempool.extend(confined_items)
