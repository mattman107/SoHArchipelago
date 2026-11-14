import random
from dataclasses import fields
import unittest

from ..MasterQuest import mq_dungeon_mapping, mq_scenes, resolve_mq_dungeons
from ..Options import MasterQuestChoice, MQDungeonCount, MQDungeons, SohOptions

# The per-dungeon quest option fields, for the tests that set options by name.
MQ_QUEST_FIELDS = [f.name for f in fields(SohOptions) if isinstance(f.type, type) and issubclass(f.type, MasterQuestChoice)]


class StubOptions:
    def __init__(self, mode, count=0, **quests):
        self.mq_dungeons = MQDungeons(mode)
        self.mq_dungeon_count = MQDungeonCount(count)
        for field in MQ_QUEST_FIELDS:
            setattr(self, field, MasterQuestChoice(MasterQuestChoice.option_random_quest))
        for field, value in quests.items():
            setattr(self, field, MasterQuestChoice(value))


class StubWorld:
    def __init__(self, options, seed=0):
        self.options = options
        self.random = random.Random(seed)


def stub_world(mode=0, seed=0, **quests):
    return StubWorld(StubOptions(mode, 0, **quests), seed)


ALL_DUNGEONS = list(mq_dungeon_mapping(stub_world()))


def resolve(mode, count=0, seed=0, **quests):
    return resolve_mq_dungeons(StubWorld(StubOptions(mode, count, **quests), seed))


class TestResolveMQDungeons(unittest.TestCase):
    def test_none_is_all_vanilla(self):
        # Even a dungeon explicitly set to Master Quest stays vanilla: None means none.
        self.assertEqual(
            resolve(MQDungeons.option_none,
                    deku_tree_quest=MasterQuestChoice.option_master_quest),
            [])

    def test_set_number_picks_exactly_that_many(self):
        for count in (0, 1, 5, 12):
            self.assertEqual(len(resolve(MQDungeons.option_set_number, count)), count,
                             f"count={count}")

    def test_forced_dungeons_count_towards_the_total(self):
        # Ship: "the dungeons chosen to be Master Quest here will count towards that total".
        chosen = resolve(MQDungeons.option_set_number, 3,
                         deku_tree_quest=MasterQuestChoice.option_master_quest,
                         ice_cavern_quest=MasterQuestChoice.option_master_quest)
        self.assertEqual(len(chosen), 3)
        self.assertIn("Deku Tree", chosen)
        self.assertIn("Ice Cavern", chosen)

    def test_vanilla_dungeons_are_never_chosen(self):
        vanilla = {field: MasterQuestChoice.option_vanilla for field in MQ_QUEST_FIELDS}
        vanilla["deku_tree_quest"] = MasterQuestChoice.option_random_quest
        chosen = resolve(MQDungeons.option_set_number, 12, **vanilla)
        # Only one dungeon was available, so Ship's "you will have fewer MQ Dungeons than the
        # number you set" applies rather than an error.
        self.assertEqual(chosen, ["Deku Tree"])

    def test_count_above_available_yields_fewer(self):
        chosen = resolve(MQDungeons.option_set_number, 12,
                         **{field: MasterQuestChoice.option_vanilla
                            for field in MQ_QUEST_FIELDS})
        self.assertEqual(chosen, [])

    def test_selection_only_keeps_forced_and_rolls_the_rest(self):
        chosen = resolve(MQDungeons.option_selection_only,
                         deku_tree_quest=MasterQuestChoice.option_master_quest,
                         ice_cavern_quest=MasterQuestChoice.option_vanilla)
        self.assertIn("Deku Tree", chosen)
        self.assertNotIn("Ice Cavern", chosen)

    def test_set_number_is_exact_only_because_random_quest_defers(self):
        deferred = {field: MasterQuestChoice.option_random_quest for field in MQ_QUEST_FIELDS}
        for seed in range(30):
            self.assertEqual(len(resolve(MQDungeons.option_set_number, 3, seed=seed, **deferred)), 3)

        # Pre-committing them instead makes the count unenforceable -- not an error, just no
        # longer the number the player chose.
        committed = dict(deferred)
        for i, field in enumerate(MQ_QUEST_FIELDS):
            committed[field] = (MasterQuestChoice.option_master_quest if i % 2
                                else MasterQuestChoice.option_vanilla)
        self.assertGreater(len(resolve(MQDungeons.option_set_number, 3, **committed)), 3)

    def test_selection_only_ignores_the_count(self):
        # The count slider belongs to Set Number; under Selection Only each dungeon is its own
        # roll, which is what makes the total a bell curve rather than a chosen number.
        everything_forced = {field: MasterQuestChoice.option_master_quest
                             for field in MQ_QUEST_FIELDS}
        chosen = resolve(MQDungeons.option_selection_only, 1, **everything_forced)
        self.assertEqual(len(chosen), len(ALL_DUNGEONS))

    def test_random_number_stays_in_range(self):
        for seed in range(25):
            self.assertLessEqual(len(resolve(MQDungeons.option_random_number, seed=seed)),
                                 len(ALL_DUNGEONS))

    def test_result_is_deterministic_for_a_seed(self):
        self.assertEqual(resolve(MQDungeons.option_set_number, 4, seed=7),
                         resolve(MQDungeons.option_set_number, 4, seed=7))

    def test_scenes_map_back(self):
        self.assertEqual(mq_scenes(stub_world(), ["Deku Tree", "Ice Cavern"]),
                         frozenset({"SCENE_DEKU_TREE", "SCENE_ICE_CAVERN"}))


