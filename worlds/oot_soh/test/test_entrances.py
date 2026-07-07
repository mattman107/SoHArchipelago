"""Entrance-randomizer tests.

Each options class below inherits WorldTestBase's default tests -- notably
``test_all_state_can_reach_everything`` (full connectivity of the shuffled
graph) and ``test_fill`` (a real fill on the shuffled graph) -- and adds the
slot-data contract checks Ship's ``ParseEntrances``/``ApplyEntranceOverrides``
depend on (see the AP-VS-SHIP DIVERGENCES notes in EntranceShuffle.py).
"""
from Options import Accessibility
from test.general import setup_multiworld
from worlds.AutoWorld import AutoWorldRegister
from .bases import SohTestBase

# Ship entrance types that are one-way overrides (destinations must be -1).
_ONE_WAY_TYPES = frozenset((1, 2, 3, 4))  # owl, spawn, warp song, blue warp


class EntranceContractMixin:
    """Slot-data contract assertions shared by every ER options class."""

    def er_overrides(self) -> list[dict[str, int]]:
        overrides = self.world.entrance_overrides
        self.assertTrue(overrides, "expected entrance overrides to be emitted")
        return overrides

    def test_override_contract(self) -> None:
        decoupled = bool(self.world.options.decouple_entrances.value)
        overrides = self.er_overrides()
        seen: set[int] = set()
        for el in overrides:
            for key in ("type", "index", "destination", "override",
                        "overrideDestination"):
                self.assertIn(key, el)
            # Ship treats an all-zero override as "unshuffled" and skips it.
            self.assertTrue(any(el[k] for k in el), f"all-zero override {el}")
            # An index may be overridden at most once.
            self.assertNotIn(el["index"], seen, f"duplicate index {el}")
            seen.add(el["index"])
            if el["type"] in _ONE_WAY_TYPES or decoupled:
                self.assertEqual(el["destination"], -1, el)
                self.assertEqual(el["overrideDestination"], -1, el)

        # Two-way overrides must permute their own index pool: every shuffled
        # doorway leads somewhere, and every destination is used exactly once.
        two_way = [el for el in overrides if el["type"] not in _ONE_WAY_TYPES]
        self.assertEqual(sorted(el["index"] for el in two_way),
                         sorted(el["override"] for el in two_way),
                         "two-way overrides are not a permutation")

        if not decoupled:
            # Coupled emission is mirrored: for a pairing S -> T, the element
            # rewiring T's reverse back to S's reverse must also exist, with the
            # destination fields cross-referencing each other.
            by_index = {el["index"]: el for el in two_way}
            for el in two_way:
                mirror = by_index.get(el["overrideDestination"])
                self.assertIsNotNone(
                    mirror, f"missing mirrored element for {el}")
                self.assertEqual(mirror["override"], el["destination"], (el, mirror))
                self.assertEqual(mirror["overrideDestination"], el["index"],
                                 (el, mirror))


class TestDungeonBossER(EntranceContractMixin, SohTestBase):
    options = {"shuffle_dungeon_entrances": 2,
               "shuffle_boss_entrances": 2,
               "shuffle_ganons_tower": 1}

    def test_blue_warps_emitted(self) -> None:
        types = {el["type"] for el in self.er_overrides()}
        self.assertIn(4, types, "blue warp overrides missing")


class TestInteriorGrottoER(EntranceContractMixin, SohTestBase):
    options = {"shuffle_interior_entrances": 1,
               "shuffle_grotto_entrances": 1}


class TestInteriorAllER(EntranceContractMixin, SohTestBase):
    # Includes the special interiors (Link's House / Temple of Time), whose
    # shuffle moves the spawn landings' way out -- the ER bootstrap case.
    options = {"shuffle_interior_entrances": 2}


class TestOverworldOneWayER(EntranceContractMixin, SohTestBase):
    options = {"shuffle_overworld_entrances": 1,
               "shuffle_overworld_spawns": 1,
               "shuffle_warp_songs": 1,
               "shuffle_owl_drops": 1}

    def test_one_way_types_present(self) -> None:
        types = {el["type"] for el in self.er_overrides()}
        for expected in (1, 2, 3):  # owl, spawn, warp song
            self.assertIn(expected, types)


class TestMixedER(EntranceContractMixin, SohTestBase):
    options = {"shuffle_dungeon_entrances": 2,
               "shuffle_boss_entrances": 2,
               "shuffle_ganons_tower": 1,
               "shuffle_interior_entrances": 2,
               "shuffle_grotto_entrances": 1,
               "shuffle_overworld_entrances": 1,
               "shuffle_thieves_hideout_entrances": 1,
               "mixed_entrance_pools": 1,
               "mix_dungeon_entrances": 1,
               "mix_interior_entrances": 1,
               "mix_grotto_entrances": 1,
               "mix_overworld_entrances": 1,
               "mix_thieves_hideout_entrances": 1,
               "mix_boss_entrances": 1}


