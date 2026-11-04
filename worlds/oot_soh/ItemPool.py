from typing import TYPE_CHECKING

from .Enums import Items, Locations, TokenCounts, Tricks
from .Items import item_data_table, filler_items, no_rules_bottles, SohItem
from .Regions import dungeon_reward_item_mapping, dungeon_boss_keys
from .MasterQuest import small_key_count
from .ship_data_gen import DUNGEON_SMALL_KEYS
from .LogicHelpers import key_to_ring
from BaseClasses import ItemClassification
from .SongShuffle import song_vanilla_locations, get_shuffled_songs
from .ShopItems import get_vanilla_shop_pool
from .Options import *

if TYPE_CHECKING:
    from . import SohWorld


def item_pool_quantity(world: "SohWorld", item: Items) -> int:
    """Number of copies of an item for the currently selected item_pool option.

    Falls back to balanced when other amounts are -1"""
    data = item_data_table[item]
    balanced = data.quantity_in_item_pool
    if world.options.item_pool == "plentiful":
        return data.plentiful_quantity if data.plentiful_quantity >= 0 else balanced
    if world.options.item_pool == "scarce":
        return data.scarce_quantity if data.scarce_quantity >= 0 else balanced
    if world.options.item_pool == "minimal":
        return data.minimal_quantity if data.minimal_quantity >= 0 else balanced
    return balanced


def apply_pool_tier(world: "SohWorld", items_to_create: dict[str, int], item: Items) -> None:
    """Rewrite an already-present item's count to its selected item_pool amount."""
    if items_to_create[item] <= 0:
        return
    data = item_data_table[item]
    if world.options.item_pool == "plentiful":
        tier = data.plentiful_quantity
    elif world.options.item_pool == "scarce":
        tier = data.scarce_quantity
    elif world.options.item_pool == "minimal":
        tier = data.minimal_quantity
    else:
        tier = -1
    if tier >= 0:
        items_to_create[item] = tier


