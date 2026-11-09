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
        sched = [(5, {"coins": 2, "tickets": 1})] * 3
        r = H.simulate_herd(m, random.Random(4), start_xp=[], weeks=3, schedule=sched, buffer=None,
                            level_pool=[3, 5], coin_points={"3": 500, "5": 900}, ticket_amount=7, gems=5,
                            stop_feeding_at=5, no_ticket_weeks={2})
        self.assertEqual(sum(r["weekly"]["sold"]), 9)
        self.assertEqual(sum(r["weekly"]["tickets"]), 14)      # week 3 has no ticket bounty
        self.assertTrue(all(lv <= 5 for lv in r["sold_levels"]))

    def test_lean_herd_size(self):
        from sflmc import herd as H
        m = S.AnimalModel(F.Farm({}, set()), "Sheep", S.Economy(PRICES))
        sched = [(10, {"coins": 2, "gems": 1, "tickets": 2})] * 2
        r = H.simulate_herd(m, random.Random(5), start_xp=[], weeks=2, schedule=sched, buffer=1,
                            level_pool=[3], coin_points={"3": 300}, ticket_amount=7, gems=5)
        self.assertEqual(r["weekly"]["herd"], [6, 6])

    def test_pig_trade_in(self):
        from sflmc import herd as H
        prices = dict(PRICES, **{"Pig Bristles": 2.0})
        m = S.AnimalModel(F.Farm({}, set()), "Pig", S.Economy(prices))
        r = H.simulate_herd(m, random.Random(6), start_xp=[], weeks=2, schedule=[(3, {})] * 2, sell=False,
                            level_pool=[5], coin_points={}, ticket_amount=0, gems=0, trade_in_at=9)
        self.assertGreater(sum(r["weekly"]["traded"]), 0)
        self.assertGreater(sum(r["weekly"]["bristles"]), 0)


    def test_sell_lowest_level_first(self):
        from sflmc import herd as H
        m = S.AnimalModel(F.Farm({}, set()), "Chicken", S.Economy(PRICES))
        old = [G.ANIMAL_LEVELS["Chicken"][13]] * 5 + [G.ANIMAL_LEVELS["Chicken"][3]] * 5
        kw = dict(start_xp=old, weeks=1, schedule=[(10, {"coins": 3})], level_pool=[3],
                  coin_points={"3": 300}, ticket_amount=0, gems=0)
        lo = H.simulate_herd(m, random.Random(8), sell_order="lowest", **kw)["sold_levels"]
        hi = H.simulate_herd(m, random.Random(8), sell_order="highest", **kw)["sold_levels"]
        self.assertTrue(lo and hi)
        self.assertLess(max(lo), 10)          # young ones go first
        self.assertGreaterEqual(min(hi), 13)  # old habit sells the old layers

    def test_level_one_has_profit(self):
        from sflmc import analysis as A
        m = S.AnimalModel(F.Farm({}, set()), "Chicken", S.Economy(PRICES))
        r = A.per_level(m, S.run_scenario(m, 20, 20, 3), 0.0)
        self.assertIsNotNone(r["levels"][0]["profit_day"])
        acc = [l["accumulated"]["p50"] for l in r["levels"][:5]]
        self.assertEqual(acc, sorted(acc))    # eggs pay for the feed, so it only grows


