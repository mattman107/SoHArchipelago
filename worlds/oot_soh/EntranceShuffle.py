from typing import TYPE_CHECKING, Callable
from BaseClasses import Location, Region, Entrance
from .Enums import SOHBossEntranceExitNames, SOHBossEntranceNames, SOHDungeonExitNames, SOHDungeonEntranceNames, Locations, SOHEntranceGroups, Regions, SOHBossWarpEntranceNames, SOHGrottoEntranceNames, SOHGrottoExitNames
from .Locations import SohLocation
from entrance_rando import disconnect_entrance_for_randomization, randomize_entrances, bake_target_group_lookup, EntranceRandomizationError
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

boss_indirect_condition_matching = {
    SOHBossEntranceNames.DEKU_TREE_BOSS_ENTRANCE: (Regions.DEKU_TREE_BOSS_ROOM, SOHBossWarpEntranceNames.DEKU_TREE_BOSS_WARP_ENTRANCE),
    SOHBossEntranceNames.DODONGOS_CAVERN_BOSS_ENTRANCE: (Regions.DODONGOS_CAVERN_BOSS_ROOM, SOHBossWarpEntranceNames.DODONGOS_CAVERN_BOSS_WARP_ENTRANCE),
    SOHBossEntranceNames.JABU_JABUS_BOSS_ENTRANCE: (Regions.JABU_JABUS_BELLY_BOSS_ROOM, SOHBossWarpEntranceNames.JABU_JABUS_BOSS_WARP_ENTRANCE),
    SOHBossEntranceNames.FOREST_TEMPLE_BOSS_ENTRANCE: (Regions.FOREST_TEMPLE_BOSS_ROOM, SOHBossWarpEntranceNames.FOREST_TEMPLE_BOSS_WARP_ENTRANCE),
    SOHBossEntranceNames.FIRE_TEMPLE_BOSS_ENTRANCE: (Regions.FIRE_TEMPLE_BOSS_ROOM, SOHBossWarpEntranceNames.FIRE_TEMPLE_BOSS_WARP_ENTRANCE),
    SOHBossEntranceNames.WATER_TEMPLE_BOSS_ENTRANCE: (Regions.WATER_TEMPLE_BOSS_ROOM, SOHBossWarpEntranceNames.WATER_TEMPLE_BOSS_WARP_ENTRANCE),
    SOHBossEntranceNames.SHADOW_TEMPLE_BOSS_ENTRANCE: (Regions.SHADOW_TEMPLE_BOSS_ROOM, SOHBossWarpEntranceNames.SHADOW_TEMPLE_BOSS_WARP_ENTRANCE),
    SOHBossEntranceNames.SPIRIT_TEMPLE_BOSS_ENTRANCE: (Regions.SPIRIT_TEMPLE_BOSS_ROOM, SOHBossWarpEntranceNames.SPIRIT_TEMPLE_BOSS_WARP_ENTRANCE),
}

default_group_lookup = {
    SOHEntranceGroups.DUNGEON_ENTRANCE: [SOHEntranceGroups.DUNGEON_ENTRANCE],
    SOHEntranceGroups.BOSS_ENTRANCE: [SOHEntranceGroups.BOSS_ENTRANCE],
    SOHEntranceGroups.GROTTO: [SOHEntranceGroups.GROTTO],
}


mixed_group_lookup = {group: [all for all in (SOHEntranceGroups.OTHER, SOHEntranceGroups.BOSS_ENTRANCE, SOHEntranceGroups.DUNGEON_ENTRANCE, SOHEntranceGroups.OVERWORLD, SOHEntranceGroups.INTERIOR, 
                                              SOHEntranceGroups.THEIVES_HIDEOUT_ENTRANCE, SOHEntranceGroups.GROTTO)] 
                                              for group in (SOHEntranceGroups.OTHER, SOHEntranceGroups.BOSS_ENTRANCE, SOHEntranceGroups.DUNGEON_ENTRANCE, SOHEntranceGroups.OVERWORLD, SOHEntranceGroups.INTERIOR, 
                                                            SOHEntranceGroups.THEIVES_HIDEOUT_ENTRANCE, SOHEntranceGroups.GROTTO)}
                                                            

# This is allowing us to brute force the problem of GER failing. May be a necessary evil as it doesn't do swap or automatic retries itself.
OOT_SOH_GER_RETRIES_AMOUNT: int = 10

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

def get_target_groups_mixed_entrance_pools(group: int) -> list[int]:
    type = group & SOHEntranceGroups.TYPE_MASK
    age = group & SOHEntranceGroups.AGE_MASK

    if(age == SOHEntranceGroups.ANY_AGE):
        return [pair_type | ages for pair_type in mixed_group_lookup[type] for ages in (SOHEntranceGroups.ANY_AGE, SOHEntranceGroups.CHILD, SOHEntranceGroups.ADULT, SOHEntranceGroups.CHILD_ONLY, SOHEntranceGroups.ADULT_ONLY, SOHEntranceGroups.BOTH_AGE)]
    
    if(age == SOHEntranceGroups.BOTH_AGE):
        return [pair_type | ages for pair_type in mixed_group_lookup[type] for ages in (SOHEntranceGroups.BOTH_AGE, SOHEntranceGroups.ADULT, SOHEntranceGroups.CHILD, SOHEntranceGroups.ANY_AGE)]
    
    if(age == SOHEntranceGroups.CHILD):
        return [pair_type | ages for pair_type in mixed_group_lookup[type] for ages in (SOHEntranceGroups.CHILD, SOHEntranceGroups.CHILD_ONLY, SOHEntranceGroups.ADULT, SOHEntranceGroups.BOTH_AGE, SOHEntranceGroups.ANY_AGE)]
    
    if(age == SOHEntranceGroups.ADULT):
        return [pair_type | ages for pair_type in mixed_group_lookup[type] for ages in (SOHEntranceGroups.ADULT, SOHEntranceGroups.ADULT_ONLY, SOHEntranceGroups.CHILD, SOHEntranceGroups.BOTH_AGE, SOHEntranceGroups.ANY_AGE)]
    
    if(age == SOHEntranceGroups.ADULT_ONLY):
        return [pair_type | ages for pair_type in mixed_group_lookup[type] for ages in (SOHEntranceGroups.ADULT_ONLY, SOHEntranceGroups.ADULT, SOHEntranceGroups.ANY_AGE)]
    
    if(age == SOHEntranceGroups.CHILD_ONLY):
        return [pair_type | ages for pair_type in mixed_group_lookup[type] for ages in (SOHEntranceGroups.CHILD_ONLY, SOHEntranceGroups.CHILD, SOHEntranceGroups.ANY_AGE)]
    
    return [pair_type | age for pair_type in mixed_group_lookup[type]]

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


