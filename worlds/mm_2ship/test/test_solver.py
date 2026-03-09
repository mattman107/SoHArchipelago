"""
Solver regression tests against the generated region graph.

These guard the pipeline end-to-end: if a regenerated RegionData/LogicHelpersGen
breaks coverage or the vanilla layout becomes uncompletable, they fail before
anything reaches a real multiworld.
"""

from . import MM2ShipTestBase
from ..Enums import Locations
from ..ItemData import ITEMS
from ..RegionData import REGIONS
from ..VanillaItems import vanilla_items


def _all_checks() -> set[str]:
    checks: set[str] = set()
    for spec in REGIONS.values():
        checks.update(rc for rc, _, _ in spec.checks)
    return checks


class TestSolverCoverage(MM2ShipTestBase):
    options = {}

    def test_full_inventory_reaches_everything(self) -> None:
        solver = self.world.logic
        counts = {entry.name: 99 for entry in ITEMS.values()}
        counts.update(solver.starting_counts)
        result = solver.solve(counts)

        self.assertEqual(set(result.regions), set(REGIONS),
                         "some regions unreachable with a full inventory")
        self.assertEqual(set(result.checks), _all_checks(),
                         "some checks unreachable with a full inventory")

    def test_progression_only_reaches_everything(self) -> None:
        solver = self.world.logic
        counts = {entry.name: 99 for entry in ITEMS.values() if entry.progression}
        counts.update(solver.starting_counts)
        result = solver.solve(counts)

        self.assertEqual(set(result.checks), _all_checks(),
                         "progression classification is missing a logic-relevant item")

    def test_vanilla_layout_completable(self) -> None:
        """Sphere-walk the vanilla item layout: collecting each reachable
        check's vanilla item must eventually reach every check."""
        solver = self.world.logic
        vanilla_by_rc = {f"RC_{loc.name}": item.value for loc, item in vanilla_items.items()}

        counts = dict(solver.starting_counts)
        seen: set[str] = set()
        for _ in range(64):  # sphere cap; vanilla completes in ~28
            result = solver.solve(dict(counts))
            new = result.checks - seen
            if not new:
                break
            for rc in new:
                name = vanilla_by_rc.get(rc)
                if name:
                    counts[name] = counts.get(name, 0) + 1
            seen |= new

        self.assertEqual(seen, _all_checks(), "vanilla layout deadlocked")

    def test_monotone_in_items(self) -> None:
        solver = self.world.logic
        empty = solver.solve(dict(solver.starting_counts))
        full_counts = {entry.name: 99 for entry in ITEMS.values()}
        full_counts.update(solver.starting_counts)
        full = solver.solve(full_counts)

        self.assertLessEqual(set(empty.checks), set(full.checks))
        self.assertLessEqual(set(empty.regions), set(full.regions))


class TestGeneratedDataShape(MM2ShipTestBase):
    options = {}

    def test_every_location_has_a_region(self) -> None:
        checks = _all_checks()
        for loc in Locations:
            if loc is Locations.VICTORY:
                continue
            self.assertIn(f"RC_{loc.name}", checks,
                          f"{loc.name} exists in Checks.cpp but no region defines it")
