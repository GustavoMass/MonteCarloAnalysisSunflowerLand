import unittest

from sflmc import nfts


class CheapNfts(unittest.TestCase):
    FARM = {"weeks_played": 1, "activity": {"Honey Harvested": 20, "Apple Seed Planted": 2, "Apple Harvested": 10},
            "collectibles": ["Macaw"], "wearables": []}

    def rows(self, market, boosts=(), usd=0.1, cap=30):
        return {r["name"]: r for r in nfts.evaluate(self.FARM, {"Honey": 0.1, "Apple": 0.02}, market, list(boosts),
                                                    set(), usd, cap_usd=cap, tax=0.1)}

    def test_flat_bonus_from_weekly_activity_and_resale(self):
        r = self.rows({"Bee Suit": {"price": 40, "kind": "wearable"}})["Bee Suit"]
        self.assertAlmostEqual(r["week"], 0.1 * 20 * 0.1 * 0.9)          # bonus x harvests x price x (1 - tax)
        self.assertAlmostEqual(r["payback_weeks"], 40 / r["week"])
        self.assertAlmostEqual(r["resale_weeks"], 4 / r["week"])           # only the marketplace cut

    def test_owned_and_over_cap_left_out(self):
        out = self.rows({"Macaw": {"price": 1}, "Lady Bug": {"price": 500}, "Spa Sheep": {"price": 30}},
                        boosts=[{"name": "Spa Sheep", "flower": 12.0}])
        self.assertEqual(set(out), {"Spa Sheep"})                         # Macaw owned, Lady Bug $50 > $30
        self.assertAlmostEqual(out["Spa Sheep"]["week"], 1.0)              # herd sim per chapter / 12


if __name__ == "__main__":
    unittest.main()
