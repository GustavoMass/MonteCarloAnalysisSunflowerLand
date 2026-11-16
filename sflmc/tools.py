"""Gold timing, tool stock and restocks: what the Midas skills really give a player who sleeps,
and whether Iron Pickaxes run out before the other tools.

Game rules (sunflower-land main):
  * recovery: tree 2 h, stone 4 h, iron 8 h, gold 24 h, crimstone 24 h (lib/constants.ts);
    Midas Sprint x0.9/0.875/0.85, Midas Rush x0.8/0.75/0.7 on gold (mineGold.ts, bumpkinSkills.ts).
  * tool stock (types/tools.ts): Axe 200, Pickaxe 60, Stone 20, Iron 5, Gold 5; Toolshed x1.5 (rounded up),
    then More Axes +50 axes and More Picks +70/+20/+7/+2 (lib/constants.ts INITIAL_STOCK).
  * free daily shipment (shipmentRestocked.ts): +50 Axe, +15 Pickaxe, +5 Stone, +1 Iron, no Gold Pickaxe,
    never above full stock. A gem restock refills every tool to full for 20 Gems (restock.ts).
  * recipes: Axe 20 coins; Pickaxe 20 + 3 Wood; Stone Pickaxe 20 + 3 Wood + 5 Stone;
    Iron Pickaxe 80 + 3 Wood + 5 Iron; Gold Pickaxe 100 + 3 Wood + 3 Gold.
  * iron per mine: 1 + Iron Beetle 0.1 - Rocky Favor 0.5 (ironMine.ts).
A node is collected at your first check after it is ready; checks run every `every` hours from
`start` to `end` (your local day). A node that becomes ready while you sleep waits for the morning.
"""
import math

RECOVERY_H = {"Tree": 2, "Stone Rock": 4, "Iron Rock": 8, "Gold Rock": 24, "Crimstone Rock": 24}
MIDAS = {"Midas Sprint": [0.9, 0.875, 0.85], "Midas Rush": [0.8, 0.75, 0.7]}
BASE_STOCK = {"Axe": 200, "Pickaxe": 60, "Stone Pickaxe": 20, "Iron Pickaxe": 5, "Gold Pickaxe": 5}
MORE_PICKS = {"Pickaxe": 70, "Stone Pickaxe": 20, "Iron Pickaxe": 7, "Gold Pickaxe": 2}
SHIPMENT = {"Axe": 50, "Pickaxe": 15, "Stone Pickaxe": 5, "Iron Pickaxe": 1, "Gold Pickaxe": 0}
RESTOCK_GEMS = 20
TOOL_FOR = {"Tree": "Axe", "Stone Rock": "Pickaxe", "Iron Rock": "Stone Pickaxe", "Gold Rock": "Iron Pickaxe",
            "Crimstone Rock": "Gold Pickaxe"}
RECIPE = {"Axe": {}, "Pickaxe": {"Wood": 3}, "Stone Pickaxe": {"Wood": 3, "Stone": 5},
          "Iron Pickaxe": {"Wood": 3, "Iron": 5}, "Gold Pickaxe": {"Wood": 3, "Gold": 3}}


def checks(start=6, end=22, every=2):
    out, h = [], float(start)
    while h <= end + 1e-9:
        out.append(h)
        h += every
    return out


def harvests_per_day(cycle_h, check_hours, days=240):
    """Best steady rate you can get collecting at your checks (every starting phase tried)."""
    cs = sorted(d * 24 + h for d in range(days) for h in check_hours)
    best = 0.0
    for start in range(0, 48):
        ready, n, first = float(start), 0, None
        for c in cs:
            if c >= ready:
                n += 1
                first = c if first is None else first
                ready = c + cycle_h
        if first is not None:
            best = max(best, n / days)
    return best


def gold_cycle(sprint=0, rush=0):
    m = (MIDAS["Midas Sprint"][sprint - 1] if sprint else 1) * (MIDAS["Midas Rush"][rush - 1] if rush else 1)
    return RECOVERY_H["Gold Rock"] * m


def stock(skills, toolshed=True):
    s = {k: math.ceil(v * 1.5) if toolshed else v for k, v in BASE_STOCK.items()}
    if skills.get("More Axes"):
        s["Axe"] += [50, 100, 150][skills["More Axes"] - 1]
    if skills.get("More Picks"):
        for k, v in MORE_PICKS.items():
            s[k] += v
    return s


