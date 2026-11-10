"""Land expansions to the next island vs. bumpkin levels (skill points) bought with an XP food.

Both paths are priced in FLOWER at market prices and valued per chapter from the farmwide
rates (your own counters) and the animal boost results. Game rules live in Data/growth_rules.json.
"""

NODE_KEYS = {"Crop Plot": "Crop Plot", "Tree": "Tree", "Stone Rock": "Stone Rock", "Iron Rock": "Iron Rock",
             "Gold Rock": "Gold Rock", "Crimstone Rock": "Crimstone Rock", "Fruit Patch": "Fruit Patch",
             "Oil Reserve": "Oil Reserve", "Sunstone Rock": "Sunstone Rock"}


def _level(xp, table):
    lv = 0
    for k, v in table.items():
        if xp >= v:
            lv = max(lv, int(k))
    return lv


def xp_food(farm, prices, rules, food, tax, faction_pet=1.0):
    """XP and FLOWER per cook of one food, with your XP boosts and Fire Pit skills.

    faction_pet: the Faction Pet XP multiplier you eat under (factions.ts: x1.5 the week after an
    8-week fed streak). Eating only in those weeks makes every level cheaper by that factor."""
    f = rules["foods"][food]
    owned = set(farm.get("collectibles", [])) | set(farm.get("wearables", []))
    skills = farm.get("skills", {})
    mult, used = 1.0, []
    for name, m in rules["xp_boosts"].items():
        if isinstance(m, list):
            r = skills.get(name, 0)
            if r:
                mult *= m[r - 1]
                used.append(f"{name} x{m[r - 1]}")
        elif (name == "VIP" and farm.get("vip")) or name in owned:
            mult *= m
            used.append(f"{name} x{m}")
    if faction_pet and faction_pet != 1:
        mult *= faction_pet
        used.append(f"Faction Pet x{faction_pet}")
    fp = rules["fire_pit"]
    hours = f["hours"] * (fp["Fast Feasts"][skills["Fast Feasts"] - 1] if skills.get("Fast Feasts") else 1)
    extra = fp["Fiery Jackpot"][skills["Fiery Jackpot"] - 1] if skills.get("Fiery Jackpot") else 0
    raw = {}
    for item, q in f["ingredients"].items():
        for sub, sq in rules["made"].get(item, {item: 1}).items():
            raw[sub] = raw.get(sub, 0) + q * sq
    buy = sum(q * (prices.get(k) or 0) for k, q in raw.items())
    return {"food": food, "xp": f["xp"] * mult, "boosts": used, "hours": hours, "extra": extra,
            "raw": raw, "cost_buy": buy, "cost_own": buy * (1 - tax),
            "lines": [{"item": k, "qty": q, "flower": q * (prices.get(k) or 0)} for k, q in raw.items()],
            "have": farm.get("inventory", {}).get(food, 0)}


def skill_queue(farmwide, boosts, skill_tree):
    """Skills you do not have yet, best FLOWER per point first, then coin-only ones."""
    info = {s["name"]: s for s in skill_tree}
    cand = {}
    for r in farmwide["rows"]:
        if r.get("kind") == "skill" and (r["flower"] > 0.05 or r["coins"] > 0):
            cand[r["name"]] = {"name": r["name"], "points": r["points"], "flower": r["flower"], "coins": r["coins"],
                               "open": r.get("open", True), "area": r["group"]}
    for b in boosts:
        if b.get("type", "").startswith("skill") and len(b.get("skills", {})) == 1:
            n = next(iter(b["skills"]))
            s = info.get(n)
            if s and n not in cand and (b["flower"] > 0.05 or b["coins"] > 0):
                cand[n] = {"name": n, "points": s["points"], "flower": b["flower"], "coins": b["coins"],
                           "open": True, "area": "Animals"}
    # tier-locked skills need other points in their tree first; left out rather than guessed
    ok = [c for c in cand.values() if c["open"]]
    fl = sorted((c for c in ok if c["flower"] > 0.05), key=lambda c: -c["flower"] / c["points"])
    co = sorted((c for c in ok if c["flower"] <= 0.05), key=lambda c: -c["coins"] / c["points"])
    return fl + co, [c for c in cand.values() if not c["open"]]


