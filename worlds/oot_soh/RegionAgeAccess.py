from collections import deque
from BaseClasses import CollectionState, MultiWorld
from worlds.AutoWorld import LogicMixin
from .LogicHelpers import IsChild, IsAdult, child_age_dependent_rules, adult_age_dependent_rules
from .Enums import Regions, Ages, TimeOfDay, AGE_TIME_COMBOS
import copy


class SohAgeLogic(LogicMixin):
    """Forward-propagated per-region day/night reachability.

    Mirrors Ship's four-flag model (childDay/childNight/adultDay/adultNight,
    location_access.h ``Region``): each (age, time) context has a reachable set
    that is grown by a forward breadth-first search in the same incremental
    sweep that AP uses for region reachability. Rule evaluation is then an O(1)
    set lookup. This replaces the old event-based "can pass time" model and is
    correct under entrance randomization without the per-call backward DFS of
    the ``day-night`` branch.
    """

    def init_mixin(self, parent: MultiWorld):
        game = "Ship of Harkinian"
        self._soh_stale = {player: True for player in parent.worlds.keys()
                           if parent.worlds[player].game == game}
        players = parent.get_game_groups(game) + parent.get_game_players(game)
        # Four reachable flag sets, one per (age, time) context.
        self._soh_childday_regions = {player: set() for player in players}
        self._soh_childnight_regions = {player: set() for player in players}
        self._soh_adultday_regions = {player: set() for player in players}
        self._soh_adultnight_regions = {player: set() for player in players}
        # Per-context blocked-edge frontier (exits awaiting a passable condition).
        self._soh_childday_blocked = {player: set() for player in players}
        self._soh_childnight_blocked = {player: set() for player in players}
        self._soh_adultday_blocked = {player: set() for player in players}
        self._soh_adultnight_blocked = {player: set() for player in players}
        self._soh_age = {player: Ages.null for player in players}
        self._soh_time = {player: TimeOfDay.NONE for player in players}

    def copy_mixin(self, ret) -> CollectionState:
        ret._soh_stale = {player: stale for player,
                          stale in self._soh_stale.items()}
        for attr in ("_soh_childday_regions", "_soh_childnight_regions",
                     "_soh_adultday_regions", "_soh_adultnight_regions",
                     "_soh_childday_blocked", "_soh_childnight_blocked",
                     "_soh_adultday_blocked", "_soh_adultnight_blocked"):
            setattr(ret, attr, {player: copy.copy(regions)
                                for player, regions in getattr(self, attr).items()})
        ret._soh_age = {player: age for player, age in self._soh_age.items()}
        ret._soh_time = {player: time for player, time in self._soh_time.items()}
        return ret

    def _soh_invalidate(self, player):
        for attr in ("_soh_childday_regions", "_soh_childnight_regions",
                     "_soh_adultday_regions", "_soh_adultnight_regions",
                     "_soh_childday_blocked", "_soh_childnight_blocked",
                     "_soh_adultday_blocked", "_soh_adultnight_blocked"):
            getattr(self, attr)[player] = set()
        self._soh_stale[player] = True

    def _soh_context_sets(self, age: Ages, time: TimeOfDay, player: int):
        """Return the (reachable, blocked) set pair for one (age, time) context."""
        if age == Ages.CHILD:
            if time == TimeOfDay.DAY:
                return self._soh_childday_regions[player], self._soh_childday_blocked[player]
            return self._soh_childnight_regions[player], self._soh_childnight_blocked[player]
        else:
            if time == TimeOfDay.DAY:
                return self._soh_adultday_regions[player], self._soh_adultday_blocked[player]
            return self._soh_adultnight_regions[player], self._soh_adultnight_blocked[player]

    def _soh_apply_time_pass(self, age: Ages, region, root, work) -> None:
        """Ship's ``Region::ApplyTimePass`` (location_access.cpp:431).

        ``region`` was just reached as ``age`` and passes time, so both day and
        night become available for that age on the region itself and on ROOT
        (time-pass amplification: ROOT then propagates the time everywhere
        reachable as that age). Every exit this newly unblocks is pushed onto the
        owning (age, time) context's worklist in ``work`` so the caller's BFS
        drains the amplification cascade to a fixpoint."""
        for time in (TimeOfDay.DAY, TimeOfDay.NIGHT):
            reachable, blocked, queue = work[(age, time)]
            for r in (region, root):
                if r not in reachable:
                    reachable.add(r)
                    for exit in r.exits:
                        blocked.add(exit)
                        queue.append(exit)

    def _soh_update_age_reachable_regions(self, player):
        self._soh_stale[player] = False
        root = self.multiworld.get_region(Regions.ROOT, player)  # type: ignore

        # Seed ROOT with day access (night-start is a stubbed TODO, mirroring
        # AccessReset, location_access.cpp:1080). Both ages are seeded at day
        # because the existing age model treats ROOT as reachable as either age;
        # the starting_age / TIME_TRAVEL edge out of ROOT still gates the
        # non-starting age until time travel, so this keeps age behaviour intact
        # while adding the day flag.
        for age in (Ages.CHILD, Ages.ADULT):
            reachable, blocked = self._soh_context_sets(age, TimeOfDay.DAY, player)
            if root not in reachable:
                reachable.add(root)
                blocked.update(root.exits)

        # Per-context worklist BFS. Each (age, time) context keeps its own queue,
        # seeded once from its persisted blocked frontier.
        #
        # This replaces an outer ``while changed`` fixpoint that re-ran all four
        # contexts -- and re-scanned each context's entire blocked frontier
        # (``deque(blocked)``) -- on every region addition anywhere. That
        # fixpoint was only ever needed to propagate ``ApplyTimePass``
        # amplification: NO edge rule does a live cross-region reachability query
        # during a rebuild. While age/time are pinned here, IsAdult/IsChild and
        # AtDay/AtNight short-circuit to O(1) pinned-context reads, and every
        # other rule is a pure item/event lookup -- so an edge that fails in a
        # given (age, time) context can never start passing in that same context
        # mid-rebuild. The only within-rebuild change is which regions/contexts
        # open. Draining a per-context queue (refilled only when a newly-reached
        # region's exits or time-pass amplification open that context) therefore
        # reaches the identical fixpoint while evaluating each edge only when
        # (re)opened instead of once per pass. The hot loop carries the
        # (reachable, blocked) refs directly and pins age/time once per drain --
        # no per-item context lookup -- and the outer loop normally runs once,
        # then confirms every queue is empty (amplification only couples an age's
        # own day<->night, never CHILD<->ADULT, so it converges fast).
        work = {}
        for age, time in AGE_TIME_COMBOS:
            reachable, blocked = self._soh_context_sets(age, time, player)
            work[(age, time)] = (reachable, blocked, deque(blocked))

        active = True
        while active:
            active = False
            for (age, time), (reachable, blocked, queue) in work.items():
                if not queue:
                    continue
                active = True
                self._soh_age[player] = age
                self._soh_time[player] = time
                while queue:
                    connection = queue.popleft()
                    if connection not in blocked:
                        continue  # already resolved via another path
                    new_region = connection.connected_region
                    if new_region is None:
                        continue
                    if new_region in reachable:
                        blocked.discard(connection)
                        continue
                    if connection.can_reach(self):
                        reachable.add(new_region)
                        blocked.discard(connection)
                        for exit in new_region.exits:
                            blocked.add(exit)
                            queue.append(exit)
                        self.path[new_region] = (new_region.name, self.path.get(
                            connection, None))  # type: ignore
                        # Time-pass amplification (location_access.cpp:431):
                        # reaching a provides_time region opens both day and night
                        # for this age (on the region and ROOT); enqueue whatever
                        # exits that unblocks into the owning context queues.
                        if new_region.provides_time:
                            self._soh_apply_time_pass(age, new_region, root, work)

        self._soh_age[player] = Ages.null
        self._soh_time[player] = TimeOfDay.NONE

    def _soh_can_reach_as_age(self, region: Regions, age: Ages, player: int):
        """Reachable as ``age`` at *any* time (day OR night). Age-only query used
        by is_child / is_adult and the EntranceShuffle / pre_fill paths."""
        if self._soh_age[player] == Ages.null:
            # first layer of recursion
            self._soh_age[player] = age
            can_reach = self.multiworld.get_region(
                region.value, player).can_reach(self)  # type: ignore
            self._soh_age[player] = Ages.null
            return can_reach
        return self._soh_age[player] == age

    def _soh_reach_at_time(self, region: Regions, time: TimeOfDay, player: int):
        """Reachable at ``time``, honouring any pinned age. Used by the AtDay /
        AtNight fallback when no time context is pinned (i.e. when a rule is
        evaluated outside the location loop)."""
        self._soh_time[player] = time
        can_reach = self.multiworld.get_region(
            region.value, player).can_reach(self)  # type: ignore
        self._soh_time[player] = TimeOfDay.NONE
        return can_reach
