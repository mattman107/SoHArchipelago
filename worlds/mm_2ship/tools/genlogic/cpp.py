"""
Minimal C++ source tooling for the 2ship rando codebase.

This is NOT a general C++ parser. The rando sources follow strict, macro-driven
table/DSL conventions (clang-format enforced), which lets us get away with:
  - comment stripping,
  - typedef-enum extraction,
  - table-macro row extraction (RC(...), RI(...), RO(...)),
  - a small Pratt parser for the boolean condition expressions used by
    CHECK/CONNECTION/EXIT/EVENT/STAY and #define macro bodies,
  - switch-statement extraction for CanKillEnemy/canPlaySong-style functions.

Anything outside those shapes should fail loudly rather than guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Source loading
# ---------------------------------------------------------------------------

def strip_comments(text: str) -> str:
    """Remove // and /* */ comments while preserving string literals and newlines
    (newlines kept so diagnostics can report line numbers)."""
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == '"' or c == "'":
            quote = c
            out.append(c)
            i += 1
            while i < n:
                out.append(text[i])
                if text[i] == "\\":
                    if i + 1 < n:
                        out.append(text[i + 1])
                        i += 2
                        continue
                elif text[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            if j == -1:
                raise ValueError("unterminated block comment")
            # keep newlines for line numbering
            out.append("\n" * text.count("\n", i, j))
            i = j + 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def load_source(path: Path) -> str:
    return strip_comments(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Enum extraction
# ---------------------------------------------------------------------------

def parse_enums(text: str) -> dict[str, list[tuple[str, int]]]:
    """Extract every `typedef enum { ... } Name;` (and `enum Name { ... };`)
    block as an ordered list of (member, value). Handles explicit `= value`
    assignments with integer literals or previously-defined members."""
    enums: dict[str, list[tuple[str, int]]] = {}

    blocks = re.findall(r"typedef enum\s*(?:\w+\s*)?\{(.*?)\}\s*(\w+)\s*;", text, re.S)
    blocks += [(body, name) for name, body in re.findall(r"\benum\s+(\w+)\s*\{(.*?)\}\s*;", text, re.S)]

    for body, name in blocks:
        members: list[tuple[str, int]] = []
        known: dict[str, int] = {}
        next_val = 0
        for raw in body.split(","):
            entry = raw.strip()
            if not entry:
                continue
            m = re.match(r"^(\w+)\s*(?:=\s*(.+))?$", entry, re.S)
            if not m:
                continue
            member, val_expr = m.group(1), m.group(2)
            if val_expr is not None:
                val_expr = val_expr.strip()
                if re.match(r"^0[xX][0-9a-fA-F]+$", val_expr):
                    value = int(val_expr, 16)
                elif re.match(r"^-?\d+$", val_expr):
                    value = int(val_expr)
                elif val_expr in known:
                    value = known[val_expr]
                else:
                    m2 = re.match(r"^(\w+)\s*\+\s*(\d+)$", val_expr)
                    if m2 and m2.group(1) in known:
                        value = known[m2.group(1)] + int(m2.group(2))
                    else:
                        # Can't evaluate (macro/shift/etc.) — skip the rest of this
                        # enum's exact values; record what we have so far.
                        break
            else:
                value = next_val
            members.append((member, value))
            known[member] = value
            next_val = value + 1
        enums[name] = members
    return enums


# ---------------------------------------------------------------------------
# Table-macro row extraction: RC(...), RI(...), RO(...)
# ---------------------------------------------------------------------------

def split_args(argstr: str) -> list[str]:
    """Split a macro argument string on top-level commas."""
    args: list[str] = []
    depth = 0
    cur: list[str] = []
    i, n = 0, len(argstr)
    while i < n:
        c = argstr[i]
        if c == '"':
            cur.append(c)
            i += 1
            while i < n:
                cur.append(argstr[i])
                if argstr[i] == "\\":
                    i += 1
                    if i < n:
                        cur.append(argstr[i])
                elif argstr[i] == '"':
                    i += 1
                    break
                i += 1
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
        if c == "," and depth == 0:
            args.append("".join(cur).strip())
            cur = []
        else:
            cur.append(c)
        i += 1
    if cur and "".join(cur).strip():
        args.append("".join(cur).strip())
    return args


def extract_macro_rows(text: str, macro: str) -> list[list[str]]:
    """Find every `MACRO(arg, arg, ...)` invocation at statement level and
    return the split top-level args. Skips the `#define MACRO(...)` itself."""
    rows: list[list[str]] = []
    for m in re.finditer(rf"(?<![\w#]){macro}\(", text):
        # skip the definition site: preceded by '#define ' on the same line
        line_start = text.rfind("\n", 0, m.start()) + 1
        if text[line_start:m.start()].lstrip().startswith("#define"):
            continue
        start = m.end()
        depth = 1
        i = start
        while depth > 0:
            c = text[i]
            if c == '"':
                i += 1
                while text[i] != '"':
                    if text[i] == "\\":
                        i += 1
                    i += 1
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
            i += 1
        rows.append(split_args(text[start:i - 1]))
    return rows


# ---------------------------------------------------------------------------
# #define macro collection
# ---------------------------------------------------------------------------

@dataclass
class MacroDef:
    name: str
    params: list[str] | None  # None = object-like
    body: str


def parse_defines(text: str) -> dict[str, MacroDef]:
    """Collect #define macros (with line continuations)."""
    macros: dict[str, MacroDef] = {}
    # Rejoin continuation lines
    joined = re.sub(r"\\\s*\n", " ", text)
    for m in re.finditer(r"^[ \t]*#define[ \t]+(\w+)(\(([^)]*)\))?[ \t]*(.*)$", joined, re.M):
        name, has_params, params, body = m.group(1), m.group(2), m.group(3), m.group(4)
        body = body.strip()
        if not body:
            continue
        if has_params:
            plist = [p.strip() for p in params.split(",") if p.strip()]
            macros[name] = MacroDef(name, plist, body)
        else:
            macros[name] = MacroDef(name, None, body)
    return macros


