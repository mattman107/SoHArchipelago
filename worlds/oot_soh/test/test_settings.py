from .. import SohWorld
from ..Options import *
from ..Items import Items, SohItem
from ..Enums import Events
from .bases import SohTestBase
from ..LogicHelpers import can_trigger_lacs, can_build_rainbow_bridge
from itertools import combinations


class SettingsBase(SohTestBase):
    __Test__ = False

    def require_all_lacs(self, items: list[Items | Events]) -> None:
        # ideally we run these as subtests, but those are currently broken 
        # and report as Success if any subtest succeeds
        # (https://github.com/microsoft/vscode-python/issues/25824)
        self.sweep()
        self.assertFalse(can_trigger_lacs(self.get_bundle()), f"Could trigger LACS but shouldn't have been able to.")
        required_items = list(map(lambda i: self.create_item(i), items))
        for size in range(1, len(required_items)):
            for invalid_combo in combinations(required_items, size):
                self.collect(invalid_combo)
                self.assertFalse(can_trigger_lacs(self.get_bundle()), f"Should not be able to access LACS with only {invalid_combo}")
                self.remove(invalid_combo)
        self.collect(required_items)
        self.assertTrue(can_trigger_lacs(self.get_bundle()), f"Wasn't able to trigger LACS, but should have been able to.")
        
        
    def require_some_lacs(self, items: list[Items | Events], required_amount: int) -> None:
        # ideally we run these as subtests, but those are currently broken 
        # and report as Success if any subtest succeeds
        # (https://github.com/microsoft/vscode-python/issues/25824)
        self.sweep()
        self.assertFalse(can_trigger_lacs(self.get_bundle()), f"Could trigger LACS but shouldn't have been able to.")
        required_items = list(map(lambda i: self.create_item(i), items))
        for size in range(1, len(required_items)):
            for invalid_combo in combinations(required_items, size):
                self.collect(invalid_combo)
                if required_amount <= len(invalid_combo) and not (Items.GREG_THE_GREEN_RUPEE in invalid_combo and self.options["ganons_castle_boss_key_greg_modifier"] == GanonsCastleBossKeyGregModifier.option_reward):
                    self.assertTrue(can_trigger_lacs(self.get_bundle()), f"Wasn't able to trigger LACS, but should have been able to with count {required_amount}, {invalid_combo}")
                else:
                    self.assertFalse(can_trigger_lacs(self.get_bundle()), f"Should not be able to access LACS with only {invalid_combo}. Required amount:{required_amount}")

                self.remove(invalid_combo)
        self.collect(required_items)
        self.assertTrue(can_trigger_lacs(self.get_bundle()), f"Wasn't able to trigger LACS, but should have been able to.")

# Greg Specific
class TestCanTriggerLacsTestGregSoloReward(SettingsBase):
    """
    Test can_trigger_lacs greg solo reward
    """
    options = {"ganons_castle_boss_key": GanonsCastleBossKey.option_lacs_stones, 
               "ganons_castle_boss_key_stones_required": 1,
               "ganons_castle_boss_key_greg_modifier": GanonsCastleBossKeyGregModifier.option_reward}

    def test_greg_solo_reward(self):
        self.require_all_lacs([Items.GREG_THE_GREEN_RUPEE])

class TestCanTriggerLacsGregSoloNonReward(SettingsBase):
    """
    Test can_trigger_lacs stones greg solo non reward
    """
    options = {"ganons_castle_boss_key": GanonsCastleBossKey.option_lacs_stones, 
               "ganons_castle_boss_key_stones_required": 1,
               "ganons_castle_boss_key_greg_modifier": GanonsCastleBossKeyGregModifier.option_off}

    def test_stones_greg_solo_nonreward(self):
        self.assertFalse(can_trigger_lacs(self.get_bundle()), f"Could trigger LACS but shouldn't have been able to.")
        self.collect(self.create_item(Items.GREG_THE_GREEN_RUPEE))
        self.assertFalse(can_trigger_lacs(self.get_bundle()), f"Could trigger LACS but shouldn't have been able to.")