class FlowerPlan(unittest.TestCase):
    def test_season_gating_and_beds(self):
        from sflmc import flowerplan as FP
        H = 3600 * 1000
        start = 1_000 * H
        flowers = {"seeds": {"Sunpetal Seed": {"days": 1, "seasons": ["spring", "summer", "autumn", "winter"], "flowers": []},
                             "Clover Seed": {"days": 3, "seasons": ["autumn"], "flowers": []}},
                   "flowers": {"Blue Cosmos": {"seed": "Sunpetal Seed", "days": 1, "parents": [["Cauliflower", 5]]},
                               "Blue Clover": {"seed": "Clover Seed", "days": 3, "parents": [["Rhubarb", 25]]}}}
        farm = {"inventory": {"Sunpetal Seed": 5, "Clover Seed": 5, "Cauliflower": 50, "Rhubarb": 100},
                "flower_beds": [{"name": None}, {"name": None}], "season": "winter", "season_started": start}
        r = FP.plan(farm, flowers, start + H, target_start_ms=start, target_days=3, tz_offset_h=0, awake=(6, 23))
        self.assertTrue(all(s["flower"] != "Blue Clover" for s in r["schedule"]))   # clover is autumn-only
        self.assertEqual(r["schedule"][0]["flower"], "Blue Cosmos")
        for s in r["schedule"]:                                                     # never planted while asleep
            self.assertTrue(6 <= (s["plant"] // H) % 24 < 23)

    def test_parent_grown_first(self):
        from sflmc import flowerplan as FP
        H = 3600 * 1000
        start = 1_000 * H
        all4 = ["spring", "summer", "autumn", "winter"]
        flowers = {"seeds": {"Sunpetal Seed": {"days": 1, "seasons": all4, "flowers": []},
                             "Bloom Seed": {"days": 2, "seasons": all4, "flowers": []}},
                   "flowers": {"Red Cosmos": {"seed": "Sunpetal Seed", "days": 3, "parents": [["Yellow Daffodil", 1]]},
                               "Yellow Daffodil": {"seed": "Bloom Seed", "days": 2, "parents": [["Radish", 5]]}}}
        farm = {"inventory": {"Sunpetal Seed": 5, "Bloom Seed": 5, "Radish": 50},
                "flower_beds": [{"name": None}], "season": "winter", "season_started": start}
        r = FP.plan(farm, flowers, start, target_start_ms=start, target_days=5, tz_offset_h=0, awake=(0, 24))
        names = [s["flower"] for s in r["schedule"]]
        self.assertEqual(names[0], "Yellow Daffodil")                  # parent stocked first
        self.assertTrue(r["schedule"][0]["why"].startswith("parent prep"))
        self.assertIn("Red Cosmos", names)                              # target grown later from a second parent
        self.assertLess(names.index("Yellow Daffodil"), names.index("Red Cosmos"))

    def test_must_have_first(self):
        from sflmc import flowerplan as FP
        H = 3600 * 1000
        start = 1_000 * H
        all4 = ["spring", "summer", "autumn", "winter"]
        flowers = {"seeds": {"Sunpetal Seed": {"days": 1, "seasons": all4, "flowers": []},
                             "Bloom Seed": {"days": 2, "seasons": all4, "flowers": []}},
                   "flowers": {"Red Daffodil": {"seed": "Bloom Seed", "days": 2, "parents": [["Yellow Pansy", 1]]},
                               "Yellow Pansy": {"seed": "Sunpetal Seed", "days": 1, "parents": [["Sunflower", 50]]},
                               "Blue Cosmos": {"seed": "Sunpetal Seed", "days": 1, "parents": [["Cauliflower", 5]]}}}
        farm = {"inventory": {"Sunpetal Seed": 5, "Bloom Seed": 5, "Sunflower": 500, "Cauliflower": 50, "Yellow Pansy": 2},
                "flower_beds": [{"name": None}], "season": "winter", "season_started": start}
        r = FP.plan(farm, flowers, start, target_start_ms=start, target_days=4, tz_offset_h=0, awake=(0, 24),
                    must_have=[{"flower": "Red Daffodil", "count": 1, "by": start + 72 * H}])
        self.assertEqual(r["schedule"][0]["flower"], "Red Daffodil")
        self.assertEqual(r["must_have"][0]["done"], 1)


class GrowthTest(unittest.TestCase):
    def test_level_path_buys_skills_as_points_arrive(self):
        from sflmc import growth
        rules = {"level_xp": {"1": 0, "2": 100, "3": 200, "4": 300}}
        food = {"xp": 50, "extra": 0, "have": 0, "cost_buy": 1.0}
        queue = [{"name": "A", "points": 1, "flower": 5, "coins": 0}, {"name": "B", "points": 2, "flower": 4, "coins": 0}]
        r = growth.level_path({"experience": 0}, food, queue, rules, cooks_per_day=1, top=4)
        self.assertEqual(r["now"], 1)
        self.assertEqual([(s["level"], [k["name"] for k in s["skills"]]) for s in r["steps"]], [(2, ["A"]), (4, ["B"])])
        self.assertAlmostEqual(r["steps"][-1]["cost"], 6.0)    # 300 XP / 50 per cook


if __name__ == "__main__":
    unittest.main()
