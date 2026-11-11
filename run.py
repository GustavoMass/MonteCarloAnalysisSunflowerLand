"""One command: fetch your farm + prices, simulate, build the report, open it.

    python run.py              # refresh from sfl-manager, then simulate
    python run.py --offline    # reuse the files in Data/
    python run.py --no-open    # don't open the browser
    python run.py --quick      # 10x fewer runs, for trying config changes

Edit config.json to change taxes, skill builds, buildings, delivery habits.
"""
import argparse
import datetime as dt
import json
import os
import random
import sys
import time
import webbrowser
import zlib

from sflmc import analysis as A
from sflmc import farmwide, growth
from sflmc import farm as F
from sflmc import fetch
from sflmc import flowerplan
from sflmc import game as G
from sflmc import herd as H
from sflmc import sim as S

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "Data")
BUILDING = {"Chicken": "Hen House", "Cow": "Barn", "Sheep": "Barn", "Pig": "Pigpen"}
SEASONS = ["spring", "summer", "autumn", "winter"]
CHAPTER_TASKS_START = dt.date(2026, 11, 9)


def load(path, default=None):
    if default is not None and not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def seed(*parts):
    return zlib.crc32("|".join(map(str, parts)).encode())


# ---------------------------------------------------------------- herd

def week_schedule(cfg, animal, farm):
    bld = BUILDING[animal]
    steps = sorted(cfg["buildings"][bld])
    out = []
    for w in range(cfg["chapter_weeks"]):
        lv = [lvl for start, lvl in steps if start <= w][-1]
        cap = cfg["capacity"][bld][lv]
        if (bld == "Hen House" and "Chicken Coop" in farm.collectibles) or \
           (bld == "Barn" and "Barn Blueprint" in farm.collectibles):
            cap += 5 * lv
        out.append((cap, cfg["board_per_week"][animal].get(str(lv), {})))
    return out


POOL = None   # process pool set up in main(); runs are split across CPU cores


