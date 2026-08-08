import orjson
import pkgutil

from typing import Any, ClassVar

from BaseClasses import Item, Tutorial, ItemClassification
from rule_builder.cached_world import CachedRuleBuilderWorld
from rule_builder.rules import Has
from worlds.AutoWorld import WebWorld
from .Items import LighthouseItem, item_data_table, item_table, LighthouseItemData
from .Locations import location_table, LighthouseLocData, location_data_table
from .Options import LighthouseOptions, lighthouse_option_groups
from .Regions import create_regions_and_locations, place_locked_items
from .Enums import *
from .ItemPool import create_item_pool
from .UniversalTracker import setup_options_from_slot_data
from rule_builder.rules import Has, Rule

import logging
logger = logging.getLogger("LIGHTHOUSE")


class LighthouseWebWorld(WebWorld):
    theme = "ice"

    setup_en = Tutorial(
        tutorial_name="Start Guide",
        description="A guide to playing Banjo-Kazooie Lighthouse.",
        language="English",
        file_name="guide_en.md",
        link="guide/en",
        authors=["aMannus"]
    )

    tutorials = [setup_en]
    game_info_languages = ["en"]
    option_groups = lighthouse_option_groups


@staticmethod
def create_groups(obj: dict[Items, LighthouseItemData] | dict[str, LighthouseLocData]) -> dict[str, set[str]]:
    groups: dict[str, set[str]] = dict()
    for key, data in obj.items():
        if data.tags is None:
            continue
        for tag in data.tags:
            tag_name = tag.name.replace('_', ' ')
            if tag_name not in groups:
                groups[tag_name] = set()
            groups[tag_name].add(str(key))
    return groups


class LighthouseWorld(CachedRuleBuilderWorld):
    """A PC Port of Banjo Kazooie"""

    game = "Banjo-Kazooie Lighthouse"
    web = LighthouseWebWorld()
    options: LighthouseOptions
    options_dataclass = LighthouseOptions
    location_name_to_id = location_table
    item_name_to_id = item_table
    item_name_groups = create_groups(item_data_table)
    location_name_groups = create_groups(location_data_table)

    # Universal Tracker stuff, does not do anything in normal gen
    glitches_item_name = Items.GLITCHED
    using_ut: bool  # so we can check if we're using UT only once
    passthrough: dict[str, Any]  # slot data that got passed through
    ut_can_gen_without_yaml = True  # class var that tells it to ignore the player yaml


    def __init__(self, multiworld, player):
        super().__init__(multiworld, player)
        self.item_pool = list[LighthouseItem]()
        self.included_locations = dict[str, LighthouseLocData]()

        apworld_manifest = orjson.loads(pkgutil.get_data(
            __name__, "archipelago.json").decode("utf-8"))
        self.apworld_version: str = apworld_manifest["world_version"]
        # The version is stored on Worlds, so when we're ready to bump our min AP version to 0.6.4, we can use this directly in our slot data:
        # slot_data["apworld_version"] = self.world_version


    def generate_early(self) -> None:
        # for use with Universal Tracker, doesn't do anything otherwise
        setup_options_from_slot_data(self)
    

    def create_regions(self) -> None:
        create_regions_and_locations(self)
        place_locked_items(self)
        for location in self.get_locations():
            location.name = str(location.name)
        for region in self.get_regions():
            region.name = str(region.name)
    

    def create_item(self, name: str, create_as_event: bool = False, classification: ItemClassification = None) -> LighthouseItem:
        item_entry = Items(name)
        return LighthouseItem(str(name), item_data_table[item_entry].classification if classification == None else classification,
                       None if create_as_event else item_data_table[item_entry].item_id, self.player)


    def set_completion_rule(self, goal: Rule = None) -> None:
        # Actual completion condition.
        if goal == None:
            super().set_completion_rule(Has(str(Events.GAME_COMPLETED)))
        else:
            super().set_completion_rule(goal)
    

    def create_items(self) -> None:
        create_item_pool(self)
        self.set_completion_rule()


    def pre_fill(self) -> None:
        self.set_completion_rule()

    
    def add_items_to_item_pool_list(self, items: list[LighthouseItem]) -> None:
        if len(items) > 0:
            self.item_pool.extend(items)
            self.multiworld.itempool.extend(items)
    

    def fill_slot_data(self) -> dict[str, Any]:
        return {
            "apworld_version": self.apworld_version,
            "shuffle_honey_combs": self.options.shuffle_honey_combs.value,
            "shuffle_jiggies": self.options.shuffle_jiggies.value,
            "shuffle_jinjos": self.options.shuffle_jinjos.value,
            "shuffle_molehills": self.options.shuffle_molehills.value,
            "shuffle_mumbo_tokens": self.options.shuffle_mumbo_tokens.value,
            "shuffle_notes": self.options.shuffle_notes.value,
            "archipelago_seed": self.random.randint(0, 4294967295)
        }
