from .. import SohWorld
from ..Items import Items, SohItem
from BaseClasses import ItemClassification as IC
from ..Enums import Regions, Events, Enemies
from .bases import SohTestBase
from ..LogicHelpers import can_kill_enemy
from itertools import combinations

class KillBase(SohTestBase):
    __Test__ = False
    def get_bundle(self) -> tuple:
        return self.multiworld.state, Regions.ROOT, self.world
    
    def create_item(self, item) -> SohItem:
        return SohItem(item, IC.progression, None, self.world.player)
    
    def sweep(self) -> None:
        self.multiworld.state.sweep_for_advancements()

# Can Kill Bosses
class TestAccessCanKillBoss(KillBase):
    """
    Testing to see if we can kill all the bosses without boss souls on
    """
    options = {"shuffle_boss_souls": 0, "closed_forest": 2, "door_of_time": 2}
    world: SohWorld

    def require_all_to_beat(self, items: list[Items | Events], enemy: Enemies) -> None:
        # ideally we run these as subtests, but those are currently broken 
        # and report as Success if any subtest succeeds
        # (https://github.com/microsoft/vscode-python/issues/25824)

        self.sweep()
        self.remove_by_name(items)

        for size in range(1, len(items)):
            for invalid_combo in combinations(items, size):
                self.collect_by_name(invalid_combo)
                self.assertFalse(can_kill_enemy(self.get_bundle(), enemy), f"Was able to kill {str(enemy)}, but shouldn't have been able to with only {invalid_combo}")
                self.remove_by_name(invalid_combo)
                

        self.collect_by_name(items)

        self.assertTrue(can_kill_enemy(self.get_bundle(), enemy), f"Wasn't able to kill {str(enemy)}, but should have been able to.")


    def test_queen_gohma(self):
        """
        Checking if player can kill Queen Ghoma
        """
        items = []

        if self.options["shuffle_boss_souls"]  >= 1:
            items.append(Items.GOHMAS_SOUL)

        self.require_all_to_beat(items, Enemies.GOHMA)

    def test_king_dodongo(self):
        """
        Checking if player can kill King Dodongo
        """
        items = [Items.PROGRESSIVE_BOMB_BAG]

        if self.options["shuffle_boss_souls"]  >= 1:
            items.append(Items.KING_DODONGOS_SOUL)

        self.require_all_to_beat(items, Enemies.KING_DODONGO)

    def test_barinade(self):
        """
        Checking if player can kill Barinade
        """
        items = [Items.BOOMERANG]

        if self.options["shuffle_boss_souls"]  >= 1:
            items.append(Items.BARINADES_SOUL)

        self.require_all_to_beat(items, Enemies.BARINADE)

    def test_phantom_ganon(self):
        """
        Checking if player can kill Phantom Ganon
        """
        items = [Items.PROGRESSIVE_HOOKSHOT]

        if self.options["shuffle_boss_souls"]  >= 1:
            items.append(Items.PHANTOM_GANONS_SOUL)

        self.require_all_to_beat(items, Enemies.PHANTOM_GANON)

    def test_volvagia(self):
        """
        Checking if player can kill Volvagia
        """
        items = [Items.MEGATON_HAMMER]

        if self.options["shuffle_boss_souls"]  >= 1:
            items.append(Items.VOLVAGIAS_SOUL)

        self.require_all_to_beat(items, Enemies.VOLVAGIA)

    def test_morpha(self):
        """
        Checking if player can kill Morpha
        """
        items = [Items.PROGRESSIVE_HOOKSHOT]

        if self.options["shuffle_boss_souls"]  >= 1:
            items.append(Items.MORPHAS_SOUL)

        self.require_all_to_beat(items, Enemies.MORPHA)

    def test_bongo_bongo(self):
        """
        Checking if player can kill Bongo Bongo
        """
        items = [Items.PROGRESSIVE_HOOKSHOT, Items.LENS_OF_TRUTH, Items.PROGRESSIVE_MAGIC_METER]

        if self.options["shuffle_boss_souls"]  >= 1:
            items.append(Items.BONGO_BONGOS_SOUL)

        self.require_all_to_beat(items, Enemies.BONGO_BONGO)

    def test_twinrova(self):
        """
        Checking if player can kill Twinrova
        """
        items = [Items.MIRROR_SHIELD]

        if self.options["shuffle_boss_souls"]  >= 1:
            items.append(Items.TWINROVAS_SOUL)

        self.require_all_to_beat(items, Enemies.TWINROVA)

    def test_ganondorf(self):
        """
        Checking if player can kill Ganondorf
        """
        items = [Items.PROGRESSIVE_MAGIC_METER, Items.LIGHT_ARROW, Items.PROGRESSIVE_BOW]

        if self.options["shuffle_boss_souls"] == 2:
            items.append(Items.GANONS_SOUL)

        self.require_all_to_beat(items, Enemies.GANONDORF)

    def test_ganon(self):
        """
        Checking if player can kill Ganon
        """
        items = []

        if self.options["shuffle_boss_souls"] == 2:
            items.append(Items.GANONS_SOUL)

        self.require_all_to_beat(items, Enemies.GANON)        
        
# Derivative of without boss soul test
class TestAccessCanKillBossWithSoul(TestAccessCanKillBoss):
    """
    Testing to see if we can kill all the bosses with boss souls on
    """
    options = {"shuffle_boss_souls": 1, "closed_forest": 2, "door_of_time": 2, "jabu_jabu": 1, "zoras_fountain": 2, "sleeping_waterfall": 1,"small_key_shuffle": 5, "boss_key_shuffle": 5, "key_rings": 1, "key_rings_count": 9,
               "shuffle_songs": 3}
    world: SohWorld

# Derivative of without boss soul test with ganons soul
class TestAccessCanKillBossWithSoulPlus(TestAccessCanKillBoss):
    """
    Testing to see if we can kill all the bosses with boss souls on
    """
    options = {"shuffle_boss_souls": 2, "closed_forest": 2, "door_of_time": 2, "jabu_jabu": 1, "zoras_fountain": 2, "sleeping_waterfall": 1,"small_key_shuffle": 5, "boss_key_shuffle": 5, "key_rings": 1, "key_rings_count": 9,
               "shuffle_songs": 3}
    world: SohWorld