def _map(fn, jobs):
    if POOL is None or len(jobs) < 8:
        return [fn(j) for j in jobs]
    return list(POOL.map(fn, jobs, chunksize=max(1, len(jobs) // (4 * (os.cpu_count() or 4)))))


def _herd_one(job):
    model, s, kw = job
    return H.simulate_herd(model, random.Random(s), **kw)


def _single_one(job):
    model, days, s = job
    return S.simulate(model, days, random.Random(s))


def run_herd(cfg, ctx, farm, animal, policy, buffer, runs, key):
    eco, farm_d, bounties = ctx["eco"], ctx["farm_d"], ctx["bounties"]
    model = S.AnimalModel(farm, animal, eco)
    coins = bounties.get("coins", {}).get(animal, {})
    board_now = bounties.get("current_board", {}).get(animal, [])
    pool = sorted({int(k) for k in coins} | {r["level"] for r in board_now}) or [5]
    live = [dict(r, amount=r["amount"] + ctx["wear"] if r["kind"] == "tickets" else r["amount"]) for r in board_now]
    live = live if any(r["kind"] == "tickets" for r in live) else None
    stop = policy.get("stop_feeding_at")
    stop = max(pool) if stop == "auto" else stop
    kw = dict(start_xp=farm_d.get("animal_xp", {}).get(animal, []),
              weeks=cfg["chapter_weeks"], schedule=week_schedule(cfg, animal, farm),
              sell=policy.get("sell", True), buffer=buffer, level_pool=pool, coin_points=coins,
              ticket_amount=cfg["ticket_base"][animal] + ctx["wear"], gems=cfg["gems_per_bounty"],
              coin_mult=F.bounty_coin_multiplier(farm), stop_feeding_at=stop,
              trade_in_at=policy.get("trade_in_at"), no_ticket_weeks=set(cfg["no_ticket_weeks"]),
              live_board=live, sell_order=policy.get("sell_order"))
    s0 = seed(key)
    res = _map(_herd_one, [(model, s0 + i, kw) for i in range(runs)])
    return {"stop_feeding_at": stop, **A.herd_totals(res, eco.coins_per_flower)}


def policies(cfg, animal):
    h = cfg["herd"][animal]
    return h["policies"] if "policies" in h else {"": h}


def apply_price_rules(cfg, prices):
    """Your price assumptions on top of the market snapshot:
    price_overrides  {item: {"price": x, "until": "YYYY-MM-DD"}} fixed price until that date;
    derived_prices   {item: {"inputs": {item: qty}, "per": units}} cost of the inputs / units made,
                     used when the market has no price (e.g. Oil from an Oil Drill)."""
    p, notes = prices["prices"], {}
    today = time.strftime("%Y-%m-%d")
    for item, o in cfg.get("price_overrides", {}).items():
        if today <= o.get("until", "9999-12-31"):
            notes[item] = f"set to {o['price']} until {o['until']} (market {p.get(item)})"
            p[item] = o["price"]
    for item, d in cfg.get("derived_prices", {}).items():
        if not p.get(item) and all(p.get(k) for k in d["inputs"]):
            p[item] = sum(q * p[k] for k, q in d["inputs"].items()) / d["per"]
            notes[item] = f"{p[item]:.4f} from " + " + ".join(f"{q} {k}" for k, q in d["inputs"].items()) + f" per {d['per']:.2f}"
    prices["assumed"] = notes
    for k, v in notes.items():
        print(f"  price {k}: {v}")


def model_signature(farm, animal, eco):
    m = S.AnimalModel(farm, animal, eco)
    return (round(m.sleep, 6), round(m.food_qty, 6), round(m.xp_mult, 6), tuple(m.love_xp.values()),
            tuple(round(x, 6) for x in m.produce), F.bounty_coin_multiplier(farm))


# ---------------------------------------------------------------- tickets

def ticket_plan(cfg, farm_d, board_week, herd_tickets):
    bonus = cfg["vip_bonus"] * bool(farm_d.get("vip", True)) + len(farm_d.get("chapter_wearables", []))
    wear = len(farm_d.get("chapter_wearables", []))
    days = cfg["delivery_days"] + cfg["double_delivery_days"]
    ticket_weeks = cfg["chapter_weeks"] - len(cfg["no_ticket_weeks"])
    npcs = []
    for name, n in cfg["ticket_npcs"].items():
        per = n["base"] + bonus
        npcs.append({"npc": name, "per_delivery": per, "freq": n["freq"], "exclude": n.get("exclude", False),
                     "tickets": per * n["freq"] * days, "max": 0 if n.get("exclude") else per * days})
    live = {}
    for b in (board_week or {}).get("board", []):
        if b.get("tickets"):
            live.setdefault(b["category"], []).append(b["tickets"])
    board = []
    for cat, b in cfg["board_items"].items():
        base = sum(live[cat]) / len(live[cat]) if cat in live else b["tickets"]
        per = base + wear
        board.append({"category": cat, "per_week": b["per_week"], "base": base, "live": cat in live,
                      "share": b["share"], "exclude": b.get("exclude", False),
                      "tickets": per * b["per_week"] * b["share"] * ticket_weeks,
                      "max": 0 if b.get("exclude") else per * b["per_week"] * ticket_weeks})
    all_board = all(b["share"] >= 1 for b in cfg["board_items"].values())
    chores = cfg.get("chore_tickets_per_week", 0) * ticket_weeks
    return {"bonus_deliveries": bonus, "bonus_bounties": wear, "days": days, "ticket_weeks": ticket_weeks,
            "npcs": npcs, "board": board, "chores": chores,
            "board_bonus": cfg["board_bonus_tickets"] * ticket_weeks if all_board else 0,
            "animals": herd_tickets, "goal": cfg["ticket_goal"]}


# ---------------------------------------------------------------- flowers

def flower_guide(farm_d, flowers, orders, board_week, weeks):
    season = farm_d.get("season") or "autumn"
    i = SEASONS.index(season)
    cal = [{"week": w, "starts": str(CHAPTER_TASKS_START + dt.timedelta(weeks=w)),
            "season": SEASONS[(i + 1 + w) % 4]} for w in range(weeks)]
    special = {}
    for sd, info in (flowers or {}).get("seeds", {}).items():
        if len(info["seasons"]) == 1:
            special[info["seasons"][0]] = {"seed": sd, "days": info["days"], "flowers": info["flowers"]}
    raven = [{"order": k, "days": v["days"]} for k, v in (orders or {}).get("raven", {}).get("orders", {}).items()]
    board_flowers = [b["label"] for b in (board_week or {}).get("board", []) if b["category"] == "Flowers"]
    return {"calendar": cal, "special": special, "flowers": (flowers or {}).get("flowers", {}),
            "seeds": (flowers or {}).get("seeds", {}), "raven": raven, "board_now": board_flowers,
            "season_now": season}


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="skip the sfl-manager refresh")
    ap.add_argument("--no-open", action="store_true", help="don't open the report")
    ap.add_argument("--quick", action="store_true", help="10x fewer runs")
    ap.add_argument("--force", action="store_true", help="fetch everything again, even files fetched minutes ago")
    ap.add_argument("--config", default=os.path.join(HERE, "config.json"))
    args = ap.parse_args()
    cfg = load(args.config)
    if args.quick:
        cfg["runs_single_animal"] = max(20, cfg["runs_single_animal"] // 10)
        cfg["runs_herd"] = max(10, cfg["runs_herd"] // 10)
    fid = cfg["farm_id"]
    nft_names = [n for b in cfg["boosts"] for n in b.get("collectibles", []) + b.get("wearables", [])] + list(farmwide.CROP_ITEMS)

    if not args.offline:
        try:
            print("Fetching farm, board, prices and NFT floors from sfl-manager ...")
            fetch.refresh(DATA, fid, nft_names,
                          {k: 0 for k in fetch.MAX_AGE} if args.force else cfg.get("refresh_max_age_hours"))
        except Exception as e:  # network down, API changed: keep going on cached data
            print(f"  refresh failed ({e}); using cached files in Data/", file=sys.stderr)
    farm_d = load(os.path.join(DATA, f"farm_{fid}.json"))
    prices = load(os.path.join(DATA, "prices_snapshot.json"))
    bounties = load(os.path.join(DATA, "bounties_observed.json"))
    nfts = load(os.path.join(DATA, "nft_prices.json"), {"items": {}})["items"]
    board_week = load(os.path.join(DATA, "board_week.json"), {})
    apply_price_rules(cfg, prices)
    eco = S.Economy(prices["prices"], cfg["sell_fee"], cfg["coins_per_flower"])
    base = F.Farm(farm_d["skills"], set(farm_d["collectibles"]), set(farm_d["wearables"]))
    ctx = {"eco": eco, "farm_d": farm_d, "bounties": bounties, "wear": len(farm_d.get("chapter_wearables", []))}
    builds = {n: base.with_skills(b["add"], b["remove"]) for n, b in cfg["builds"].items()}
    plan_name = next(iter(builds))
    plan = builds[plan_name]

    out = {"meta": {"generated": time.strftime("%Y-%m-%d %H:%M"), "config": cfg, "farm": farm_d, "prices": prices,
                    "bounties": bounties, "slops": {f: eco.cheapest_slop_ingredient(f) for f in G.SLOP_OPTIONS},
                    "plan": plan_name},
           "single": [], "herd": [], "boosts": [], "building_costs": G.BUILDING_COSTS}
    t0 = time.time()

    for bname, farm in builds.items():
        for animal in G.ANIMALS:
            model = S.AnimalModel(farm, animal, eco)
            s0 = seed(bname, animal)
            runs = _map(_single_one, [(model, cfg["days_single_animal"], s0 + i) for i in range(cfg["runs_single_animal"])])
            out["single"].append({"build": bname, "animal": animal, "sleep_h": model.sleep, "food_qty": model.food_qty,
                                  "xp_mult": model.xp_mult, "produce_units": model.produce_units,
                                  **A.per_level(model, runs, eco.coin_flower(H.BUY_COINS[animal]))})
            for pname, pol in policies(cfg, animal).items():
                for buf in pol.get("buffers", [None]):
                    r = run_herd(cfg, ctx, farm, animal, pol, buf, cfg["runs_herd"], ("herd", bname, animal, pname, buf))
                    out["herd"].append({"build": bname, "animal": animal, "policy": pname, "buffer": buf, **r})
            print(f"  {bname:26s} {animal:8s} ({time.time() - t0:.0f}s)")

    # boosts: plan build, the first policy and buffer 1 where offered
    def pick(animal):
        pname, pol = list(policies(cfg, animal).items())[-1 if animal == "Pig" else 0]
        bufs = pol.get("buffers", [None])
        return pname, pol, (1 if 1 in bufs else bufs[0])

    base_vals = {}
    for animal in G.ANIMALS:
        pname, pol, buf = pick(animal)
        base_vals[animal] = run_herd(cfg, ctx, plan, animal, pol, buf, cfg["runs_herd"], ("boost-base", animal))
    for b in cfg["boosts"]:
        farm = plan.with_skills(b.get("skills", {}), [])
        farm.collectibles |= set(b.get("collectibles", []))
        farm.wearables |= set(b.get("wearables", []))
        names = b.get("collectibles", []) + b.get("wearables", [])
        price = b.get("price")
        if names:
            ps = [(nfts.get(n) or {}).get("price") for n in names]
            price = None if None in ps else sum(ps)
        gain = {"flower": 0.0, "coins": 0.0, "feed": 0.0, "animals": []}
        for animal in G.ANIMALS:
            if model_signature(farm, animal, eco) == model_signature(plan, animal, eco):
                continue
            pname, pol, buf = pick(animal)
            r = run_herd(cfg, ctx, farm, animal, pol, buf, cfg["runs_herd"], ("boost-base", animal))
            gain["animals"].append(animal)
            gain["flower"] += r["value_flower"]["mean"] - base_vals[animal]["value_flower"]["mean"]
            gain["coins"] += r["coins_net"]["mean"] - base_vals[animal]["coins_net"]["mean"]
            gain["feed"] += base_vals[animal]["feed"]["mean"] - r["feed"]["mean"]
        out["boosts"].append({**b, "price": price, **gain})
        print(f"  boost {b['name']:24s} ({time.time() - t0:.0f}s)")
    already = {n for b in cfg["boosts"] for n in b.get("collectibles", []) + b.get("wearables", [])
               if n in plan.collectibles or n in plan.wearables}
    out["meta"]["boosts_owned"] = sorted(already)

    # building upgrade paths: tickets and value per path, against building costs
    owned_lv = {"Barn": farm_d["buildings"].get("Barn", 0), "Pigpen": farm_d["buildings"].get("Pigpen", 0)}
    out["upgrades"] = []
    for bld, paths in cfg.get("upgrade_paths", {}).items():
        animals = ["Cow", "Sheep"] if bld == "Barn" else ["Pig"]
        for pname, path in paths.items():
            c2 = json.loads(json.dumps(cfg))
            c2["buildings"][bld] = path
            tot = {"tickets": 0.0, "value": 0.0, "coins": 0.0}
            for animal in animals:
                pn, pol, buf = pick(animal)
                r = run_herd(c2, ctx, plan, animal, pol, buf, cfg["runs_herd"], ("upg", bld, animal))
                tot["tickets"] += r["tickets"]["mean"]
                tot["value"] += r["value_flower"]["mean"]
                tot["coins"] += r["coins_net"]["mean"]
            top = max(lv for _, lv in path)
            coins, items = 0, {}
            for lv in range(owned_lv[bld] + 1, top + 1):
                cst = G.BUILDING_COSTS[bld][lv]
                coins += cst["coins"]
                for k, q in cst["items"].items():
                    items[k] = items.get(k, 0) + q
            priced = sum(q * eco.unit(k) for k, q in items.items())
            step = G.BUILDING_COSTS[bld].get(top, {"coins": 0, "items": {}})   # from the level below
            step_fl = eco.coin_flower(step["coins"]) + sum(q * eco.unit(k) for k, q in step["items"].items())
            out["upgrades"].append({"building": bld, "path": pname, "top_level": top, **tot,
                                    "cost_coins": coins, "cost_items": items, "step_coins": step["coins"],
                                    "step_items": step["items"], "step_flower": step_fl,
                                    "cost_flower": eco.coin_flower(coins) + priced,
                                    "unpriced": {k: q for k, q in items.items() if not eco.unit(k)},
                                    "have": {k: farm_d.get("inventory", {}).get(k, 0) for k in items}})
        print(f"  upgrades {bld} ({time.time() - t0:.0f}s)")

    fw = cfg.get("farmwide", {})
    out["farmwide"] = farmwide.evaluate(farm_d, prices["prices"], load(os.path.join(DATA, "skill_tree.json"), []), nfts,
                                        tax=cfg["sell_fee"], speed_credit=fw.get("speed_credit", 0.5),
                                        coins_per_flower=fw.get("coins_per_flower", 1000), weeks=cfg["chapter_weeks"],
                                        item_prices=fw.get("item_prices"), crop_plan=fw.get("crop_plan"),
                                        crop_yield=fw.get("crop_yield"))
    gw = cfg.get("growth", {})
    out["growth"] = growth.evaluate(farm_d, prices["prices"], load(os.path.join(DATA, "growth_rules.json"), {}),
                                    out["farmwide"], out["boosts"], load(os.path.join(DATA, "skill_tree.json"), []),
                                    tax=cfg["sell_fee"], weeks=cfg["chapter_weeks"],
                                    food=gw.get("xp_food", "Pizza Margherita"), cooks_per_day=gw.get("cooks_per_day", 1.0),
                                    oil_per_drill=cfg.get("derived_prices", {}).get("Oil", {}).get("per", 16.6667),
                                    faction_pet=gw.get("faction_pet_xp", 1.0))
    herd_tickets = {}
    for animal in G.ANIMALS:
        pname, pol, buf = pick(animal)
        h = next(x for x in out["herd"] if x["build"] == plan_name and x["animal"] == animal
                 and x["policy"] == pname and x["buffer"] == buf)
        herd_tickets[animal] = {"tickets": h["tickets"]["p50"], "policy": pname, "buffer": buf}
    out["tickets"] = ticket_plan(cfg, farm_d, board_week, herd_tickets)
    out["flowers"] = flower_guide(farm_d, load(os.path.join(DATA, "flowers.json"), {}),
                                  load(os.path.join(DATA, "ticket_orders_history.json"), {}), board_week,
                                  cfg["chapter_weeks"])

    fl = load(os.path.join(DATA, "flowers.json"), {})
    if fl and farm_d.get("flower_beds") is not None and farm_d.get("season_started"):
        owed = flowerplan.needs(farm_d, fl, board_week, int(time.time() * 1000), fetch.TICKET,
                                prio=cfg.get("flower_priorities", {}))
        fp = flowerplan.plan_week(farm_d, fl, int(time.time() * 1000), prices["prices"],
                             tz_offset_h=cfg.get("timezone_offset_hours", 0), awake=tuple(cfg.get("awake_hours", (0, 24))),
                             board_now=[b["label"] for b in board_week.get("board", []) if b["category"] == "Flowers"],
                             must_have=[{**m, "by": int((dt.datetime.strptime(m["by"], "%Y-%m-%d %H:%M")
                                                         - dt.timedelta(hours=cfg.get("timezone_offset_hours", 0)))
                                                        .replace(tzinfo=dt.timezone.utc).timestamp() * 1000)}
                                        for m in cfg.get("flower_must_have", [])] + list(owed))   # count 0 still protects what you owe
        fp["owed"] = owed
        out["flower_plan"] = fp

    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    with open(os.path.join(HERE, "results", "results.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"))

    import build_report
    path = build_report.main()
    print(f"Report: {path}")
    if not args.no_open:
        webbrowser.open("file://" + path.replace("\\", "/"))


if __name__ == "__main__":
    from concurrent.futures import ProcessPoolExecutor
    with ProcessPoolExecutor() as POOL:
        main()
