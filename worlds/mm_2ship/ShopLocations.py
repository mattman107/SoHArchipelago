"""
Shop and Tingle shop locations that need randomized prices.

Derived from the generated LOCATION_RCTYPE table so new shop checks flow in
automatically when the apworld data is regenerated.
"""

from .Enums import Locations
from .LocationData import LOCATION_RCTYPE

# All shop locations (RCTYPE_SHOP)
shop_locations: set[Locations] = {
    Locations[key] for key, rctype in LOCATION_RCTYPE.items() if rctype == "RCTYPE_SHOP"
}

# All tingle shop locations (RCTYPE_TINGLE_SHOP)
tingle_shop_locations: set[Locations] = {
    Locations[key] for key, rctype in LOCATION_RCTYPE.items() if rctype == "RCTYPE_TINGLE_SHOP"
}

# Combined set of all shop/tingle locations that need prices
all_shop_locations: set[Locations] = shop_locations | tingle_shop_locations
