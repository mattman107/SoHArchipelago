"""
Hand-written logic runtime for the generated region graph.

This is the one deliberately hand-maintained piece of the logic pipeline: it
ports the C++ solver semantics (FindReachableRegions + TimeLogic expansion +
event fixpoint from GlitchlessLogic.cpp) and implements the primitive
vocabulary the generated rules call (`s.has_item`, `s.event`, `s.opt`, ...).

Everything DATA-shaped (the region graph, conditions, helper predicates, item
grant maps, enum values) lives in the generated modules and flows in from the
2ship sources automatically. This file only needs attention when the C++
*algorithms* change — the genlogic drift ledger flags exactly that.

C++ counterparts:
    LogicContext primitives  <->  Logic.h macros marked as primitives in
                                  tools/genlogic/translate.py
    Solver.solve()           <->  GlitchlessLogic.cpp fixpoint +
                                  Logic.cpp FindReachableRegions
    expand_time_forward()    <->  TimeLogic.cpp ExpandTimeForward
    owned_time_slices()      <->  TimeLogic.cpp GetOwnedTimeSlices
    owns_half_day()          <->  Logic.h OwnsHalfDayForMode
    can_access_dungeon()     <->  Logic.h CanAccessDungeon
    starting items           <->  StartingItems.cpp GetComputedStartingItems
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from . import LogicHelpersGen as H
from .ItemData import ITEMS
from .LogicHelpersGen import (
    ACTOR_TO_SOUL_ITEM,
    BOTTLE_ITEMS,
    DUNGEON_ITEMS,
    HALF_DAY_TIME_RANGES,
    ITEM_TO_ITEMS,
    MOON_MASK_ITEMS,
    OWL_WARP_TO_ITEMS,
    QUEST_TO_ITEMS,
    QUEST_TO_OCARINA,
    RANDO_INF_TO_ITEMS,
    REMAINS_ITEMS,
    SONG_NOTE_REQS,
    TOKEN_SCENE_TO_ITEMS,
    WEEKEVENTREG_TO_ITEMS,
)
from .OptionData import RO_OPTIONS
from .RegionData import REGIONS, START_REGION

if TYPE_CHECKING:
    from . import MM2ShipWorld

TIME_SLICE_COUNT = 45
TIME_ALL_SLICES = (1 << TIME_SLICE_COUNT) - 1


def _item(key: str) -> str:
    """AP display name for an RI enum key — keeps this file rename-proof."""
    return ITEMS[key].name


# Option value constants used structurally here. Their integer values mirror
# Types.h; the ones referenced by translated conditions are emitted (and thus
# verified) in LogicHelpersGen.
RO_CLOCK_SHUFFLE_RANDOM = 0
RO_CLOCK_SHUFFLE_ASCENDING = 1
RO_CLOCK_SHUFFLE_DESCENDING = 2

RO_ACCESS_DUNGEONS_FORM_AND_SONG = 0
RO_ACCESS_DUNGEONS_FORM_OR_SONG = 1
RO_ACCESS_DUNGEONS_FORM_ONLY = 2
RO_ACCESS_DUNGEONS_SONG_ONLY = 3
RO_ACCESS_DUNGEONS_OPEN = 4

# Per-dungeon access requirements for CanAccessDungeon (hand port; the
# generator's drift ledger hashes the C++ body).
_DUNGEON_ACCESS = {
    "DUNGEON_SCENE_INDEX_WOODFALL_TEMPLE":  ("SONATA", "ITEM_MASK_DEKU"),
    "DUNGEON_SCENE_INDEX_SNOWHEAD_TEMPLE":  ("LULLABY", "ITEM_MASK_GORON"),
    "DUNGEON_SCENE_INDEX_GREAT_BAY_TEMPLE": ("BOSSA_NOVA", "ITEM_MASK_ZORA"),
}

OCARINA_BUTTON_FLAGS = [
    "RANDO_INF_OBTAINED_OCARINA_BUTTON_A",
    "RANDO_INF_OBTAINED_OCARINA_BUTTON_C_DOWN",
    "RANDO_INF_OBTAINED_OCARINA_BUTTON_C_RIGHT",
    "RANDO_INF_OBTAINED_OCARINA_BUTTON_C_LEFT",
    "RANDO_INF_OBTAINED_OCARINA_BUTTON_C_UP",
]


class SolveResult(NamedTuple):
    regions: dict[str, int]     # RR_* -> reachable time-slice bitmask
    events: dict[str, int]      # RE_* -> times fired (C++ RANDO_EVENTS counters)
    checks: frozenset[str]      # RC_*


class LogicContext:
    """Evaluation context handed to every generated rule as `s`.

    Carries the per-world snapshot (options, prices), the current inventory
    (item name -> count) and, while the solver walks the graph, the current
    region's reachable time mask in `self.time`.
    """

    __slots__ = ("solver", "counts", "time", "events", "_owned_time")

    def __init__(self, solver: "Solver", counts: dict[str, int]):
        self.solver = solver
        self.counts = counts
        self.time = 0
        # RANDO_EVENTS are counters in C++ (each region's EVENT() instance
        # increments once); conditions may compare counts (e.g. Zora eggs >= 7).
        self.events: dict[str, int] = {}
        self._owned_time: int | None = None

    # -- inventory ----------------------------------------------------------

    def count(self, item_name: str) -> int:
        return self.counts.get(item_name, 0)

    def _any(self, item_names) -> bool:
        counts = self.counts
        for name in item_names:
            if counts.get(name, 0):
                return True
        return False

    def has_item(self, item_const: str) -> bool:
        """HAS_ITEM(ITEM_X): does the inventory slot for ITEM_X hold it?"""
        if self._any(ITEM_TO_ITEMS.get(item_const, ())):
            return True
        extra = self.solver.item_extra_grants.get(item_const)
        return extra is not None and self._any(extra)

    def has_magic(self) -> bool:
        return self._any(self.solver.magic_items)

    def has_bottle(self) -> bool:
        return self._any(BOTTLE_ITEMS)

    def bottle_item(self, item_const: str) -> bool:
        raise NotImplementedError(
            f"HAS_BOTTLE_ITEM({item_const}) appeared in logic but has no runtime "
            f"implementation yet — add one to LogicRuntime.LogicContext."
        )

    def is_form(self, form: str) -> bool:
        # Logic solves from a fresh save: Link is human.
        return form == "HUMAN"

    def player_form(self) -> int:
        return 4  # PLAYER_FORM_HUMAN

    def equip_value(self, equip_type: str) -> int:
        if equip_type == "EQUIP_TYPE_SWORD":
            tier = min(3, self.count(self.solver.progressive_sword))
            for name, direct_tier in self.solver.direct_sword_tiers:
                if self.counts.get(name, 0):
                    tier = max(tier, direct_tier)
            return tier
        if equip_type == "EQUIP_TYPE_SHIELD":
            if self._any(ITEM_TO_ITEMS.get("ITEM_SHIELD_MIRROR", ())):
                return 2
            if self._any(ITEM_TO_ITEMS.get("ITEM_SHIELD_HERO", ())):
                return 1
            return 0
        raise NotImplementedError(f"equip_value({equip_type})")

    def upg_value(self, upg: str) -> int:
        if upg == "UPG_WALLET":
            tier = min(3, self.count(self.solver.progressive_wallet))
            for name, direct_tier in self.solver.direct_wallet_tiers:
                if self.counts.get(name, 0):
                    tier = max(tier, direct_tier)
            return tier
        raise NotImplementedError(f"upg_value({upg})")

    def max_hp(self, target: int) -> bool:
        capacity = (self.solver.starting_health
                    + self.count(self.solver.heart_container)
                    + self.count(self.solver.heart_piece) // 4)
        return capacity >= target

    # -- flags / events / options ---------------------------------------------

    def rando_inf(self, flag: str) -> bool:
        return self._any(RANDO_INF_TO_ITEMS.get(flag, ()))

    def weekeventreg(self, reg: str) -> bool:
        return self._any(WEEKEVENTREG_TO_ITEMS.get(reg, ()))

    def event(self, re_name: str) -> int:
        return self.events.get(re_name, 0)

    def can_access(self, access: str) -> int:
        return self.events.get(f"RE_ACCESS_{access}", 0)

    def opt(self, ro_name: str) -> int:
        return self.solver.options[ro_name]

    def ability(self, name: str) -> bool:
        return self.rando_inf(f"RANDO_INF_OBTAINED_{name}")

    def have_enemy_soul(self, actor: str) -> bool:
        item = ACTOR_TO_SOUL_ITEM.get(actor)
        if item is None:
            return True  # no soul exists for this enemy -> treated as obtained
        return bool(self.counts.get(item, 0))

    def owl_warp(self, owl: str) -> bool:
        if not self.opt("RO_SHUFFLE_OWL_STATUES"):
            # Unshuffled owls activate by touching the statue; the warp can
            # never grant reachability beyond walking there, so it adds nothing.
            return False
        return self._any(OWL_WARP_TO_ITEMS.get(owl, ()))

    # -- songs -------------------------------------------------------------------

    def quest_item(self, quest: str) -> bool:
        if self._any(QUEST_TO_ITEMS.get(quest, ())):
            return True
        prog = self.solver.progressive_quest_grants.get(quest)
        if prog is not None:
            name, needed = prog
            return self.count(name) >= needed
        return False

    def found_ocarina_buttons(self) -> int:
        return sum(1 for flag in OCARINA_BUTTON_FLAGS if self.rando_inf(flag))

    def can_play_notes(self, ocarina_song: str) -> bool:
        req = SONG_NOTE_REQS.get(ocarina_song)
        if req is None:
            return True  # canPlaySong's default case
        kind, payload = req
        if kind == "all":
            return all(self.rando_inf(flag) for flag in payload)
        if kind == "count":
            return self.found_ocarina_buttons() >= payload
        return True

    def can_play_song(self, song: str) -> bool:
        """CAN_PLAY_SONG(song): ocarina + quest song + enough buttons."""
        quest = f"QUEST_SONG_{song}"
        return (self.has_item("ITEM_OCARINA_OF_TIME")
                and self.quest_item(quest)
                and self.can_play_notes(QUEST_TO_OCARINA[quest]))

    def can_use_magic_arrow(self, arrow: str) -> bool:
        return (self.has_item("ITEM_BOW")
                and self.has_item(f"ITEM_ARROW_{arrow}")
                and self.has_magic())

    # -- dungeons ------------------------------------------------------------------

    @staticmethod
    def _dungeon_key(dungeon_const: str) -> str:
        return dungeon_const.replace("DUNGEON_SCENE_INDEX_", "")

    def key_count(self, dungeon: str) -> int:
        if self.counts.get(self.solver.skeleton_key, 0):
            return 99  # Skeleton Key grants max keys for every dungeon
        return self.count(DUNGEON_ITEMS[self._dungeon_key(dungeon)]["small_key"])

    def dungeon_item(self, kind: str, dungeon_const: str) -> bool:
        info = DUNGEON_ITEMS[self._dungeon_key(dungeon_const)]
        if kind == "DUNGEON_BOSS_KEY":
            return bool(self.counts.get(info["boss_key"], 0))
        raise NotImplementedError(f"dungeon_item({kind})")

    def enough_stray_fairies(self, dungeon_const: str) -> bool:
        info = DUNGEON_ITEMS[self._dungeon_key(dungeon_const)]
        return self.count(info["stray_fairy"]) >= self.opt("RO_STRAY_FAIRIES_REQUIRED")

    def enough_skull_tokens(self, scene: str) -> bool:
        total = sum(self.count(n) for n in TOKEN_SCENE_TO_ITEMS.get(scene, ()))
        return total >= self.opt("RO_SKULLTULA_TOKENS_REQUIRED")

    def can_access_dungeon(self, dungeon_const: str) -> bool:
        song, form_mask = _DUNGEON_ACCESS.get(dungeon_const, (None, None))
        has_song = self.can_play_song(song) if song else False
        has_form = (self.has_item(form_mask)
                    and self.has_item("ITEM_OCARINA_OF_TIME")) if form_mask else False
        mode = self.opt("RO_ACCESS_DUNGEONS")
        if mode == RO_ACCESS_DUNGEONS_FORM_OR_SONG:
            return has_song or has_form
        if mode == RO_ACCESS_DUNGEONS_FORM_ONLY:
            return has_form
        if mode == RO_ACCESS_DUNGEONS_SONG_ONLY:
            return has_song
        if mode == RO_ACCESS_DUNGEONS_OPEN:
            return True
        return has_song and has_form

    # -- shops ----------------------------------------------------------------------

    def can_afford(self, rc_name: str) -> bool:
        key = rc_name if rc_name.startswith("RC_") else f"RC_{rc_name}"
        price = self.solver.shop_prices.get(key, 0)
        if price < 100:
            return True
        wallet = self.upg_value("UPG_WALLET")
        if price <= 200:
            return wallet >= 1
        return wallet >= 2

    # -- moon -------------------------------------------------------------------------

    def moon_mask_count(self) -> int:
        return sum(1 for name in MOON_MASK_ITEMS if self.counts.get(name, 0))

    def remains_count(self) -> int:
        return sum(1 for name in REMAINS_ITEMS if self.counts.get(name, 0))

    # -- clock / time ---------------------------------------------------------------------

    def setting_clocks(self) -> bool:
        return bool(self.opt("RO_CLOCK_SHUFFLE"))

    def clock_count(self) -> int:
        total = sum(1 for name in self.solver.clock_items if self.counts.get(name, 0))
        total += self.count(self.solver.progressive_clock)
        return min(6, total)

    def owns_clock_half_day(self, half_day: int) -> bool:
        """Logic.h OwnsClockHalfDay: is this specific half-day's clock owned?"""
        if half_day < 0 or half_day > 5:
            return False
        return bool(self.counts.get(self.solver.clock_items[half_day], 0))

    def owns_half_day(self, half_day: int) -> bool:
        """Logic.h OwnsHalfDayForMode."""
        if not self.setting_clocks() or half_day < 0 or half_day > 5:
            return not self.setting_clocks()
        mode = self.opt("RO_CLOCK_SHUFFLE_PROGRESSIVE")
        if mode == RO_CLOCK_SHUFFLE_RANDOM:
            return self.owns_clock_half_day(half_day)
        total = self.clock_count()
        if mode == RO_CLOCK_SHUFFLE_ASCENDING:
            return total > half_day
        if mode == RO_CLOCK_SHUFFLE_DESCENDING:
            return total > (5 - half_day)
        return False

    def owned_time_slices(self) -> int:
        """TimeLogic.cpp GetOwnedTimeSlices (mode-aware via owns_half_day)."""
        if self._owned_time is not None:
            return self._owned_time
        if not self.setting_clocks():
            mask = TIME_ALL_SLICES
        else:
            mask = 0
            for i, (start, end) in enumerate(HALF_DAY_TIME_RANGES):
                if self.owns_half_day(i):
                    for s in range(start, end + 1):
                        mask |= 1 << s
            if not mask:
                mask = 1  # Day 1 6:00 AM
        self._owned_time = mask
        return mask

    def is_time_slice_owned(self, s: int) -> bool:
        if not self.setting_clocks():
            return True
        for i, (start, end) in enumerate(HALF_DAY_TIME_RANGES):
            if start <= s <= end:
                return self.owns_half_day(i)
        return False

    def raw_at(self, s: int) -> bool:
        return bool(self.time & (1 << s))

    def raw_before(self, s: int) -> bool:
        if s == 0:
            return False
        return bool(self.time & ((1 << s) - 1))

    def raw_after(self, s: int) -> bool:
        return bool(self.time & ~((1 << s) - 1) & TIME_ALL_SLICES)

    def raw_between(self, start: int, end: int) -> bool:
        mask = ((1 << end) - 1) & ~((1 << start) - 1)
        return bool(self.time & mask)

    # AT/BEFORE/AFTER/BETWEEN macros: Raw* && ClockFilter() (generated helper).
    def time_at(self, s: int) -> bool:
        return self.raw_at(s) and H.ClockFilter(self)

    def time_before(self, s: int) -> bool:
        return self.raw_before(s) and H.ClockFilter(self)

    def time_after(self, s: int) -> bool:
        return self.raw_after(s) and H.ClockFilter(self)

    def time_between(self, start: int, end: int) -> bool:
        return self.raw_between(start, end) and H.ClockFilter(self)