# Vanilla
class TestCanTriggerLacsVanilla(SettingsBase):
    """
    Test can_trigger_lacs vanilla
    """
    options = {"ganons_castle_boss_key": GanonsCastleBossKey.option_vanilla,
               "door_of_time": DoorOfTime.option_closed, 
               "start_with_links_pocket": StartWithLinksPocket.option_nothing,
               "shuffle_dungeon_rewards": ShuffleDungeonRewards.option_anywhere,}

    def test_vanilla_setting(self):
        self.require_all_lacs([Items.SHADOW_MEDALLION, Items.SPIRIT_MEDALLION])

class TestCanTriggerLacsAnywhere(SettingsBase):
    """
    Test can_trigger_lacs anywhere
    """
    options = {"ganons_castle_boss_key": GanonsCastleBossKey.option_anywhere,
               "door_of_time": DoorOfTime.option_closed, 
               "start_with_links_pocket": StartWithLinksPocket.option_nothing,
               "shuffle_dungeon_rewards": ShuffleDungeonRewards.option_anywhere,}

    def test_anywhere_setting(self):
        self.require_all_lacs([Items.SHADOW_MEDALLION, Items.SPIRIT_MEDALLION])

class TestCanTriggerLacsLACSVanilla(SettingsBase):
    """
    Test can_trigger_lacs anywhere
    """
    options = {"ganons_castle_boss_key": GanonsCastleBossKey.option_lacs_vanilla,
               "door_of_time": DoorOfTime.option_closed, 
               "start_with_links_pocket": StartWithLinksPocket.option_nothing,
               "shuffle_dungeon_rewards": ShuffleDungeonRewards.option_anywhere,}

    def test_lacs_vanilla_setting(self):
        self.require_all_lacs([Items.SHADOW_MEDALLION, Items.SPIRIT_MEDALLION])

# Stones
class TestCanTriggerLacsStonesAll(SettingsBase):
    """
    Test can_trigger_lacs all stones
    """
    options = {"ganons_castle_boss_key": GanonsCastleBossKey.option_lacs_stones, 
               "door_of_time": DoorOfTime.option_closed, 
               "start_with_links_pocket": StartWithLinksPocket.option_nothing,
               "shuffle_dungeon_rewards": ShuffleDungeonRewards.option_anywhere,
               "ganons_castle_boss_key_stones_required": 3}

    def test_stones_all(self):
        self.require_all_lacs([Items.KOKIRIS_EMERALD, Items.GORONS_RUBY, Items.ZORAS_SAPPHIRE])

class TestCanTriggerLacsStonesFew(SettingsBase):
    """
    Test can_trigger_lacs a few stones
    """
    options = {"ganons_castle_boss_key": GanonsCastleBossKey.option_lacs_stones, 
               "door_of_time": DoorOfTime.option_closed, 
               "start_with_links_pocket": StartWithLinksPocket.option_nothing,
               "shuffle_dungeon_rewards": ShuffleDungeonRewards.option_anywhere,
               "ganons_castle_boss_key_stones_required": 2}

    def test_stones_few(self):
        self.require_some_lacs([Items.KOKIRIS_EMERALD, Items.GORONS_RUBY, Items.ZORAS_SAPPHIRE], 
                               self.options["ganons_castle_boss_key_stones_required"])

