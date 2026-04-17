from .. import SohWorld
from ..Items import Items, SohItem
from BaseClasses import ItemClassification as IC
from ..Enums import Regions, Events, Enemies, EnemyDistance
from .bases import SohTestBase
from ..LogicHelpers import can_kill_enemy
from itertools import combinations

class KillBase(SohTestBase):
    __Test__ = False

    def require_all_to_beat(self, items: list[Items | Events], enemy: Enemies, distance: EnemyDistance = EnemyDistance.CLOSE,
                   wall_or_floor: bool = True, quantity: int = 1, timer: bool = False, in_water: bool = False) -> None:
        # ideally we run these as subtests, but those are currently broken 
        # and report as Success if any subtest succeeds
        # (https://github.com/microsoft/vscode-python/issues/25824)

        self.sweep()
        self.remove_by_name(items)

        for size in range(1, len(items)):
            for invalid_combo in combinations(items, size):
                self.collect_by_name(invalid_combo)
                self.assertFalse(can_kill_enemy(self.get_bundle(), enemy, distance, wall_or_floor, quantity, timer, in_water), f"Was able to kill {quantity} {str(enemy)}, but shouldn't have been able to with only {invalid_combo} at distance {str(distance.name)} {"on wall or floor" if wall_or_floor else "not on wall or floor"}")
                self.remove_by_name(invalid_combo)
                

        self.collect_by_name(items)

        self.assertTrue(can_kill_enemy(self.get_bundle(), enemy, distance, wall_or_floor, quantity, timer, in_water), f"Wasn't able to kill {quantity} {str(enemy)}, but should have been able to at distance {str(distance.name)} {"on wall or floor" if wall_or_floor else "not on wall or floor"}")

        self.remove_by_name(items)

    def require_any_to_beat(self, items: list[Items | Events], enemy: Enemies, distance: EnemyDistance = EnemyDistance.CLOSE,
                   wall_or_floor: bool = True, quantity: int = 1, timer: bool = False, in_water: bool = False) -> None:
        # ideally we run these as subtests, but those are currently broken 
        # and report as Success if any subtest succeeds
        # (https://github.com/microsoft/vscode-python/issues/25824)

        self.sweep()
        self.remove_by_name(items)

        for size in range(1, len(items)):
            for valid_combo in combinations(items, size):
                self.collect_by_name(valid_combo)
                self.assertTrue(can_kill_enemy(self.get_bundle(), enemy, distance, wall_or_floor, quantity, timer, in_water), f"Wasn't able to kill {quantity} {str(enemy)}, but should have been able to with only {valid_combo} at distance {str(distance.name)} {"on wall or floor" if wall_or_floor else "not on wall or floor"}")
                self.remove_by_name(valid_combo)
                

        self.collect_by_name(items)

        self.assertTrue(can_kill_enemy(self.get_bundle(), enemy, distance, wall_or_floor, quantity, timer, in_water), f"Wasn't able to kill {quantity} {str(enemy)}, but should have been able to at distance {str(distance.name)} {"on wall or floor" if wall_or_floor else "not on wall or floor"}")
        
        self.remove_by_name(items)