class TestDecoupledER(EntranceContractMixin, SohTestBase):
    options = {"shuffle_dungeon_entrances": 2,
               "shuffle_boss_entrances": 2,
               "shuffle_ganons_tower": 1,
               "shuffle_interior_entrances": 2,
               "shuffle_grotto_entrances": 1,
               "shuffle_overworld_entrances": 1,
               "shuffle_thieves_hideout_entrances": 1,
               "decouple_entrances": 1}


class TestMinimalAccessibilityER(EntranceContractMixin, SohTestBase):
    # The ER validation/fill gate must honour minimal accessibility without
    # spuriously rejecting (or spuriously accepting unbeatable) layouts.
    options = {"accessibility": Accessibility.option_minimal,
               "shuffle_dungeon_entrances": 1,
               "shuffle_interior_entrances": 1,
               "shuffle_grotto_entrances": 1}


class TestEntranceDeterminism(SohTestBase):
    auto_construct = False

    def test_same_seed_same_layout(self) -> None:
        soh = AutoWorldRegister.world_types["Ship of Harkinian"]
        opts = {"shuffle_dungeon_entrances": 1, "shuffle_boss_entrances": 2,
                "shuffle_grotto_entrances": 1}
        steps = ("generate_early", "create_regions", "create_items",
                 "set_rules", "connect_entrances")
        first = setup_multiworld(soh, steps=steps, seed=12345, options=opts)
        second = setup_multiworld(soh, steps=steps, seed=12345, options=opts)
        self.assertEqual(first.worlds[1].entrance_overrides,
                         second.worlds[1].entrance_overrides)


class TestTwoPlayerER(SohTestBase):
    # Regression guard: the ER fill gate must be scoped per player -- a
    # multiworld-wide accessibility sweep rejects every layout when a second,
    # not-yet-filled SoH player exists.
    auto_construct = False

    def test_two_soh_players_generate(self) -> None:
        soh = AutoWorldRegister.world_types["Ship of Harkinian"]
        opts = {"shuffle_dungeon_entrances": 1, "shuffle_boss_entrances": 1,
                "shuffle_grotto_entrances": 1}
        multiworld = setup_multiworld([soh, soh], seed=99, options=[opts, opts])
        for player in (1, 2):
            self.assertTrue(multiworld.worlds[player].entrance_overrides)


class TestUniversalTrackerReplay(SohTestBase):
    """Re-generating from slot data (Universal Tracker) must reproduce the
    seed's exact entrance graph without re-shuffling."""
    auto_construct = False

    def test_replay_matches_generation(self) -> None:
        soh = AutoWorldRegister.world_types["Ship of Harkinian"]
        opts = {"shuffle_dungeon_entrances": 2, "shuffle_boss_entrances": 2,
                "shuffle_ganons_tower": 1, "shuffle_interior_entrances": 2,
                "shuffle_grotto_entrances": 1, "shuffle_overworld_entrances": 1,
                "shuffle_thieves_hideout_entrances": 1}
        steps = ("generate_early", "create_regions", "create_items",
                 "set_rules", "connect_entrances")
        original = setup_multiworld(soh, steps=steps, seed=777, options=opts)
        world = original.worlds[1]
        # Slot data as the UT replay path consumes it: every option value by
        # name (setup_options_from_slot_data restores logic options from these
        # keys) plus the stored entrance layout.
        slot_data = {name: getattr(world.options, name).value
                     for name in soh.options_dataclass.type_hints
                     if hasattr(getattr(world.options, name), "value")}
        slot_data["no_logic"] = world.options.true_no_logic.value
        slot_data["required_trials"] = list(world.ganons_trials)
        slot_data["entrances"] = world.entrance_overrides

        # Replicate test.general.setup_multiworld, injecting re_gen_passthrough
        # before the gen steps so the UT path activates.
        from argparse import Namespace
        from BaseClasses import CollectionState, MultiWorld
        from worlds.AutoWorld import call_all

        multiworld = MultiWorld(1)
        multiworld.game = {1: soh.game}
        multiworld.player_name = {1: "Tester1"}
        multiworld.set_seed(31337)  # deliberately a different seed
        multiworld.re_gen_passthrough = {soh.game: slot_data}
        args = Namespace()
        for key, option in soh.options_dataclass.type_hints.items():
            setattr(args, key, {1: option.from_any(option.default)})
        multiworld.set_options(args)
        multiworld.state = CollectionState(multiworld)
        for step in ("generate_early", "create_regions", "create_items",
                     "set_rules", "connect_entrances"):
            call_all(multiworld, step)
        replayed = multiworld.worlds[1]

        self.assertTrue(getattr(replayed, "using_ut", False))
        self.assertEqual(
            sorted((el["index"], el["override"])
                   for el in world.entrance_overrides),
            sorted((el["index"], el["override"])
                   for el in replayed.entrance_overrides))

        def graph(w) -> set[tuple[str, str]]:
            return {(ent.parent_region.name, ent.connected_region.name)
                    for region in w.multiworld.get_regions(w.player)
                    for ent in region.exits if ent.connected_region is not None
                    and ent.parent_region is not None}

        self.assertEqual(graph(world), graph(replayed))
