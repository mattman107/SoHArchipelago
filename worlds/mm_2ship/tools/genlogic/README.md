# genlogic — the mm_2ship data/logic generation pipeline

This apworld is **data-driven**: its locations, items, options, region graph
and access-rule logic are all generated from the 2ship2harkinian randomizer's
own sources. After changing the built-in rando (new checks, new items, logic
edits, new regions, condition tweaks), regenerate the apworld with one command:

```
python worlds/mm_2ship/tools/genlogic/generate.py /path/to/2ship2harkinian
```

Run it from the Archipelago repo root. With no argument it looks for a
`2ship2harkinian` checkout next to the Archipelago repo.

Then run the world's tests to confirm everything still holds together:

```
python -m unittest discover -s worlds/mm_2ship/test -t .
```

## What gets generated (never edit these by hand)

| File | Source of truth | Contents |
|---|---|---|
| `Enums.py` | `Rando/Types.h`, `StaticData/Items.cpp` | `Regions`/`Locations`/`Items` string enums |
| `LocationData.py` | `StaticData/Checks.cpp`, `PlacementConstraints.cpp` | RCTYPE / scene / dungeon per check |
| `VanillaItems.py` | `StaticData/Checks.cpp` | vanilla item per check |
| `ItemData.py` | `StaticData/Items.cpp` + computed | AP item ids, names, RITYPE, progression flag |
| `OptionData.py` | `StaticData/Options.cpp` | `RO_*` → (AP option attr, default) |
| `LogicHelpersGen.py` | `Logic/Logic.h`, `GiveItem.cpp`, `Souls.cpp`, ... | constants, helper predicates, `CanKillEnemy`, item/flag grant maps |
| `RegionData.py` | `Logic/Regions/*.cpp`, `Logic/Logic.cpp` | the full region graph with translated access rules |

Everything else in the apworld is hand-written and consumes the generated
modules (most importantly `LogicRuntime.py`, the reachability solver).

## How logic translation works

Region files use a strict macro DSL (`CHECK`/`CONNECTION`/`EXIT`/`EVENT`/`STAY`
with boolean condition expressions). The generator:

1. parses every condition into an expression AST (`cpp.py`),
2. translates it to a Python lambda over a `LogicContext` (`translate.py`) —
   `HAS_ITEM(ITEM_BOW)` → `s.has_item('ITEM_BOW')`, `RANDO_EVENTS[RE_X]` →
   `s.event('RE_X')`, etc.,
3. auto-generates helper functions from `Logic.h` macro bodies (`CAN_BE_DEKU`,
   `IS_DAY1`, `MIDNIGHT`, `ClockFilter`, ...) and from the `CanKillEnemy` /
   `canPlaySong` switch statements,
4. resolves exits to their target regions the same way
   `GetRegionIdFromEntrance` does (unclaimed entrances route to `RR_MAX`).

**Unknown constructs fail loudly.** If upstream adds a new primitive (a new
function call or macro shape the translator doesn't know), generation stops
and lists every offending condition. Teach the translator about it in
`translate.py` (usually one line in `PRIMITIVE_CALLS`) and implement the
matching method on `LogicRuntime.LogicContext` if it needs runtime state.

New *expression-shaped* macros and `inline bool` helpers written as
`if (cond) return true; ... return expr;` chains translate automatically —
no Python changes needed.

## What is hand-ported (and how drift is caught)

`LogicRuntime.py` ports the C++ *algorithms* (not data):

- `Solver.solve()` ← `GlitchlessLogic.cpp` reachability fixpoint (regions ×
  time masks × event counters, plus vanilla self-grants for option-disabled
  checks) and `Logic.cpp FindReachableRegions`
- `expand_time_forward` / `owned_time_slices` ← `TimeLogic.cpp`
- `owns_half_day` ← `Logic.h OwnsHalfDayForMode`
- `can_access_dungeon` ← `Logic.h CanAccessDungeon`
- starting items ← `StartingItems.cpp GetComputedStartingItems`
- pool composition ← `GeneratePools.cpp` (in `ItemPool.py`)
- own-dungeon placement ← `PlacementConstraints.cpp` (in `PlacementConstraints.py`)

The generator hashes those C++ sources into `drift_hashes.json`. When any of
them changes upstream, regeneration exits with code 2 and lists exactly which
hand-ported pieces need review. After updating the Python ports (or confirming
no change is needed), re-run with `--accept-drift` to record the new baseline.

## Wire-contract invariants (do not break)

- **Location ids are C++ enum ordinals.** The game client does
  `RANDO_SAVE_CHECKS[<ap location id>]`, so the `Locations` enum must mirror
  `RandoCheckId` order exactly. The generator guarantees this — which also
  means ids shift when upstream inserts checks mid-enum. Game build and
  apworld must always be built from the same 2ship commit.
- **Item names must match `Items.cpp` exactly.** The client resolves received
  items by display name. Item *ids* are permanent: the generator re-reads
  `ItemData.py` and only ever appends (seeded originally from the hand-written
  `Items.py` table). Duplicate display names collapse to the canonical entry
  (`Piece of the Triforce` → `RI_TRIFORCE_PIECE`, mirroring the client).
- **Progression classification is computed.** An item is progression when the
  translated logic can test something it grants (inventory item, flag, quest
  item, event-adjacent family, ...). Overrides live in `Items.py`.

## Typical workflow after a rando change

```
# 1. hack on the 2ship rando (add checks, tweak logic, ...)
# 2. regenerate the apworld
python worlds/mm_2ship/tools/genlogic/generate.py ~/Developer/2ship2harkinian
# 3. review the diff (generated files are deterministic, diffs are readable)
git -C . diff --stat worlds/mm_2ship
# 4. run the tests
python -m unittest discover -s worlds/mm_2ship/test -t .
```

If step 2 prints translation errors: the message names the exact region,
check and C++ condition. If it exits with the drift warning: review the listed
hand-ported files, then `--accept-drift`.
