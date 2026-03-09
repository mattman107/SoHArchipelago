"""
Option-based location filtering (pure — no Archipelago imports).

Used by Regions.py (to decide which AP locations exist), by generate_early
(to filter location_name_to_id) and by LogicRuntime (disabled checks still
self-grant their vanilla items when reachable, like the C++ solver).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .Enums import Locations
from .LocationData import LOCATION_RCTYPE

if TYPE_CHECKING:
    from . import MM2ShipWorld

# Maps C++ RandoCheckType → the MM2ShipOptions attribute that enables it.
# Types absent from this dict are always active (RCTYPE_CHEST, RCTYPE_NPC,
# RCTYPE_SONG, RCTYPE_STRAY_FAIRY, RCTYPE_HEART, RCTYPE_MINIGAME, etc.).
RCTYPE_OPTION: dict[str, str] = {
    "RCTYPE_BARREL":      "shuffle_barrel_drops",
    "RCTYPE_COW":         "shuffle_cows",
    "RCTYPE_CRATE":       "shuffle_crate_drops",
    "RCTYPE_ENEMY_DROP":  "shuffle_enemy_drops",
    "RCTYPE_FREESTANDING":"shuffle_freestanding_items",
    "RCTYPE_FROG":        "shuffle_frogs",
    "RCTYPE_GRASS":       "shuffle_grass_drops",
    "RCTYPE_OWL":         "shuffle_owl_statues",
    "RCTYPE_POT":         "shuffle_pot_drops",
    # "RCTYPE_REMAINS":     "shuffle_boss_remains",
    "RCTYPE_SHOP":        "shuffle_shops",
    "RCTYPE_SKULL_TOKEN": "shuffle_gold_skulltulas",
    "RCTYPE_SNOWBALL":    "shuffle_snowball_drops",
    "RCTYPE_TINGLE_SHOP": "shuffle_tingle_shops",
    "RCTYPE_TREE":        "shuffle_tree_drops",
}


def location_should_be_included(world: "MM2ShipWorld", loc: Locations) -> bool:
    """
    Return True if this location belongs in the item pool given the current world options.

    Filtering is type-based: each location's C++ RandoCheckType (stored in
    LocationData.LOCATION_RCTYPE) is mapped to the option that controls it.
    This avoids fragile name-pattern matching and stays in sync with C++.

    Called from generate_early (to filter location_name_to_id), from
    create_regions_and_locations (to filter Location objects) and from the
    logic solver (disabled checks self-grant their vanilla items). All must
    stay in sync — always go through this function.
    """
    name = loc.name  # UPPER_SNAKE_CASE enum key

    rctype = LOCATION_RCTYPE.get(name)

    # Look up which option controls this RCTYPE (None → always active)
    option_name = RCTYPE_OPTION.get(rctype) if rctype else None
    if option_name is not None:
        option = getattr(world.options, option_name, None)
        if option is not None and not option.value:
            return False

    # Sub-exclusions for grass (only reached when shuffle_grass_drops is ON)
    if rctype == "RCTYPE_GRASS":
        if world.options.exclude_termina_field_grass.value and name.startswith("TERMINA_FIELD_GRASS_"):
            return False
        if world.options.exclude_cow_grotto_grass.value and (
            "TERMINA_FIELD_COW_GROTTO_GRASS_" in name
            or "GREAT_BAY_COAST_COW_GROTTO_GRASS_" in name
        ):
            return False

    return True
