from test.bases import WorldTestBase
from ..Items import Items, SohItem
from BaseClasses import ItemClassification as IC
from ..Enums import Regions

class SohTestBase(WorldTestBase):
    game = "Ship of Harkinian"
    glitches_item_name = Items.GLITCHED

    def enable_glitched_item(self):
        """
        Enable the use of the glitched/sequence breaking item for unit test purposes.

        Also automatically award the item for convenience sake.
        """
        self.collect(self.world.create_item(Items.GLITCHED))

    def get_bundle(self) -> tuple:
        return self.multiworld.state, Regions.ROOT, self.world
    
    def create_item(self, item) -> SohItem:
        return SohItem(item, IC.progression, None, self.world.player)
    
    def sweep(self) -> None:
        self.multiworld.state.sweep_for_advancements()
