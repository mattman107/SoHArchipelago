from typing import TYPE_CHECKING, Callable
from .Enums import SOHBossEntranceExitNames, SOHBossEntranceNames, SOHDungeonExitNames, SOHDungeonEntranceNames  # , Ages, Regions
from entrance_rando import disconnect_entrance_for_randomization, randomize_entrances
# from entrance_rando import ERPlacementState, Entrance
# from . import RegionAgeAccess

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
def randomize_entrances_soh(world: "SohWorld", entrances_to_shuffle: set[SOHBossEntranceNames | SOHDungeonEntranceNames | SOHDungeonExitNames], entrance_groups: dict[int: list[int]]) -> None:
    for entranceEnum in entrances_to_shuffle:
        disconnect_entrance_for_randomization(world.multiworld.get_entrance(
            entranceEnum.value, world.player), one_way_target_name=entrance_matching[entranceEnum].value if entranceEnum in entrance_matching else None)

    randomize_entrances(
        world, (not bool(world.options.decouple_entrances)), entrance_groups, True)
