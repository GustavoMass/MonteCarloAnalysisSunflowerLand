import random
import unittest

from sflmc import farm as F
from sflmc import game as G
from sflmc import sim as S

PRICES = {"Corn": 0.02, "Wheat": 0.01, "Barley": 0.02, "Egg": 0.03, "Feather": 0.003,
          "Soybean": 0.002, "Lemon": 0.01, "Radish": 0.008, "Celestine": 0.14, "Truffle": 0.18}


class GameRules(unittest.TestCase):
    def test_levels(self):
        self.assertEqual(G.level_for_xp("Chicken", 0), 0)
        self.assertEqual(G.level_for_xp("Chicken", 59.9), 0)
        self.assertEqual(G.level_for_xp("Chicken", 60), 1)
        self.assertEqual(G.level_for_xp("Chicken", 99999), 15)

    def test_max_level_cycle(self):
        # chicken cycle at L15 is 2720 - 2400 = 320 XP
        self.assertEqual(G.xp_until_ready("Chicken", 2720), 320)
        self.assertEqual(G.xp_until_ready("Chicken", 2720 + 100), 220)
        self.assertTrue(G.completed_cycle("Chicken", 2720 + 300, 20))
        self.assertFalse(G.completed_cycle("Chicken", 2720 + 300, 19))

    def test_love_weights_cover_levels(self):
        self.assertEqual(len(G.LOVE_WEIGHTS), 16)
        for w in G.LOVE_WEIGHTS[1:]:
            self.assertEqual(sum(w), 10)


class Boosts(unittest.TestCase):
    farm = F.Farm({"Restless Animals": 2, "Clucky Grazing": 1, "Efficient Feeding": 1,
                   "Abundant Harvest": 1, "Double Bale": 1, "Featherweight": 1},
                  {"El Pollo Veloz", "Speed Chicken", "Fat Chicken", "Cluckulator", "Chicken Coop", "Bale"})

    def test_chicken_sleep(self):
        self.assertAlmostEqual(F.sleep_hours(self.farm, "Chicken"), (24 - 2) * 0.9 * 0.85)

    def test_diet_skill_buff_and_debuff(self):
        self.assertAlmostEqual(F.food_multiplier(self.farm, "Chicken"), 0.9 * 0.75 * 0.95 * 0.75)
        self.assertAlmostEqual(F.food_multiplier(self.farm, "Cow"), 0.95 * 1.5)

    def test_chonky(self):
        f = self.farm.with_skills({"Chonky Feed": 1}, ["Clucky Grazing"])
        self.assertEqual(F.feed_xp_multiplier(f), 2)
        self.assertAlmostEqual(F.food_multiplier(f, "Cow"), 0.95 * 1.5)

    def test_egg_yield(self):
        # 5 base + coop 1 + abundant 0.2 + bale 0.1*2
        self.assertAlmostEqual(F.yield_amount(self.farm, "Chicken", "Egg", 5), 6.4)
        # featherweight debuff on leather
        self.assertAlmostEqual(F.yield_amount(self.farm, "Cow", "Leather", 4), 3.9)


class Simulation(unittest.TestCase):
    def test_one_level_per_cycle_and_loves(self):
        farm = F.Farm({}, set())
        m = S.AnimalModel(farm, "Chicken", S.Economy(PRICES))
        ev = S.simulate(m, 20, random.Random(1))
        levels = [e[1] for e in ev]
        self.assertEqual(levels[:15], list(range(1, 16)))
        # perfect player always fits both loves into every sleep
        self.assertTrue(all(e[4] == 2 for e in ev[1:]))
        # 24h sleep, no boosts: one claim per day
        self.assertAlmostEqual(ev[5][0] - ev[4][0], 24.0)

    def test_ready_animal_can_still_be_petted(self):
        farm = F.Farm({"Heartwarming Instruments": 1}, set())
        m = S.AnimalModel(farm, "Chicken", S.Economy(PRICES))
        p = S.Pet(m, random.Random(3), xp=100.0)   # level 1, 20 XP short of level 2
        p.feed_and_claim(0.0)                     # feeds to 120 and sleeps
        p.xp, p.item = 230.0, "Music Box"         # 10 XP short of level 3
        p.pet(p.next_time())
        self.assertTrue(p.ready)
        p.item = "Music Box"
        p.pet(p.next_time())                      # second pet while already ready
        self.assertEqual(p.xp, 230 + 75 + 75)     # XP kept, carries past level 3

    def test_herd_sells_and_parks(self):
        from sflmc import herd as H
        m = S.AnimalModel(F.Farm({}, set()), "Cow", S.Economy(PRICES))
        r = H.simulate_herd(m, random.Random(4), start_xp=[], capacity=5, weeks=3, sell=True,
                            counts={"coins": 2, "tickets": 1}, level_pool=[3, 5], coin_points={"3": 500, "5": 900},
                            ticket_amount=7, gems=5, stop_feeding_at=5)
        self.assertEqual(sum(r["weekly"]["sold"]), 9)
        self.assertEqual(sum(r["weekly"]["tickets"]), 21)
        self.assertTrue(all(lv <= 5 for lv in r["sold_levels"]))

if __name__ == "__main__":
    unittest.main()
