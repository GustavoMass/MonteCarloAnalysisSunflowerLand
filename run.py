"""One command: fetch your farm + prices, simulate, build the report, open it.

    python run.py              # refresh from sfl-manager, then simulate
    python run.py --offline    # reuse the files in Data/
    python run.py --no-open    # don't open the browser

Edit config.json to change taxes, skill builds, barn levels, delivery habits.
"""
import argparse
import json
import os
import random
import sys
import time
import webbrowser
import zlib

from sflmc import analysis as A
from sflmc import farm as F
from sflmc import fetch
from sflmc import game as G
from sflmc import herd as H
from sflmc import sim as S

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "Data")


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def seed(*parts):
    return zlib.crc32("|".join(map(str, parts)).encode())


def ticket_plan(cfg, farm):
    bonus = cfg["vip_bonus"] * farm.get("vip", True) + len(farm.get("chapter_wearables", []))
    days = cfg["delivery_days"] + cfg["double_delivery_days"]
    rows = []
    for name, n in cfg["ticket_npcs"].items():
        per = n["base"] + bonus
        rows.append({"npc": name, "per_delivery": per, "freq": n["freq"], "tickets": per * n["freq"] * days,
                     "if_daily": per * days, "flower_per_ticket": n["flower_per_ticket"]})
    board = 100 * cfg["board_bonus_weeks"] if cfg["board_bonus"] else 0
    return {"bonus_deliveries": bonus, "days": days, "npcs": rows, "board_bonus": board,
            "deliveries_total": sum(r["tickets"] for r in rows)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="skip the sfl-manager refresh")
    ap.add_argument("--no-open", action="store_true", help="don't open the report")
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"))
    args = ap.parse_args()
    cfg = load(args.config)
    fid = cfg["farm_id"]

    if not args.offline:
        try:
            print("Fetching farm and prices from sfl-manager ...")
            fetch.refresh(DATA, fid)
        except Exception as e:  # network down, API changed: keep going on cached data
            print(f"  refresh failed ({e}); using cached files in Data/", file=sys.stderr)
    farm_d = load(os.path.join(DATA, f"farm_{fid}.json"))
    prices = load(os.path.join(DATA, "prices_snapshot.json"))
    bounties = load(os.path.join(DATA, "bounties_observed.json"))
    eco = S.Economy(prices["prices"], cfg["sell_fee"], cfg["coins_per_flower"])
    base = F.Farm(farm_d["skills"], set(farm_d["collectibles"]), set(farm_d["wearables"]))
    board_now = bounties.get("current_board", {})
    wear_bonus = len(farm_d.get("chapter_wearables", []))

    out = {"meta": {"generated": time.strftime("%Y-%m-%d %H:%M"), "config": cfg, "farm": farm_d,
                    "prices": prices, "bounties": bounties,
                    "slops": {f: eco.cheapest_slop_ingredient(f) for f in G.SLOP_OPTIONS}},
           "single": [], "herd": [], "tickets": ticket_plan(cfg, farm_d)}
    t0 = time.time()
    for bname, b in cfg["builds"].items():
        farm = base.with_skills(b["add"], b["remove"])
        for animal in G.ANIMALS:
            model = S.AnimalModel(farm, animal, eco)
            buy = H.BUY_COINS[animal] / eco.coins_per_flower
            runs = S.run_scenario(model, cfg["days_single_animal"], cfg["runs_single_animal"], seed(bname, animal))
            out["single"].append({"build": bname, "animal": animal, "sleep_h": model.sleep,
                                  "food_qty": model.food_qty, "xp_mult": model.xp_mult,
                                  "produce_units": model.produce_units, **A.per_level(model, runs, buy)})

            # herd over the chapter
            coins = bounties.get("coins", {}).get(animal, {})
            pool = sorted({int(k) for k in coins} | {r["level"] for r in board_now.get(animal, [])}) or [5]
            live = [dict(r, amount=r["amount"] + wear_bonus if r["kind"] == "tickets" else r["amount"])
                    for r in board_now.get(animal, [])]
            live = live if any(r["kind"] == "tickets" for r in live) else None
            if animal == "Chicken":
                lvls = [cfg["building_levels"]["Hen House"]]
                bld = "Hen House"
            elif animal == "Pig":
                lvls = [cfg["building_levels"]["Pigpen"]]
                bld = "Pigpen"
            else:
                lvls = [lv for lv in cfg["compare_barn_levels"] if lv > 0]
                bld = "Barn"
            for blv in lvls:
                cap = cfg["capacity"][bld][blv]
                if (bld == "Hen House" and "Chicken Coop" in farm.collectibles) or \
                   (bld == "Barn" and "Barn Blueprint" in farm.collectibles):
                    cap += 5 * blv
                counts = cfg["board_per_week"][animal].get(str(blv), {})
                stop = cfg.get("stop_feeding_at", {}).get(animal)
                stop = max(pool) if stop == "auto" else stop
                rng = random.Random(seed("herd", bname, animal, blv))
                res = [H.simulate_herd(model, rng, start_xp=farm_d.get("animal_xp", {}).get(animal, []),
                                       capacity=cap, weeks=cfg["chapter_weeks"],
                                       sell=animal not in cfg["keep_animals"], counts=counts, level_pool=pool,
                                       coin_points=coins, ticket_amount=cfg["ticket_base"][animal] + wear_bonus,
                                       gems=cfg["gems_per_bounty"], live_board=live, stop_feeding_at=stop)
                       for _ in range(cfg["runs_herd"])]
                out["herd"].append({"build": bname, "animal": animal, "building": bld, "building_level": blv,
                                    "stop_feeding_at": stop,
                                    "capacity": cap, "counts": counts, "live_board": bool(live),
                                    **A.herd_totals(res, eco.coins_per_flower)})
            print(f"  {bname:28s} {animal:8s} done ({time.time() - t0:.0f}s)")

    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    with open(os.path.join(HERE, "results", "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))

    import build_report
    path = build_report.main()
    print(f"Report: {path}")
    if not args.no_open:
        webbrowser.open("file://" + path.replace("\\", "/"))


if __name__ == "__main__":
    main()