# Special Randomization for one ways like Owl Drop and Warp Songs 
def randomize_soh_one_way_entrances(world: "SohWorld") -> None:
    if world.options.shuffle_owl_drop_entrances or world.options.shuffle_warp_song_entrances:
        one_way_entrance_names = list()
        one_way_exit_region_names = list()

        if world.options.shuffle_owl_drop_entrances:
            one_way_entrance_names += [Regions.LH_OWL_FLIGHT, Regions.DMT_OWL_FLIGHT]

        if world.options.shuffle_warp_song_entrances:
            # SOH Seems to put these at random places, except for glitchless. They enforce Graveyard, Crater, and Colossus Warp pads be assigned when glitchless.
            one_way_entrance_names +=[Regions.MINUET_OF_FOREST_WARP, Regions.BOLERO_OF_FIRE_WARP, Regions.SERENADE_OF_WATER_WARP, Regions.NOCTURNE_OF_SHADOW_WARP, Regions.REQUIEM_OF_SPIRIT_WARP, Regions.PRELUDE_OF_LIGHT_WARP]
            one_way_exit_region_names += [Regions.DMC_CENTRAL_LOCAL, Regions.DESERT_COLOSSUS, Regions.GRAVEYARD_WARP_PAD_REGION]

        # Remove the existing exit
        for name in one_way_entrance_names:
            entrance = world.get_entrance(str(name))
            entrance.connected_region.entrances.remove(entrance)
            entrance.connected_region = None

        # Get enough entrances to connect up
        # TODO This will need to be updated as we make more named entrances
        all_named_entrances = list(SOHDungeonEntranceNames) + list(SOHDungeonExitNames) + list(SOHGrottoExitNames) + list(SOHGrottoEntranceNames) 
        world.random.shuffle(all_named_entrances)
        for entrance_name in all_named_entrances:
            if len(one_way_entrance_names) == len(one_way_exit_region_names):
                break
                
            if entrance_name not in one_way_exit_region_names:
                one_way_exit_region_names.append(entrance_name)

        # Randomize the the entrance name list and iterate through 
        world.random.shuffle(one_way_exit_region_names)

        index: int = 0
        for entrance_name in one_way_entrance_names:
            entrance = world.get_entrance(str(entrance_name))
        
            if one_way_exit_region_names[index] in all_named_entrances:
                connected_region_name = world.get_entrance(str(one_way_exit_region_names[index])).parent_region.name
            else:
                connected_region_name = str(one_way_exit_region_names[index])

            entrance.connected_region = world.get_region(connected_region_name)
            entrance.connected_region.entrances.append(entrance)
            
            index += 1


# Might need to return the ER Placement state at the end
def randomize_entrances_soh(world: "SohWorld", entrances_to_shuffle: set[SOHBossEntranceNames | SOHDungeonEntranceNames | SOHDungeonExitNames], on_connect: Callable[[ERPlacementState, list[Entrance], list[Entrance]], bool | None] | None = None, coupled: bool = True, ageRestricted: bool = False) -> None:
    for entranceEnum in entrances_to_shuffle:
        disconnect_entrance_for_randomization(world.multiworld.get_entrance(
            entranceEnum.value, world.player), one_way_target_name=entrance_matching[entranceEnum].value if entranceEnum in entrance_matching else None)

    if ageRestricted:
        target_group_lookup = bake_target_group_lookup(world, get_target_groups_age_restrictive)
    elif world.options.mixed_entrances_pools:
        target_group_lookup = bake_target_group_lookup(world, get_target_groups_mixed_entrance_pools)
    else:
        target_group_lookup = bake_target_group_lookup(world, get_target_groups)
    

    for i in range(OOT_SOH_GER_RETRIES_AMOUNT):
        try:
            er_state = randomize_entrances(world, coupled, target_group_lookup, False, on_connect=on_connect)
            world.er_pairings += er_state.pairings
            print(f"Took {i} attempts to get GER working.")
            break
        except EntranceRandomizationError as error:
            if i >= OOT_SOH_GER_RETRIES_AMOUNT - 1:
                raise EntranceRandomizationError(f"OOT SOH: failed GER after {OOT_SOH_GER_RETRIES_AMOUNT} "
                                                     f"attempts. Final error here: \n\n{error}")
            # need to disconnect all entrances that are supposed to be shuffled
            for entranceEnum in entrances_to_shuffle:
                _exit: Entrance = world.multiworld.get_entrance(entranceEnum.value, world.player)
                if (_exit.randomization_group in target_group_lookup and _exit.parent_region and _exit.connected_region and _exit.name not in world.er_pairings):
                    disconnect_entrance_for_randomization(_exit, one_way_target_name=entrance_matching[entranceEnum].value if entranceEnum in entrance_matching else None)


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