class TestCanTriggerLacsStonesGregReward(SettingsBase):
    """
    Test can_trigger_lacs stones greg reward
    """
    options = {"ganons_castle_boss_key": GanonsCastleBossKey.option_lacs_stones, 
                "door_of_time": DoorOfTime.option_closed, 
               "start_with_links_pocket": StartWithLinksPocket.option_nothing,
               "shuffle_dungeon_rewards": ShuffleDungeonRewards.option_anywhere,
               # Needs to be updated when Greg Reward fixes get merged
               "ganons_castle_boss_key_stones_required": 3,
               "ganons_castle_boss_key_greg_modifier": GanonsCastleBossKeyGregModifier.option_reward}

    def test_stones_greg_all(self):
        # Needs to be updated when Greg Reward fixes get merged
        self.require_some_lacs([Items.KOKIRIS_EMERALD, Items.GORONS_RUBY, Items.ZORAS_SAPPHIRE, 
                                Items.GREG_THE_GREEN_RUPEE], self.options["ganons_castle_boss_key_stones_required"])

# Medallions
class TestCanTriggerLacsMedallionsAll(SettingsBase):
    """
    Test can_trigger_lacs all medallions
    """
    options = {"ganons_castle_boss_key": GanonsCastleBossKey.option_lacs_medallions, 
               "ganons_castle_boss_key_medallions_required": 6, 
               "door_of_time": DoorOfTime.option_closed, 
               "start_with_links_pocket": StartWithLinksPocket.option_nothing,
               "shuffle_dungeon_rewards": ShuffleDungeonRewards.option_anywhere}

    def test_medallions_all(self):
        self.require_all_lacs([Items.FOREST_MEDALLION, Items.FIRE_MEDALLION, Items.WATER_MEDALLION, 
                               Items.SPIRIT_MEDALLION, Items.SHADOW_MEDALLION, Items.LIGHT_MEDALLION])

class TestCanTriggerLacsMedallionsFew(SettingsBase):
    """
    Test can_trigger_lacs a few medallions
    """
    options = {"ganons_castle_boss_key": GanonsCastleBossKey.option_lacs_medallions, 
               "ganons_castle_boss_key_medallions_required": 5,
               "door_of_time": DoorOfTime.option_closed, 
               "start_with_links_pocket": StartWithLinksPocket.option_nothing,
               "shuffle_dungeon_rewards": ShuffleDungeonRewards.option_anywhere,}

    def test_medallions_few(self):
        self.require_some_lacs([Items.FOREST_MEDALLION, Items.FIRE_MEDALLION, Items.WATER_MEDALLION, 
                               Items.SPIRIT_MEDALLION, Items.SHADOW_MEDALLION, Items.LIGHT_MEDALLION], self.options["ganons_castle_boss_key_medallions_required"])

class TestCanTriggerLacsMedallionsGregReward(SettingsBase):
    """
    Test can_trigger_lacs medallions greg reward
    """
    options = {"ganons_castle_boss_key": GanonsCastleBossKey.option_lacs_medallions, 
               # Needs to be updated when Greg Reward fixes get merged
               "ganons_castle_boss_key_medallions_required": 6,
               "ganons_castle_boss_key_greg_modifier": GanonsCastleBossKeyGregModifier.option_reward,
               "door_of_time": DoorOfTime.option_closed, 
               "start_with_links_pocket": StartWithLinksPocket.option_nothing,
               "shuffle_dungeon_rewards": ShuffleDungeonRewards.option_anywhere,}

    def test_medallions_greg_all(self):
        # Needs to be updated when Greg Reward fixes get merged
        self.require_some_lacs([Items.FOREST_MEDALLION, Items.FIRE_MEDALLION, Items.WATER_MEDALLION, 
                               Items.SPIRIT_MEDALLION, Items.SHADOW_MEDALLION, Items.LIGHT_MEDALLION,
                                Items.GREG_THE_GREEN_RUPEE], self.options["ganons_castle_boss_key_medallions_required"])

