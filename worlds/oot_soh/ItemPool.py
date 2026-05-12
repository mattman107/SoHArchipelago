from typing import TYPE_CHECKING

from .Enums import *
from .Items import item_data_table, filler_items, no_rules_bottles, SohItem
from .Regions import dungeon_reward_item_mapping, small_key_vanilla_mapping, dungeon_boss_key_vanilla_mapping
from .LogicHelpers import key_to_ring
from .KeyShuffle import small_key_option_matching
from BaseClasses import ItemClassification
from .SongShuffle import song_vanilla_locations, get_shuffled_songs
from .ShopItems import get_vanilla_shop_pool

if TYPE_CHECKING:
    from . import SohWorld


def create_item_pool(world: "SohWorld") -> None:
    items_to_create: dict[str, int] = {
        Items.PROGRESSIVE_WALLET: 4,
        Items.PROGRESSIVE_OCARINA: 2,
        Items.MINUET_OF_FOREST: 1,
        Items.SONG_OF_TIME: 1,
        Items.PROGRESSIVE_HOOKSHOT: 1,
        Items.SHADOW_MEDALLION: 1,
        Items.SPIRIT_MEDALLION: 1,
        Items.GREG_THE_GREEN_RUPEE: 1
    }

    items: list[SohItem] = list()
    # Add regular item pool
    for item, quantity in items_to_create.items():
        items.extend([world.create_item(item) for _ in range(quantity)])

    world.add_items_to_item_pool_list(items)


def create_special_progression_item(world: "SohWorld", item: Items, classification: ItemClassification, amount: int = 1) -> int:
    items = [world.create_item(item, classification=classification)
             for _ in range(amount)]

    world.add_items_to_item_pool_list(items)

    return amount


def create_triforce_pieces(world: "SohWorld") -> None:
    total_triforce_pieces: int = min(
        get_open_location_count(world), world.options.triforce_hunt_pieces_total.value)

    triforce_pieces_to_win: int = max(1, round(
        total_triforce_pieces * (world.options.triforce_hunt_pieces_required_percentage.value * .01)))

    triforce_pieces_made = [world.create_item(
        Items.TRIFORCE_PIECE, classification=ItemClassification.progression_skip_balancing) for _ in range(triforce_pieces_to_win)]
    triforce_pieces_made += [world.create_item(Items.TRIFORCE_PIECE)
                             for _ in range(total_triforce_pieces - triforce_pieces_to_win)]

    world.add_items_to_item_pool_list(triforce_pieces_made)

    world.options.triforce_hunt_pieces_total.value = total_triforce_pieces
    world.triforce_pieces_required = triforce_pieces_to_win

    if world.using_ut:
        world.triforce_pieces_required = world.passthrough["triforce_hunt_pieces_required"]


def create_filler_item_pool(world: "SohWorld") -> None:
    filler_item_count = get_open_location_count(world)

    # Ice Trap Count
    ice_trap_count = min(filler_item_count, world.options.ice_trap_count.value)
    world.multiworld.itempool += [world.create_item(
        Items.ICE_TRAP) for _ in range(ice_trap_count)]

    filler_item_count -= ice_trap_count

    # Ice Trap Filler Replacement
    ice_traps_to_place: int = int(
        filler_item_count * (world.options.ice_trap_filler_replacement.value * .01))
    world.multiworld.itempool += [world.create_item(
        Items.ICE_TRAP) for _ in range(ice_traps_to_place)]

    filler_item_count -= ice_traps_to_place

    # Add junk items to fill remaining locations
    world.multiworld.itempool += [world.create_item(
        get_filler_item(world)) for _ in range(filler_item_count)]


def get_open_location_count(world: "SohWorld") -> int:
    open_location_count = len(world.multiworld.get_unfilled_locations(
        world.player)) - len(world.item_pool) - len(world.pre_fill_pool) #+ len(get_vanilla_shop_pool(world))

    return open_location_count


def get_filler_item(world: "SohWorld") -> str:
    return world.random.choice(filler_items)


def get_filler_bottle(world: "SohWorld") -> str:
    return world.random.choice(no_rules_bottles)


def give_starting_items(world: "SohWorld") -> None:
    if world.options.start_with_kokiri_sword:
        world.push_precollected(world.create_item(Items.KOKIRI_SWORD, True))

    if world.options.start_with_master_sword and world.options.shuffle_master_sword:
        world.push_precollected(world.create_item(Items.MASTER_SWORD, True))

    # doesn't actually do anything logically since deku shields can be lost
    if world.options.start_with_deku_shield:
        world.push_precollected(world.create_item(Items.DEKU_SHIELD, True))

    if world.options.start_with_ocarina == "fairy_ocarina":
        world.push_precollected(world.create_item(Items.PROGRESSIVE_OCARINA, True))

    if world.options.start_with_ocarina == "ocarina_of_time":
        world.push_precollected(world.create_item(Items.PROGRESSIVE_OCARINA, True))
        world.push_precollected(world.create_item(Items.PROGRESSIVE_OCARINA, True))
    
    if world.options.start_with_magic_beans:
        world.push_precollected(world.create_item(Items.MAGIC_BEAN_PACK, True))
    
        # Songs
    starting_songs =  set(song_vanilla_locations.values()) - get_shuffled_songs(world)
    for song in starting_songs:
        world.push_precollected(world.create_item(song, True))

    if world.options.small_key_shuffle == "start_with":
        for key_ring in key_to_ring.values():
            world.push_precollected(world.create_item(key_ring, True))
        
    if world.options.boss_key_shuffle == "start_with":
        for boss_key in dungeon_boss_key_vanilla_mapping.values():
            world.push_precollected(world.create_item(boss_key, True))
