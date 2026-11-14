from collections import namedtuple
from typing import TYPE_CHECKING

from .Options import MQDungeons, MasterQuestChoice
from .gen.Ship.ship_data_gen import CheckArea, DUNGEON_SMALL_KEYS

if TYPE_CHECKING:
    from . import SohWorld

MQDungeon = namedtuple('MQDungeon', ['Option', 'Scene'])


def mq_dungeon_mapping(world: "SohWorld") -> dict[CheckArea, MQDungeon]:
    options = world.options
    return {
        CheckArea.RCAREA_DEKU_TREE: MQDungeon(options.deku_tree_quest, "SCENE_DEKU_TREE"),
        CheckArea.RCAREA_DODONGOS_CAVERN: MQDungeon(options.dodongos_cavern_quest, "SCENE_DODONGOS_CAVERN"),
        CheckArea.RCAREA_JABU_JABUS_BELLY: MQDungeon(options.jabu_jabus_belly_quest, "SCENE_JABU_JABU"),
        CheckArea.RCAREA_FOREST_TEMPLE: MQDungeon(options.forest_temple_quest, "SCENE_FOREST_TEMPLE"),
        CheckArea.RCAREA_FIRE_TEMPLE: MQDungeon(options.fire_temple_quest, "SCENE_FIRE_TEMPLE"),
        CheckArea.RCAREA_WATER_TEMPLE: MQDungeon(options.water_temple_quest, "SCENE_WATER_TEMPLE"),
        CheckArea.RCAREA_SPIRIT_TEMPLE: MQDungeon(options.spirit_temple_quest, "SCENE_SPIRIT_TEMPLE"),
        CheckArea.RCAREA_SHADOW_TEMPLE: MQDungeon(options.shadow_temple_quest, "SCENE_SHADOW_TEMPLE"),
        CheckArea.RCAREA_BOTTOM_OF_THE_WELL: MQDungeon(options.bottom_of_the_well_quest, "SCENE_BOTTOM_OF_THE_WELL"),
        CheckArea.RCAREA_ICE_CAVERN: MQDungeon(options.ice_cavern_quest, "SCENE_ICE_CAVERN"),
        CheckArea.RCAREA_GERUDO_TRAINING_GROUND: MQDungeon(options.gerudo_training_ground_quest, "SCENE_GERUDO_TRAINING_GROUND"),
        CheckArea.RCAREA_GANONS_CASTLE: MQDungeon(options.ganons_castle_quest, "SCENE_INSIDE_GANONS_CASTLE"),
    }


def resolve_mq_dungeons(world: "SohWorld") -> list[CheckArea]:
    """The dungeons that are Master Quest this seed, as CheckArea names."""
    mode = world.options.mq_dungeons

    if mode == MQDungeons.option_none:
        return []

    forced: list[CheckArea] = []
    eligible: list[CheckArea] = []
    mapping = mq_dungeon_mapping(world)
    for dungeon, (option, _scene) in mapping.items():
        choice = option.value
        if choice == MasterQuestChoice.option_master_quest:
            forced.append(dungeon)
        elif choice == MasterQuestChoice.option_random_quest:
            eligible.append(dungeon)
        # option_vanilla: never chosen, in any mode.

    if mode == MQDungeons.option_selection_only:
        return sorted(forced + [d for d in eligible if world.random.randint(0, 1)])

    if mode == MQDungeons.option_random_number:
        target = world.random.randint(0, len(mapping))
    else:
        target = world.options.mq_dungeon_count.value

    remaining = max(0, target - len(forced))
    world.random.shuffle(eligible)
    return sorted(forced + eligible[:remaining])


def mq_scenes(world: "SohWorld", dungeons: list[str]) -> frozenset[str]:
    mapping = mq_dungeon_mapping(world)
    return frozenset(mapping[dungeon].Scene for dungeon in dungeons if dungeon in mapping)


def small_key_count(world: "SohWorld", key) -> int:
    """How many of a dungeon's small keys exist. Vanilla VS MQ"""
    dungeon, vanilla, mq = DUNGEON_SMALL_KEYS[key]
    return mq if dungeon in world.mq_dungeons else vanilla
