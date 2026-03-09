"""
genlogic — data-driven APWorld generation pipeline for 2 Ship 2 Harkinian (MM).

Parses the 2ship2harkinian randomizer sources (StaticData tables, Types.h enums,
Logic.h macros, Logic/Regions/*.cpp region graph) and regenerates the mm_2ship
apworld's data modules, including fully translated access-rule logic.

Entry point: python -m worlds.mm_2ship.tools.genlogic /path/to/2ship2harkinian
         or: python worlds/mm_2ship/tools/genlogic/generate.py /path/to/2ship2harkinian
"""
