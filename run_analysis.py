"""Run the full Monte Carlo study and write results/results.json.

    python run_analysis.py [--runs 1000] [--days 45]
"""
import argparse
import json
import os
import time
import zlib

from sflmc import analysis as A
from sflmc import farm as F
from sflmc import game as G
from sflmc import sim as S

HERE = os.path.dirname(os.path.abspath(__file__))
ANIMAL_COINS = {"Chicken": 50, "Cow": 100, "Sheep": 120, "Pig": 100}

# Builds: the farm's skills with its tier-3 feed skill swapped.
BUILDS = {
    "Clucky Grazing R1 (current)": {"remove": [], "add": {}},
    "Chonky Feed R1 (reset)": {"remove": ["Clucky Grazing"], "add": {"Chonky Feed": 1}},
    "Clucky R1 + Chonky R1": {"remove": [], "add": {"Chonky Feed": 1}},
    "No tier-3 feed skill": {"remove": ["Clucky Grazing"], "add": {}},
    "Clucky Grazing R3": {"remove": [], "add": {"Clucky Grazing": 3}},
    "Chonky Feed R3": {"remove": ["Clucky Grazing"], "add": {"Chonky Feed": 3}},
}


def load(name):
    with open(os.path.join(HERE, "Data", name), encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1000)
    ap.add_argument("--days", type=int, default=45)
    args = ap.parse_args()

    farm_d = load("farm_3621107187220366.json")
    prices = load("prices_snapshot.json")
    bounties = load("bounties_observed.json")
    base = F.Farm(farm_d["skills"], set(farm_d["collectibles"]), set(farm_d["wearables"]))
    eco = S.Economy(prices["prices"])

    out = {
        "meta": {
            "runs": args.runs, "days": args.days, "farm": farm_d, "prices": prices,
            "bounties": bounties, "schedules": S.SCHEDULES, "builds": BUILDS,
            "coins_per_flower": eco.coins_per_flower, "sell_fee": eco.sell_fee,
            "generated": time.strftime("%Y-%m-%d %H:%M"),
            "slops": {f: eco.cheapest_slop_ingredient(f) for f in G.SLOP_OPTIONS},
        },
        "scenarios": [],
    }
    t0 = time.time()
    for bname, b in BUILDS.items():
        farm = base.with_skills(b["add"], b["remove"])
        for animal in G.ANIMALS:
            model = S.AnimalModel(farm, animal, eco)
            coins = bounties["coins"][animal]
            mult = F.bounty_coin_multiplier(farm)
            bounty = []
            for L in range(G.MAX_LEVEL + 1):
                c = A.interp_bounty(coins, L)
                bounty.append(None if c is None else c * mult / eco.coins_per_flower + model.bristle_value[L])
            buy = ANIMAL_COINS[animal] / eco.coins_per_flower
            for sname in S.SCHEDULES:
                runs = S.run_scenario(model, sname, args.days, args.runs, seed=zlib.crc32(f"{bname}|{animal}|{sname}".encode()))
                summ = A.summarise(model, runs, args.days, buy, bounty)
                out["scenarios"].append({
                    "build": bname, "animal": animal, "schedule": sname,
                    "sleep_h": model.sleep, "food_qty_per_feed": model.food_qty, "xp_mult": model.xp_mult,
                    "produce_units": model.produce_units, "produce_flower": model.produce,
                    **summ,
                })
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    with open(os.path.join(HERE, "results", "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"{len(out['scenarios'])} scenarios in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