# Dungeon Rewards
class TestCanTriggerLacsDungeonRewardsAll(SettingsBase):
    """
    Test can_trigger_lacs all dungeonrewards
    """
    options = {"ganons_castle_boss_key": GanonsCastleBossKey.option_lacs_dungeon_rewards, 
               "door_of_time": DoorOfTime.option_closed, 
               "start_with_links_pocket": StartWithLinksPocket.option_nothing,
               "shuffle_dungeon_rewards": ShuffleDungeonRewards.option_anywhere,
               "ganons_castle_boss_key_dungeon_rewards_required": 9}

    def test_dungeon_rewards_all(self):
        self.require_all_lacs([Items.KOKIRIS_EMERALD, Items.GORONS_RUBY, Items.ZORAS_SAPPHIRE,
                                Items.FOREST_MEDALLION, Items.FIRE_MEDALLION, Items.WATER_MEDALLION, 
                                Items.SPIRIT_MEDALLION, Items.SHADOW_MEDALLION, Items.LIGHT_MEDALLION])

class TestCanTriggerLacsDungeonRewardsFew(SettingsBase):
    """
    Test can_trigger_lacs a few dungeonrewards
    """
    options = {"ganons_castle_boss_key": GanonsCastleBossKey.option_lacs_dungeon_rewards, 
               "door_of_time": DoorOfTime.option_closed, 
               "start_with_links_pocket": StartWithLinksPocket.option_nothing,
               "shuffle_dungeon_rewards": ShuffleDungeonRewards.option_anywhere,
               "ganons_castle_boss_key_dungeon_rewards_required": 8}

    def test_dungeon_rewards_few(self):
        self.require_some_lacs([Items.KOKIRIS_EMERALD, Items.GORONS_RUBY, Items.ZORAS_SAPPHIRE,
                                Items.FOREST_MEDALLION, Items.FIRE_MEDALLION, Items.WATER_MEDALLION, 
                                Items.SPIRIT_MEDALLION, Items.SHADOW_MEDALLION, Items.LIGHT_MEDALLION], 
                               self.options["ganons_castle_boss_key_dungeon_rewards_required"])

class TestCanTriggerLacsDungeonRewardsGregReward(SettingsBase):
    """
    Test can_trigger_lacs dungeonrewards greg reward
    """
    options = {"ganons_castle_boss_key": GanonsCastleBossKey.option_lacs_dungeon_rewards, 
                "door_of_time": DoorOfTime.option_closed, 
               "start_with_links_pocket": StartWithLinksPocket.option_nothing,
               "shuffle_dungeon_rewards": ShuffleDungeonRewards.option_anywhere,
               # Needs to be updated when Greg Reward fixes get merged
               "ganons_castle_boss_key_dungeon_rewards_required": 9,
               "ganons_castle_boss_key_greg_modifier": GanonsCastleBossKeyGregModifier.option_reward}

    def test_dungeon_rewards_greg_all(self):
        # Needs to be updated when Greg Reward fixes get merged
        self.require_some_lacs([Items.KOKIRIS_EMERALD, Items.GORONS_RUBY, Items.ZORAS_SAPPHIRE,
                                Items.FOREST_MEDALLION, Items.FIRE_MEDALLION, Items.WATER_MEDALLION, 
                                Items.SPIRIT_MEDALLION, Items.SHADOW_MEDALLION, Items.LIGHT_MEDALLION, 
                                Items.GREG_THE_GREEN_RUPEE], self.options["ganons_castle_boss_key_dungeon_rewards_required"])

# Dungeons
class TestCanTriggerLacsDungeonsAll(SettingsBase):
    """
    Test can_trigger_lacs all dungeons
    """
    options = {"ganons_castle_boss_key": GanonsCastleBossKey.option_lacs_dungeons, 
               "door_of_time": DoorOfTime.option_closed, 
               "start_with_links_pocket": StartWithLinksPocket.option_nothing,
               "shuffle_dungeon_rewards": ShuffleDungeonRewards.option_anywhere,
               "ganons_castle_boss_key_dungeons_required": 8}

    def test_dungeons_all(self):
        self.require_all_lacs([Events.DEKU_TREE_COMPLETED, Events.DODONGOS_CAVERN_COMPLETED, Events.JABU_JABUS_BELLY_COMPLETED,
                               Events.FOREST_TEMPLE_COMPLETED, Events.FIRE_TEMPLE_COMPLETED, Events.WATER_TEMPLE_COMPLETED,
                               Events.SHADOW_TEMPLE_COMPLETED, Events.SPIRIT_TEMPLE_COMPLETED])

