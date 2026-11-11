"""Flower plan invariants: whatever the goals, the plan must be something you can actually do.

Checked on a synthetic 4-bed farm and, when present, on your live farm in Data/.
"""
import datetime as dt
import json
import os
import unittest

from sflmc import flowerplan as FP

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "Data")
H = 3600 * 1000
DAY = 24 * H
SEASONS = ["spring", "summer", "autumn", "winter"]


def _load(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        return json.load(f)


def check(tc, farm, flowers, r, tz, awake, label):
    """Assert every invariant on the full (unseen) plan."""
    fl, seeds = flowers["flowers"], flowers["seeds"]
    sched = r["schedule_full"]
    nbeds = len(farm["flower_beds"])
    tc.assertGreater(len(sched), 0, f"{label}: nothing planned")
    # 1. bed numbers exist; no overlap inside a bed; a bed is replanted only after its flower is ready
    beds = {b["bed"]: b for b in r["beds"]}
    by_bed = {}
    for x in sched:
        tc.assertIn(x["bed"], range(1, nbeds + 1), f"{label}: bed {x['bed']} does not exist")
        by_bed.setdefault(x["bed"], []).append(x)
    for b, xs in by_bed.items():
        xs.sort(key=lambda x: x["plant"])
        prev = beds[b]["ready"] if beds[b].get("growing") else None
        for x in xs:
            if prev is not None:
                tc.assertGreaterEqual(x["plant"], prev, f"{label}: bed {b} planted before it was free")
            tc.assertGreater(x["ready"], x["plant"])
            prev = x["ready"]
    # 2. never more flowers growing at once than beds
    ev = [(x["plant"], 1) for x in sched] + [(x["ready"], -1) for x in sched]
    ev += [(0, 1) for b in r["beds"] if b.get("growing")] + [(b["ready"], -1) for b in r["beds"] if b.get("growing")]
    n = peak = 0
    for _, d in sorted(ev, key=lambda e: (e[0], e[1])):
        n += d
        peak = max(peak, n)
    tc.assertLessEqual(peak, nbeds, f"{label}: {peak} flowers growing at once in {nbeds} beds")
    # 3. planted only while awake
    for x in sched:
        h = (dt.datetime.fromtimestamp(x["plant"] / 1000, dt.timezone.utc) + dt.timedelta(hours=tz)).hour
        tc.assertTrue(awake[0] <= h < awake[1], f"{label}: planted at {h}:00 while asleep")
    # 4. a flower used to cross-breed exists at that moment (no invented flowers)
    stock = {k: int(farm["inventory"].get(k, 0)) for k in fl}
    events = [(b["ready"], 0, b["growing"], 1) for b in r["beds"] if b.get("growing")]
    for x in sched:
        events.append((x["ready"], 0, x["flower"], 1))
        q, parent = x["cross"].split(" ", 1)
        if parent in fl:
            events.append((x["plant"], 1, parent, -int(q)))
    for t, _, name, d in sorted(events, key=lambda e: (e[0], e[1])):
        stock[name] += d
        tc.assertGreaterEqual(stock[name], 0, f"{label}: {name} crossed away before it existed")
    # 5. seasonal seeds only in their season
    s0, season0 = farm["season_started"], farm["season"]
    for x in sched:
        season = SEASONS[(SEASONS.index(season0) + int((x["plant"] - s0) // (7 * DAY))) % 4]
        tc.assertIn(season, seeds[fl[x["flower"]]["seed"]]["seasons"], f"{label}: {x['flower']} out of season")
    # 6. grow time is the game's: seed base time x your permanent boosts (never faster)
    mult, _ = FP.grow_multiplier(farm)
    for x in sched:
        base = seeds[fl[x["flower"]]["seed"]]["days"] * DAY
        tc.assertAlmostEqual(x["ready"] - x["plant"], base * mult, delta=1000,
                             msg=f"{label}: {x['flower']} grows in {(x['ready'] - x['plant']) / H:.1f} h")
    # 7. beds growing now are ready when the game says (plantedAt + baseDurationMs)
    for b, fb in zip(r["beds"], farm["flower_beds"]):
        if b.get("growing"):
            tc.assertEqual(b["ready"], FP.bed_ready(fb, flowers))
    # 8. shown part is the first two weeks only
    for x in r["schedule"]:
        tc.assertLess(x["plant"], r["horizon"])


class GrowTimeRules(unittest.TestCase):
    def test_multiplier_from_boosts(self):
        self.assertEqual(FP.grow_multiplier({})[0], 1.0)
        self.assertAlmostEqual(FP.grow_multiplier({"skills": {"Blooming Boost": 1}})[0], 0.9)
        self.assertAlmostEqual(FP.grow_multiplier({"skills": {"Blooming Boost": 2, "Flower Power": 1},
                                                   "wearables": ["Flower Crown"], "collectibles": ["Flower Fox"]})[0],
                               0.875 * 0.8 * 0.5 * 0.9)

    def test_bed_ready_uses_base_duration(self):
        fl = {"flowers": {"Purple Cosmos": {"seed": "Sunpetal Seed"}}, "seeds": {"Sunpetal Seed": {"days": 1}}}
        self.assertEqual(FP.bed_ready({"name": "Purple Cosmos", "planted_at": 1000, "base_duration_ms": 77_760_000}, fl),
                         1000 + 77_760_000)                                  # speed-rate model
        self.assertEqual(FP.bed_ready({"name": "Purple Cosmos", "planted_at": 1000}, fl), 1000 + DAY)  # legacy

    @unittest.skipUnless(os.path.exists(os.path.join(DATA, "farm_3621107187220366.json")), "needs your farm")
    def test_live_sunpetal_takes_most_of_a_day(self):
        farm, flowers = _load("farm_3621107187220366.json"), _load("flowers.json")
        mult, _ = FP.grow_multiplier(farm)
        self.assertGreaterEqual(flowers["seeds"]["Sunpetal Seed"]["days"] * DAY * mult, 12 * H)


class FlowerPlanInvariants(unittest.TestCase):
    PRIO = {"parents_over_days": 5, "guria": ["Purple Daffodil", "Blue Balloon Flower", "Red Balloon Flower"],
            "guria_each": 2, "seasonal_each": 2, "every_each": 2,
            "bloom_doll": {"Prism Petal": 3, "Celestial Frostbloom": 2, "Primula Enigma": 3},
            "floral_bed": {"Prism Petal": 1, "Celestial Frostbloom": 1, "Primula Enigma": 1,
                           "Red Pansy": 1, "Blue Pansy": 1, "Yellow Pansy": 1}}

    def run_plan(self, farm, flowers, board, now, tz, awake):
        owed = FP.needs(farm, flowers, board, now, prio=self.PRIO)
        return FP.plan_week(farm, flowers, now, {}, must_have=owed, tz_offset_h=tz, awake=awake,
                            extend_days=8 * 7, keep_full=True)

    @unittest.skipUnless(os.path.exists(os.path.join(DATA, "flowers.json")), "needs Data/flowers.json")
    def test_synthetic_four_beds(self):
        flowers = _load("flowers.json")
        start = 1_794_000_000_000
        crops = {c: 500 for c in ["Sunflower", "Potato", "Pumpkin", "Carrot", "Cabbage", "Beetroot", "Cauliflower",
                                  "Parsnip", "Eggplant", "Corn", "Radish", "Wheat", "Kale", "Barley", "Artichoke",
                                  "Onion", "Rhubarb", "Pepper", "Apple", "Banana", "Blueberry", "Orange", "Tomato",
                                  "Lemon", "Grape", "Zucchini", "Yam", "Broccoli", "Soybean", "Turnip"]}
        farm = {"inventory": dict(crops, **{"White Carnation": 1, "Yellow Cosmos": 2, "Blue Pansy": 1}),
                "flower_beds": [{"name": "Yellow Lotus", "planted_at": start - DAY, "boosted_ms": 0},
                                {"name": None}, {"name": "Purple Cosmos", "planted_at": start - 2 * H, "boosted_ms": 0},
                                {"name": None}],
                "season": "winter", "season_started": start - 3 * DAY,
                "orders": [{"from": "raven", "items": {"Red Edelweiss": 1}}],
                "chores": [{"npc": "guria", "name": "Grow Blue Pansy 6 times", "initial": 0,
                            "reward": {"items": {"Duende Cap": 3}}}],
                "activity": {}}
        board = {"board": [{"category": "Flowers", "label": "Blue Daffodil", "done": False}]}
        r = self.run_plan(farm, flowers, board, start, -3, (6, 23))
        check(self, farm, flowers, r, -3, (6, 23), "synthetic")
        # goals go in order: the first planting serves goal 1 or 2
        self.assertLessEqual(r["schedule_full"][0]["tier"], 2)

    @unittest.skipUnless(os.path.exists(os.path.join(DATA, "farm_3621107187220366.json")), "needs your farm")
    def test_live_farm(self):
        farm, flowers = _load("farm_3621107187220366.json"), _load("flowers.json")
        board = _load("board_week.json") if os.path.exists(os.path.join(DATA, "board_week.json")) else {}
        cfg = _load(os.path.join("..", "config.json"))
        tz, awake = cfg.get("timezone_offset_hours", 0), tuple(cfg.get("awake_hours", (0, 24)))
        now = max([b["planted_at"] for b in farm["flower_beds"] if b.get("planted_at")] + [farm["season_started"]])
        owed = FP.needs(farm, flowers, board, now, prio=cfg.get("flower_priorities", self.PRIO))
        r = FP.plan_week(farm, flowers, now, {}, must_have=owed, tz_offset_h=tz, awake=awake,
                         extend_days=8 * 7, keep_full=True)
        check(self, farm, flowers, r, tz, awake, "live farm")

    @unittest.skipUnless(os.path.exists(os.path.join(DATA, "farm_3621107187220366.json")), "needs your farm")
    def test_bloom_doll_first_takes_weeks_not_months(self):
        """3 Primula Enigma, 3 Prism Petal, 2 Celestial Frostbloom with all 4 beds: the chains run side by
        side, the longest (Primula, 4 steps) first. Must finish inside 4 weeks."""
        farm, flowers = _load("farm_3621107187220366.json"), _load("flowers.json")
        cfg = _load(os.path.join("..", "config.json"))
        now = max([b["planted_at"] for b in farm["flower_beds"] if b.get("planted_at")] + [farm["season_started"]])
        doll = [m for m in FP.needs(farm, flowers, {}, now, prio=cfg["flower_priorities"]) if m["note"] == "Bloom Doll"]
        for m in doll:
            m["tier"], m["by"] = 1, now + 400 * DAY
        r = FP.plan_week(farm, flowers, now, {}, must_have=doll, tz_offset_h=-3, awake=(6, 23),
                         extend_days=8 * 7, keep_full=True)
        self.assertEqual(sum(m["left_after_full"] for m in r["must_have"]), 0)
        self.assertLess(r["tiers"][1]["done_at"] - now, 28 * DAY)
        check(self, farm, flowers, r, -3, (6, 23), "doll first")


if __name__ == "__main__":
    unittest.main()
