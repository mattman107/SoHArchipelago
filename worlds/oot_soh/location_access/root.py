from ..LogicHelpers import *

if TYPE_CHECKING:
    from .. import SohWorld


class EventLocations(StrEnum):
    TRIFORCE_HUNT_COMPLETION = "Triforce Hunt Completion"
    BEAT_GANONDORF = "Beat Ganondorf"
    CHAMBER_OF_SAGES = "Chamber of Sages"


def set_region_rules(world: "SohWorld") -> None:
    # Root
    # Locations
    add_locations(Regions.ROOT, world, [
        (Locations.LINKS_POCKET, lambda bundle: True_())
    ])
    # Connections
    connect_regions(Regions.ROOT, world, [
        (Regions.CHILD_SPAWN, lambda bundle: is_child(bundle)),
        (Regions.ADULT_SPAWN, lambda bundle: is_adult(bundle)),
        (Regions.MINUET_OF_FOREST_WARP, lambda bundle: can_use(Items.MINUET_OF_FOREST, bundle))
    ])

    # Child Spawn
    # Connections
    connect_regions(Regions.CHILD_SPAWN, world, [
        (Regions.KF_LINKS_HOUSE_CHILD, lambda bundle: True_()) # <- Disconnect here for random child spawn
    ])

    # Adult Spawn
    # Connections
    connect_regions(Regions.ADULT_SPAWN, world, [
        (Regions.TEMPLE_OF_TIME_ADULT, lambda bundle: True_()) # <- Disconnect here for random adult spawn
    ])

    # Minuet of Forest Warp
    # Connections
    connect_regions(Regions.MINUET_OF_FOREST_WARP, world, [
        (Regions.KOKIRI_FOREST_CHILD, lambda bundle: is_child(bundle)),

    ])

    # Temple of Time Child
    # Connections
    connect_regions(Regions.TEMPLE_OF_TIME_CHILD, world, [
        (Regions.BEYOND_DOOR_OF_TIME, lambda bundle: can_use(Items.SONG_OF_TIME, bundle)),
        (Regions.KOKIRI_FOREST_CHILD, lambda bundle: True_())
    ])

    # Temple of Time Adult
    # Locations
    add_locations(Regions.TEMPLE_OF_TIME_ADULT, world, [
        (Locations.MARKET_TOT_LIGHT_ARROW_CUTSCENE, lambda bundle: can_trigger_lacs(bundle))
    ])
    # Connections
    connect_regions(Regions.TEMPLE_OF_TIME_ADULT, world, [
        (Regions.BEYOND_DOOR_OF_TIME, lambda bundle: can_use(Items.SONG_OF_TIME, bundle)),
        (Regions.KOKIRI_FOREST_ADULT, lambda bundle: True_())
    ])

    # Beyond Door of Time
    # Events
    add_events(Regions.BEYOND_DOOR_OF_TIME, world, [
        (EventLocations.CHAMBER_OF_SAGES,
         Events.TIME_TRAVEL, lambda bundle: True_())
    ])
    # Locations
    add_locations(Regions.BEYOND_DOOR_OF_TIME, world, [
        (Locations.GIFT_FROM_RAURU, lambda bundle: True_())
    ])
    # Connections
    connect_regions(Regions.BEYOND_DOOR_OF_TIME, world, [
        (Regions.TEMPLE_OF_TIME_CHILD, lambda bundle: is_child(bundle)),
        (Regions.TEMPLE_OF_TIME_ADULT, lambda bundle: is_adult(bundle)),
        (Regions.MASTER_SWORD_PEDESTAL, lambda bundle: True_())
    ])

    # Get Master Sword
    # Locations
    add_locations(Regions.MASTER_SWORD_PEDESTAL, world, [
        (Locations.MARKET_TOT_MASTER_SWORD, lambda bundle: True_()),
    ])

    # KF Link's House Child
    # Connections
    connect_regions(Regions.KF_LINKS_HOUSE_CHILD, world, [
        (Regions.KOKIRI_FOREST_CHILD, lambda bundle: True_()),
        (Regions.KF_LINKS_HOUSE_SHARED, lambda bundle: True_())
    ])

    # KF Link's House Shared
    # Locations
    add_locations(Regions.KF_LINKS_HOUSE_SHARED, world, [
        (Locations.KF_LINKS_HOUSE_POT, lambda bundle: can_break_pots(bundle))
    ])

    # KF Link's House Adult
    # Connections
    connect_regions(Regions.KF_LINKS_HOUSE_ADULT, world, [
        (Regions.KOKIRI_FOREST_ADULT, lambda bundle: True_()),
        (Regions.KF_LINKS_HOUSE_SHARED, lambda bundle: True_())
    ])

    # Kokiri Forest Child
    # Locations
    add_locations(Regions.KOKIRI_FOREST_CHILD, world, [
        (Locations.KF_KOKIRI_SWORD_CHEST, lambda bundle: True_())
    ])
    # Connections
    connect_regions(Regions.KOKIRI_FOREST_CHILD, world, [
        (Regions.KF_LINKS_HOUSE_CHILD, lambda bundle: True_()),
        (Regions.KOKIRI_FOREST_SHARED, lambda bundle: True_()),
        (Regions.KF_MIDOS_HOUSE_CHILD, lambda bundle: True_()),
        (Regions.TEMPLE_OF_TIME_CHILD, lambda bundle: True_())
    ])

    # Kokiri Forest Shared
    # Locations
    add_locations(Regions.KOKIRI_FOREST_SHARED, world, [
        (Locations.KF_SHOP_ITEM1, lambda bundle: can_afford_slot(Locations.KF_SHOP_ITEM1, bundle)),
        (Locations.KF_SHOP_ITEM2, lambda bundle: can_afford_slot(Locations.KF_SHOP_ITEM2, bundle)),
        (Locations.KF_SHOP_ITEM3, lambda bundle: can_afford_slot(Locations.KF_SHOP_ITEM3, bundle)),
        (Locations.KF_SHOP_ITEM4, lambda bundle: can_afford_slot(Locations.KF_SHOP_ITEM4, bundle)),
        (Locations.KF_SHOP_ITEM5, lambda bundle: can_afford_slot(Locations.KF_SHOP_ITEM5, bundle)),
        (Locations.KF_SHOP_ITEM6, lambda bundle: can_afford_slot(Locations.KF_SHOP_ITEM6, bundle)),
        (Locations.KF_SHOP_ITEM7, lambda bundle: can_afford_slot(Locations.KF_SHOP_ITEM7, bundle)),
        (Locations.KF_SHOP_ITEM8, lambda bundle: can_afford_slot(Locations.KF_SHOP_ITEM8, bundle))    
    ])

    # Kokiri Forest Adult
    # Locations
    add_locations(Regions.KOKIRI_FOREST_ADULT, world, [
        (Locations.KF_GS_HOUSE_OF_TWINS, lambda bundle: hookshot_or_boomerang(bundle))
    ])
    # Connections
    connect_regions(Regions.KOKIRI_FOREST_ADULT, world, [
        (Regions.KF_LINKS_HOUSE_ADULT, lambda bundle: True_()),
        (Regions.KF_LINKS_HOUSE_SHARED, lambda bundle: True_()),
        (Regions.KF_MIDOS_HOUSE_ADULT, lambda bundle: True_()),
        (Regions.TEMPLE_OF_TIME_ADULT, lambda bundle: True_()),
        (Regions.GANONDORFS_LAIR, lambda bundle: Has(Items.GREG_THE_GREEN_RUPEE))
    ])

    # KF Mido's House Child
    # Connections
    connect_regions(Regions.KF_MIDOS_HOUSE_CHILD, world, [
        (Regions.KOKIRI_FOREST_CHILD, lambda bundle: True_()),
        (Regions.KF_MIDOS_HOUSE_SHARED, lambda bundle: True_())
    ])

    # KF Mido's House Shared
    # Locations
    add_locations(Regions.KF_MIDOS_HOUSE_SHARED, world, [
        (Locations.KF_MIDO_TOP_LEFT_CHEST, lambda bundle: True_()),
        (Locations.KF_MIDO_TOP_RIGHT_CHEST, lambda bundle: True_()),
        (Locations.KF_MIDO_BOTTOM_LEFT_CHEST, lambda bundle: True_()),
        (Locations.KF_MIDO_BOTTOM_RIGHT_CHEST, lambda bundle: True_())
    ])

    # KF Mido's House Adult
    # Connections
    connect_regions(Regions.KF_MIDOS_HOUSE_ADULT, world, [
        (Regions.KOKIRI_FOREST_ADULT, lambda bundle: True_()),
        (Regions.KF_MIDOS_HOUSE_SHARED, lambda bundle: True_())
    ])

    #Ganondorfs Lair
    #Events
    add_events(Regions.GANONDORFS_LAIR, world, [
        (EventLocations.BEAT_GANONDORF, Events.GAME_COMPLETED, lambda bundle: True_())
    ])