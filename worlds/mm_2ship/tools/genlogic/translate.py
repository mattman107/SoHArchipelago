"""
C++ condition AST -> Python source translator.

Every condition in the region DSL is translated into a Python expression over:
  - `s`, a LogicContext instance (see mm_2ship/LogicRuntime.py) exposing the
    hand-written primitive vocabulary (s.has_item, s.event, s.opt, ...), and
  - generated helper functions (CAN_BE_DEKU(s), CanKillEnemy(s, actor), ...)
    emitted into LogicHelpersGen.py from the Logic.h macro bodies.

The translator only knows the explicit vocabulary below. Anything else is
reported as an error, so new upstream constructs surface immediately instead
of being silently mistranslated.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .cpp import ExprError, MacroDef, parse_expr


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------
# Function-like macros / functions mapped straight onto LogicContext primitives.
# Value = (python_attr, arg_specs) where each arg spec is:
#   "name"          -> identifier argument becomes a string literal
#   "name:PREFIX_"  -> same, but usage tracking records PREFIX_<arg> (the fully
#                      qualified constant the C++ macro token-pastes)
#   "expr"          -> argument is translated recursively
PRIMITIVE_CALLS: dict[str, tuple[str, tuple[str, ...]]] = {
    "HAS_ITEM":                    ("s.has_item", ("name",)),
    "CAN_PLAY_SONG":               ("s.can_play_song", ("name:QUEST_SONG_",)),
    "CAN_USE_MAGIC_ARROW":         ("s.can_use_magic_arrow", ("name:ITEM_ARROW_",)),
    "KEY_COUNT":                   ("s.key_count", ("name:DUNGEON_SCENE_INDEX_",)),
    "CAN_ACCESS":                  ("s.can_access", ("name:RE_ACCESS_",)),
    "CAN_USE_ABILITY":             ("s.ability", ("name:RANDO_INF_OBTAINED_",)),
    "CHECK_DUNGEON_ITEM":          ("s.dungeon_item", ("name", "name")),
    "CHECK_QUEST_ITEM":            ("s.quest_item", ("name",)),
    "CHECK_WEEKEVENTREG":          ("s.weekeventreg", ("name",)),
    "Flags_GetRandoInf":           ("s.rando_inf", ("name",)),
    "HAS_BOTTLE_ITEM":             ("s.bottle_item", ("name",)),
    "CHECK_MAX_HP":                ("s.max_hp", ("expr",)),
    "CAN_AFFORD":                  ("s.can_afford", ("name",)),
    "HAS_ENOUGH_STRAY_FAIRIES":    ("s.enough_stray_fairies", ("name",)),
    "HAS_ENOUGH_SKULLTULA_TOKENS": ("s.enough_skull_tokens", ("name",)),
    "CAN_OWL_WARP":                ("s.owl_warp", ("name",)),
    "HaveEnemySoul":               ("s.have_enemy_soul", ("name",)),
    "canPlaySong":                 ("s.can_play_notes", ("name",)),
    "GET_CUR_EQUIP_VALUE":         ("s.equip_value", ("name",)),
    "CUR_UPG_VALUE":               ("s.upg_value", ("name",)),
    "GET_CUR_UPG_VALUE":           ("s.upg_value", ("name",)),
    "CanAccessDungeon":            ("s.can_access_dungeon", ("name",)),
    "Inventory_HasItemInBottle":   ("s.bottle_item", ("name",)),
    "OwnsHalfDayForMode":          ("s.owns_half_day", ("expr",)),
    "OwnsClockHalfDay":            ("s.owns_clock_half_day", ("expr",)),
    "IsTimeSliceOwned":            ("s.is_time_slice_owned", ("expr",)),
    # time operators
    "AT":                          ("s.time_at", ("expr",)),
    "BEFORE":                      ("s.time_before", ("expr",)),
    "AFTER":                       ("s.time_after", ("expr",)),
    "BETWEEN":                     ("s.time_between", ("expr", "expr")),
    "RawAt":                       ("s.raw_at", ("expr",)),
    "RawBefore":                   ("s.raw_before", ("expr",)),
    "RawAfter":                    ("s.raw_after", ("expr",)),
    "RawBetween":                  ("s.raw_between", ("expr", "expr")),
}

# Zero-arg calls mapped onto LogicContext primitives. Everything expressible
# as a pure macro/early-return function (IS_DAY1, MIDNIGHT, ClockFilter,
# SettingClocks, ...) is auto-translated from its C++ body instead of being
# listed here — only loop/switch-shaped functions need a runtime primitive.
PRIMITIVE_CALLS_0: dict[str, str] = {
    "MoonMaskCount":          "s.moon_mask_count()",
    "RemainsCount":           "s.remains_count()",
    "FoundOcarinaButtons":    "s.found_ocarina_buttons()",
    "ClockCount":             "s.clock_count()",
    "GET_PLAYER_FORM":        "s.player_form()",
}

# Indexed globals.
PRIMITIVE_INDEXES: dict[str, tuple[str, str]] = {
    "RANDO_EVENTS":       ("s.event", "name"),
    "RANDO_SAVE_OPTIONS": ("s.opt", "name"),
}

# Object-like macros that are runtime primitives rather than generated helpers.
PRIMITIVE_IDENTS: dict[str, str] = {
    "HAS_MAGIC":  "s.has_magic()",
    "HAS_BOTTLE": "s.has_bottle()",
    "IS_DEKU":    "s.is_form('DEKU')",
    "IS_ZORA":    "s.is_form('ZORA')",
    "IS_DEITY":   "s.is_form('DEITY')",
    "IS_GORON":   "s.is_form('GORON')",
    "IS_HUMAN":   "s.is_form('HUMAN')",
}

# Identifier prefixes treated as symbolic integer constants. Their values are
# emitted into LogicHelpersGen.py from the parsed enums; the translator just
# needs to know they're legal as constant expressions.
CONSTANT_PREFIXES = (
    "TIME_",            # TimeSlice
    "RO_",              # option value enums (RO_GENERIC_YES, RO_ACCESS_TRIALS_...)
    "EQUIP_VALUE_",
    "PLAYER_FORM_",
    "OCARINA_SONG_",
    "QUEST_",
    "DUNGEON_",         # DUNGEON_BOSS_KEY etc. (z64item.h)
    "OWL_WARP_",
    "SCENE_",
    "ITEM_",            # only in constant positions (rare); items normally via HAS_ITEM
    "ACTOR_",
    "WEEKEVENTREG_",
    "RANDO_INF_",
    "RI_",
    "RC_",
    "RE_",
    "RR_",
)


class TranslateError(ValueError):
    pass


@dataclass
class Translator:
    """Translates parsed condition ASTs to Python expressions.

    `helper_macros` holds object-like (or zero-arg function-like) macros whose
    bodies get translated into generated helper functions; referencing one
    emits `NAME(s)` and registers the helper for emission.
    `local_functions` are pre-flattened inline bool helpers (C++ expr text).
    """
    helper_macros: dict[str, MacroDef]
    local_functions: dict[str, str] = field(default_factory=dict)
    needed_helpers: dict[str, str] = field(default_factory=dict)   # name -> python body expr
    needed_constants: set[str] = field(default_factory=set)
    used_names: set[str] = field(default_factory=set)              # identifier args passed as strings
    errors: list[str] = field(default_factory=list)
    _in_progress: set[str] = field(default_factory=set)

    # -- public API ---------------------------------------------------------

    def translate_condition(self, cpp_text: str, where: str) -> str:
        """C++ condition text -> Python expression string (over `s`)."""
        try:
            ast = parse_expr(cpp_text)
        except ExprError as e:
            self.errors.append(f"{where}: parse error: {e} in: {cpp_text!r}")
            return "False"
        try:
            return self.emit(ast)
        except TranslateError as e:
            self.errors.append(f"{where}: {e} in: {cpp_text!r}")
            return "False"

    # -- helper generation ---------------------------------------------------

    def _ensure_helper(self, name: str) -> None:
        if name in self.needed_helpers or name in self._in_progress:
            return
        self._in_progress.add(name)
        try:
            if name in self.local_functions:
                body_src = self.local_functions[name]
            else:
                macro = self.helper_macros[name]
                if macro.params:
                    raise TranslateError(
                        f"macro {name} has parameters and no primitive mapping — "
                        f"add it to PRIMITIVE_CALLS or expand support"
                    )
                body_src = macro.body
            ast = parse_expr(body_src)
            self.needed_helpers[name] = self.emit(ast)
        except (ExprError, TranslateError, KeyError) as e:
            raise TranslateError(f"while generating helper {name}: {e}")
        finally:
            self._in_progress.discard(name)

    # -- AST emission ---------------------------------------------------------

    def emit(self, ast) -> str:
        kind = ast[0]
        if kind == "int":
            return str(ast[1])
        if kind == "bool":
            return "True" if ast[1] else "False"
        if kind == "not":
            return f"not {self._paren(ast[1])}"
        if kind == "and":
            return " and ".join(self._paren(a) for a in ast[1])
        if kind == "or":
            return " or ".join(self._paren(a) for a in ast[1])
        if kind == "cmp":
            _, op, lhs, rhs = ast
            return f"{self._paren(lhs)} {op} {self._paren(rhs)}"
        if kind == "arith":
            _, op, lhs, rhs = ast
            if op == "/":
                op = "//"
            return f"{self._paren(lhs)} {op} {self._paren(rhs)}"
        if kind == "index":
            _, base, idx = ast
            if base in PRIMITIVE_INDEXES:
                attr, argspec = PRIMITIVE_INDEXES[base]
                return f"{attr}({self._arg(idx, argspec)})"
            raise TranslateError(f"unknown indexed global {base}[...]")
        if kind == "call":
            return self._emit_call(ast[1], ast[2])
        if kind == "ident":
            return self._emit_ident(ast[1])
        raise TranslateError(f"unhandled AST node {kind}")

    def _paren(self, ast) -> str:
        src = self.emit(ast)
        if ast[0] in ("and", "or", "cmp", "not", "arith"):
            return f"({src})"
        return src

    def _arg(self, ast, spec: str) -> str:
        if spec.startswith("name"):
            if ast[0] != "ident":
                raise TranslateError(f"expected identifier argument, got {ast!r}")
            prefix = spec[5:] if spec.startswith("name:") else ""
            self.used_names.add(prefix + ast[1])
            return repr(ast[1])
        return self.emit(ast)

    def _emit_call(self, name: str, args: list) -> str:
        if name in PRIMITIVE_CALLS:
            attr, argspecs = PRIMITIVE_CALLS[name]
            if len(args) != len(argspecs):
                raise TranslateError(f"{name} expects {len(argspecs)} args, got {len(args)}")
            emitted = [self._arg(a, spec) for a, spec in zip(args, argspecs)]
            return f"{attr}({', '.join(emitted)})"
        if name in PRIMITIVE_CALLS_0:
            if args:
                raise TranslateError(f"{name} expects no args")
            return PRIMITIVE_CALLS_0[name]
        if name == "CanKillEnemy":
            if len(args) != 1 or args[0][0] != "ident":
                raise TranslateError("CanKillEnemy expects a single actor identifier")
            self.used_names.add(args[0][1])
            return f"CanKillEnemy(s, {args[0][1]!r})"
        if not args and (name in self.helper_macros or name in self.local_functions):
            # zero-arg function-like macro or local inline helper
            self._ensure_helper(name)
            return f"{name}(s)"
        raise TranslateError(f"unknown call {name}(...)")

    def _emit_ident(self, name: str) -> str:
        if name in PRIMITIVE_IDENTS:
            return PRIMITIVE_IDENTS[name]
        if name in self.helper_macros or name in self.local_functions:
            self._ensure_helper(name)
            return f"{name}(s)"
        if name.startswith(CONSTANT_PREFIXES):
            self.needed_constants.add(name)
            return name
        raise TranslateError(f"unknown identifier {name}")