# Can Kill Regular Enemies
class TestCanKillEnemy(KillBase):
    options = {"shuffle_deku_nut_bag": True, "shuffle_deku_stick_bag": True, "closed_forest": 2, "door_of_time": 0, "shuffle_kokiri_sword": 1}

    """
    Testing to see if we can kill regular enemies. 
    This only checks for special cases, not other helper functions
    """
    def test_gerudo_guard(self):
        """
        Checking if player can kill Gerudo Guard
        """
        for enemy in (Enemies.GERUDO_GUARD, Enemies.BREAK_ROOM_GUARD):
            self.assertFalse(can_kill_enemy(self.get_bundle(), enemy), f'Could kill {str(enemy)}. This should be impossible.')

    def test_gold_skulltula(self):
        """
        Checking if player can kill Gold Skulltula
        """
        enemy = Enemies.GOLD_SKULLTULA
        items = [Items.BOOMERANG]
        # Boomerang and Hookshot overlapping distances
        for distance in (EnemyDistance.CLOSE, EnemyDistance.SHORT_JUMPSLASH, EnemyDistance.MASTER_SWORD_JUMPSLASH, 
                         EnemyDistance.LONG_JUMPSLASH, EnemyDistance.BOMB_THROW, EnemyDistance.BOOMERANG):
            self.require_all_to_beat(items, enemy, distance)

        # Dins Fire
        items = [Items.PROGRESSIVE_MAGIC_METER, Items.DINS_FIRE]
        for distance in (EnemyDistance.CLOSE, EnemyDistance.SHORT_JUMPSLASH, EnemyDistance.MASTER_SWORD_JUMPSLASH, 
                         EnemyDistance.LONG_JUMPSLASH, EnemyDistance.BOMB_THROW, EnemyDistance.BOOMERANG):
            self.require_all_to_beat(items, enemy, distance)

        # Bombchus
        items = [Items.PROGRESSIVE_BOMB_BAG]
        for distance in (EnemyDistance.CLOSE, EnemyDistance.SHORT_JUMPSLASH, EnemyDistance.MASTER_SWORD_JUMPSLASH, 
                         EnemyDistance.LONG_JUMPSLASH, EnemyDistance.BOMB_THROW, EnemyDistance.BOOMERANG, 
                         EnemyDistance.HOOKSHOT, EnemyDistance.LONGSHOT):
            self.require_all_to_beat(items, enemy, distance)

    def test_big_skulltula(self):
        """
        Checking if player can kill Big Skulltula
        """
        enemy = Enemies.BIG_SKULLTULA
        items = [Items.BOOMERANG]

        # Dins Fire
        items = [Items.PROGRESSIVE_MAGIC_METER, Items.DINS_FIRE]
        for distance in (EnemyDistance.CLOSE, EnemyDistance.SHORT_JUMPSLASH, EnemyDistance.MASTER_SWORD_JUMPSLASH, 
                         EnemyDistance.LONG_JUMPSLASH, EnemyDistance.BOMB_THROW, EnemyDistance.BOOMERANG):
            self.require_all_to_beat(items, enemy, distance)

    def test_dodongo(self):
        """
        Checking if player can kill Dodongo
        """
        enemy = Enemies.DODONGO
     
 
        items = [Items.MEGATON_HAMMER, Items.PROGRESSIVE_SLINGSHOT, Items.PROGRESSIVE_BOW]
        self.require_any_to_beat(items, enemy)

        # Sticks
        items = [Items.PROGRESSIVE_STICK_CAPACITY]
        for i in range(1,6):
            self.require_any_to_beat(items, enemy, quantity=i)

    def test_lizalfos(self):
        """
        Checking if player can kill Lizalfos
        """
        enemy = Enemies.DODONGO
     
 
        items = [Items.MEGATON_HAMMER, Items.PROGRESSIVE_SLINGSHOT, Items.PROGRESSIVE_BOW]
        self.require_any_to_beat(items, enemy)

        # Sticks
        items = [Items.PROGRESSIVE_STICK_CAPACITY]
        for i in range(1,6):
            self.require_any_to_beat(items, enemy, quantity=i)

    # def test_keese(self):
    #     for enemy in (Enemies.KEESE, Enemies.FIRE_KEESE):



# Can Kill Bosses
class TestCanKillBoss(KillBase):
    """
    Testing to see if we can kill all the bosses without boss souls on
    """
    options = {"shuffle_boss_souls": 0, "closed_forest": 2, "door_of_time": 2}
    world: SohWorld

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
class TestAccessCanKillBossWithSoul(TestCanKillBoss):
    """
    Testing to see if we can kill all the bosses with boss souls on
    """
    options = {"shuffle_boss_souls": 1, "closed_forest": 2, "door_of_time": 2, "jabu_jabu": 1, "zoras_fountain": 2, "sleeping_waterfall": 1,"small_key_shuffle": 5, "boss_key_shuffle": 5, "key_rings": 1, "key_rings_count": 9,
               "shuffle_songs": 3}
    world: SohWorld

# Derivative of without boss soul test with ganons soul
class TestAccessCanKillBossWithSoulPlus(TestCanKillBoss):
    """
    Testing to see if we can kill all the bosses with boss souls on
    """
    options = {"shuffle_boss_souls": 2, "closed_forest": 2, "door_of_time": 2, "jabu_jabu": 1, "zoras_fountain": 2, "sleeping_waterfall": 1,"small_key_shuffle": 5, "boss_key_shuffle": 5, "key_rings": 1, "key_rings_count": 9,
               "shuffle_songs": 3}
    world: SohWorld