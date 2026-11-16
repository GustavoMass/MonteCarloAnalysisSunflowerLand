"""What is still open on this week's mega bounty board, and how to make each item.

Only what you still have to deliver; animals and Obsidian are left out. For each kind:
  * crafting (dolls and the like): the exact 3x3 grid and its FLOWER cost, each square
    bought at market or crafted from its own grid, whichever is cheaper;
  * crustaceans: which trap and which chum, and the chum's FLOWER cost;
  * fish: bait, the chum it likes, its seasons and any Fish Market bait that guarantees it;
  * flowers: when your flower plan plants and harvests it;
  * exotic crops: where they come from (giant fruit is left out: daily village help).
Grids come from Data/crafting_recipes.json (sfl.world), the rest from the game code (game.py,
Data/fish_rules.json). Prices are today's floors.
"""
from . import game as G

SKIP = set(G.ANIMALS) | {"Obsidian"} | set(G.GIANT_FRUIT)  # giant fruit: daily village help, not up to the player


def _craft_cost(name, grids, prices, depth=0, seen=()):
    """(FLOWER, how) for one unit: market floor or crafting it, whichever is cheaper."""
    market = prices.get(name)
    crafted = None
    if name in grids and depth < 4 and name not in seen:
        cost = 0.0
        for c in grids[name]:
            if not c:
                continue
            v, _ = _craft_cost(c, grids, prices, depth + 1, seen + (name,))
            if v is None:
                cost = None
                break
            cost += v
        crafted = cost
    if market is not None and (crafted is None or market <= crafted):
        return market, "buy"
    if crafted is not None:
        return crafted, "craft"
    return None, "no price"


def _crafting(name, grids, prices, inv):
    cells = grids[name]
    counts = {}
    for c in cells:
        if c:
            counts[c] = counts.get(c, 0) + 1
    lines, total, missing = [], 0.0, False
    for item, q in counts.items():
        unit, how = _craft_cost(item, grids, prices)
        sub = None
        if how == "craft":
            sub = {k: grids[item].count(k) for k in dict.fromkeys(c for c in grids[item] if c)}
        lines.append({"item": item, "qty": q, "unit": unit, "cost": None if unit is None else unit * q, "how": how,
                      "have": int(inv.get(item, 0) or 0), "sub": sub})
        if unit is None:
            missing = True
        else:
            total += unit * q
    return {"grid": cells, "lines": lines, "total": total, "partial": missing}


def _bait_recipe(chum, season, prices):
    """Fish Market recipe for a non-tradeable bait this season, and its FLOWER cost if all priced."""
    r = G.FISH_MARKET.get(chum, {}).get(season)
    if not r:
        return None, None
    cost = sum(prices[k] * q for k, q in r.items()) if all(prices.get(k) for k in r) else None
    return r, cost


def _crustacean(name, prices, season, inv):
    ways = []
    for trap, table in G.CRUSTACEAN_TRAPS.items():
        for chum, out in table.items():
            if out != name:
                continue
            q = G.CRUSTACEAN_CHUMS[trap].get(chum, 0) if chum else 0
            unit = prices.get(chum) if chum else 0.0
            recipe = None
            if chum and unit is None:
                recipe, unit = _bait_recipe(chum, season, prices)
            pot = G.TRAP_RECIPES.get(trap, {"coins": 0, "items": {}})
            pot_items = [{"item": k, "qty": n, "unit": prices.get(k),
                          "cost": None if prices.get(k) is None else prices[k] * n} for k, n in pot["items"].items()]
            pot_cost = sum(x["cost"] or 0 for x in pot_items)
            chum_cost = None if unit is None else unit * q
            ways.append({"trap": trap, "hours": G.TRAP_HOURS[trap], "chum": chum, "qty": q, "recipe": recipe,
                         "have": int(inv.get(chum, 0) or 0) if chum else None,
                         "cost": chum_cost, "pot_have": int(inv.get(trap, 0) or 0), "pot_coins": pot["coins"],
                         "pot_items": pot_items, "pot_cost": pot_cost,
                         "total": None if chum_cost is None else chum_cost + pot_cost})
    ways.sort(key=lambda w: (w["total"] is None, w["total"] or 0))
    return ways


def _fish(name, rules, prices):
    f = rules["fish"].get(name, {})
    amounts = rules.get("chum_amounts", {})
    likes = [{"chum": c, "qty": amounts.get(c), "cost": None if prices.get(c) is None or amounts.get(c) is None
              else prices[c] * amounts[c]} for c in f.get("likes", [])]
    guaranteed = [b for b, xs in rules.get("guaranteed_bait", {}).items() if name in xs]
    return {"baits": f.get("baits", []), "likes": likes, "seasons": f.get("seasons", []), "guaranteed": guaranteed}


def open_items(board_week, prices, inv, grids, fish_rules, flowers, schedule, season=None):
    """Every open board item with how to make it, grouped by kind."""
    out = []
    for b in board_week.get("board", []):
        name = b["label"]
        if b.get("done") or name in SKIP:
            continue
        row = {"name": name, "tickets": b.get("tickets"), "have": int(inv.get(name, 0) or 0)}
        if name in flowers:
            plan = [x for x in schedule if x["flower"] == name and not x.get("parent_for")]
            row.update(kind="flower", plan=plan[:1])
        elif name in grids:
            row.update(kind="craft", **_crafting(name, grids, prices, inv))
        elif any(name in t.values() for t in G.CRUSTACEAN_TRAPS.values()):
            row.update(kind="crustacean", ways=_crustacean(name, prices, season, inv))
        elif name in fish_rules.get("fish", {}):
            row.update(kind="fish", **_fish(name, fish_rules, prices))
        elif name in G.EXOTIC_TICKETS:
            row.update(kind="exotic", how=f"Potion House: {G.EXOTIC_TICKETS[name]} Potion Tickets")
        else:
            row.update(kind="other")
        row["price"] = prices.get(name)
        out.append(row)
    order = {"craft": 0, "crustacean": 1, "flower": 2, "fish": 3, "exotic": 4, "other": 5}
    out.sort(key=lambda r: (order[r["kind"]], -(r["tickets"] or 0)))
    return out
