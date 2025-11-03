from typing import TYPE_CHECKING, Callable
from BaseClasses import Location, Region
from .Enums import SOHBossEntranceExitNames, SOHBossEntranceNames, SOHDungeonExitNames, SOHDungeonEntranceNames, Locations
from .Locations import SohLocation
from entrance_rando import disconnect_entrance_for_randomization, randomize_entrances
from entrance_rando import ERPlacementState, Entrance
from .LogicHelpers import rule_wrapper
from worlds.generic.Rules import set_rule

if TYPE_CHECKING:
    from . import SohWorld

# This is only needed for One Way entrances
entrance_matching = {
    SOHBossEntranceNames.DEKU_TREE_BOSS_ENTRANCE: SOHBossEntranceExitNames.DEKU_TREE_BOSS_EXIT,
    SOHBossEntranceNames.DODONGOS_CAVERN_BOSS_ENTRANCE: SOHBossEntranceExitNames.DODONGOS_CAVERN_BOSS_EXIT,
    SOHBossEntranceNames.JABU_JABUS_BOSS_ENTRANCE: SOHBossEntranceExitNames.JABU_JABUS_BOSS_EXIT,
    SOHBossEntranceNames.FOREST_TEMPLE_BOSS_ENTRANCE: SOHBossEntranceExitNames.FOREST_TEMPLE_BOSS_EXIT,
    SOHBossEntranceNames.FIRE_TEMPLE_BOSS_ENTRANCE: SOHBossEntranceExitNames.FIRE_TEMPLE_BOSS_EXIT,
    SOHBossEntranceNames.WATER_TEMPLE_BOSS_ENTRANCE: SOHBossEntranceExitNames.WATER_TEMPLE_BOSS_EXIT,
    SOHBossEntranceNames.SHADOW_TEMPLE_BOSS_ENTRANCE: SOHBossEntranceExitNames.SHADOW_TEMPLE_BOSS_EXIT,
    SOHBossEntranceNames.SPIRIT_TEMPLE_BOSS_ENTRANCE: SOHBossEntranceExitNames.SPIRIT_TEMPLE_BOSS_EXIT,
}


# Might need to return the ER Placement state at the end
def randomize_entrances_soh(world: "SohWorld", entrances_to_shuffle: set[SOHBossEntranceNames | SOHDungeonEntranceNames | SOHDungeonExitNames], entrance_groups: dict[int: list[int]], on_connect: Callable[[ERPlacementState, list[Entrance], list[Entrance]], bool | None] | None = None) -> None:
    for entranceEnum in entrances_to_shuffle:
        disconnect_entrance_for_randomization(world.multiworld.get_entrance(
            entranceEnum.value, world.player), one_way_target_name=entrance_matching[entranceEnum].value if entranceEnum in entrance_matching else None)

    # Figure out decoupled entrances. For now setting to False
    #randomize_entrances(world, (not bool(world.options.decouple_entrances)), entrance_groups, True, on_connect=on_connect)
    randomize_entrances(
        world, False, entrance_groups, True, on_connect=on_connect)


# This should probably be double checked by someone who knows how to properly remove a location from a region and give it a new parent region
def on_connect_soh_sheik_at_collosus(er_state: ERPlacementState, placed_exits: list[Entrance], paired_entrances: list[Entrance]) -> bool:
    if len(paired_entrances) >= 2 and paired_entrances[1].name == SOHDungeonEntranceNames.SPIRIT_TEMPLE_DUNGEON_ENTRNACE:
        world: SohWorld = er_state.world
        def locationRule(bundle): return True

        print(f'Placed Exits: {placed_exits} | Paired Entrances: {paired_entrances}')
        location: Location = world.get_location(Locations.SHEIK_AT_COLOSSUS)
        location.parent_region.locations.remove(location)

        new_parent_region: Region = world.get_entrance(paired_entrances[0].name).parent_region
        location.parent_region = new_parent_region
        new_parent_region.add_locations({str(location.name): location.address}, SohLocation)
        set_rule(world.get_location(location.name), rule_wrapper.wrap(new_parent_region, locationRule, world))

    return False
