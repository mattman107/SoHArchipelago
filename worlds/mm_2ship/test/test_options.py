"""
Option-profile generation tests. Each class runs the full WorldTestBase suite
(fill, accessibility, empty-state sanity) under one option profile.
"""

from . import MM2ShipTestBase


class TestDefault(MM2ShipTestBase):
    options = {}


class TestAllShuffles(MM2ShipTestBase):
    options = {
        "shuffle_pot_drops": True,
        "shuffle_crate_drops": True,
        "shuffle_barrel_drops": True,
        "shuffle_grass_drops": True,
        "shuffle_tree_drops": True,
        "shuffle_snowball_drops": True,
        "shuffle_freestanding_items": True,
        "shuffle_enemy_drops": True,
        "shuffle_cows": True,
        "shuffle_frogs": True,
        "shuffle_shops": True,
        "shuffle_tingle_shops": True,
        "shuffle_gold_skulltulas": True,
        "shuffle_owl_statues": True,
        "shuffle_boss_remains": True,
        "shuffle_boss_souls": True,
        "shuffle_enemy_souls": True,
        "shuffle_ocarina": True,
        "shuffle_ocarina_buttons": True,
        "shuffle_swim": True,
        "shuffle_sword": True,
        "shuffle_shield": True,
        "shuffle_song_time": True,
        "shuffle_song_sun": True,
        "shuffle_song_double_time": True,
        "shuffle_song_inverted_time": True,
        "shuffle_song_saria": True,
        "shuffle_skeleton_key": True,
        "shuffle_tycoon_wallet": True,
    }


class TestClockShuffleRandom(MM2ShipTestBase):
    options = {
        "clock_shuffle": True,
        "clock_shuffle_progressive": "random",
    }


class TestClockShuffleAscending(MM2ShipTestBase):
    options = {
        "clock_shuffle": True,
        "clock_shuffle_progressive": "ascending",
    }


class TestOwnDungeonPlacement(MM2ShipTestBase):
    options = {
        "placement_small_keys": "own_dungeon",
        "placement_boss_keys": "own_dungeon",
        "placement_stray_fairies": "own_dungeon",
    }


class TestSoulsanity(MM2ShipTestBase):
    options = {
        "shuffle_enemy_souls": True,
        "shuffle_boss_souls": True,
        "shuffle_enemy_drops": True,
    }


class TestTriforceHunt(MM2ShipTestBase):
    options = {
        "shuffle_triforce_pieces": True,
        "triforce_pieces_max": 15,
        "triforce_pieces_required": 10,
    }


class TestDungeonAccessOpen(MM2ShipTestBase):
    options = {
        "access_dungeons": "open",
    }


class TestMoonRemainsZero(MM2ShipTestBase):
    options = {
        "access_moon_remains_count": 0,
        "access_trials": "open",
    }