class TestRegionGating(unittest.TestCase):
    """A region belongs to a quest variant; only the rolled one is built."""

    def setUp(self):
        from ..LogicHelpers import REGION_SCENE, Regions, region_is_active
        self.REGION_SCENE, self.Regions, self.active = REGION_SCENE, Regions, region_is_active

    @staticmethod
    def world(*dungeons):
        """region_is_active only reads world.mq_scenes."""
        return type("StubMQWorld", (), {"mq_scenes": mq_scenes(stub_world(), list(dungeons))})()

    def test_mq_regions_only_when_that_dungeon_is_mq(self):
        mq_region = self.Regions.RR_DEKU_TREE_MQ_1F
        van_region = self.Regions.RR_DEKU_TREE_LOBBY

        self.assertTrue(self.active(mq_region, self.world("Deku Tree")))
        self.assertFalse(self.active(van_region, self.world("Deku Tree")))

        self.assertFalse(self.active(mq_region, self.world()))
        self.assertTrue(self.active(van_region, self.world()))

    def test_other_dungeons_are_unaffected(self):
        # Ice Cavern being MQ says nothing about the Deku Tree.
        self.assertTrue(self.active(self.Regions.RR_DEKU_TREE_LOBBY, self.world("Ice Cavern")))

    def test_non_dungeon_regions_are_always_active(self):
        self.assertTrue(self.active(self.Regions.RR_KOKIRI_FOREST, self.world()))
        self.assertTrue(self.active(self.Regions.RR_KOKIRI_FOREST, self.world("Deku Tree")))

    def test_dungeon_comes_from_the_scene_not_the_name(self):
        # RR_GANONS_CASTLE_* regions sit in SCENE_INSIDE_GANONS_CASTLE, and it is the scene that
        # ties them to the "Ganon's Castle" dungeon option -- the same scene Ganon's Tower uses,
        # which is why the tower correctly follows the castle's quest rather than its own name.
        vanilla_only = self.Regions.RR_GANONS_CASTLE_DEKU_SCRUBS
        self.assertEqual(self.REGION_SCENE[vanilla_only], "SCENE_INSIDE_GANONS_CASTLE")
        self.assertTrue(self.active(vanilla_only, self.world()))
        self.assertFalse(self.active(vanilla_only, self.world("Ganon's Castle")))
        # Another dungeon being MQ must not disturb it.
        self.assertTrue(self.active(vanilla_only, self.world("Deku Tree")))

    def test_shared_regions_stay_active_in_both_quests(self):
        from ..LogicHelpers import REGION_QUEST
        entryway = self.Regions.RR_DEKU_TREE_ENTRYWAY
        self.assertEqual(REGION_QUEST[entryway], "")
        self.assertTrue(self.active(entryway, self.world()))
        self.assertTrue(self.active(entryway, self.world("Deku Tree")))

    def test_every_dungeon_region_is_reachable_in_exactly_one_configuration(self):
        """No region may be dropped by both quests, and every variant-specific scene must be a
        dungeon MasterQuest.py knows about -- otherwise it could never be switched on."""
        from ..LogicHelpers import REGION_QUEST
        vanilla, all_mq = self.world(), self.world(*ALL_DUNGEONS)
        orphans = [r.name for r in self.REGION_SCENE
                   if not self.active(r, vanilla) and not self.active(r, all_mq)]
        self.assertEqual(orphans, [], "regions no configuration can reach")

        variant_scenes = {self.REGION_SCENE[r] for r, q in REGION_QUEST.items() if q}
        known_scenes = mq_scenes(stub_world(), ALL_DUNGEONS)
        self.assertTrue(variant_scenes <= known_scenes,
                        f"quest-specific regions in unknown scenes: {variant_scenes - known_scenes}")


if __name__ == "__main__":
    unittest.main()
