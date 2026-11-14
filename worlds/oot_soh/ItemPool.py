from typing import TYPE_CHECKING

from .Enums import Items, Locations, TokenCounts, Tricks
from .Items import item_data_table, GroupTag, filler_items, no_rules_bottles, SohItem
from .Regions import dungeon_reward_item_mapping, dungeon_boss_keys
from .MasterQuest import small_key_count
from .ship_data_gen import CheckArea, DUNGEON_SMALL_KEYS
from .LogicHelpers import key_to_ring
from BaseClasses import ItemClassification
from .SongShuffle import song_vanilla_locations, get_shuffled_songs
from .ShopItems import get_vanilla_shop_pool
from .Options import *

if TYPE_CHECKING:
    from . import SohWorld


def item_pool_quantity(world: "SohWorld", item: Items) -> int:
    data = item_data_table[item]
    amount = getattr(data, f"{world.options.item_pool.current_key}_quantity")
    return amount if amount >= 0 else data.balanced_quantity


def create_item_pool(world: "SohWorld") -> None:
    items_to_create: dict[str, int] = {item: item_pool_quantity(world, item) for item in item_data_table}

    def enable(*items: Items) -> None:
        for item in items:
            items_to_create[item] = item_pool_quantity(world, item) or 1

    def enable_tagged(tag: GroupTag, skip: Items | None = None) -> None:
        enable(*(item for item, data in item_data_table.items() if data.tags and data.tags & tag and item != skip))

    # King Zora
    if world.options.zoras_fountain == RSK_ZORAS_FOUNTAIN.option_open:
        items_to_create[Items.RG_RUTOS_LETTER] = 0

    # Overworld door keys
    if world.options.lock_overworld_doors:
        enable_tagged(GroupTag.Overworld_Key)

    # Ocarina Buttons
    if world.options.shuffle_ocarina_buttons:
        enable_tagged(GroupTag.Ocarina_Button)

    # Fishing Pole
    if world.options.shuffle_fishing_pole:
        enable(Items.RG_FISHING_POLE)

    # Merchants
    if world.options.shuffle_merchants not in (ShuffleMerchants.option_all, ShuffleMerchants.option_bean_merchant_only):
        items_to_create[Items.RG_MAGIC_BEAN_PACK] = 0

    if world.options.shuffle_merchants in (ShuffleMerchants.option_all, ShuffleMerchants.option_all_but_beans):
        enable(Items.RG_GIANTS_KNIFE)

    # Adult Trade Items
    if world.options.shuffle_adult_trade_items:
        enable(Items.RG_POCKET_EGG, Items.RG_COJIRO, Items.RG_ODD_MUSHROOM, Items.RG_ODD_POTION, Items.RG_POACHERS_SAW,
               Items.RG_BROKEN_SWORD, Items.RG_PRESCRIPTION, Items.RG_EYEBALL_FROG, Items.RG_EYEDROPS)

    # Boss Souls
    if world.options.shuffle_boss_souls:
        enable_tagged(GroupTag.Boss_Soul, skip=Items.RG_GANON_SOUL)

    if world.options.shuffle_boss_souls == RSK_SHUFFLE_BOSS_SOULS.option_on_plus_ganons:
        enable(Items.RG_GANON_SOUL)

    # Maps and Compasses
    if world.options.maps_and_compasses != MapsAndCompasses.option_start_with:
        enable_tagged(GroupTag.Map | GroupTag.Compass)

    # Ganon's Castle Boss Key
    if not world.options.triforce_hunt:
        enable(Items.RG_GANONS_CASTLE_BOSS_KEY)

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
            enable(ring)

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
    if world.options.bombchu_bag in (BombchuBag.option_single_bag, BombchuBag.option_progressive_bags):
        for chu in (Items.RG_BOMBCHU_5, Items.RG_BOMBCHU_10, Items.RG_BOMBCHU_20):
            items_to_create[chu] = 0
        single = world.options.bombchu_bag == BombchuBag.option_single_bag
        bags = {ItemPool.option_plentiful: 6, ItemPool.option_scarce: 3, ItemPool.option_minimal: 1}.get(world.options.item_pool.value, 5) if single else \
            {ItemPool.option_plentiful: 4, ItemPool.option_scarce: 2, ItemPool.option_minimal: 1}.get(world.options.item_pool.value, 3)
        if single and world.options.shuffle_merchants in (ShuffleMerchants.option_all, ShuffleMerchants.option_all_but_beans):
            bags += 1
        items_to_create[Items.RG_PROGRESSIVE_BOMBCHU_BAG] = bags

    # Skeleton Key
    if world.options.skeleton_key:
        enable(Items.RG_SKELETON_KEY)

    # Roc's Feather
    if world.options.rocs_feather:
        enable(Items.RG_ROCS_FEATHER)

    # Max Hearts logic for Item Pool
    max_hearts: int = 20
    if world.options.item_pool == ItemPool.option_scarce:
        max_hearts = 12
    elif world.options.item_pool == ItemPool.option_minimal:
        max_hearts = 3

    starting_hearts: int = world.multiworld.state.soh_heart_count[world.player]
    if starting_hearts < max_hearts:
        items_to_create[Items.RG_TREASURE_GAME_HEART] = 1
        items_to_create[Items.RG_PIECE_OF_HEART] = 3
        starting_hearts += 1
        if starting_hearts < max_hearts:
            hearts_to_place: int = max_hearts - starting_hearts
            if world.options.item_pool in (ItemPool.option_plentiful, ItemPool.option_minimal):
                items_to_create[Items.RG_HEART_CONTAINER] = hearts_to_place
            elif world.options.item_pool == ItemPool.option_balanced:
                half_hearts: int = int(hearts_to_place / 2)
                items_to_create[Items.RG_HEART_CONTAINER] = hearts_to_place - half_hearts
                items_to_create[Items.RG_PIECE_OF_HEART] += half_hearts * 4
            elif world.options.item_pool == ItemPool.option_scarce:
                items_to_create[Items.RG_PIECE_OF_HEART] += hearts_to_place * 4

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

    for item, extra in {
        Items.RG_PROGRESSIVE_BOW: infinite_upgrades,
        Items.RG_PROGRESSIVE_SLINGSHOT: infinite_upgrades,
        Items.RG_PROGRESSIVE_BOMB_BAG: infinite_upgrades,
        Items.RG_PROGRESSIVE_MAGIC_METER: infinite_upgrades,
        Items.RG_PROGRESSIVE_WALLET: infinite_upgrades + extra_wallets,
        Items.RG_PROGRESSIVE_STICK_UPGRADE: infinite_upgrades + 1,
        Items.RG_PROGRESSIVE_NUT_UPGRADE: infinite_upgrades + 1,
        Items.RG_PROGRESSIVE_SCALE: 1,
        Items.RG_PROGRESSIVE_STRENGTH: 1,
    }.items():
        items_to_create[item] = item_pool_quantity(world, item) + extra
    if options.bombchu_bag == BombchuBag.option_progressive_bags:
        items_to_create[Items.RG_PROGRESSIVE_BOMBCHU_BAG] += infinite_upgrades

    ability_count = 2 if world.options.item_pool == ItemPool.option_plentiful else 1
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
    for option_name, items in ability_items.items():
        if getattr(world.options, option_name):
            for item in items:
                items_to_create[item] = ability_count

    if world.options.complete_mask_quest == RSK_MASK_QUEST.option_shuffle:
        for mask in (Items.RG_KEATON_MASK, Items.RG_SKULL_MASK, Items.RG_SPOOKY_MASK, Items.RG_BUNNY_HOOD,
                     Items.RG_GORON_MASK, Items.RG_ZORA_MASK, Items.RG_GERUDO_MASK, Items.RG_MASK_OF_TRUTH):
            items_to_create[mask] = ability_count

    # The plentiful pool adds in extra Gold Skulltula Tokens
    if world.options.item_pool == ItemPool.option_plentiful and world.options.shuffle_skull_tokens:
        items_to_create[Items.RG_GOLD_SKULLTULA_TOKEN] += 10

    # It there are more randomized skulltula tokens than required progression, set the excess to useful
    if items_to_create[Items.RG_GOLD_SKULLTULA_TOKEN] > world.randomized_progressive_skulltula_count:
        demote(world, items_to_create, Items.RG_GOLD_SKULLTULA_TOKEN, ItemClassification.useful | ItemClassification.deprioritized | ItemClassification.skip_balancing, items_to_create[Items.RG_GOLD_SKULLTULA_TOKEN] - world.randomized_progressive_skulltula_count)

    # If you start with enough hearts to do everything and tricks aren't enabled make the rest of them useful
    if not (world.options.enable_all_tricks or str(Tricks.RT_FEWER_TUNIC_REQUIREMENTS) in world.options.tricks_in_logic.value):
        min_hearts_needed: int = 3
        if world.multiworld.state.soh_heart_count[world.player] >= min_hearts_needed:
            demote(world, items_to_create, Items.RG_PIECE_OF_HEART, ItemClassification.useful, items_to_create[Items.RG_PIECE_OF_HEART])
            demote(world, items_to_create, Items.RG_TREASURE_GAME_HEART, ItemClassification.useful, items_to_create[Items.RG_TREASURE_GAME_HEART])
            demote(world, items_to_create, Items.RG_HEART_CONTAINER, ItemClassification.useful, items_to_create[Items.RG_HEART_CONTAINER])
        else:
             # starting health is less than min_hearts_needed
            # Get the total number of heart classifications we have to work with
            total_non_progression_hearts: int = max_hearts - min_hearts_needed

            if total_non_progression_hearts > 0:
                # Heart Piece amount to make useful. Convert to actual hearts, then convert back later
                non_progression_piece_amount: int = (items_to_create[Items.RG_PIECE_OF_HEART] + items_to_create[Items.RG_TREASURE_GAME_HEART]) // 4
            
                if total_non_progression_hearts >= non_progression_piece_amount: 
                    demote(world, items_to_create, Items.RG_PIECE_OF_HEART, ItemClassification.useful, ((non_progression_piece_amount * 4) - 1))
                    demote(world, items_to_create, Items.RG_TREASURE_GAME_HEART, ItemClassification.useful, 1)

                    total_non_progression_hearts -= non_progression_piece_amount
                elif world.options.item_pool not in (ItemPool.option_plentiful, ItemPool.option_minimal):
                    non_progression_piece_amount = total_non_progression_hearts
                    
                    demote(world, items_to_create, Items.RG_PIECE_OF_HEART, ItemClassification.useful, ((non_progression_piece_amount * 4) - 1))
                    demote(world, items_to_create, Items.RG_TREASURE_GAME_HEART, ItemClassification.useful, 1)

                    total_non_progression_hearts = 0

                # Container amount to make useful
                if total_non_progression_hearts >= items_to_create[Items.RG_HEART_CONTAINER]:
                    demote(world, items_to_create, Items.RG_HEART_CONTAINER, ItemClassification.useful, items_to_create[Items.RG_HEART_CONTAINER])
                else:
                    demote(world, items_to_create, Items.RG_HEART_CONTAINER, ItemClassification.useful, total_non_progression_hearts)

    # if Greg isn't necessary to win, make him filler
    if not (world.options.rainbow_bridge == RainbowBridge.option_greg or (world.options.rainbow_bridge and world.options.rainbow_bridge_greg_modifier) or (world.options.ganons_castle_boss_key and world.options.ganons_castle_boss_key_greg_modifier)):
        demote(world, items_to_create, Items.RG_GREG_RUPEE, ItemClassification.filler)

    # Stone of Agony is Progression unless not required for Grottos
    if world.options.enable_all_tricks or str(Tricks.RT_GROTTOS_WITHOUT_AGONY) in world.options.tricks_in_logic:
        demote(world, items_to_create, Items.RG_STONE_OF_AGONY, ItemClassification.filler)

    # Ice Arrows set to filler if not useful (blue fire arrows enabled)
    if not world.options.blue_fire_arrows:
        demote(world, items_to_create, Items.RG_ICE_ARROWS, ItemClassification.filler)

    items: list[SohItem] = list()
    # Add regular item pool
    for item, quantity in items_to_create.items():
        items.extend([world.create_item(item) for _ in range(quantity)])

    filler_bottle_amount: int = 2
    if world.options.zoras_fountain == RSK_ZORAS_FOUNTAIN.option_open:
        filler_bottle_amount += 1
    if world.options.big_poe_target_count == 0:
        filler_bottle_amount += 1

    # Add random filler bottles
    items.extend([world.create_item(world.random.choice(no_rules_bottles)) for _ in range(filler_bottle_amount)])

    world.add_items_to_item_pool_list(items)


