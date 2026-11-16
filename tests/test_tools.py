import unittest

from sflmc import tools as T


class GoldTiming(unittest.TestCase):
    def test_midas_rank1_is_lost_while_you_sleep(self):
        day = T.checks(6, 22, 2)
        self.assertAlmostEqual(T.gold_cycle(1, 1), 17.28)
        self.assertAlmostEqual(T.harvests_per_day(T.gold_cycle(1, 1), day), 1.0, places=2)      # 06:00 -> 23:17 -> 06:00
        self.assertAlmostEqual(T.harvests_per_day(T.gold_cycle(1, 1), T.checks(6, 24, 2)), 4 / 3, places=2)
        self.assertAlmostEqual(T.harvests_per_day(T.gold_cycle(2, 2), day), 1.5, places=2)      # 3 every 2 days

    def test_stock_and_binding_tool(self):
        full = T.stock({"More Axes": 1, "More Picks": 1}, toolshed=True)
        self.assertEqual((full["Axe"], full["Iron Pickaxe"], full["Pickaxe"]), (350, 15, 160))
        s = T.scenario("x", {"Axe": 228, "Iron Pickaxe": 10.5}, full, {}, 0)
        self.assertEqual(s["binding"], "Iron Pickaxe")                    # (10.5 - 1) / 15 > (228 - 50) / 350
        self.assertAlmostEqual(s["iron_need"], 52.5)


if __name__ == "__main__":
    unittest.main()