def create_item_pool(world: "SohWorld") -> None:
    items_to_create: dict[str, int] = {
        item: data.quantity_in_item_pool for item, data in item_data_table.items()}

    # King Zora
    if world.options.zoras_fountain == "open":
        items_to_create[Items.RG_RUTOS_LETTER] = 0

    # Overworld door keys
    if world.options.lock_overworld_doors:
        items_to_create[Items.RG_GUARD_HOUSE_KEY] = 1
        items_to_create[Items.RG_MARKET_BAZAAR_KEY] = 1
        items_to_create[Items.RG_MARKET_POTION_SHOP_KEY] = 1
        items_to_create[Items.RG_MASK_SHOP_KEY] = 1
        items_to_create[Items.RG_MARKET_SHOOTING_GALLERY_KEY] = 1
        items_to_create[Items.RG_BOMBCHU_BOWLING_KEY] = 1
        items_to_create[Items.RG_TREASURE_CHEST_GAME_BUILDING_KEY] = 1
        items_to_create[Items.RG_BOMBCHU_SHOP_KEY] = 1
        items_to_create[Items.RG_RICHARDS_HOUSE_KEY] = 1
        items_to_create[Items.RG_ALLEY_HOUSE_KEY] = 1
        items_to_create[Items.RG_KAK_BAZAAR_KEY] = 1
        items_to_create[Items.RG_KAK_POTION_SHOP_KEY] = 1
        items_to_create[Items.RG_BOSS_HOUSE_KEY] = 1
        items_to_create[Items.RG_GRANNYS_POTION_SHOP_KEY] = 1
        items_to_create[Items.RG_SKULLTULA_HOUSE_KEY] = 1
        items_to_create[Items.RG_IMPAS_HOUSE_KEY] = 1
        items_to_create[Items.RG_WINDMILL_KEY] = 1
        items_to_create[Items.RG_KAK_SHOOTING_GALLERY_KEY] = 1
        items_to_create[Items.RG_DAMPES_HUT_KEY] = 1
        items_to_create[Items.RG_TALONS_HOUSE_KEY] = 1
        items_to_create[Items.RG_STABLES_KEY] = 1
        items_to_create[Items.RG_BACK_TOWER_KEY] = 1
        items_to_create[Items.RG_HYLIA_LAB_KEY] = 1
        items_to_create[Items.RG_FISHING_HOLE_KEY] = 1

    # Ocarina Buttons
    if world.options.shuffle_ocarina_buttons:
        items_to_create[Items.RG_OCARINA_A_BUTTON] = 1
        items_to_create[Items.RG_OCARINA_C_DOWN_BUTTON] = 1
        items_to_create[Items.RG_OCARINA_C_LEFT_BUTTON] = 1
        items_to_create[Items.RG_OCARINA_C_RIGHT_BUTTON] = 1
        items_to_create[Items.RG_OCARINA_C_UP_BUTTON] = 1

    # Fishing Pole
    if world.options.shuffle_fishing_pole:
        items_to_create[Items.RG_FISHING_POLE] = 1

    # Merchants
    if world.options.shuffle_merchants not in (ShuffleMerchants.option_all, ShuffleMerchants.option_bean_merchant_only):
        items_to_create[Items.RG_MAGIC_BEAN_PACK] = 0

    if world.options.shuffle_merchants in ("all", "all_but_beans"):
        items_to_create[Items.RG_GIANTS_KNIFE] = 1

    # Adult Trade Items
    if world.options.shuffle_adult_trade_items:
        items_to_create[Items.RG_POCKET_EGG] = 1
        items_to_create[Items.RG_COJIRO] = 1
        items_to_create[Items.RG_ODD_MUSHROOM] = 1
        items_to_create[Items.RG_ODD_POTION] = 1
        items_to_create[Items.RG_POACHERS_SAW] = 1
        items_to_create[Items.RG_BROKEN_SWORD] = 1
        items_to_create[Items.RG_PRESCRIPTION] = 1
        items_to_create[Items.RG_EYEBALL_FROG] = 1
        items_to_create[Items.RG_EYEDROPS] = 1

    # Boss Souls
    if world.options.shuffle_boss_souls:
        items_to_create[Items.RG_GOHMA_SOUL] = 1
        items_to_create[Items.RG_KING_DODONGO_SOUL] = 1
        items_to_create[Items.RG_BARINADE_SOUL] = 1
        items_to_create[Items.RG_PHANTOM_GANON_SOUL] = 1
        items_to_create[Items.RG_VOLVAGIA_SOUL] = 1
        items_to_create[Items.RG_MORPHA_SOUL] = 1
        items_to_create[Items.RG_BONGO_BONGO_SOUL] = 1
        items_to_create[Items.RG_TWINROVA_SOUL] = 1

    if world.options.shuffle_boss_souls == "on_plus_ganons":
        items_to_create[Items.RG_GANON_SOUL] = 1

    # Maps and Compasses
    if world.options.maps_and_compasses != MapsAndCompasses.option_start_with:
        items_to_create[Items.RG_DEKU_TREE_MAP] = 1
        items_to_create[Items.RG_DODONGOS_CAVERN_MAP] = 1
        items_to_create[Items.RG_JABU_JABUS_BELLY_MAP] = 1
        items_to_create[Items.RG_FOREST_TEMPLE_MAP] = 1
        items_to_create[Items.RG_FIRE_TEMPLE_MAP] = 1
        items_to_create[Items.RG_WATER_TEMPLE_MAP] = 1
        items_to_create[Items.RG_SPIRIT_TEMPLE_MAP] = 1
        items_to_create[Items.RG_SHADOW_TEMPLE_MAP] = 1
        items_to_create[Items.RG_BOTTOM_OF_THE_WELL_MAP] = 1
        items_to_create[Items.RG_ICE_CAVERN_MAP] = 1
        items_to_create[Items.RG_DEKU_TREE_COMPASS] = 1
        items_to_create[Items.RG_DODONGOS_CAVERN_COMPASS] = 1
        items_to_create[Items.RG_JABU_JABUS_BELLY_COMPASS] = 1
        items_to_create[Items.RG_FOREST_TEMPLE_COMPASS] = 1
        items_to_create[Items.RG_FIRE_TEMPLE_COMPASS] = 1
        items_to_create[Items.RG_WATER_TEMPLE_COMPASS] = 1
        items_to_create[Items.RG_SPIRIT_TEMPLE_COMPASS] = 1
        items_to_create[Items.RG_SHADOW_TEMPLE_COMPASS] = 1
        items_to_create[Items.RG_BOTTOM_OF_THE_WELL_COMPASS] = 1
        items_to_create[Items.RG_ICE_CAVERN_COMPASS] = 1

    # Ganon's Castle Boss Key
    if not world.options.triforce_hunt:
        items_to_create[Items.RG_GANONS_CASTLE_BOSS_KEY] = 1

    # Keys. Key rings replace the small keys of their dungeon.
    for ring_option, key, ring in (
            (world.options.forest_temple_key_ring, Items.RG_FOREST_TEMPLE_SMALL_KEY, Items.RG_FOREST_TEMPLE_KEY_RING),
            (world.options.fire_temple_key_ring, Items.RG_FIRE_TEMPLE_SMALL_KEY, Items.RG_FIRE_TEMPLE_KEY_RING),
            (world.options.water_temple_key_ring, Items.RG_WATER_TEMPLE_SMALL_KEY, Items.RG_WATER_TEMPLE_KEY_RING),
            (world.options.spirit_temple_key_ring, Items.RG_SPIRIT_TEMPLE_SMALL_KEY, Items.RG_SPIRIT_TEMPLE_KEY_RING),
            (world.options.shadow_temple_key_ring, Items.RG_SHADOW_TEMPLE_SMALL_KEY, Items.RG_SHADOW_TEMPLE_KEY_RING),
            (world.options.bottom_of_the_well_key_ring, Items.RG_BOTTOM_OF_THE_WELL_SMALL_KEY, Items.RG_BOTTOM_OF_THE_WELL_KEY_RING),
            (world.options.gerudo_training_ground_key_ring, Items.RG_GERUDO_TRAINING_GROUND_SMALL_KEY, Items.RG_GERUDO_TRAINING_GROUND_KEY_RING),
            (world.options.ganons_castle_key_ring, Items.RG_GANONS_CASTLE_SMALL_KEY, Items.RG_GANONS_CASTLE_KEY_RING)):
        if ring_option:
            items_to_create[key] = 0
            items_to_create[ring] = 1

    # Gerudo Fortress Keys
    fortress_fast = world.options.fortress_carpenters == RSK_GERUDO_FORTRESS.option_fast
    fortress_plentiful = world.options.item_pool == ItemPool.option_plentiful
    if world.options.fortress_carpenters == RSK_GERUDO_FORTRESS.option_free:
        items_to_create[Items.RG_GERUDO_FORTRESS_SMALL_KEY] = 0
    elif world.options.gerudo_fortress_key_shuffle == GerudoFortressKeyShuffle.option_vanilla:
        # The carpenter locations take these from the pool
        items_to_create[Items.RG_GERUDO_FORTRESS_SMALL_KEY] = 1 if fortress_fast else 4
    elif fortress_fast:
        # Only one key is needed, freeing a single carpenter
        items_to_create[Items.RG_GERUDO_FORTRESS_SMALL_KEY] = 2 if fortress_plentiful else 1
    elif world.options.gerudo_fortress_key_ring:
        items_to_create[Items.RG_GERUDO_FORTRESS_SMALL_KEY] = 0
        items_to_create[Items.RG_GERUDO_FORTRESS_KEY_RING] = 2 if fortress_plentiful else 1
    else:
        items_to_create[Items.RG_GERUDO_FORTRESS_SMALL_KEY] = 5 if fortress_plentiful else 4

    # Big Poe Bottle
    if world.options.big_poe_target_count == 0:
        items_to_create[Items.RG_BOTTLE_WITH_BIG_POE] = 0

    # Bombchu bag. Loose bombchus (set in item_data_table) are only kept when no bag is shuffled.
    if world.options.bombchu_bag == "single_bag":
        items_to_create[Items.RG_BOMBCHU_5] = 0
        items_to_create[Items.RG_BOMBCHU_10] = 0
        items_to_create[Items.RG_BOMBCHU_20] = 0
        if world.options.item_pool == "plentiful":
            bombchu_bags = 6
        elif world.options.item_pool == "scarce":
            bombchu_bags = 3
        elif world.options.item_pool == "minimal":
            bombchu_bags = 1
        else:
            bombchu_bags = 5
        if world.options.shuffle_merchants in ("all_but_beans", "all"):
            bombchu_bags += 1
        items_to_create[Items.RG_PROGRESSIVE_BOMBCHU_BAG] = bombchu_bags
    elif world.options.bombchu_bag == "progressive_bags":
        items_to_create[Items.RG_BOMBCHU_5] = 0
        items_to_create[Items.RG_BOMBCHU_10] = 0
        items_to_create[Items.RG_BOMBCHU_20] = 0
        if world.options.item_pool == "plentiful":
            bombchu_bags = 4
        elif world.options.item_pool == "scarce":
            bombchu_bags = 2
        elif world.options.item_pool == "minimal":
            bombchu_bags = 1
        else:
            bombchu_bags = 3
        if world.options.infinite_upgrades == "progressive":
            bombchu_bags += 1
        items_to_create[Items.RG_PROGRESSIVE_BOMBCHU_BAG] = bombchu_bags

    # Skeleton Key
    if world.options.skeleton_key:
        items_to_create[Items.RG_SKELETON_KEY] = 1

    # Roc's Feather
    if world.options.rocs_feather:
        items_to_create[Items.RG_ROCS_FEATHER] = 1

    # Max Hearts logic for Item Pool
    max_hearts: int = 20
    if world.options.item_pool == "scarce":
        max_hearts = 12
    elif world.options.item_pool == "minimal":
        max_hearts = 3

    starting_hearts: int = world.multiworld.state.soh_heart_count[world.player]
    if starting_hearts < max_hearts:
        items_to_create[Items.RG_TREASURE_GAME_HEART] = 1
        items_to_create[Items.RG_PIECE_OF_HEART] = 3
        starting_hearts += 1
        if starting_hearts < max_hearts:
            hearts_to_place: int = max_hearts - starting_hearts
            if world.options.item_pool in ("plentiful", "minimal"):
                items_to_create[Items.RG_HEART_CONTAINER] = hearts_to_place
            elif world.options.item_pool == "balanced":
                half_hearts: int = int(hearts_to_place / 2)
                items_to_create[Items.RG_HEART_CONTAINER] = hearts_to_place - half_hearts
                items_to_create[Items.RG_PIECE_OF_HEART] += half_hearts * 4
            elif world.options.item_pool == "scarce":
                items_to_create[Items.RG_PIECE_OF_HEART] += hearts_to_place * 4

    # Item Pool Modifications: apply the selected item_pool amount to every item that is
    # already in the pool and defines a per-option amount in item_data_table.
    for item in items_to_create:
        apply_pool_tier(world, items_to_create, item)

    # The default pool holds one copy of the items that are placed or given when not shuffled.
    # The extra plentiful copies only exist for shuffled items.
    options = world.options
    shuffled_songs = get_shuffled_songs(world) if options.shuffle_songs == ShuffleSongs.option_anywhere else set()
    only_default = {
        Items.RG_KOKIRI_SWORD: options.shuffle_kokiri_sword and not options.start_with_kokiri_sword,
        Items.RG_MASTER_SWORD: options.shuffle_master_sword and not options.start_with_master_sword,
        Items.RG_GERUDO_MEMBERSHIP_CARD: options.shuffle_gerudo_membership_card and options.fortress_carpenters != RSK_GERUDO_FORTRESS.option_free,
        Items.RG_WEIRD_EGG: options.shuffle_weird_egg and not options.skip_child_zelda,
        Items.RG_MAGIC_BEAN_PACK: not options.start_with_magic_beans,
        **{song: song in shuffled_songs for song in song_vanilla_locations.values()},
    }
    for item, extras in only_default.items():
        if not extras:
            items_to_create[item] = min(items_to_create[item], 1)
    if options.small_key_shuffle == RSK_KEYSANITY.option_start_with:
        # Starting with the keys gives every key ring, the fortress and chest game ones too
        items_to_create[Items.RG_GERUDO_FORTRESS_KEY_RING] = 1
        items_to_create[Items.RG_TREASURE_GAME_KEY_RING] = 1
        for ring in key_to_ring.values():
            items_to_create[ring] = min(items_to_create[ring], 1)
    if options.ganons_castle_boss_key != GanonsCastleBossKey.option_anywhere:
        items_to_create[Items.RG_GANONS_CASTLE_BOSS_KEY] = min(items_to_create[Items.RG_GANONS_CASTLE_BOSS_KEY], 1)
    if options.boss_key_shuffle in (BossKeyShuffle.option_start_with, BossKeyShuffle.option_vanilla):
        for boss_key in dungeon_boss_keys:
            items_to_create[boss_key] = min(items_to_create[boss_key], 1)

    # Plentiful adds an ocarina, but never when starting with the Ocarina of Time
    if options.item_pool == ItemPool.option_plentiful and options.shuffle_ocarinas and options.start_with_ocarina != StartWithOcarina.option_ocarina_of_time:
        items_to_create[Items.RG_PROGRESSIVE_OCARINA] += 1

    # Small keys follow each dungeon's quest: Master Quest layouts hold a different number.
    plentiful_keys = 1 if options.item_pool == ItemPool.option_plentiful and options.small_key_shuffle not in (RSK_KEYSANITY.option_start_with, RSK_KEYSANITY.option_vanilla) else 0
    for key in DUNGEON_SMALL_KEYS:
        if items_to_create[key]:
            items_to_create[key] = small_key_count(world, key) + plentiful_keys

    # Progressive upgrades take their per-option amount plus any extra copies granted by
    # other options (infinite upgrades and the tycoon wallet). The extra copy of the wallet, deku bags,
    # swim and strength is the one given at the start when it isn't shuffled.
    infinite_upgrades = 1 if options.infinite_upgrades == InfiniteUpgrades.option_progressive else 0
    extra_wallets = 1 + (1 if options.shuffle_tycoon_wallet else 0)

    items_to_create[Items.RG_PROGRESSIVE_BOW] = item_pool_quantity(world, Items.RG_PROGRESSIVE_BOW) + infinite_upgrades
    items_to_create[Items.RG_PROGRESSIVE_SLINGSHOT] = item_pool_quantity(world, Items.RG_PROGRESSIVE_SLINGSHOT) + infinite_upgrades
    items_to_create[Items.RG_PROGRESSIVE_BOMB_BAG] = item_pool_quantity(world, Items.RG_PROGRESSIVE_BOMB_BAG) + infinite_upgrades
    items_to_create[Items.RG_PROGRESSIVE_MAGIC_METER] = item_pool_quantity(world, Items.RG_PROGRESSIVE_MAGIC_METER) + infinite_upgrades
    items_to_create[Items.RG_PROGRESSIVE_WALLET] = item_pool_quantity(world, Items.RG_PROGRESSIVE_WALLET) + infinite_upgrades + extra_wallets
    items_to_create[Items.RG_PROGRESSIVE_STICK_UPGRADE] = item_pool_quantity(world, Items.RG_PROGRESSIVE_STICK_UPGRADE) + infinite_upgrades + 1
    items_to_create[Items.RG_PROGRESSIVE_NUT_UPGRADE] = item_pool_quantity(world, Items.RG_PROGRESSIVE_NUT_UPGRADE) + infinite_upgrades + 1
    items_to_create[Items.RG_PROGRESSIVE_SCALE] = item_pool_quantity(world, Items.RG_PROGRESSIVE_SCALE) + 1
    items_to_create[Items.RG_PROGRESSIVE_STRENGTH] = item_pool_quantity(world, Items.RG_PROGRESSIVE_STRENGTH) + 1

    ability_items: dict[str, list[Items]] = {
        "shuffle_climb": [Items.RG_CLIMB],
        "shuffle_crawl": [Items.RG_CRAWL],
        "shuffle_open_chest": [Items.RG_OPEN_CHEST],
        "shuffle_jabber_nuts": [Items.RG_SPEAK_DEKU, Items.RG_SPEAK_GERUDO, Items.RG_SPEAK_GORON,
                                Items.RG_SPEAK_HYLIAN, Items.RG_SPEAK_KOKIRI, Items.RG_SPEAK_ZORA],
        "shuffle_bean_souls": [Items.RG_DEATH_MOUNTAIN_CRATER_BEAN_SOUL,
                               Items.RG_DEATH_MOUNTAIN_TRAIL_BEAN_SOUL,
                               Items.RG_DESERT_COLOSSUS_BEAN_SOUL, Items.RG_GERUDO_VALLEY_BEAN_SOUL,
                               Items.RG_GRAVEYARD_BEAN_SOUL, Items.RG_KOKIRI_FOREST_BEAN_SOUL,
                               Items.RG_LAKE_HYLIA_BEAN_SOUL, Items.RG_LOST_WOODS_BEAN_SOUL,
                               Items.RG_LOST_WOODS_BRIDGE_BEAN_SOUL, Items.RG_ZORAS_RIVER_BEAN_SOUL],
    }
    ability_count = 2 if world.options.item_pool == "plentiful" else 1
    for option_name, items in ability_items.items():
        if getattr(world.options, option_name):
            for item in items:
                items_to_create[item] = ability_count

    if world.options.complete_mask_quest == "shuffle":
        for mask in (Items.RG_KEATON_MASK, Items.RG_SKULL_MASK, Items.RG_SPOOKY_MASK, Items.RG_BUNNY_HOOD,
                     Items.RG_GORON_MASK, Items.RG_ZORA_MASK, Items.RG_GERUDO_MASK, Items.RG_MASK_OF_TRUTH):
            items_to_create[mask] = 2 if world.options.item_pool == "plentiful" else 1

    # The plentiful pool adds in extra Gold Skulltula Tokens
    if world.options.item_pool == "plentiful" and world.options.shuffle_skull_tokens:
        items_to_create[Items.RG_GOLD_SKULLTULA_TOKEN] += 10

    # It there are more randomized skulltula tokens than required progression, set the excess to useful
    if items_to_create[Items.RG_GOLD_SKULLTULA_TOKEN] > world.randomized_progressive_skulltula_count:
        items_to_create[Items.RG_GOLD_SKULLTULA_TOKEN] -= create_special_progression_item(
            world, Items.RG_GOLD_SKULLTULA_TOKEN, ItemClassification.useful | ItemClassification.deprioritized | ItemClassification.skip_balancing, items_to_create[Items.RG_GOLD_SKULLTULA_TOKEN] - world.randomized_progressive_skulltula_count)

    # If you start with enough hearts to do everything and tricks aren't enabled make the rest of them useful
    if not (world.options.enable_all_tricks or str(Tricks.RT_FEWER_TUNIC_REQUIREMENTS) in world.options.tricks_in_logic.value):
        min_hearts_needed: int = 3
        if world.multiworld.state.soh_heart_count[world.player] >= min_hearts_needed:
            items_to_create[Items.RG_PIECE_OF_HEART] -= create_special_progression_item(world, Items.RG_PIECE_OF_HEART, ItemClassification.useful, items_to_create[Items.RG_PIECE_OF_HEART])
            items_to_create[Items.RG_TREASURE_GAME_HEART] -= create_special_progression_item(world, Items.RG_TREASURE_GAME_HEART, ItemClassification.useful, items_to_create[Items.RG_TREASURE_GAME_HEART])
            items_to_create[Items.RG_HEART_CONTAINER] -= create_special_progression_item(world, Items.RG_HEART_CONTAINER, ItemClassification.useful, items_to_create[Items.RG_HEART_CONTAINER])
        else:
             # starting health is less than min_hearts_needed
            # Get the total number of heart classifications we have to work with
            total_non_progression_hearts: int = max_hearts - min_hearts_needed

            if total_non_progression_hearts > 0:
                # Heart Piece amount to make useful. Convert to actual hearts, then convert back later
                non_progression_piece_amount: int = int((items_to_create[Items.RG_PIECE_OF_HEART] + items_to_create[Items.RG_TREASURE_GAME_HEART]) / 4)
            
                if total_non_progression_hearts >= non_progression_piece_amount: 
                    items_to_create[Items.RG_PIECE_OF_HEART] -= create_special_progression_item(world, Items.RG_PIECE_OF_HEART, ItemClassification.useful, ((non_progression_piece_amount * 4) - 1))
                    items_to_create[Items.RG_TREASURE_GAME_HEART] -= create_special_progression_item(world, Items.RG_TREASURE_GAME_HEART, ItemClassification.useful, 1)

                    total_non_progression_hearts -= non_progression_piece_amount
                elif world.options.item_pool not in ("plentiful", "minimal"):
                    non_progression_piece_amount = total_non_progression_hearts
                    
                    items_to_create[Items.RG_PIECE_OF_HEART] -= create_special_progression_item(world, Items.RG_PIECE_OF_HEART, ItemClassification.useful, ((non_progression_piece_amount * 4) - 1))
                    items_to_create[Items.RG_TREASURE_GAME_HEART] -= create_special_progression_item(world, Items.RG_TREASURE_GAME_HEART, ItemClassification.useful, 1)

                    total_non_progression_hearts = 0

                # Container amount to make useful
                if total_non_progression_hearts >= items_to_create[Items.RG_HEART_CONTAINER]:
                    items_to_create[Items.RG_HEART_CONTAINER] -= create_special_progression_item(world, Items.RG_HEART_CONTAINER, ItemClassification.useful, items_to_create[Items.RG_HEART_CONTAINER])
                else:
                    items_to_create[Items.RG_HEART_CONTAINER] -= create_special_progression_item(world, Items.RG_HEART_CONTAINER, ItemClassification.useful, total_non_progression_hearts)

    # if Greg isn't necessary to win, make him filler
    if not (world.options.rainbow_bridge == "greg" or (world.options.rainbow_bridge and world.options.rainbow_bridge_greg_modifier) or (world.options.ganons_castle_boss_key and world.options.ganons_castle_boss_key_greg_modifier)):
        items_to_create[Items.RG_GREG_RUPEE] -= create_special_progression_item(
            world, Items.RG_GREG_RUPEE, ItemClassification.filler)

    # Stone of Agony is Progression unless not required for Grottos
    if world.options.enable_all_tricks or str(Tricks.RT_GROTTOS_WITHOUT_AGONY) in world.options.tricks_in_logic:
        items_to_create[Items.RG_STONE_OF_AGONY] -= create_special_progression_item(
            world, Items.RG_STONE_OF_AGONY, ItemClassification.filler)

    # Ice Arrows set to filler if not useful (blue fire arrows enabled)
    if not world.options.blue_fire_arrows:
        items_to_create[Items.RG_ICE_ARROWS] -= create_special_progression_item(
            world, Items.RG_ICE_ARROWS, ItemClassification.filler)

    items: list[SohItem] = list()
    # Add regular item pool
    for item, quantity in items_to_create.items():
        items.extend([world.create_item(item) for _ in range(quantity)])

    filler_bottle_amount: int = 2
    if world.options.zoras_fountain == "open":
        filler_bottle_amount += 1
    if world.options.big_poe_target_count == 0:
        filler_bottle_amount += 1

    # Add random filler bottles
    items.extend([world.create_item(get_filler_bottle(world)) for _ in range(filler_bottle_amount)])

    world.add_items_to_item_pool_list(items)