class TestCanTriggerLacsDungeonsFew(SettingsBase):
    """
    Test can_trigger_lacs a few dungeons
    """
    options = {"ganons_castle_boss_key": GanonsCastleBossKey.option_lacs_dungeons, 
               "door_of_time": DoorOfTime.option_closed, 
               "start_with_links_pocket": StartWithLinksPocket.option_nothing,
               "shuffle_dungeon_rewards": ShuffleDungeonRewards.option_anywhere,
               "ganons_castle_boss_key_dungeons_required": 7}

    def test_dungeons_few(self):
        self.require_some_lacs([Events.DEKU_TREE_COMPLETED, Events.DODONGOS_CAVERN_COMPLETED, Events.JABU_JABUS_BELLY_COMPLETED,
                               Events.FOREST_TEMPLE_COMPLETED, Events.FIRE_TEMPLE_COMPLETED, Events.WATER_TEMPLE_COMPLETED,
                               Events.SHADOW_TEMPLE_COMPLETED, Events.SPIRIT_TEMPLE_COMPLETED], 
                               self.options["ganons_castle_boss_key_dungeons_required"])

class TestCanTriggerLacsDungeonsGregReward(SettingsBase):
    """
    Test can_trigger_lacs dungeons greg reward
    """
    options = {"ganons_castle_boss_key": GanonsCastleBossKey.option_lacs_dungeons, 
                "door_of_time": DoorOfTime.option_closed, 
               "start_with_links_pocket": StartWithLinksPocket.option_nothing,
               "shuffle_dungeon_rewards": ShuffleDungeonRewards.option_anywhere,
               # Needs to be updated when Greg Reward fixes get merged
               "ganons_castle_boss_key_dungeons_required": 8,
               "ganons_castle_boss_key_greg_modifier": GanonsCastleBossKeyGregModifier.option_reward}

    def test_dungeons_greg_all(self):
        # Needs to be updated when Greg Reward fixes get merged
        self.require_some_lacs([Events.DEKU_TREE_COMPLETED, Events.DODONGOS_CAVERN_COMPLETED, Events.JABU_JABUS_BELLY_COMPLETED,
                                Events.FOREST_TEMPLE_COMPLETED, Events.FIRE_TEMPLE_COMPLETED, Events.WATER_TEMPLE_COMPLETED,
                                Events.SHADOW_TEMPLE_COMPLETED, Events.SPIRIT_TEMPLE_COMPLETED, 
                                Items.GREG_THE_GREEN_RUPEE], self.options["ganons_castle_boss_key_dungeons_required"])

# Tokens
class TestCanTriggerLacsTokensAll(SettingsBase):
    """
    Test can_trigger_lacs all tokens
    """
    options = {"ganons_castle_boss_key": GanonsCastleBossKey.option_lacs_skull_tokens,
               "shuffle_skull_tokens": ShuffleTokens.option_all, 
               "ganons_castle_boss_key_skull_tokens_required": 100}

    def test_tokens_all(self):
        self.assertFalse(can_trigger_lacs(self.get_bundle()), f"Could trigger LACS but shouldn't have been able to.")
        self.collect(self.create_item(Items.GOLD_SKULLTULA_TOKEN) for _ in range(99))
        self.assertFalse(can_trigger_lacs(self.get_bundle()), f"Could trigger LACS but shouldn't have been able to.")
        self.collect(self.create_item(Items.GOLD_SKULLTULA_TOKEN))
        self.assertTrue(can_trigger_lacs(self.get_bundle()), f"Couldn't trigger LACS but should have been able to.")