def demote(world: "SohWorld", items_to_create: dict[str, int], item: Items, classification: ItemClassification, amount: int = 1) -> None:
    """Move `amount` of an item out of the regular pool into one with a different classification."""
    items_to_create[item] -= create_special_progression_item(world, item, classification, amount)


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
    return (len(world.multiworld.get_unfilled_locations(world.player)) - len(world.item_pool)
            - len(world.pre_fill_pool) + len(get_vanilla_shop_pool(world)))


def get_filler_item(world: "SohWorld") -> str:
    return world.random.choice(filler_items)


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
    if options.small_key_shuffle in (RSK_KEYSANITY.option_vanilla, RSK_KEYSANITY.option_own_dungeon) and CheckArea.RCAREA_FIRE_TEMPLE not in world.mq_dungeons:
        world.multiworld.push_precollected(
            world.create_item(str(Items.RG_FIRE_TEMPLE_SMALL_KEY), True))

    if options.start_with_kokiri_sword:
        world.precollect_from_pool(Items.RG_KOKIRI_SWORD)

    if options.start_with_master_sword and options.shuffle_master_sword:
        world.precollect_from_pool(Items.RG_MASTER_SWORD)

    # doesn't actually do anything logically since deku shields can be lost
    if options.start_with_deku_shield:
        world.precollect_from_pool(Items.RG_DEKU_SHIELD)

    for _ in range({StartWithOcarina.option_fairy_ocarina: 1, StartWithOcarina.option_ocarina_of_time: 2}.get(options.start_with_ocarina.value, 0)):
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