def create_special_progression_item(world: "SohWorld", item: Items, classification: ItemClassification, amount: int = 1) -> int:
    if amount < 1:
        return 0

    items = [world.create_item(item, classification=classification)
             for _ in range(amount)]

    world.add_items_to_item_pool_list(items)

    return amount


def create_triforce_pieces(world: "SohWorld") -> None:
    total_triforce_pieces: int = min(
        get_open_location_count(world), world.options.triforce_hunt_pieces_total.value)

    triforce_pieces_to_win: int = max(1, round(
        total_triforce_pieces * (world.options.triforce_hunt_pieces_required_percentage.value * .01)))

    triforce_pieces_made = [world.create_item(Items.RG_TRIFORCE_PIECE) 
                            for _ in range(triforce_pieces_to_win)]
    triforce_pieces_made += [world.create_item(Items.RG_TRIFORCE_PIECE, classification=ItemClassification.useful | ItemClassification.skip_balancing) 
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
        Items.RG_ICE_TRAP) for _ in range(ice_trap_count)]

    filler_item_count -= ice_trap_count

    # Ice Trap Filler Replacement
    ice_traps_to_place: int = int(
        filler_item_count * (world.options.ice_trap_filler_replacement.value * .01))
    world.multiworld.itempool += [world.create_item(
        Items.RG_ICE_TRAP) for _ in range(ice_traps_to_place)]

    filler_item_count -= ice_traps_to_place

    # Add junk items to fill remaining locations
    world.multiworld.itempool += [world.create_item(
        get_filler_item(world)) for _ in range(filler_item_count)]