class Solver:
    """Per-world reachability solver over the generated region graph."""

    def __init__(self, world: "MM2ShipWorld"):
        self.world = world
        self.player = world.player

        # options snapshot: RO_* -> int via generated ap-name mapping
        self.options: dict[str, int] = {}
        for ro, (ap_name, default) in RO_OPTIONS.items():
            option = getattr(world.options, ap_name, None)
            self.options[ro] = int(option.value) if option is not None else default

        self.shop_prices: dict[str, int] = dict(world.shop_prices)
        self.starting_health: int = self.options.get("RO_STARTING_HEALTH", 3)

        # Item names resolved from ItemData so upstream renames flow through.
        self.progressive_sword = _item("PROGRESSIVE_SWORD")
        self.progressive_wallet = _item("PROGRESSIVE_WALLET")
        self.progressive_clock = _item("TIME_PROGRESSIVE")
        self.skeleton_key = _item("SKELETON_KEY")
        self.heart_container = _item("HEART_CONTAINER")
        self.heart_piece = _item("HEART_PIECE")
        self.magic_items = (_item("SINGLE_MAGIC"), _item("DOUBLE_MAGIC"), _item("PROGRESSIVE_MAGIC"))
        self.direct_sword_tiers = (
            (_item("SWORD_KOKIRI"), 1), (_item("SWORD_RAZOR"), 2), (_item("SWORD_GILDED"), 3),
        )
        self.direct_wallet_tiers = (
            (_item("WALLET_ADULT"), 1), (_item("WALLET_GIANT"), 2), (_item("WALLET_TYCOON"), 3),
        )
        self.clock_items = [
            _item("TIME_DAY_1"), _item("TIME_NIGHT_1"), _item("TIME_DAY_2"),
            _item("TIME_NIGHT_2"), _item("TIME_DAY_3"), _item("TIME_NIGHT_3"),
        ]
        # Derived-inventory grants that Items.cpp's itemId column can't express
        # (progressive items materialize their tier on receipt — ConvertItem.cpp).
        self.item_extra_grants: dict[str, tuple[str, ...]] = {
            "ITEM_BOMB": (_item("PROGRESSIVE_BOMB_BAG"),),
            "ITEM_BOW": (_item("PROGRESSIVE_BOW"),),
        }
        # QUEST_* satisfiable via progressive items: (item name, copies needed)
        self.progressive_quest_grants: dict[str, tuple[str, int]] = {
            "QUEST_SONG_LULLABY": (_item("PROGRESSIVE_LULLABY"), 2),
            "QUEST_SONG_LULLABY_INTRO": (_item("PROGRESSIVE_LULLABY"), 1),
        }

        self.starting_counts: dict[str, int] = self._compute_starting_items()

        # Checks disabled by options (not AP locations) still hand out their
        # vanilla items in-game when reached — e.g. unshuffled shops still sell
        # the All-Night Mask. GlitchlessLogic.cpp models this by GiveItem()ing
        # every reachable check that isn't in the shuffle pool; the solver
        # mirrors it by self-granting these vanilla items during the fixpoint.
        self.disabled_check_vanilla: dict[str, str] = self._compute_disabled_vanilla(world)

        # world-level memo: inventory signature -> SolveResult
        self._memo: dict[tuple, SolveResult] = {}

    @staticmethod
    def _compute_disabled_vanilla(world: "MM2ShipWorld") -> dict[str, str]:
        from .Enums import Locations
        from .LocationFilter import location_should_be_included
        from .VanillaItems import vanilla_items

        disabled: dict[str, str] = {}
        for loc in Locations:
            if loc is Locations.VICTORY:
                continue
            if location_should_be_included(world, loc):
                continue
            vanilla = vanilla_items.get(loc)
            if vanilla is not None:
                disabled[f"RC_{loc.name}"] = vanilla.value
        return disabled

    # -- starting items (port of GetComputedStartingItems, IS_ARCHI branch) ----

    def _compute_starting_items(self) -> dict[str, int]:
        opts = self.options
        start: dict[str, int] = {}

        def give(key: str, n: int = 1) -> None:
            name = _item(key)
            start[name] = start.get(name, 0) + n

        if opts.get("RO_STARTING_MAPS_AND_COMPASSES"):
            for key in ("GREAT_BAY_COMPASS", "GREAT_BAY_MAP", "SNOWHEAD_COMPASS", "SNOWHEAD_MAP",
                        "STONE_TOWER_COMPASS", "STONE_TOWER_MAP", "TINGLE_MAP_CLOCK_TOWN",
                        "TINGLE_MAP_GREAT_BAY", "TINGLE_MAP_ROMANI_RANCH", "TINGLE_MAP_SNOWHEAD",
                        "TINGLE_MAP_STONE_TOWER", "TINGLE_MAP_WOODFALL", "WOODFALL_COMPASS",
                        "WOODFALL_MAP"):
                give(key)
        if not opts.get("RO_SHUFFLE_SWIM"):
            give("ABILITY_SWIM")
        if not opts.get("RO_SHUFFLE_ENEMY_SOULS"):
            for name in sorted(set(ACTOR_TO_SOUL_ITEM.values())):
                start[name] = start.get(name, 0) + 1
        if not opts.get("RO_SHUFFLE_OCARINA_BUTTONS"):
            for flag in OCARINA_BUTTON_FLAGS:
                for name in RANDO_INF_TO_ITEMS.get(flag, ()):
                    start[name] = start.get(name, 0) + 1
        if not opts.get("RO_SHUFFLE_SONG_DOUBLE_TIME"):
            give("SONG_DOUBLE_TIME")
        if not opts.get("RO_SHUFFLE_SONG_INVERTED_TIME"):
            give("SONG_INVERTED_TIME")
        if not opts.get("RO_SHUFFLE_SONG_TIME"):
            give("SONG_TIME")
        if not opts.get("RO_SHUFFLE_SWORD"):
            give("PROGRESSIVE_SWORD")
        if not opts.get("RO_SHUFFLE_SHIELD"):
            give("SHIELD_HERO")
        if not opts.get("RO_SHUFFLE_OCARINA"):
            give("OCARINA")
        if opts.get("RO_STARTING_BUNNY_HOOD"):
            give("MASK_BUNNY")
        # Clock shuffle's guaranteed starting time item is pushed as a real
        # precollected AP item by MM2ShipWorld (so the client also grants it);
        # it therefore arrives via state.prog_items, not here.
        return start

    # -- time expansion (port of TimeLogic.cpp) ---------------------------------

    @staticmethod
    def _forward_fill(mask: int) -> int:
        mask |= (mask << 1)
        mask |= (mask << 2)
        mask |= (mask << 4)
        mask |= (mask << 8)
        mask |= (mask << 16)
        mask |= (mask << 32)
        return mask & TIME_ALL_SLICES

    def expand_time_forward(self, ctx: LogicContext, time_mask: int, spec) -> int:
        if not spec.stays and not ctx.setting_clocks():
            return self._forward_fill(time_mask)

        filtered = time_mask
        if ctx.setting_clocks():
            filtered &= ctx.owned_time_slices()

        stays = {s: rule for s, rule, _src in spec.stays}
        expanded = filtered
        can_wait = False
        for i in range(TIME_SLICE_COUNT):
            bit = 1 << i
            if filtered & bit:
                can_wait = True
                expanded |= bit
            elif can_wait:
                if ctx.setting_clocks() and not ctx.is_time_slice_owned(i):
                    can_wait = False
                    continue
                rule = stays.get(i)
                if rule is not None:
                    if rule(ctx):
                        expanded |= bit
                    else:
                        can_wait = False  # kicked out; expansion stops
                else:
                    expanded |= bit
        return expanded

    # -- main fixpoint (port of GlitchlessLogic.cpp reachability core) ----------

    def solve(self, counts: dict[str, int]) -> SolveResult:
        sig = tuple(sorted((k, v) for k, v in counts.items() if v))
        hit = self._memo.get(sig)
        if hit is not None:
            return hit

        ctx = LogicContext(self, dict(counts))

        regions: dict[str, int] = {}
        can_stay: dict[str, bool] = {}

        if ctx.setting_clocks():
            start_mask = ctx.owned_time_slices()
        else:
            start_mask = 1  # Day 1, 6:00 AM
        regions[START_REGION] = start_mask
        can_stay[START_REGION] = False  # InitialTimeState / InitializeRegionTimeStates

        fired_events: set[tuple[str, int]] = set()  # (region, event index) instances
        granted_checks: set[str] = set()            # disabled checks already self-granted
        events_changed = True
        while events_changed:
            # region/time fixpoint with the current event counters
            work = list(regions)
            while work:
                rid = work.pop()
                spec = REGIONS[rid]
                cur = regions[rid]
                if can_stay[rid]:
                    new_cur = self.expand_time_forward(ctx, cur, spec)
                    if new_cur != cur:
                        regions[rid] = cur = new_cur

                ctx.time = cur
                for edge in spec.connections:
                    if edge[1](ctx):
                        self._propagate(regions, can_stay, work, edge[0], cur)
                for edge in spec.exits:
                    if edge[2](ctx):
                        self._propagate(regions, can_stay, work, edge[0], cur)

            # event pass: each region's EVENT() instance increments its counter
            # once, mirroring GlitchlessLogic's RANDO_EVENTS[event]++.
            events_changed = False
            for rid, mask in regions.items():
                ctx.time = mask
                for idx, (ev, rule, _src) in enumerate(REGIONS[rid].events):
                    key = (rid, idx)
                    if key not in fired_events and rule(ctx):
                        fired_events.add(key)
                        ctx.events[ev] = ctx.events.get(ev, 0) + 1
                        events_changed = True

            # self-grant pass: option-disabled checks hand out their vanilla
            # item when reachable (unshuffled shops/frogs/skulltulas/...),
            # mirroring GlitchlessLogic's GiveItem() for non-pool checks.
            if self.disabled_check_vanilla:
                for rid, mask in regions.items():
                    ctx.time = mask
                    for rc, rule, _src in REGIONS[rid].checks:
                        item_name = self.disabled_check_vanilla.get(rc)
                        if item_name is not None and rc not in granted_checks and rule(ctx):
                            granted_checks.add(rc)
                            ctx.counts[item_name] = ctx.counts.get(item_name, 0) + 1
                            ctx._owned_time = None
                            events_changed = True

        checks: set[str] = set()
        for rid, mask in regions.items():
            ctx.time = mask
            for rc, rule, _src in REGIONS[rid].checks:
                if rc not in checks and rule(ctx):
                    checks.add(rc)

        result = SolveResult(regions=regions, events=dict(ctx.events), checks=frozenset(checks))
        self._memo[sig] = result
        return result

    @staticmethod
    def _propagate(regions: dict[str, int], can_stay: dict[str, bool],
                   work: list[str], target: str, incoming: int) -> None:
        existing = regions.get(target)
        if existing is None:
            regions[target] = incoming
            can_stay[target] = REGIONS[target].can_stay
            work.append(target)
        elif (existing | incoming) != existing:
            regions[target] = existing | incoming
            work.append(target)

    # -- AP-facing API ------------------------------------------------------------

    def result_for(self, state) -> SolveResult:
        cache = state.mm2ship_result
        res = cache.get(self.player)
        if res is None:
            counts = dict(self.starting_counts)
            for name, n in state.prog_items[self.player].items():
                counts[name] = counts.get(name, 0) + n
            res = self.solve(counts)
            cache[self.player] = res
        return res

    def check_reachable(self, state, rc_name: str) -> bool:
        return rc_name in self.result_for(state).checks

    def region_reachable(self, state, rr_name: str) -> bool:
        return rr_name in self.result_for(state).regions

    def event_reachable(self, state, re_name: str) -> bool:
        return self.result_for(state).events.get(re_name, 0) > 0
