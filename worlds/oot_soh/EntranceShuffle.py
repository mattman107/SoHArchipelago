from typing import TYPE_CHECKING, Callable
from BaseClasses import Location, Region
from .Enums import SOHBossEntranceExitNames, SOHBossEntranceNames, SOHDungeonExitNames, SOHDungeonEntranceNames, Locations, SOHEntranceGroups
from .Locations import SohLocation
from entrance_rando import disconnect_entrance_for_randomization, randomize_entrances, bake_target_group_lookup
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

default_group_lookup = {
    SOHEntranceGroups.DUNGEON_ENTRANCE: [SOHEntranceGroups.DUNGEON_ENTRANCE],
    SOHEntranceGroups.BOSS_ENTRANCE: [SOHEntranceGroups.BOSS_ENTRANCE],
    SOHEntranceGroups.GROTTO: [SOHEntranceGroups.GROTTO],
}


mixed_group_lookup = {group: [all for all in (SOHEntranceGroups.OTHER, SOHEntranceGroups.BOSS_ENTRANCE, SOHEntranceGroups.DUNGEON_ENTRANCE, SOHEntranceGroups.OVERWORLD, SOHEntranceGroups.INTERIOR, 
                                              SOHEntranceGroups.THEIVES_HIDEOUT_ENTRANCE, SOHEntranceGroups.GROTTO, SOHEntranceGroups.OWL_DROP, SOHEntranceGroups.WARP_SONG)] 
                                              for group in (SOHEntranceGroups.OTHER, SOHEntranceGroups.BOSS_ENTRANCE, SOHEntranceGroups.DUNGEON_ENTRANCE, SOHEntranceGroups.OVERWORLD, SOHEntranceGroups.INTERIOR, 
                                                            SOHEntranceGroups.THEIVES_HIDEOUT_ENTRANCE, SOHEntranceGroups.GROTTO, SOHEntranceGroups.OWL_DROP, SOHEntranceGroups.WARP_SONG)}


def get_target_groups(group: int) -> list[int]:
    type = group & SOHEntranceGroups.TYPE_MASK
    age = group & SOHEntranceGroups.AGE_MASK

    if(age == SOHEntranceGroups.ANY_AGE):
        return [pair_type | ages for pair_type in default_group_lookup[type] for ages in (SOHEntranceGroups.ANY_AGE, SOHEntranceGroups.CHILD, SOHEntranceGroups.ADULT, SOHEntranceGroups.CHILD_ONLY, SOHEntranceGroups.ADULT_ONLY, SOHEntranceGroups.BOTH_AGE)]
    
    if(age == SOHEntranceGroups.BOTH_AGE):
        return [pair_type | ages for pair_type in default_group_lookup[type] for ages in (SOHEntranceGroups.BOTH_AGE, SOHEntranceGroups.ADULT, SOHEntranceGroups.CHILD, SOHEntranceGroups.ANY_AGE)]
    
    if(age == SOHEntranceGroups.CHILD):
        return [pair_type | ages for pair_type in default_group_lookup[type] for ages in (SOHEntranceGroups.CHILD, SOHEntranceGroups.CHILD_ONLY, SOHEntranceGroups.ADULT, SOHEntranceGroups.BOTH_AGE, SOHEntranceGroups.ANY_AGE)]
    
    if(age == SOHEntranceGroups.ADULT):
        return [pair_type | ages for pair_type in default_group_lookup[type] for ages in (SOHEntranceGroups.ADULT, SOHEntranceGroups.ADULT_ONLY, SOHEntranceGroups.CHILD, SOHEntranceGroups.BOTH_AGE, SOHEntranceGroups.ANY_AGE)]
    
    if(age == SOHEntranceGroups.ADULT_ONLY):
        return [pair_type | ages for pair_type in default_group_lookup[type] for ages in (SOHEntranceGroups.ADULT_ONLY, SOHEntranceGroups.ADULT, SOHEntranceGroups.ANY_AGE)]
    
    if(age == SOHEntranceGroups.CHILD_ONLY):
        return [pair_type | ages for pair_type in default_group_lookup[type] for ages in (SOHEntranceGroups.CHILD_ONLY, SOHEntranceGroups.CHILD, SOHEntranceGroups.ANY_AGE)]
    
    return [pair_type | age for pair_type in default_group_lookup[type]]


def get_target_groups_age_restrictive(group: int) -> list[int]:
    type = group & SOHEntranceGroups.TYPE_MASK
    age = group & SOHEntranceGroups.AGE_MASK
    
    if(age == SOHEntranceGroups.CHILD):
        return [pair_type | ages for pair_type in default_group_lookup[type] for ages in (SOHEntranceGroups.CHILD_ONLY, SOHEntranceGroups.CHILD)]
    
    if(age == SOHEntranceGroups.ADULT):
        return [pair_type | ages for pair_type in default_group_lookup[type] for ages in (SOHEntranceGroups.ADULT_ONLY, SOHEntranceGroups.ADULT)]
    
    if(age == SOHEntranceGroups.ADULT_ONLY):
        return [pair_type | ages for pair_type in default_group_lookup[type] for ages in (SOHEntranceGroups.ADULT, SOHEntranceGroups.ADULT_ONLY)]
    
    if(age == SOHEntranceGroups.CHILD_ONLY):
        return [pair_type | ages for pair_type in default_group_lookup[type] for ages in (SOHEntranceGroups.CHILD, SOHEntranceGroups.CHILD_ONLY)]
    
    return [pair_type | age for pair_type in default_group_lookup[type]]


# Might need to return the ER Placement state at the end
def randomize_entrances_soh(world: "SohWorld", entrances_to_shuffle: set[SOHBossEntranceNames | SOHDungeonEntranceNames | SOHDungeonExitNames], on_connect: Callable[[ERPlacementState, list[Entrance], list[Entrance]], bool | None] | None = None, coupled: bool = True, ageRestricted: bool = False) -> None:
    for entranceEnum in entrances_to_shuffle:
        disconnect_entrance_for_randomization(world.multiworld.get_entrance(
            entranceEnum.value, world.player), one_way_target_name=entrance_matching[entranceEnum].value if entranceEnum in entrance_matching else None)

    if ageRestricted:
        target_group_lookup = bake_target_group_lookup(world, get_target_groups_age_restrictive)
    else:
        target_group_lookup = bake_target_group_lookup(world, get_target_groups)

    randomize_entrances(
        world, coupled, target_group_lookup, True, on_connect=on_connect)


# This should probably be double checked by someone who knows how to properly remove a location from a region and give it a new parent region
def on_connect_soh_sheik_at_colossus(er_state: ERPlacementState, placed_exits: list[Entrance], paired_entrances: list[Entrance]) -> bool:
    if er_state.world.options.decouple_entrances and len(paired_entrances) >= 2 and paired_entrances[1].name == SOHDungeonEntranceNames.SPIRIT_TEMPLE_DUNGEON_ENTRNACE:
        world: SohWorld = er_state.world
        def locationRule(bundle): return True

        # print(f'Placed Exits: {placed_exits} | Paired Entrances: {paired_entrances}')
        location: Location = world.get_location(Locations.SHEIK_AT_COLOSSUS)
        location.parent_region.locations.remove(location)

        new_parent_region: Region = world.get_entrance(paired_entrances[0].name).parent_region
        location.parent_region = new_parent_region
        new_parent_region.add_locations({str(location.name): location.address}, SohLocation)
        set_rule(world.get_location(location.name), rule_wrapper.wrap(new_parent_region, locationRule, world))

    return False