# ---------------------------------------------------------------------------
# Expression AST + parser
# ---------------------------------------------------------------------------
# AST nodes are tuples:
#   ("int", value)
#   ("bool", True|False)
#   ("ident", name)
#   ("call", name, [args])           name has namespaces stripped
#   ("index", base_name, arg_ast)    e.g. RANDO_EVENTS[RE_X]
#   ("not", ast)
#   ("and", [asts]) / ("or", [asts])
#   ("cmp", op, lhs, rhs)            op in == != <= >= < >
#   ("arith", op, lhs, rhs)          op in + - * / %

TOKEN_RE = re.compile(r"""
    \s*(?:
      (?P<hex>0[xX][0-9a-fA-F]+)
    | (?P<int>\d+)
    | (?P<ident>[A-Za-z_]\w*)
    | (?P<ns>::)
    | (?P<op>&&|\|\||==|!=|<=|>=|->|[!<>()\[\],.+\-*/%&|])
    )""", re.X)


class ExprError(ValueError):
    pass


def tokenize(expr: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    i = 0
    while i < len(expr):
        m = TOKEN_RE.match(expr, i)
        if not m or m.end() == i:
            rest = expr[i:].strip()
            if not rest:
                break
            raise ExprError(f"cannot tokenize near: {rest[:40]!r}")
        i = m.end()
        for kind in ("hex", "int", "ident", "ns", "op"):
            v = m.group(kind)
            if v is not None:
                tokens.append((kind, v))
                break
    tokens.append(("end", ""))
    return tokens


class Parser:
    """Pratt parser for the C boolean/arithmetic expression subset."""

    def __init__(self, tokens: list[tuple[str, str]]):
        self.toks = tokens
        self.pos = 0

    def peek(self) -> tuple[str, str]:
        return self.toks[self.pos]

    def next(self) -> tuple[str, str]:
        t = self.toks[self.pos]
        self.pos += 1
        return t

    def expect(self, val: str) -> None:
        kind, v = self.next()
        if v != val:
            raise ExprError(f"expected {val!r}, got {v!r}")

    def parse(self):
        ast = self.parse_or()
        if self.peek()[0] != "end":
            raise ExprError(f"trailing tokens: {self.toks[self.pos:]}")
        return ast

    def parse_or(self):
        parts = [self.parse_and()]
        while self.peek()[1] == "||":
            self.next()
            parts.append(self.parse_and())
        return parts[0] if len(parts) == 1 else ("or", parts)

    def parse_and(self):
        parts = [self.parse_cmp()]
        while self.peek()[1] == "&&":
            self.next()
            parts.append(self.parse_cmp())
        return parts[0] if len(parts) == 1 else ("and", parts)

    def parse_cmp(self):
        lhs = self.parse_add()
        while self.peek()[1] in ("==", "!=", "<=", ">=", "<", ">"):
            op = self.next()[1]
            rhs = self.parse_add()
            lhs = ("cmp", op, lhs, rhs)
        return lhs

    def parse_add(self):
        lhs = self.parse_mul()
        while self.peek()[1] in ("+", "-"):
            op = self.next()[1]
            lhs = ("arith", op, lhs, self.parse_mul())
        return lhs

    def parse_mul(self):
        lhs = self.parse_unary()
        while self.peek()[1] in ("*", "/", "%"):
            op = self.next()[1]
            lhs = ("arith", op, lhs, self.parse_unary())
        return lhs

    def parse_unary(self):
        kind, v = self.peek()
        if v == "!":
            self.next()
            return ("not", self.parse_unary())
        if v == "-":
            self.next()
            inner = self.parse_unary()
            if inner[0] == "int":
                return ("int", -inner[1])
            return ("arith", "-", ("int", 0), inner)
        return self.parse_primary()

    def parse_primary(self):
        kind, v = self.next()
        if kind == "int":
            return ("int", int(v))
        if kind == "hex":
            return ("int", int(v, 16))
        if v == "(":
            inner = self.parse_or()
            self.expect(")")
            return inner
        if kind == "ident":
            name = v
            # swallow namespace qualifiers: Rando::Logic::foo -> foo
            while self.peek()[0] == "ns":
                self.next()
                kind2, v2 = self.next()
                if kind2 != "ident":
                    raise ExprError(f"bad namespace member after ::: {v2!r}")
                name = v2
            if name == "true":
                return ("bool", True)
            if name == "false":
                return ("bool", False)
            nxt = self.peek()[1]
            if nxt == "(":
                self.next()
                args = []
                if self.peek()[1] != ")":
                    while True:
                        args.append(self.parse_or())
                        if self.peek()[1] == ",":
                            self.next()
                            continue
                        break
                self.expect(")")
                return ("call", name, args)
            if nxt == "[":
                self.next()
                idx = self.parse_or()
                self.expect("]")
                return ("index", name, idx)
            if nxt in (".", "->"):
                raise ExprError(f"raw member access not supported in logic: {name}{nxt}...")
            return ("ident", name)
        raise ExprError(f"unexpected token {v!r}")


def parse_expr(expr: str):
    return Parser(tokenize(expr)).parse()


# ---------------------------------------------------------------------------
# Switch extraction (CanKillEnemy, canPlaySong, GiveItem)
# ---------------------------------------------------------------------------

@dataclass
class SwitchCase:
    labels: list[str]           # case labels (identifiers); "default" for default
    body: str                   # raw statement text up to break/return end
    field: str = ""


def find_balanced(text: str, open_pos: int, open_ch: str = "{", close_ch: str = "}") -> int:
    """Given index of an opening brace, return index just past its match."""
    depth = 0
    i = open_pos
    n = len(text)
    while i < n:
        c = text[i]
        if c == '"':
            i += 1
            while i < n and text[i] != '"':
                if text[i] == "\\":
                    i += 1
                i += 1
        elif c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise ValueError("unbalanced braces")


def extract_function_body(text: str, signature_re: str) -> str:
    """Return the raw body of the first function whose signature matches."""
    m = re.search(signature_re, text)
    if not m:
        raise ValueError(f"function not found: {signature_re}")
    brace = text.find("{", m.end() - 1)
    end = find_balanced(text, brace)
    return text[brace + 1:end - 1]


def parse_switch_cases(body: str, switch_var: str | None = None) -> list[SwitchCase]:
    """Parse the FIRST switch statement in `body` into grouped cases.
    Case bodies are raw text (caller interprets them)."""
    m = re.search(r"switch\s*\(", body)
    if not m:
        raise ValueError("no switch found")
    open_paren = m.end() - 1
    close_paren = find_balanced(body, open_paren, "(", ")")
    brace = body.find("{", close_paren)
    end = find_balanced(body, brace)
    inner = body[brace + 1:end - 1]

    cases: list[SwitchCase] = []
    # Split on case labels while keeping them
    parts = re.split(r"(?m)^\s*(case\s+[\w:]+\s*:|default\s*:)", inner)
    # parts[0] is preamble junk; then alternating label, chunk
    pending_labels: list[str] = []
    for i in range(1, len(parts), 2):
        label = parts[i].strip().rstrip(":").strip()
        chunk = parts[i + 1] if i + 1 < len(parts) else ""
        if label.startswith("case"):
            label_name = label[len("case"):].strip()
        else:
            label_name = "default"
        pending_labels.append(label_name)
        if chunk.strip():
            cases.append(SwitchCase(labels=pending_labels, body=chunk.strip()))
            pending_labels = []
    return cases


def case_body_to_return_expr(body: str) -> str | None:
    """For switch cases shaped `return <expr>;` return the expression text."""
    m = re.match(r"^return\s+(.*?);\s*$", body.strip(), re.S)
    if m:
        return m.group(1).strip()
    return None


# ---------------------------------------------------------------------------
# Simple statement translation: inline bool helpers written as
#   if (<expr>) { return true; }  ... return <expr>;
# become the OR of their guard expressions.
# ---------------------------------------------------------------------------

def translate_if_return_chain(body: str) -> str | None:
    """Translate a function body consisting only of `if (cond) return true;`
    blocks (braced or not) followed by a final `return expr;` into a single
    boolean expression string `(cond1) || (cond2) || ... || (expr)`.
    Returns None if the body doesn't fit that shape."""
    text = body.strip()
    parts: list[str] = []
    while text:
        m = re.match(r"^if\s*\(", text)
        if m:
            close = find_balanced(text, m.end() - 1, "(", ")")
            cond = text[m.end():close - 1].strip()
            rest = text[close:].lstrip()
            m2 = re.match(r"^\{\s*return\s+true\s*;\s*\}", rest, re.S)
            if m2 is None:
                m2 = re.match(r"^return\s+true\s*;", rest, re.S)
            if m2 is None:
                return None
            parts.append(f"({cond})")
            text = rest[m2.end():].strip()
            continue
        m = re.match(r"^return\s+(.*?);\s*$", text, re.S)
        if m:
            final = m.group(1).strip()
            if final == "false":
                pass  # contributes nothing to the OR
            elif final == "true":
                parts.append("true")
            else:
                parts.append(f"({final})")
            text = ""
            continue
        return None
    if not parts:
        return "false"
    return " || ".join(parts)