def get_open_location_count(world: "SohWorld") -> int:
    open_location_count = len(world.multiworld.get_unfilled_locations(
        world.player)) - len(world.item_pool) - len(world.pre_fill_pool) + len(get_vanilla_shop_pool(world))

    return open_location_count


def get_filler_item(world: "SohWorld") -> str:
    return world.random.choice(filler_items)


def get_filler_bottle(world: "SohWorld") -> str:
    return world.random.choice(no_rules_bottles)


def give_starting_items(world: "SohWorld") -> None:
    options = world.options

    # The progressive items below are always in the pool, the copy given here keeps collect/remove working
    if not options.shuffle_swim:
        world.precollect_from_pool(Items.RG_PROGRESSIVE_SCALE)
    if not options.shuffle_grab:
        world.precollect_from_pool(Items.RG_PROGRESSIVE_STRENGTH)
    if not options.shuffle_deku_stick_bag:
        world.precollect_from_pool(Items.RG_PROGRESSIVE_STICK_UPGRADE)
    if not options.shuffle_deku_nut_bag:
        world.precollect_from_pool(Items.RG_PROGRESSIVE_NUT_UPGRADE)
    if not options.shuffle_childs_wallet:
        world.precollect_from_pool(Items.RG_PROGRESSIVE_WALLET)

    # Pre-Collect Extra Fire Temple Small Key (vanilla Fire Temple only)
    if options.small_key_shuffle in (RSK_KEYSANITY.option_vanilla, RSK_KEYSANITY.option_own_dungeon) and "Fire Temple" not in world.mq_dungeons:
        world.multiworld.push_precollected(
            world.create_item(str(Items.RG_FIRE_TEMPLE_SMALL_KEY), True))

    if options.start_with_kokiri_sword:
        world.precollect_from_pool(Items.RG_KOKIRI_SWORD)

    if options.start_with_master_sword and options.shuffle_master_sword:
        world.precollect_from_pool(Items.RG_MASTER_SWORD)

    # doesn't actually do anything logically since deku shields can be lost
    if options.start_with_deku_shield:
        world.precollect_from_pool(Items.RG_DEKU_SHIELD)

    if options.start_with_ocarina == StartWithOcarina.option_fairy_ocarina:
        world.precollect_from_pool(Items.RG_PROGRESSIVE_OCARINA)

    if options.start_with_ocarina == StartWithOcarina.option_ocarina_of_time:
        world.precollect_from_pool(Items.RG_PROGRESSIVE_OCARINA)
        world.precollect_from_pool(Items.RG_PROGRESSIVE_OCARINA)

    if options.start_with_magic_beans:
        world.precollect_from_pool(Items.RG_MAGIC_BEAN_PACK)

    if options.fortress_carpenters == RSK_GERUDO_FORTRESS.option_free:
        world.precollect_from_pool(Items.RG_GERUDO_MEMBERSHIP_CARD)

    shuffled_songs = get_shuffled_songs(world)
    for song in song_vanilla_locations.values():
        if song not in shuffled_songs:
            world.precollect_from_pool(song)

    if options.small_key_shuffle == RSK_KEYSANITY.option_start_with:
        for key_ring in key_to_ring.values():
            world.precollect_from_pool(key_ring)

    if options.boss_key_shuffle == BossKeyShuffle.option_start_with:
        for boss_key in dungeon_boss_keys:
            world.precollect_from_pool(boss_key)
