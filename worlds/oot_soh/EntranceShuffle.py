from .Enums import SOHBossEntranceExitNames, SOHBossEntranceNames  # , Ages, Regions
# from entrance_rando import ERPlacementState, Entrance
# from . import RegionAgeAccess

# Pretty sure this is only needed for One Way entrances
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


# special_entrance_requirements = {
#     SOHBossEntranceExitNames.JABU_JABUS_BOSS_EXIT.value: Ages.CHILD,
#     SOHBossEntranceExitNames.WATER_TEMPLE_BOSS_EXIT.value: Ages.ADULT
# }

# Couldn't get this to work. I instead opted for more groups that intermingle. I feel like this could work though.
# Two issues:
# 1. At this point no items have been collected so our age logic always returns false.
# 2. I was having a hard time
# def soh_oot_on_connect(er_state: ERPlacementState, placed_exits: list[Entrance], paired_entrances: list[Entrance]) -> bool:

#     updated: bool = False
#     index: int = 0
#     regions_dict = {i.value: i for i in Regions}

#     for _ in paired_entrances:
#         print(
#             f"Entrance:{paired_entrances[index].name} | Exit Region: {placed_exits[index].connected_region.name}")
#         if paired_entrances[index].name in special_entrance_requirements:

#             if er_state.collection_state._soh_can_reach_as_age(regions_dict.get(placed_exits[index].connected_region.name), special_entrance_requirements[paired_entrances[index].name], er_state.world.player):
#                 index += 1
#                 continue

#             # pick another random exit and see if this age can reach it
#             exits = [er_state.entrance_lookup.find_target(
#                 exit.value) for exit in SOHBossEntranceExitNames]
#             er_state.world.random.shuffle(exits)
#             picked_exit = None

#             for exit in exits:
#                 if er_state.collection_state._soh_can_reach_as_age(regions_dict.get(exit.connected_region.name), special_entrance_requirements[paired_entrances[index].name], er_state.world.player):
#                     picked_exit = exit
#                     break

#             er_state.connect(picked_exit, paired_entrances[index])
#             if not updated:
#                 updated = True

#         index += 1

#     return updated
