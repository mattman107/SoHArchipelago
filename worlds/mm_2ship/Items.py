from __future__ import annotations

from typing import NamedTuple

from BaseClasses import Item, ItemClassification as IC

from .Enums import Items
from .ItemData import ITEMS


class MM2ShipItem(Item):
    game = "2 Ship 2 Harkinian (MM)"


class MM2ShipItemData(NamedTuple):
    # None means it's just here for the data, and won't be added to the datapackage
    item_id: int | None
    classification: IC = IC.progression


# Classification overrides for items whose generated data can't fully decide.
_CLASSIFICATION_OVERRIDES: dict[str, IC] = {
    "TRAP": IC.trap,
}


def _classify(key: str, entry) -> IC:
    override = _CLASSIFICATION_OVERRIDES.get(key)
    if override is not None:
        return override
    if entry.progression:
        # Logic-relevant consumables/health (bombchu packs, deku sticks, heart
        # pieces, ...) shouldn't participate in progression balancing.
        if entry.ritype in ("RITYPE_JUNK", "RITYPE_HEALTH"):
            return IC.progression_skip_balancing
        return IC.progression
    if entry.ritype in ("RITYPE_JUNK", "RITYPE_HEALTH"):
        return IC.filler
    return IC.useful


# item_data_table keyed by the Items enum, mirroring the generated ItemData
# (ids are permanent; names match StaticData/Items.cpp so the game client can
# resolve items by name).
item_data_table: dict[Items, MM2ShipItemData] = {}
for _key, _entry in ITEMS.items():
    _member = Items[_key]
    item_data_table[_member] = MM2ShipItemData(_entry.ap_id, _classify(_key, _entry))

# Event items (not sent over the network)
item_data_table[Items.VICTORY] = MM2ShipItemData(None, IC.progression)

item_table: dict[str, int] = {
    member.value: data.item_id for member, data in item_data_table.items() if data.item_id is not None
}

item_name_groups: dict[str, set[str]] = {}
for _key, _entry in ITEMS.items():
    _groups = []
    if _entry.ritype == "RITYPE_MASK":
        _groups.append("Masks")
    if _key.startswith("SOUL_ENEMY"):
        _groups.append("Enemy Souls")
    if _key.startswith("SOUL_BOSS"):
        _groups.append("Boss Souls")
    if _key.startswith("SONG_") or _key == "PROGRESSIVE_LULLABY":
        _groups.append("Songs")
    if _entry.ritype == "RITYPE_SMALL_KEY" or _entry.ritype == "RITYPE_BOSS_KEY":
        _groups.append("Keys")
    if _entry.ritype == "RITYPE_STRAY_FAIRY":
        _groups.append("Stray Fairies")
    if _key.startswith("TIME_"):
        _groups.append("Clocks")
    for _g in _groups:
        item_name_groups.setdefault(_g, set()).add(_entry.name)
