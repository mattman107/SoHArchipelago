"""
Parser for mm/2s2h/Rando/Logic/Regions/*.cpp region definition files.

Each file registers entries of the form:

    Regions[RR_X] = RandoRegion{ .name = "...", .sceneId = SCENE_X,
        .checks = { CHECK(RC_A, <cond>), ... },
        .exits = { EXIT(ENTRANCE(A, n), ENTRANCE(B, m) | ONE_WAY_EXIT, <cond>), ... },
        .connections = { CONNECTION(RR_Y, <cond>), ... },
        .events = { EVENT(RE_Z, <cond>), ... },
        .oneWayEntrances = { ENTRANCE(C, k), ... },
        .timeStayRestrictions = { STAY(TIME_T, <cond>), ... },
        .canStayOverTime = <bool>,
    };

Files may also carry local `#define` helper macros and small
`inline bool Helper() { if (...) return true; ...; return <expr>; }` functions,
both of which are captured for the condition translator.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .cpp import (
    MacroDef,
    extract_macro_rows,
    find_balanced,
    load_source,
    parse_defines,
    split_args,
    translate_if_return_chain,
)


@dataclass
class Entrance:
    scene: str      # e.g. "WOODFALL_TEMPLE" (the ENTRANCE() first arg)
    spawn: int

    def key(self) -> tuple[str, int]:
        return (self.scene, self.spawn)


@dataclass
class RegionExit:
    to: Entrance                    # destination entrance (used to resolve target region)
    return_entrance: Entrance | None  # entrance back into this region; None = ONE_WAY_EXIT
    condition: str                  # raw C++ condition text


@dataclass
class RegionDef:
    region_id: str                  # RR_* name (without prefix stripping)
    source_file: str
    display_name: str = ""          # .name (room label, informational only)
    scene_id: str = ""              # SCENE_*
    checks: list[tuple[str, str]] = field(default_factory=list)        # (RC_*, cond)
    connections: list[tuple[str, str]] = field(default_factory=list)   # (RR_*, cond)
    exits: list[RegionExit] = field(default_factory=list)
    events: list[tuple[str, str]] = field(default_factory=list)        # (RE_*, cond)
    one_way_entrances: list[Entrance] = field(default_factory=list)
    stays: list[tuple[str, str]] = field(default_factory=list)         # (TIME_*, cond)
    can_stay_over_time: bool = True


@dataclass
class RegionFile:
    path: Path
    regions: list[RegionDef]
    local_macros: dict[str, MacroDef]
    local_functions: dict[str, str]  # name -> boolean expression (C++ text)


def _parse_entrance(text: str) -> Entrance | None:
    text = text.strip()
    if text == "ONE_WAY_EXIT":
        return None
    m = re.match(r"^ENTRANCE\(\s*(\w+)\s*,\s*(\d+)\s*\)$", text)
    if not m:
        raise ValueError(f"cannot parse entrance: {text!r}")
    return Entrance(m.group(1), int(m.group(2)))


def _split_designated_fields(body: str) -> dict[str, str]:
    """Split a RandoRegion{...} body into {field_name: raw_value_text} by
    scanning for `.field =` at brace depth 0."""
    fields: dict[str, str] = {}
    # positions of top-level `.name =` markers
    markers: list[tuple[int, str]] = []
    depth = 0
    i, n = 0, len(body)
    while i < n:
        c = body[i]
        if c == '"':
            i += 1
            while i < n and body[i] != '"':
                if body[i] == "\\":
                    i += 1
                i += 1
        elif c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        elif c == "." and depth == 0:
            m = re.match(r"\.(\w+)\s*=", body[i:])
            if m:
                markers.append((i, m.group(1)))
                i += m.end() - 1
        i += 1
    for idx, (pos, name) in enumerate(markers):
        end = markers[idx + 1][0] if idx + 1 < len(markers) else n
        value = body[pos:end]
        value = value[value.index("=") + 1:].strip().rstrip(",").strip()
        fields[name] = value
    return fields


def parse_region_file(path: Path) -> RegionFile:
    text = load_source(path)
    local_macros = parse_defines(text)

    # local inline bool helpers
    local_functions: dict[str, str] = {}
    for m in re.finditer(r"inline\s+bool\s+(\w+)\s*\(\s*\)\s*\{", text):
        name = m.group(1)
        end = find_balanced(text, m.end() - 1)
        body = text[m.end():end - 1]
        expr = translate_if_return_chain(body)
        if expr is None:
            raise ValueError(
                f"{path.name}: local helper {name}() is too complex for automatic "
                f"translation. Either simplify it to `if (cond) return true;` chains "
                f"or add a hand-written implementation (see HANDWRITTEN_HELPERS)."
            )
        local_functions[name] = expr

    regions: list[RegionDef] = []
    for m in re.finditer(r"Regions\[\s*(RR_\w+)\s*\]\s*=\s*RandoRegion\s*\{", text):
        region_id = m.group(1)
        end = find_balanced(text, m.end() - 1)
        body = text[m.end():end - 1]
        fields = _split_designated_fields(body)

        rd = RegionDef(region_id=region_id, source_file=path.name)

        if "name" in fields:
            nm = re.match(r'^"(.*)"$', fields["name"].strip(), re.S)
            rd.display_name = nm.group(1) if nm else fields["name"].strip()
        if "sceneId" in fields:
            rd.scene_id = fields["sceneId"].strip()
        if "canStayOverTime" in fields:
            rd.can_stay_over_time = fields["canStayOverTime"].strip() == "true"

        if "checks" in fields:
            for row in extract_macro_rows(fields["checks"], "CHECK"):
                if len(row) != 2:
                    raise ValueError(f"{path.name} {region_id}: bad CHECK row: {row}")
                rd.checks.append((row[0], row[1]))

        if "connections" in fields:
            for row in extract_macro_rows(fields["connections"], "CONNECTION"):
                if len(row) != 2:
                    raise ValueError(f"{path.name} {region_id}: bad CONNECTION row: {row}")
                rd.connections.append((row[0], row[1]))

        if "events" in fields:
            for row in extract_macro_rows(fields["events"], "EVENT"):
                if len(row) != 2:
                    raise ValueError(f"{path.name} {region_id}: bad EVENT row: {row}")
                rd.events.append((row[0], row[1]))

        if "exits" in fields:
            for row in extract_macro_rows(fields["exits"], "EXIT"):
                if len(row) != 3:
                    raise ValueError(f"{path.name} {region_id}: bad EXIT row: {row}")
                to = _parse_entrance(row[0])
                if to is None:
                    raise ValueError(f"{path.name} {region_id}: EXIT 'to' cannot be ONE_WAY_EXIT")
                rd.exits.append(RegionExit(to=to, return_entrance=_parse_entrance(row[1]), condition=row[2]))

        if "oneWayEntrances" in fields:
            # brace list of ENTRANCE(...) entries
            inner = fields["oneWayEntrances"].strip()
            if inner.startswith("{"):
                inner = inner[1:inner.rindex("}")]
            for part in split_args(inner):
                if not part.strip():
                    continue
                ent = _parse_entrance(part)
                if ent is None:
                    raise ValueError(f"{path.name} {region_id}: bad oneWayEntrance {part!r}")
                rd.one_way_entrances.append(ent)

        if "timeStayRestrictions" in fields:
            for row in extract_macro_rows(fields["timeStayRestrictions"], "STAY"):
                if len(row) != 2:
                    raise ValueError(f"{path.name} {region_id}: bad STAY row: {row}")
                rd.stays.append((row[0], row[1]))

        unknown = set(fields) - {
            "name", "sceneId", "canStayOverTime", "checks", "connections",
            "events", "exits", "oneWayEntrances", "timeStayRestrictions", "timeSlices",
        }
        if unknown:
            raise ValueError(
                f"{path.name} {region_id}: unhandled RandoRegion fields {sorted(unknown)} — "
                f"the generator needs to be taught about them."
            )

        regions.append(rd)

    return RegionFile(path=path, regions=regions, local_macros=local_macros, local_functions=local_functions)


def parse_all_region_files(regions_dir: Path, extra_files: list[Path] = ()) -> list[RegionFile]:
    files = sorted(regions_dir.glob("*.cpp")) + list(extra_files)
    return [parse_region_file(p) for p in files]
