#!/usr/bin/env python3
"""Regenerate the RLS-derived logic for the oot_soh world into rls_data/.

Builds the RandoLogicScript compiler from the logic/ submodule and transpiles logic/src/*.rls into Python.

Usage: python3 worlds/oot_soh/tools/gen_logic.py
"""
import os
import pathlib
import shutil
import subprocess
import sys
import multiprocessing

WORLD = pathlib.Path(__file__).resolve().parent.parent
LOGIC = WORLD / "logic"
COMPILER = LOGIC / "RandoLogicScript"
BUILD = COMPILER / "build"
OUT = WORLD / "rls_data"


def run(*cmd: object, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def git(*args: str, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(COMPILER), *args], text=True, **kw)


def main() -> int:
    if not (LOGIC / "rls.json").exists():
        print("error: logic submodule not checked out. Run: git submodule update --init --recursive", file=sys.stderr)
        return 1

    print("==> Building RandoLogicScript")
    run("cmake", "-S", COMPILER, "-B", BUILD, "-G", "Ninja", stdout=subprocess.DEVNULL)
    run("cmake", "--build", BUILD, "--target", "RandoLogicScript", "-j", multiprocessing.cpu_count())

    # The transpiler stamps this into the generated-file headers.
    rev = git("rev-parse", "--short", "HEAD", capture_output=True, check=True).stdout.strip()
    if git("diff", "--quiet", "HEAD").returncode != 0:
        rev += "-dirty"

    OUT.mkdir(exist_ok=True)
    (OUT / "__init__.py").touch()

    print(f"==> Transpiling logic -> {OUT}")
    run(BUILD / "console" / "RandoLogicScript", "-p", LOGIC / "rls.json", "-t", "soh_ap", "-o", OUT,
        env={**os.environ, "RLS_REVISION": rev})

    print("==> Syncing runtime support modules")
    for name in ("rls_match.py", "rls_conditional.py"):
        shutil.copyfile(COMPILER / "transpilers" / "soh_ap" / "src" / name, OUT / name)

    print("==> Done. Generated: rls_data/{enums,functions,regions}_gen.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