def scenario(name, use, full, prices, iron_own):
    """use: tools needed a day. Restocks a day each tool forces = (use - shipment) / full stock."""
    p = lambda k: prices.get(k) or 0.0                                  # noqa: E731
    rows = {}
    for tool, n in use.items():
        rows[tool] = {"use": n, "restocks": max(0.0, n - SHIPMENT[tool]) / full[tool],
                      "flower": n * sum(q * p(i) for i, q in RECIPE[tool].items())}
    bind = max(rows, key=lambda t: rows[t]["restocks"])
    iron_need = use.get("Iron Pickaxe", 0) * 5
    return {"name": name, "tools": rows, "binding": bind, "restocks_day": rows[bind]["restocks"],
            "gems_week": rows[bind]["restocks"] * 7 * RESTOCK_GEMS, "iron_need": iron_need,
            "iron_own": iron_own, "iron_buy": max(0.0, iron_need - iron_own)}


def evaluate(farm, prices, cfg, wood_per_chop, gold_per_mine):
    """cfg: {"start", "end", "every", "tree_checks", "tree_mult", "stone_checks"} from config tools."""
    inv, skills = farm.get("inventory", {}), farm.get("skills", {})
    n = lambda k: int(inv.get(k, 0) or 0)                               # noqa: E731
    ch = checks(cfg.get("start", 6), cfg.get("end", 22), cfg.get("every", 2))
    late = checks(cfg.get("start", 6), 24, cfg.get("every", 2))
    full = stock(skills, toolshed=bool(n("Toolshed")))
    cur = (skills.get("Midas Sprint", 0), skills.get("Midas Rush", 0))
    combos = [("now", cur), ("Midas Sprint + Rush (rank 1, 5 points)", (1, 1)),
              ("Midas Sprint R2 + Rush R2 (14 points + 5 shards)", (2, 2))]
    gold = []
    for label, (s, r) in combos:
        cyc = gold_cycle(s, r)
        gold.append({"label": label, "cycle_h": cyc, "per_day": harvests_per_day(cyc, ch),
                     "per_day_midnight": harvests_per_day(cyc, late), "ideal": 24 / cyc})
    iron_y = 1 + (0.1 if "Iron Beetle" in farm.get("collectibles", []) else 0) - (0.5 if skills.get("Rocky Favor") else 0)
    # iron: with Rocky Favor a mine gives 0.6 iron for a Stone Pickaxe (3 Wood + 5 Stone): cheaper to buy.
    # tools.iron_checks = mines a day per iron rock you still do (0 = you buy your iron)
    iron_mines = n("Iron Rock") * cfg.get("iron_checks", 0)
    trees = n("Tree") * cfg.get("tree_mult", 1.15) * cfg.get("tree_checks", 9)
    stones = n("Stone Rock") * cfg.get("stone_checks", 5)
    crim = n("Crimstone Rock") * 1.0

    def use(gold_rate, extra_tree=0, extra_gold=0):
        return {"Axe": trees + extra_tree * cfg.get("tree_mult", 1.15) * cfg.get("tree_checks", 9),
                "Pickaxe": stones, "Stone Pickaxe": iron_mines, "Gold Pickaxe": crim,
                "Iron Pickaxe": (n("Gold Rock") + extra_gold) * gold_rate}

    g_now, g_r1, g_r2 = (g["per_day"] for g in gold)
    iron_own = iron_mines * iron_y
    scen = [scenario("Today", use(g_now), full, prices, iron_own),
            scenario("Midas rank 1 (your checks)", use(g_r1), full, prices, iron_own),
            scenario("Gold 3x every 2 days (Midas R2 pair)", use(g_r2), full, prices, iron_own),
            scenario("... + 1 Tree (7 Sunstone)", use(g_r2, extra_tree=1), full, prices, iron_own),
            scenario("... + 1 Gold Rock (10 Sunstone)", use(g_r2, extra_gold=1), full, prices, iron_own)]
    p = lambda k: prices.get(k) or 0.0                                  # noqa: E731
    tree_week = cfg.get("tree_mult", 1.15) * cfg.get("tree_checks", 9) * 7 * wood_per_chop * p("Wood")
    gold_week = {g["label"]: g["per_day"] * 7 * gold_per_mine for g in gold}
    return {"checks": ch, "gold": gold, "stock": full, "shipment": SHIPMENT, "restock_gems": RESTOCK_GEMS,
            "iron": {"rocks": n("Iron Rock"), "per_mine": iron_y, "mines_day": iron_mines, "per_day": iron_own},
            "use": {"trees": n("Tree"), "stones": n("Stone Rock"), "gold": n("Gold Rock"), "crim": n("Crimstone Rock")},
            "scenarios": scen, "sunstone": {"tree": {"cost": 7, "flower_week": tree_week, "axe_coins_week": -20 * tree_week / max(1e-9, wood_per_chop * p("Wood"))},
                                            "gold": {"cost": 10, "flower_week": gold_week}},
            "shards": n("Ascension Shard"), "sunstone_have": n("Sunstone")}
