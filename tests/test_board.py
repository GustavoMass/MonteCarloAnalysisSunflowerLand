import unittest

from sflmc import board


class WeeklyBoard(unittest.TestCase):
    GRIDS = {"Doll": ["Leather", "Wool", "Leather", "Wool", "Wool", "Wool", "Leather", "Wool", "Leather"],
             "Moo Doll": ["Leather"] * 4 + ["Doll"] + ["Leather"] * 4}

    def items(self, board_rows, prices, inv=None):
        return board.open_items({"board": board_rows}, prices, inv or {}, self.GRIDS,
                                {"fish": {"Tuna": {"baits": ["Grub"], "likes": ["Orange"], "seasons": ["spring"]}},
                                 "chum_amounts": {"Orange": 3}, "guaranteed_bait": {"Fish Stick": ["Tuna"]}},
                                {"Red Cosmos"}, [], "spring")

    def test_only_open_items_and_no_animals_or_obsidian(self):
        out = self.items([{"label": "Moo Doll", "done": True}, {"label": "Pig", "done": False},
                          {"label": "Obsidian", "done": False}, {"label": "Giant Banana", "done": False},
                          {"label": "Tuna", "done": False, "tickets": 3}], {})
        self.assertEqual([r["name"] for r in out], ["Tuna"])
        self.assertEqual(out[0]["guaranteed"], ["Fish Stick"])

    def test_doll_cost_buys_or_crafts_whichever_is_cheaper(self):
        prices = {"Leather": 0.1, "Wool": 0.05}
        r = self.items([{"label": "Moo Doll", "done": False, "tickets": 20}], dict(prices, Doll=9.0))[0]
        doll = next(x for x in r["lines"] if x["item"] == "Doll")
        self.assertEqual(doll["how"], "craft")                       # 4 Leather + 5 Wool = 0.65 < 9
        self.assertAlmostEqual(r["total"], 8 * 0.1 + 0.65)
        r = self.items([{"label": "Moo Doll", "done": False}], dict(prices, Doll=0.3))[0]
        self.assertEqual(next(x for x in r["lines"] if x["item"] == "Doll")["how"], "buy")

    def test_crustacean_trap_and_chum(self):
        r = self.items([{"label": "Octopus", "done": False}], {"Moonfur": 4.0, "Merino Wool": 0.05, "Feather": 0.01})[0]
        w = r["ways"][0]
        self.assertEqual((w["trap"], w["chum"], w["cost"]), ("Mariner Pot", "Moonfur", 4.0))
        self.assertAlmostEqual(w["pot_cost"], 10 * 0.05 + 10 * 0.01)       # pot used up per placement
        self.assertAlmostEqual(w["total"], 4.0 + 0.6)
        self.assertEqual(w["pot_coins"], 500)
        r = self.items([{"label": "Oyster", "done": False}], {})[0]
        self.assertEqual(r["ways"][0]["recipe"]["Red Snapper"], 6)  # Fish Stick: not tradeable, Fish Market recipe


if __name__ == "__main__":
    unittest.main()
