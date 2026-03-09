"""
Orchestrator: parse the 2ship2harkinian rando sources and regenerate the
mm_2ship apworld data modules.

Usage:
    python worlds/mm_2ship/tools/genlogic/generate.py [/path/to/2ship2harkinian]
                                                      [--accept-drift]

Exit codes:
    0 - regenerated cleanly
    1 - hard errors (untranslatable logic, dangling references, ...)
    2 - regenerated, but hand-ported C++ drifted (see drift report)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # allow direct execution

from genlogic import cpp, emit, regions as regions_mod, translate  # noqa: E402

APWORLD_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

@dataclass
class Sources:
    root: Path
    types_h: str
    checks_cpp: str
    items_cpp: str
    options_cpp: str
    static_data_h: str
    logic_h: str
    logic_cpp_path: Path
    regions_dir: Path
    souls_cpp: str
    give_item_cpp: str
    placement_cpp: str
    z64item_h: str
    z64save_h: str
    z64scene_h: str
    z64player_h: str
    z64ocarina_h: str

    @classmethod
    def load(cls, root: Path) -> "Sources":
        mm = root / "mm"
        rando = mm / "2s2h" / "Rando"

        def rd(p: Path) -> str:
            if not p.exists():
                sys.exit(f"ERROR: expected source file missing: {p}")
            return cpp.load_source(p)

        return cls(
            root=root,
            types_h=rd(rando / "Types.h"),
            checks_cpp=rd(rando / "StaticData" / "Checks.cpp"),
            items_cpp=rd(rando / "StaticData" / "Items.cpp"),
            options_cpp=rd(rando / "StaticData" / "Options.cpp"),
            static_data_h=rd(rando / "StaticData" / "StaticData.h"),
            logic_h=rd(rando / "Logic" / "Logic.h"),
            logic_cpp_path=rando / "Logic" / "Logic.cpp",
            regions_dir=rando / "Logic" / "Regions",
            souls_cpp=rd(rando / "ActorBehavior" / "Souls.cpp"),
            give_item_cpp=rd(rando / "GiveItem.cpp"),
            placement_cpp=rd(rando / "Logic" / "PlacementConstraints.cpp"),
            z64item_h=rd(mm / "include" / "z64item.h"),
            z64save_h=rd(mm / "include" / "z64save.h"),
            z64scene_h=rd(mm / "include" / "z64scene.h"),
            z64player_h=rd(mm / "include" / "z64player.h"),
            z64ocarina_h=rd(mm / "include" / "z64ocarina.h"),
        )


# ---------------------------------------------------------------------------
# Display names
# ---------------------------------------------------------------------------

# Words kept lowercase in display names when not the first word.
# Derived from the existing hand-checked Enums.py contents; "near"/"or" are
# intentionally capitalized to match the shipped datapackage names.
SMALL_WORDS = {"and", "in", "of", "on", "the", "to", "with"}


def display_name(enum_key: str) -> str:
    words = enum_key.lower().split("_")
    out = []
    for i, w in enumerate(words):
        out.append(w if (i > 0 and w in SMALL_WORDS) else w.capitalize())
    return " ".join(out)


# ---------------------------------------------------------------------------
# GiveItem.cpp flag extraction
# ---------------------------------------------------------------------------

def parse_give_item_flags(give_item_cpp: str) -> tuple[dict[str, list[str]], dict[str, list[str]],
                                                       dict[str, list[str]], dict[str, list[str]]]:
    """Extract RANDO_INF flags, WEEKEVENTREG flags, skulltula-token scenes and
    owl warps set per item.

    Returns (rando_inf_grants, weekeventreg_grants, token_scene_grants, owl_grants):
        flag/reg/scene name -> [RI_* item ids that set it]
    Only simple `Flags_SetRandoInf(IDENT)` / `SET_WEEKEVENTREG(IDENT)` /
    `Flags_SetWeekEventReg(IDENT)` calls are captured; arithmetic flag
    expressions (ocarina buttons, clocks, souls) are parallel enum ranges
    handled by add_range_grants().
    """
    body = cpp.extract_function_body(give_item_cpp, r"\bGiveItem\s*\(\s*RandoItemId\s+randoItemId\s*\)\s*")
    cases = cpp.parse_switch_cases(body)
    rando_inf: dict[str, list[str]] = {}
    weekevent: dict[str, list[str]] = {}
    token_scenes: dict[str, list[str]] = {}
    owl_grants: dict[str, list[str]] = {}
    for case in cases:
        ris = [l for l in case.labels if l.startswith("RI_")]
        if not ris:
            continue
        for m in re.finditer(r"Flags_SetRandoInf\(\s*(RANDO_INF_\w+)\s*\)", case.body):
            for ri in ris:
                rando_inf.setdefault(m.group(1), []).append(ri)
        for m in re.finditer(r"(?:SET_WEEKEVENTREG|Flags_SetWeekEventReg)\(\s*(WEEKEVENTREG_\w+)\s*\)", case.body):
            for ri in ris:
                weekevent.setdefault(m.group(1), []).append(ri)
        for m in re.finditer(r"Inventory_IncrementSkullTokenCount\(\s*(SCENE_\w+)\s*\)", case.body):
            for ri in ris:
                token_scenes.setdefault(m.group(1), []).append(ri)
        for m in re.finditer(r"Sram_ActivateOwl\(\s*(OWL_WARP_\w+)\s*\)", case.body):
            for ri in ris:
                owl_grants.setdefault(m.group(1), []).append(ri)
    return rando_inf, weekevent, token_scenes, owl_grants


def add_range_grants(enums: dict[str, list[tuple[str, int]]],
                     rando_inf_grants: dict[str, list[str]]) -> None:
    """The C++ sets several flag families via parallel-enum arithmetic:

        SOUL_RI_TO_RANDO_INF:  (ri - RI_SOUL_BOSS_GOHT) + RANDO_INF_OBTAINED_SOUL_OF_BOSS_GOHT
        ocarina buttons:       RANDO_INF_OBTAINED_OCARINA_BUTTON_A + (ri - RI_OCARINA_BUTTON_A)
        clocks:                RANDO_INF_OBTAINED_CLOCK_DAY_1 + (ri - RI_TIME_DAY_1)

    Mirror those by pairing the enum ranges positionally."""
    ri_members = enums["RandoItemId"]
    inf_members = enums["RandoInf"]

    def span(members: list[tuple[str, int]], start: str, end: str) -> list[str]:
        names = [n for n, _ in members]
        try:
            i, j = names.index(start), names.index(end)
        except ValueError:
            sys.exit(f"ERROR: enum range {start}..{end} not found")
        if j < i:
            sys.exit(f"ERROR: enum range {start}..{end} reversed")
        return names[i:j + 1]

    pairs = [
        (span(ri_members, "RI_SOUL_BOSS_GOHT", "RI_SOUL_ENEMY_WOLFOS"),
         span(inf_members, "RANDO_INF_OBTAINED_SOUL_OF_BOSS_GOHT", "RANDO_INF_OBTAINED_SOUL_OF_ENEMY_WOLFOS")),
        (span(ri_members, "RI_OCARINA_BUTTON_A", "RI_OCARINA_BUTTON_C_UP"),
         span(inf_members, "RANDO_INF_OBTAINED_OCARINA_BUTTON_A", "RANDO_INF_OBTAINED_OCARINA_BUTTON_C_UP")),
        (span(ri_members, "RI_TIME_DAY_1", "RI_TIME_NIGHT_3"),
         span(inf_members, "RANDO_INF_OBTAINED_CLOCK_DAY_1", "RANDO_INF_OBTAINED_CLOCK_NIGHT_3")),
    ]
    for ris, infs in pairs:
        if len(ris) != len(infs):
            sys.exit(f"ERROR: parallel enum ranges out of sync: {ris[0]}({len(ris)}) vs {infs[0]}({len(infs)})")
        for ri, inf in zip(ris, infs):
            rando_inf_grants.setdefault(inf, []).append(ri)


def parse_half_day_ranges(logic_h: str) -> list[tuple[int, int]]:
    m = re.search(r"HALF_DAY_TIME_RANGES\[6\]\s*=\s*\{(.*?)\};", logic_h, re.S)
    if not m:
        sys.exit("ERROR: HALF_DAY_TIME_RANGES not found in Logic.h")
    ranges = re.findall(r"\{\s*(\d+)\s*,\s*(\d+)\s*\}", m.group(1))
    if len(ranges) != 6:
        sys.exit(f"ERROR: expected 6 half-day ranges, got {len(ranges)}")
    return [(int(a), int(b)) for a, b in ranges]


def compute_quest_item_grants(enums: dict[str, list[tuple[str, int]]],
                              items: dict[str, dict]) -> dict[str, list[str]]:
    """QUEST_* -> [RI_* granting it], mirroring Item_Give's parallel-range
    arithmetic (ITEM_SONG_SONATA..<->QUEST_SONG_SONATA.., remains likewise).
    Robust against name divergence like QUEST_SONG_BOSSA_NOVA <-> ITEM_SONG_NOVA."""
    def enum_with(member: str) -> dict[str, int]:
        for members in enums.values():
            d = dict(members)
            if member in d:
                return d
        sys.exit(f"ERROR: no parsed enum contains {member}")

    quest_enum = enum_with("QUEST_SONG_SONATA")
    item_enum = enum_with("ITEM_SONG_SONATA")
    item_by_value = {v: n for n, v in item_enum.items()}

    anchors = [
        ("QUEST_SONG_", "QUEST_SONG_SONATA", "ITEM_SONG_SONATA"),
        ("QUEST_REMAINS_", "QUEST_REMAINS_ODOLWA", "ITEM_REMAINS_ODOLWA"),
    ]
    quest_to_item: dict[str, str] = {}
    for prefix, q_anchor, i_anchor in anchors:
        if q_anchor not in quest_enum or i_anchor not in item_enum:
            sys.exit(f"ERROR: anchor {q_anchor}/{i_anchor} missing from enums")
        base_q, base_i = quest_enum[q_anchor], item_enum[i_anchor]
        for q_name, q_val in quest_enum.items():
            if q_name.startswith(prefix):
                item_name = item_by_value.get(base_i + (q_val - base_q))
                if item_name:
                    quest_to_item[q_name] = item_name

    # reverse index: ITEM_X -> RIs granting it
    grants_by_item: dict[str, list[str]] = {}
    for ri, meta in items.items():
        grants_by_item.setdefault(meta["item_id"], []).append(ri)

    return {quest: grants_by_item[item_name]
            for quest, item_name in quest_to_item.items()
            if item_name in grants_by_item}


def compute_quest_to_ocarina(enums: dict[str, list[tuple[str, int]]]) -> dict[str, str]:
    """Mirror CAN_PLAY_SONG's index arithmetic:
        ocarina = (QUEST_SONG_x - QUEST_SONG_SONATA) + OCARINA_SONG_SONATA
    """
    quest = {n: v for members in enums.values() for n, v in members if n.startswith("QUEST_SONG_")}
    ocarina = {v: n for members in enums.values() for n, v in members if n.startswith("OCARINA_SONG_")}
    if "QUEST_SONG_SONATA" not in quest:
        sys.exit("ERROR: QUEST_SONG_SONATA not found in parsed enums")
    base_q = quest["QUEST_SONG_SONATA"]
    base_o_name = "OCARINA_SONG_SONATA"
    base_o = next((v for v, n in ocarina.items() if n == base_o_name), None)
    if base_o is None:
        sys.exit("ERROR: OCARINA_SONG_SONATA not found in parsed enums")
    out: dict[str, str] = {}
    for q_name, q_val in quest.items():
        o_val = (q_val - base_q) + base_o
        if o_val in ocarina:
            out[q_name] = ocarina[o_val]
    return out


def parse_soul_map(souls_cpp: str) -> dict[str, str]:
    """enemySoulMap: ACTOR_* -> RI_SOUL_* pairs."""
    m = re.search(r"enemySoulMap\s*=\s*\{(.*?)\};", souls_cpp, re.S)
    if not m:
        sys.exit("ERROR: enemySoulMap not found in Souls.cpp")
    return dict(re.findall(r"\{\s*(ACTOR_\w+)\s*,\s*(RI_\w+)\s*\}", m.group(1)))


def parse_scene_to_dungeon(placement_cpp: str) -> dict[str, str]:
    """SceneIdToDungeon(): SCENE_* -> DUNGEON_SCENE_INDEX_*."""
    body = cpp.extract_function_body(placement_cpp, r"int\s+SceneIdToDungeon\s*\(")
    out: dict[str, str] = {}
    pending: list[str] = []
    for line in body.splitlines():
        line = line.strip()
        cm = re.match(r"^case\s+(SCENE_\w+)\s*:$", line)
        if cm:
            pending.append(cm.group(1))
            continue
        rm = re.match(r"^return\s+(DUNGEON_SCENE_INDEX_\w+)\s*;$", line)
        if rm:
            for s in pending:
                out[s] = rm.group(1)
            pending = []
    return out


def parse_item_to_dungeon(placement_cpp: str) -> dict[str, str]:
    """RandoItemIdToDungeon(): RI_* -> DUNGEON_SCENE_INDEX_* (unconditional part)."""
    body = cpp.extract_function_body(placement_cpp, r"int\s+RandoItemIdToDungeon\s*\(")
    out: dict[str, str] = {}
    pending: list[str] = []
    for line in body.splitlines():
        line = line.strip()
        cm = re.match(r"^case\s+(RI_\w+)\s*:$", line)
        if cm:
            pending.append(cm.group(1))
            continue
        am = re.match(r"^dungeon\s*=\s*(DUNGEON_SCENE_INDEX_\w+)\s*;$", line)
        if am:
            for ri in pending:
                out[ri] = am.group(1)
            pending = []
    return out


# ---------------------------------------------------------------------------
# canPlaySong switch -> note requirements
# ---------------------------------------------------------------------------

def parse_song_note_reqs(logic_h: str) -> dict[str, tuple[str, object]]:
    """OCARINA_SONG_* -> ("all", [RANDO_INF flags]) or ("count", n) or ("free", None)."""
    body = cpp.extract_function_body(logic_h, r"inline\s+bool\s+canPlaySong\s*\(")
    cases = cpp.parse_switch_cases(body)
    reqs: dict[str, tuple[str, object]] = {}
    for case in cases:
        expr = cpp.case_body_to_return_expr(case.body)
        if expr is None:
            sys.exit(f"ERROR: canPlaySong case too complex: {case.labels}: {case.body[:80]!r}")
        flags = re.findall(r"Flags_GetRandoInf\(\s*(RANDO_INF_\w+)\s*\)", expr)
        count_m = re.search(r"FoundOcarinaButtons\(\)\s*>=\s*(\d+)", expr)
        if count_m:
            val: tuple[str, object] = ("count", int(count_m.group(1)))
        elif flags:
            val = ("all", flags)
        elif expr.strip() == "true":
            val = ("free", None)
        else:
            sys.exit(f"ERROR: canPlaySong case not understood: {case.labels}: {expr!r}")
        for label in case.labels:
            if label != "default":
                reqs[label] = val
    return reqs


# ---------------------------------------------------------------------------
# CanKillEnemy switch -> per-actor conditions
# ---------------------------------------------------------------------------

def parse_can_kill_enemy(logic_h: str) -> dict[str, str]:
    """ACTOR_* -> raw C++ condition text."""
    body = cpp.extract_function_body(logic_h, r"inline\s+bool\s+CanKillEnemy\s*\(")
    cases = cpp.parse_switch_cases(body)
    out: dict[str, str] = {}
    for case in cases:
        expr = cpp.case_body_to_return_expr(case.body)
        if expr is None:
            if "default" in case.labels:
                continue  # assert(false) fallback
            sys.exit(f"ERROR: CanKillEnemy case too complex: {case.labels}: {case.body[:80]!r}")
        for label in case.labels:
            if label != "default":
                out[label] = expr
    return out


# ---------------------------------------------------------------------------
# Drift ledger for hand-ported C++
# ---------------------------------------------------------------------------

DRIFT_TARGETS = [
    # (key, path-relative-to-2ship-root, extraction)
    ("GeneratePools.cpp",        "mm/2s2h/Rando/Logic/GeneratePools.cpp", None),
    ("StartingItems.cpp",        "mm/2s2h/Rando/StartingItems.cpp", None),
    ("ConvertItem.cpp",          "mm/2s2h/Rando/ConvertItem.cpp", None),
    ("PlacementConstraints.cpp", "mm/2s2h/Rando/Logic/PlacementConstraints.cpp", None),
    ("TimeLogic.cpp",            "mm/2s2h/Rando/Logic/TimeLogic.cpp", None),
    ("Logic.cpp",                "mm/2s2h/Rando/Logic/Logic.cpp", None),
    ("GlitchlessLogic.cpp",      "mm/2s2h/Rando/Logic/GlitchlessLogic.cpp", None),
    ("Logic.h:CanAccessDungeon", "mm/2s2h/Rando/Logic/Logic.h", r"inline\s+bool\s+CanAccessDungeon\s*\("),
    ("Logic.h:MeetsMoonRequirements", "mm/2s2h/Rando/Logic/Logic.h", r"inline\s+bool\s+MeetsMoonRequirements\s*\("),
    ("Logic.h:OwnsHalfDayForMode", "mm/2s2h/Rando/Logic/Logic.h", r"inline\s+bool\s+OwnsHalfDayForMode\s*\("),
    ("Archipelago.cpp",          "mm/2s2h/Network/Archipelago/Archipelago.cpp", None),
]


def compute_drift(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for key, rel, extract_re in DRIFT_TARGETS:
        p = root / rel
        if not p.exists():
            hashes[key] = "MISSING"
            continue
        text = cpp.load_source(p)
        if extract_re:
            try:
                text = cpp.extract_function_body(text, extract_re)
            except ValueError:
                hashes[key] = "FUNCTION-MISSING"
                continue
        normalized = re.sub(r"\s+", " ", text).strip()
        hashes[key] = hashlib.sha256(normalized.encode()).hexdigest()[:16]
    return hashes


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("ship_root", nargs="?", default=None,
                    help="Path to the 2ship2harkinian checkout (default: sibling of the Archipelago repo)")
    ap.add_argument("--accept-drift", action="store_true",
                    help="Record current hashes of hand-ported C++ sources as the new baseline")
    args = ap.parse_args()

    if args.ship_root:
        root = Path(args.ship_root).resolve()
    else:
        root = APWORLD_ROOT.parents[1].parent / "2ship2harkinian"
    if not (root / "mm" / "2s2h" / "Rando").is_dir():
        sys.exit(f"ERROR: {root} does not look like a 2ship2harkinian checkout")

    print(f"[genlogic] reading 2ship sources from {root}")
    src = Sources.load(root)

    # ---- enums ------------------------------------------------------------
    enums: dict[str, list[tuple[str, int]]] = {}
    for text in (src.types_h, src.logic_h, src.z64item_h, src.z64save_h,
                 src.z64scene_h, src.z64player_h, src.z64ocarina_h):
        for name, members in cpp.parse_enums(text).items():
            enums.setdefault(name, members if members else enums.get(name, []))

    # Global constant table (last-wins is fine; names are unique in practice).
    # Includes plain integer #defines (e.g. STRAY_FAIRY_SCATTERED_TOTAL) so
    # option defaults expressed via macros resolve correctly.
    # Headers Options.cpp includes may define option-default constants
    # (e.g. SPIDER_HOUSE_TOKENS_REQUIRED in the En_Sth actor header).
    extra_texts: list[str] = []
    for inc in re.findall(r'#include\s+"([^"]+)"', (root / "mm" / "2s2h" / "Rando" /
                                                    "StaticData" / "Options.cpp").read_text()):
        for base in (root / "mm" / "src", root / "mm" / "include", root / "mm" / "2s2h"):
            p = base / inc
            if p.exists():
                extra_texts.append(cpp.load_source(p))
                break

    const_values: dict[str, int] = {}
    for text in (src.types_h, src.logic_h, src.static_data_h, src.z64item_h,
                 src.z64save_h, src.z64scene_h, src.z64player_h, src.z64ocarina_h,
                 *extra_texts):
        for name, macro in cpp.parse_defines(text).items():
            body = macro.body.strip().strip("()")
            if macro.params is None and re.match(r"^\d+$", body):
                const_values[name] = int(body)
            elif macro.params is None and re.match(r"^0[xX][0-9a-fA-F]+$", body):
                const_values[name] = int(body, 16)
    for members in enums.values():
        for name, value in members:
            const_values[name] = value

    def enum_names(enum: str, strip_unknown_max: bool = True) -> list[str]:
        if enum not in enums or not enums[enum]:
            sys.exit(f"ERROR: enum {enum} not found/parsed")
        names = [n for n, _ in enums[enum]]
        if strip_unknown_max:
            names = [n for n in names if not n.endswith("_MAX") and not n.endswith("_UNKNOWN")]
        return names

    rc_order = enum_names("RandoCheckId")
    # RI_ARCHIPELAGO_* are client-side placeholders for other players' items —
    # they are never real AP items and must not enter the datapackage.
    ri_order = [ri for ri in enum_names("RandoItemId") if not ri.startswith("RI_ARCHIPELAGO_")]
    rr_order = enum_names("RandoRegionId")
    re_order = enum_names("RandoEvent")

    # ---- static tables ------------------------------------------------------
    checks_rows = cpp.extract_macro_rows(src.checks_cpp, "RC")
    checks: dict[str, dict] = {}
    for row in checks_rows:
        if len(row) != 6:
            sys.exit(f"ERROR: RC row with {len(row)} args: {row}")
        rc, rctype, scene, flag_type, flag, vanilla = row
        checks[rc] = {"rctype": rctype, "scene": scene, "flag_type": flag_type,
                      "flag": flag, "vanilla": vanilla}
    print(f"[genlogic] parsed {len(checks)} checks")

    items_rows = cpp.extract_macro_rows(src.items_cpp, "RI")
    items: dict[str, dict] = {}
    for row in items_rows:
        if len(row) != 7:
            sys.exit(f"ERROR: RI row with {len(row)} args: {row}")
        ri, article, name, ritype, item_id, get_item_id, draw_id = row
        nm = re.match(r'^"(.*)"$', name.strip(), re.S)
        am = re.match(r'^"(.*)"$', article.strip(), re.S)
        items[ri] = {"name": nm.group(1) if nm else name.strip(),
                     "article": am.group(1) if am else "",
                     "ritype": ritype, "item_id": item_id}
    print(f"[genlogic] parsed {len(items)} items")

    def resolve_constant(token: str) -> int | None:
        token = token.strip()
        if re.match(r"^\d+$", token):
            return int(token)
        if token in const_values:
            return const_values[token]
        # Last resort: the constant lives in some header we didn't parse
        # (e.g. SPIDER_HOUSE_TOKENS_REQUIRED, two include-hops deep).
        import subprocess
        out = subprocess.run(
            ["grep", "-rhoE", f"#define[[:space:]]+{token}[[:space:]]+[0-9]+", str(root / "mm")],
            capture_output=True, text=True,
        ).stdout
        m = re.search(rf"#define\s+{token}\s+(\d+)", out)
        if m:
            const_values[token] = int(m.group(1))
            return int(m.group(1))
        return None

    options_rows = cpp.extract_macro_rows(src.options_cpp, "RO")
    options: dict[str, dict] = {}
    for row in options_rows:
        if len(row) != 3:
            sys.exit(f"ERROR: RO row with {len(row)} args: {row}")
        ro, default, ap_name = row
        nm = re.match(r'^"(.*)"$', ap_name.strip())
        default_val = resolve_constant(default)
        if default_val is None:
            print(f"[genlogic] WARNING: cannot resolve default {default!r} for {ro}; using 0")
            default_val = 0
        options[ro] = {"ap_name": nm.group(1) if nm else ap_name.strip(), "default": default_val}
    print(f"[genlogic] parsed {len(options)} options")

    # ---- structural maps -----------------------------------------------------
    soul_map = parse_soul_map(src.souls_cpp)
    rando_inf_grants, weekevent_grants, token_scene_grants, owl_grants = parse_give_item_flags(src.give_item_cpp)
    add_range_grants(enums, rando_inf_grants)
    scene_to_dungeon = parse_scene_to_dungeon(src.placement_cpp)
    item_to_dungeon = parse_item_to_dungeon(src.placement_cpp)
    song_note_reqs = parse_song_note_reqs(src.logic_h)
    can_kill_raw = parse_can_kill_enemy(src.logic_h)
    half_day_ranges = parse_half_day_ranges(src.logic_h)
    quest_to_ocarina = compute_quest_to_ocarina(enums)
    quest_item_grants = compute_quest_item_grants(enums, items)

    # ITEM_X -> RIs granting it (Items.cpp itemId column), with ammo-pack
    # normalization for inventory slots that exist independently of a bag
    # (getting any bombchu pack sets INV_CONTENT(ITEM_BOMBCHU), etc.).
    pack_normalize = {
        "ITEM_BOMBCHUS_1": "ITEM_BOMBCHU", "ITEM_BOMBCHUS_5": "ITEM_BOMBCHU",
        "ITEM_BOMBCHUS_10": "ITEM_BOMBCHU", "ITEM_BOMBCHUS_20": "ITEM_BOMBCHU",
        "ITEM_DEKU_STICKS_5": "ITEM_DEKU_STICK", "ITEM_DEKU_STICKS_10": "ITEM_DEKU_STICK",
        "ITEM_DEKU_NUTS_5": "ITEM_DEKU_NUT", "ITEM_DEKU_NUTS_10": "ITEM_DEKU_NUT",
    }
    item_grants: dict[str, list[str]] = {}
    for ri in ri_order:
        if ri not in items:
            continue
        iid = pack_normalize.get(items[ri]["item_id"], items[ri]["item_id"])
        if iid != "ITEM_NONE":
            item_grants.setdefault(iid, []).append(ri)

    # sanity: structural GiveItem cases the runtime handles by hand
    for needed in ("RI_SKELETON_KEY", "RI_TIME_PROGRESSIVE"):
        if needed not in src.give_item_cpp:
            print(f"[genlogic] WARNING: GiveItem.cpp no longer mentions {needed}; "
                  f"review LogicRuntime's structural handling.")

    # ---- region graph ----------------------------------------------------------
    region_files = regions_mod.parse_all_region_files(src.regions_dir, [src.logic_cpp_path])
    all_regions: dict[str, regions_mod.RegionDef] = {}
    local_macros: dict[str, cpp.MacroDef] = {}
    local_functions: dict[str, str] = {}
    for rf in region_files:
        for name, macro in rf.local_macros.items():
            if name in local_macros and local_macros[name].body != macro.body:
                sys.exit(f"ERROR: conflicting local macro {name} across region files")
            local_macros[name] = macro
        for name, expr in rf.local_functions.items():
            if name in local_functions and local_functions[name] != expr:
                sys.exit(f"ERROR: conflicting local function {name} across region files")
            local_functions[name] = expr
        for rd in rf.regions:
            if rd.region_id in all_regions:
                sys.exit(f"ERROR: region {rd.region_id} defined twice")
            all_regions[rd.region_id] = rd
    print(f"[genlogic] parsed {len(all_regions)} regions from {len(region_files)} files")

    missing_regions = [r for r in all_regions if r not in set(rr_order) | {"RR_MAX"}]
    if missing_regions:
        sys.exit(f"ERROR: regions not in RandoRegionId enum: {missing_regions}")

    # entrance -> owning region (mirrors GetRegionIdFromEntrance's static map)
    entrance_owner: dict[tuple[str, int], str] = {}
    for rd in all_regions.values():
        for ex in rd.exits:
            if ex.return_entrance is not None:
                entrance_owner[ex.return_entrance.key()] = rd.region_id
        for ent in rd.one_way_entrances:
            entrance_owner[ent.key()] = rd.region_id

    # ---- translation -------------------------------------------------------------
    logic_macros = cpp.parse_defines(src.logic_h)
    # Structural/non-condition macros must not be treated as helpers.
    for structural in ("EVENT", "EXIT", "CONNECTION", "CHECK", "STAY", "ONE_WAY_EXIT",
                       "SET_OWL_WARP", "CLEAR_OWL_WARP", "RANDO_LOGIC_H"):
        logic_macros.pop(structural, None)

    helper_macros = dict(logic_macros)
    for name, macro in local_macros.items():
        if name in helper_macros:
            sys.exit(f"ERROR: local macro {name} shadows a Logic.h macro")
        helper_macros[name] = macro

    # Harvest Logic.h zero-arg inline bool functions whose bodies are pure
    # if/return chains (ClockFilter, SettingClocks, MeetsMoonRequirements, ...)
    # so they auto-translate instead of needing runtime primitives. Functions
    # that don't fit (switches, loops) stay primitives in translate.py.
    for m in re.finditer(r"inline\s+bool\s+(\w+)\s*\(\s*\)\s*\{", src.logic_h):
        name = m.group(1)
        if name in translate.PRIMITIVE_CALLS or name in translate.PRIMITIVE_CALLS_0:
            continue
        end = cpp.find_balanced(src.logic_h, m.end() - 1)
        expr = cpp.translate_if_return_chain(src.logic_h[m.end():end - 1])
        if expr is not None and name not in local_functions:
            local_functions[name] = expr

    tr = translate.Translator(helper_macros=helper_macros, local_functions=local_functions)

    translated: dict[str, dict] = {}
    for rid in sorted(all_regions):
        rd = all_regions[rid]
        t = {
            "display": rd.display_name,
            "scene": rd.scene_id,
            "can_stay": rd.can_stay_over_time,
            "checks": [(rc, tr.translate_condition(cond, f"{rid}.checks[{rc}]"), cond)
                       for rc, cond in rd.checks],
            "connections": [(target, tr.translate_condition(cond, f"{rid}->{target}"), cond)
                            for target, cond in rd.connections],
            "events": [(ev, tr.translate_condition(cond, f"{rid}.events[{ev}]"), cond)
                       for ev, cond in rd.events],
            "stays": [(slice_name, tr.translate_condition(cond, f"{rid}.stay[{slice_name}]"), cond)
                      for slice_name, cond in rd.stays],
            "one_way_entrances": [e.key() for e in rd.one_way_entrances],
            "exits": [],
        }
        for ex in rd.exits:
            target = entrance_owner.get(ex.to.key())
            if target is None:
                # Mirrors GetRegionIdFromEntrance(): unclaimed entrances resolve to
                # RR_MAX (the start region), i.e. the exit grants nothing new.
                print(f"[genlogic] note: {rid} exit to ENTRANCE{ex.to.key()} has no owning "
                      f"region; routing to RR_MAX like the C++ solver")
                target = "RR_MAX"
            t["exits"].append((target, ex.to.key(),
                               tr.translate_condition(ex.condition, f"{rid}=>ENT{ex.to.key()}"),
                               ex.condition))
        translated[rid] = t

    # CanKillEnemy bodies
    can_kill: dict[str, str] = {}
    for actor in sorted(can_kill_raw):
        can_kill[actor] = tr.translate_condition(can_kill_raw[actor], f"CanKillEnemy[{actor}]")

    # Helpers the LogicRuntime needs even when no region rule references them
    # directly (the AT/BEFORE/AFTER/BETWEEN primitives wrap ClockFilter).
    tr.translate_condition("ClockFilter()", "runtime-required")
    if "ClockFilter" not in tr.needed_helpers:
        tr.errors.append("ClockFilter did not auto-translate from Logic.h — "
                         "LogicRuntime.time_at/between depend on it")

    # every actor the logic tries to kill must have a CanKillEnemy case
    killed_actors = {u for u in tr.used_names if u.startswith("ACTOR_")}
    missing_actors = sorted(killed_actors - set(can_kill))
    if missing_actors:
        tr.errors.append(f"CanKillEnemy has no case for referenced actors: {missing_actors}")

    # referenced constants must have known values when they aren't stringly args
    missing_consts = sorted(c for c in tr.needed_constants if c not in const_values)
    if missing_consts:
        tr.errors.append(f"constants with unknown values: {missing_consts}")

    if tr.errors:
        print(f"\n[genlogic] {len(tr.errors)} TRANSLATION ERRORS:")
        for err in tr.errors:
            print("   -", err)
        sys.exit(1)

    print(f"[genlogic] translated all conditions "
          f"({sum(len(t['checks']) for t in translated.values())} checks, "
          f"{sum(len(t['connections']) + len(t['exits']) for t in translated.values())} edges, "
          f"{len(tr.needed_helpers)} generated helpers)")

    # ---- consistency checks -------------------------------------------------------
    # Every check in the region graph must exist in Checks.cpp; report checks
    # never placed in any region (they'd be unreachable).
    placed_checks: set[str] = set()
    for t in translated.values():
        placed_checks.update(rc for rc, _, _ in t["checks"])
    unknown_checks = sorted(placed_checks - set(checks))
    if unknown_checks:
        sys.exit(f"ERROR: region graph references unknown checks: {unknown_checks[:10]}")
    unplaced = sorted(set(checks) - placed_checks - {"RC_UNKNOWN", "RC_MAX"})
    if unplaced:
        print(f"[genlogic] WARNING: {len(unplaced)} checks exist in Checks.cpp but are in no region "
              f"(first few: {unplaced[:6]}) — they will be UNREACHABLE if enabled")

    # options used via s.opt() must exist in Options.cpp
    used_ro_ids = {u for u in tr.used_names if u.startswith("RO_")}
    unknown_ros = sorted(used_ro_ids - set(options))
    if unknown_ros:
        sys.exit(f"ERROR: logic reads options missing from Options.cpp: {unknown_ros}")

    # every C++ option should have an AP-side counterpart in Options.py;
    # the solver falls back to the C++ default when one is missing, so this
    # is a warning rather than an error.
    options_py = APWORLD_ROOT / "Options.py"
    if options_py.exists():
        options_py_text = options_py.read_text()
        missing_ap = sorted(
            f"{ro} ({meta['ap_name']})" for ro, meta in options.items()
            if f"{meta['ap_name']}:" not in options_py_text
        )
        if missing_ap:
            print(f"[genlogic] WARNING: {len(missing_ap)} option(s) in Options.cpp have no "
                  f"attribute in the AP Options.py dataclass (solver will use C++ defaults):")
            for entry in missing_ap:
                print(f"   - {entry}")

    # ---- auto-classification --------------------------------------------------------
    progression_items = compute_progression(
        usages=tr.used_names, items=items, item_grants=item_grants,
        quest_item_grants=quest_item_grants,
        rando_inf_grants=rando_inf_grants, weekevent_grants=weekevent_grants,
        soul_map=soul_map, item_to_dungeon=item_to_dungeon,
        song_note_reqs=song_note_reqs, enums=enums,
    )

    # ---- id registry ------------------------------------------------------------------
    canonical_ris = emit.canonical_ri_list_for(
        [ri for ri in ri_order if ri in items], {ri: items[ri]["name"] for ri in items})
    item_ids = load_item_id_registry(canonical_ris)

    # ---- emit ---------------------------------------------------------------------------
    ctx = emit.EmitContext(
        apworld_root=APWORLD_ROOT,
        rc_order=[rc for rc in rc_order if rc in checks],
        ri_order=[ri for ri in ri_order if ri in items],
        rr_order=rr_order,
        re_order=re_order,
        checks=checks,
        items=items,
        options=options,
        translated_regions=translated,
        helpers=tr.needed_helpers,
        constants={c: const_values[c] for c in sorted(tr.needed_constants)},
        can_kill=can_kill,
        soul_map=soul_map,
        rando_inf_grants=rando_inf_grants,
        weekevent_grants=weekevent_grants,
        scene_to_dungeon=scene_to_dungeon,
        item_to_dungeon=item_to_dungeon,
        song_note_reqs=song_note_reqs,
        progression_items=progression_items,
        item_ids=item_ids,
        display_name=display_name,
        enums=enums,
        token_scene_grants=token_scene_grants,
        owl_grants=owl_grants,
        item_grants=item_grants,
        half_day_ranges=half_day_ranges,
        quest_to_ocarina=quest_to_ocarina,
        quest_item_grants=quest_item_grants,
    )
    emit.emit_all(ctx)

    # ---- drift ledger -------------------------------------------------------------------
    ledger_path = Path(__file__).with_name("drift_hashes.json")
    current = compute_drift(root)
    drifted: list[str] = []
    if ledger_path.exists():
        baseline = json.loads(ledger_path.read_text())
        drifted = [k for k, v in current.items() if baseline.get(k) != v]
    if args.accept_drift or not ledger_path.exists():
        ledger_path.write_text(json.dumps(current, indent=2) + "\n")
        print(f"[genlogic] drift baseline written to {ledger_path.name}")
        drifted = []
    if drifted:
        print("\n[genlogic] DRIFT WARNING — hand-ported C++ changed upstream; review the Python ports:")
        for k in drifted:
            print(f"   - {k}")
        print("   After reviewing/updating the ports, re-run with --accept-drift.")
        sys.exit(2)

    print("[genlogic] done.")


# ---------------------------------------------------------------------------
# Progression classification
# ---------------------------------------------------------------------------

def compute_progression(*, usages: set[str], items: dict[str, dict],
                        item_grants: dict[str, list[str]],
                        quest_item_grants: dict[str, list[str]],
                        rando_inf_grants: dict[str, list[str]],
                        weekevent_grants: dict[str, list[str]],
                        soul_map: dict[str, str],
                        item_to_dungeon: dict[str, str],
                        song_note_reqs: dict[str, tuple[str, object]],
                        enums: dict[str, list[tuple[str, int]]]) -> set[str]:
    """Compute the set of RI_* ids whose items can gate logic.

    An item is progression when anything the logic can test is granted by it:
    vanilla inventory items (via HAS_ITEM et al.), rando-inf flags, week event
    regs, quest items, dungeon items/keys/fairies/tokens, songs+buttons+ocarina,
    wallets, swords/shields, magic, health, bottles, moon masks, remains,
    clocks, owls, souls, triforce pieces, skeleton key.
    """
    prog: set[str] = set()

    used_item_consts = {u for u in usages if u.startswith("ITEM_")}
    for item_const in used_item_consts:
        prog.update(item_grants.get(item_const, []))

    used_flags = {u for u in usages if u.startswith("RANDO_INF_")}
    # ocarina-note flags are used implicitly via can_play_song / can_play_notes
    for _, req in song_note_reqs.items():
        if req[0] == "all":
            used_flags.update(req[1])
    for flag in used_flags:
        prog.update(rando_inf_grants.get(flag, []))

    for reg in {u for u in usages if u.startswith("WEEKEVENTREG_")}:
        prog.update(weekevent_grants.get(reg, []))

    # quest items (songs, remains) — via the Item_Give parallel-range mapping
    for quest in {u for u in usages if u.startswith("QUEST_")}:
        prog.update(quest_item_grants.get(quest, []))

    # structural families (always potentially logic-relevant)
    families = {
        "swords":   [ri for ri in items if "SWORD" in ri],
        "shields":  [ri for ri in items if "SHIELD" in ri],
        "wallets":  [ri for ri in items if "WALLET" in ri],
        "magic":    [ri for ri in items if "MAGIC" in ri and items[ri]["ritype"] != "RITYPE_JUNK"],
        "health":   ["RI_HEART_PIECE", "RI_HEART_CONTAINER"],
        "keys":     list(item_to_dungeon.keys()) + ["RI_SKELETON_KEY"],
        "souls":    sorted(set(soul_map.values())),
        "ocarina":  [ri for ri in items if ri.startswith("RI_OCARINA")],
        "clocks":   [ri for ri in items if ri.startswith("RI_TIME_")],
        "bottles":  [ri for ri in items if ri.startswith("RI_BOTTLE_")],
        "owls":     [ri for ri in items if ri.startswith("RI_OWL_")],
        "tokens":   [ri for ri in items if ri.startswith("RI_GS_TOKEN")],
        "triforce": [ri for ri in items if "TRIFORCE" in ri],
        "boss_souls": [ri for ri in items if ri.startswith("RI_SOUL_BOSS")],
        "progressive": [ri for ri in items if ri.startswith("RI_PROGRESSIVE_")],
        "songs":    [ri for ri in items if ri.startswith("RI_SONG_")],
    }
    for fam in families.values():
        prog.update(ri for ri in fam if ri in items)

    # moon masks: ITEM enum range MASK_TRUTH..MASK_GIANT
    item_enum = {n: v for n, v in enums.get("ItemId", [])}
    lo, hi = item_enum.get("ITEM_MASK_TRUTH"), item_enum.get("ITEM_MASK_GIANT")
    if lo is not None and hi is not None:
        for ri, meta in items.items():
            v = item_enum.get(meta["item_id"])
            if v is not None and lo <= v <= hi:
                prog.add(ri)

    prog.discard("RI_UNKNOWN")
    return prog


# ---------------------------------------------------------------------------
# Item id registry
# ---------------------------------------------------------------------------

def load_item_id_registry(canonical_ris: list[str]) -> dict[str, int]:
    """AP item ids keyed by RI enum key (minus prefix). Ids must never change
    once assigned. Previous output (ItemData.py) is the registry; on first run,
    seed from the hand-written Items.py table. Only canonical (datapackage)
    items receive ids."""
    registry: dict[str, int] = {}

    itemdata_py = APWORLD_ROOT / "ItemData.py"
    items_py_path = APWORLD_ROOT / "Items.py"
    if itemdata_py.exists():
        for m in re.finditer(r'^\s*"(\w+)":\s*ItemEntry\((\d+),', itemdata_py.read_text(), re.M):
            registry[m.group(1)] = int(m.group(2))
    elif items_py_path.exists():
        for m in re.finditer(r"Items\.(\w+):\s*MM2ShipItemData\((\d+)", items_py_path.read_text()):
            registry[m.group(1)] = int(m.group(2))

    next_id = max(registry.values(), default=0) + 1
    for ri in canonical_ris:
        key = ri[3:]  # strip RI_
        if key not in registry:
            registry[key] = next_id
            print(f"[genlogic] new item id assigned: {key} = {next_id}")
            next_id += 1
    return registry


if __name__ == "__main__":
    main()