def level_path(farm, food, queue, rules, cooks_per_day, top=100):
    table = rules["level_xp"]
    xp0 = farm.get("experience", 0) + food["have"] * food["xp"]   # pizzas you already hold count as eaten
    now = _level(farm.get("experience", 0), table)
    per_cook = food["xp"] * (1 + food["extra"])
    steps, pts, q, prev_cost, prev_lv = [], 0, list(queue), 0.0, now
    for lv in range(now + 1, top + 1):
        pts += 1
        cooks = max(0.0, (table[str(lv)] - xp0) / per_cook)
        bought = []
        while q and q[0]["points"] <= pts:
            s = q.pop(0)
            pts -= s["points"]
            bought.append(s)
        if bought or lv == top:
            cost = cooks * food["cost_buy"]
            steps.append({"level": lv, "from": prev_lv, "skills": bought, "cooks": cooks, "cost": cost,
                          "step_cost": cost - prev_cost, "days": cooks / cooks_per_day,
                          "flower": sum(s["flower"] for s in bought), "coins": sum(s["coins"] for s in bought),
                          "spare_points": pts})
            prev_cost, prev_lv = cost, lv
    return {"now": now, "xp": farm.get("experience", 0), "steps": steps, "per_cook_xp": per_cook}


def node_values(farm, rates, prices, weeks):
    """FLOWER per chapter one more node of each kind adds, from your weekly counters."""
    inv = farm.get("inventory", {})
    n = lambda k: max(1.0, float(inv.get(k, 0) or 0))   # noqa: E731
    v = {
        "Crop Plot": (rates["crop_value_week"] / max(1, rates["plots"]), 0, "your crop plan per plot"),
        "Tree": (rates["chops"] / n("Tree") * rates["wood_per_chop"] * rates["wood_price"],
                 -rates["chops"] / n("Tree") * 20, f"{rates['chops'] / n('Tree'):.0f} chops a week, wood at buy price, axes in coins"),
        "Stone Rock": (rates["stone_mines"] / n("Stone Rock") * rates["per_stone_mine"], 0, "stone barely beats the pickaxe"),
        "Gold Rock": (rates["gold_mines"] / n("Gold Rock") * rates["per_gold_mine"], 0, ""),
        "Crimstone Rock": (rates["crimstone_mines"] / n("Crimstone Rock") * rates["per_crim_mine"], 0, "net of the gold pickaxe"),
        "Fruit Patch": (rates["fruit_value_week"] / n("Fruit Patch"), 0, "your fruit mix per patch"),
        "Iron Rock": (0, 0, "mining iron costs more than buying it"),
        "Oil Reserve": (0, 0, "oil valued at its drill cost; it saves time, not FLOWER"),
        "Sunstone Rock": (0, 0, "no market price"),
    }
    return {k: {"flower": a * weeks, "coins": c * weeks, "note": note} for k, (a, c, note) in v.items()}


def max_rates(farm, rules, oil_per_drill, crim_per_mine):
    """What your nodes give a week if you drill/mine every time they are ready (you mine these
    only when you need them, so stock and past rate do not matter). Oil reserves refill in 20 h
    (Oil Be Back shortens it), crimstone rocks in 24 h."""
    inv, skills = farm.get("inventory", {}), farm.get("skills", {})
    obb = [0.8, 0.7, 0.6]
    oil_h = 20 * (obb[skills["Oil Be Back"] - 1] if skills.get("Oil Be Back") else 1)
    fa = [0.85, 0.75, 0.65]
    crim_h = 24 * (fa[skills["Fireside Alchemist"] - 1] if skills.get("Fireside Alchemist") else 1)
    reserves = float(inv.get("Oil Reserve", 0) or 0)
    rocks = float(inv.get("Crimstone Rock", 0) or 0)
    return {"Oil": reserves * 168 / oil_h * oil_per_drill, "Crimstone": rocks * 168 / crim_h * crim_per_mine,
            "_oil": {"nodes": reserves, "hours": oil_h, "per": oil_per_drill},
            "_crim": {"nodes": rocks, "hours": crim_h, "per": crim_per_mine}}


def expansion_path(farm, prices, rules, nodes, activity, weeks_played, level_xp):
    island = farm.get("island")
    table = rules["expansions"].get(island, {})
    inv = farm.get("inventory", {})
    have_land = int(inv.get("Basic Land", 0) or 0)
    up = rules["island_upgrade"].get(island)
    rows, tot_items = [], {}
    for k in sorted(table, key=int):
        if int(k) <= have_land:
            continue
        e = table[k]
        priced = sum(q * (prices.get(i) or 0) for i, q in e["items"].items() if i != "Gem")
        val = sum(nodes[g]["flower"] * q for g, q in e["gives"].items() if g in nodes)
        coins_val = sum(nodes[g]["coins"] * q for g, q in e["gives"].items() if g in nodes)
        rows.append({"expansion": int(k), "items": e["items"], "flower_cost": priced, "coins": e["coins"],
                     "gems": e["items"].get("Gem", 0), "hours": e["hours"], "level": e["level"],
                     "gives": e["gives"], "value": val, "value_coins": coins_val})
        for i, q in e["items"].items():
            tot_items[i] = tot_items.get(i, 0) + q
    if up and rows and rows[-1]["expansion"] >= up["expansions"]:
        priced = sum(q * (prices.get(i) or 0) for i, q in up["items"].items())
        rows.append({"expansion": f"{up['to'].title()} island", "items": up["items"], "flower_cost": priced, "coins": 0,
                     "gems": 0, "hours": 0, "level": 0, "gives": {}, "value": 0, "value_coins": 0})
        for i, q in up["items"].items():
            tot_items[i] = tot_items.get(i, 0) + q
    rate = max_rates(farm, rules, prices.get("_oil_per_drill", 16.6667), prices.get("_crim_per_mine", 1.6))
    needs = []
    for i, q in sorted(tot_items.items(), key=lambda x: -x[1] * (prices.get(x[0]) or 0)):
        have = float(inv.get(i, 0) or 0)
        short = max(0.0, q - have)
        needs.append({"item": i, "need": q, "have": have, "flower": short * (prices.get(i) or 0) if i != "Gem" else None,
                      "weeks": short / rate[i] if rate.get(i) else None, "per_week": rate.get(i)})
    rate_basis = {"Oil": rate["_oil"], "Crimstone": rate["_crim"]}
    lv_needed = max((r["level"] for r in rows if isinstance(r["expansion"], int)), default=0)
    return {"island": island, "have": have_land, "rows": rows, "needs": needs, "rate_basis": rate_basis,
            "flower_cost": sum(r["flower_cost"] for r in rows), "coins": sum(r["coins"] for r in rows),
            "gems": tot_items.get("Gem", 0), "gems_have": float(inv.get("Gem", 0) or 0),
            "hours": sum(r["hours"] for r in rows), "value": sum(r["value"] for r in rows),
            "value_coins": sum(r["value_coins"] for r in rows), "level_needed": lv_needed,
            "level_xp_needed": max(0.0, level_xp.get(str(lv_needed), 0) - farm.get("experience", 0))}


def daily_mining(farm, prices, rates, tax):
    """FLOWER a week from mining every gold and crimstone rock once a day (both refill in 24 h).
    Crimstone is sold (after the marketplace cut); its Gold Pickaxe uses your own gold first."""
    inv = farm.get("inventory", {})
    p = lambda k: float(prices.get(k) or 0)   # noqa: E731
    g_rocks, c_rocks = float(inv.get("Gold Rock", 0) or 0), float(inv.get("Crimstone Rock", 0) or 0)
    g_mines, c_mines = g_rocks * 7, c_rocks * 7
    gold = g_mines * rates.get("gold_per_mine", 1.8)
    crim = c_mines * rates.get("crim_per_mine", 1.6)
    gold_for_crim = c_mines * 3
    crim_sell = crim * p("Crimstone") * (1 - tax)
    crim_cost = gold_for_crim * p("Gold") + c_mines * 3 * p("Wood")         # pickaxes, gold at market
    gold_cost = g_mines * (5 * p("Iron") + 3 * p("Wood"))
    gold_left = gold - gold_for_crim
    return {"gold_rocks": g_rocks, "crim_rocks": c_rocks, "gold_week": gold, "crim_week": crim,
            "gold_for_crim": gold_for_crim, "gold_left": gold_left,
            "crim_net": crim_sell - crim_cost, "gold_net": gold * p("Gold") - gold_cost,
            "both_net": crim_sell + gold_left * p("Gold") * (1 - tax if gold_left > 0 else 1) - gold_cost - c_mines * 3 * p("Wood"),
            "coins": -(g_mines * 80 + c_mines * 100)}


def evaluate(farm, prices, rules, farmwide, boosts, skill_tree, tax, weeks, food="Pizza Margherita",
             cooks_per_day=1.0, oil_per_drill=16.6667, faction_pet=1.0):
    prices = dict(prices, _oil_per_drill=oil_per_drill, _crim_per_mine=farmwide["rates"].get("crim_per_mine", 1.6))
    f = xp_food(farm, prices, rules, food, tax, faction_pet)
    nodes = node_values(farm, farmwide["rates"], prices, weeks)
    q, locked = skill_queue(farmwide, boosts, skill_tree)
    lv = level_path(farm, f, q, rules, cooks_per_day)
    lv["locked"] = locked
    ex = expansion_path(farm, prices, rules, nodes, farm.get("activity", {}), farm.get("weeks_played", 1),
                        rules["level_xp"])
    if ex["level_needed"] > lv["now"]:
        cooks = max(0.0, (rules["level_xp"][str(ex["level_needed"])] - lv["xp"] - f["have"] * f["xp"]) / lv["per_cook_xp"])
        ex["level_cost"] = cooks * f["cost_buy"]
    else:
        ex["level_cost"] = 0.0
    return {"food": f, "levels": lv, "expansions": ex, "nodes": nodes, "cooks_per_day": cooks_per_day,
            "faction_pet": faction_pet, "pet_streak": farm.get("pet_streak"),
            "mining": daily_mining(farm, prices, farmwide["rates"], tax)}
