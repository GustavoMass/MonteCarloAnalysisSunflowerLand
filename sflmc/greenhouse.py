"""Greenhouse: what one round of Rice, Olive or Grape costs and gives, and which skills / NFTs make it pay.

Game rules (sunflower-land src/features/game):
  * Building (types/buildings.ts): 4800 coins, 500 Wood, 100 Stone, 25 Crimstone, 100 Oil, level 46, desert.
  * 4 pots (plantGreenhouse.ts MAX_POTS). Oil goes into a tank of up to 100 (oilGreenHouse.ts) and each
    planting drains OIL_USAGE: Grape 3, Rice 4, Olive 6. Seeds cost coins only (not counted here).
  * Grow time: Rice 32 h, Olive 44 h (crops.ts), Grape 12 h (fruits.ts).
  * Yield (harvestGreenHouse.ts getGreenhouseCropYieldAmount): 1 per pot. Rice and Olive also get the
    generic crop boosts of harvest.ts (Scarecrow / Kuebiko x1.2, Infernal Pitchfork +3); Grape gets only the
    grape items of fruitHarvested.ts (patch-fruit boosts such as Macaw or Fruitful Fumble do not apply).
    Then every greenhouse plant: Greenhouse Gamble (chance of +1), Pharaoh Gnome +2, Glass Room,
    Seeded Bounty, Greasy Plants.
  * Oil (plantGreenhouse.ts getOilUsage): x Greasy Plants, then - Slick Saver, then Rice Shirt x0.5 on Rice.
  * Skill tiers (choseSkill.ts getTierThresholds): Greenhouse tier 2 opens after 2 points in the tree,
    tier 3 after 5 points in tiers 1-2.
Oil has no market price; it is valued at its Oil Drill cost (config derived_prices).
"""

CROPS = {"Rice": {"hours": 32, "oil": 4, "crop": True},
         "Olive": {"hours": 44, "oil": 6, "crop": True},
         "Grape": {"hours": 12, "oil": 3, "crop": False}}
POTS = 4
BUILD = {"Wood": 500, "Stone": 100, "Crimstone": 25, "Oil": 100}

# name: kind, cost (skill points, or None for NFTs: priced from nft_prices.json), effect
#   add: {crop or "*": +yield}, mult: {crop: x yield before the adds}, oil_mult / oil_minus / time: {crop or "*": v}
BOOSTS = [
    ("Glass Room", "skill", 1, "tier 1", {"add": {"*": 0.1}}),
    ("Seeded Bounty", "skill", 2, "tier 2 (2 points in the tree first); +1 seed per planting (coins)", {"add": {"*": 0.5}}),
    ("Greenhouse Gamble", "skill", 3, "tier 3 (5 points in tiers 1-2 first); 30% chance of +1", {"add": {"*": 0.3}}),
    ("Slick Saver", "skill", 3, "tier 3; -1 Oil per planting", {"oil_minus": {"*": 1}}),
    ("Greasy Plants", "skill", 3, "tier 3; +1 yield but x2 Oil", {"add": {"*": 1}, "oil_mult": {"*": 2}}),
    ("Rice and Shine", "skill", 1, "tier 1; x0.95 grow time", {"time": {"*": 0.95}}),
    ("Pharaoh Gnome", "collectible", None, "+2 every greenhouse plant", {"add": {"*": 2}}),
    ("Scarecrow", "collectible", None, "x1.2 crops (Rice, Olive)", {"mult": {"Rice": 1.2, "Olive": 1.2}}),
    ("Rice Panda", "collectible", None, "+0.25 Rice", {"add": {"Rice": 0.25}}),
    ("Non La Hat", "wearable", None, "+1 Rice", {"add": {"Rice": 1}}),
    ("Rice Shirt", "wearable", None, "+1 Rice, x0.5 Oil on Rice", {"add": {"Rice": 1}, "oil_half": {"Rice": 0.5}}),
    ("Olive Royalty Shirt", "wearable", None, "+0.25 Olive", {"add": {"Olive": 0.25}}),
    ("Olive Shield", "wearable", None, "+1 Olive", {"add": {"Olive": 1}}),
    ("Vinny", "collectible", None, "+0.25 Grape", {"add": {"Grape": 0.25}}),
    ("Grape Pants", "wearable", None, "+0.2 Grape", {"add": {"Grape": 0.2}}),
    ("Grape Granny", "collectible", None, "+1 Grape", {"add": {"Grape": 1}}),
    ("Turbo Sprout", "collectible", None, "x0.5 grow time", {"time": {"*": 0.5}}),
]
BY_NAME = {b[0]: b for b in BOOSTS}


def _get(d, crop, default):
    return d.get(crop, d.get("*", default))


def plant(crop, names, prices, oil_price, tax):
    """One planting of crop with the boosts in names: oil, yield, FLOWER value used / sold, profit."""
    c = CROPS[crop]
    eff = [BY_NAME[n][4] for n in names]
    mult, add, time = 1.0, 0.0, c["hours"]
    for e in eff:
        if c["crop"]:
            mult *= e.get("mult", {}).get(crop, 1)
        add += _get(e.get("add", {}), crop, 0)
        time *= _get(e.get("time", {}), crop, 1)
    oil = c["oil"]
    for e in eff:
        oil *= _get(e.get("oil_mult", {}), crop, 1)
    for e in eff:
        oil -= _get(e.get("oil_minus", {}), crop, 0)
    for e in eff:
        oil *= e.get("oil_half", {}).get(crop, 1)
    oil = max(0.0, oil)
    y = mult + add
    price = prices.get(crop) or 0
    oil_cost = oil * oil_price
    per_day = POTS * 24 / time
    return {"crop": crop, "oil": oil, "oil_cost": oil_cost, "yield": y, "hours": time,
            "used": y * price - oil_cost, "sold": y * price * (1 - tax) - oil_cost,
            "per_day": per_day, "used_day": per_day * (y * price - oil_cost), "oil_day": per_day * oil,
            "break_even": oil_cost / price if price else None}


def evaluate(farm, prices, nft_prices, tax, oil_per_drill=16.6667):
    oil_price = prices.get("Oil") or 0
    owned = set(farm.get("collectibles", [])) | set(farm.get("wearables", []))
    skills = farm.get("skills", {})
    have = [n for n, kind, *_ in BOOSTS if (kind == "skill" and skills.get(n)) or (kind != "skill" and n in owned)]
    build = {k: q * (prices.get(k) or 0) for k, q in BUILD.items()}
    base = {c: plant(c, have, prices, oil_price, tax) for c in CROPS}
    # skill paths, cheapest first (points include the ones that open each tier)
    paths = [("Today", []),
             ("Glass Room (1 point)", ["Glass Room"]),
             ("+ Rice and Shine + Seeded Bounty (4 points)", ["Glass Room", "Rice and Shine", "Seeded Bounty"]),
             ("+ Greenhouse Gamble + Slick Saver (11 points: one more tier-1 point, e.g. Seedy Business, opens tier 3)",
              ["Glass Room", "Rice and Shine", "Seeded Bounty", "Greenhouse Gamble", "Slick Saver"])]
    skill_rows = [{"name": label, "crops": {c: plant(c, sorted(set(have) | set(ns)), prices, oil_price, tax) for c in CROPS}}
                  for label, ns in paths]
    best_skills = paths[-1][1]
    nft_rows = []
    for n, kind, _, note, eff in BOOSTS:
        if kind == "skill":
            continue
        crops = [c for c in CROPS if _get(eff.get("add", {}), c, 0) or eff.get("mult", {}).get(c) or
                 _get(eff.get("time", {}), c, 1) != 1 or eff.get("oil_half", {}).get(c)]
        for c in crops:
            if c == "Grape" and eff.get("mult"):
                continue
            row = {"name": n, "kind": kind, "note": note, "crop": c, "owned": n in owned,
                   "price": (nft_prices.get(n) or {}).get("price")}
            for tag, ns in (("now", have), ("skills", best_skills)):
                a = plant(c, sorted(set(have) | set(ns)), prices, oil_price, tax)
                b = plant(c, sorted(set(have) | set(ns) | {n}), prices, oil_price, tax)
                row[tag] = {"day": b["used_day"], "gain_week": 7 * (b["used_day"] - a["used_day"])}
            row["payback_weeks"] = (row["price"] / row["skills"]["gain_week"]
                                    if row["price"] and row["skills"]["gain_week"] > 0.01 else None)
            nft_rows.append(row)
    return {"oil_price": oil_price, "tax": tax, "pots": POTS, "build": build, "build_total": sum(build.values()),
            "have": have, "today": base, "skills": skill_rows, "nfts": nft_rows,
            "oil_made_day": float(farm.get("inventory", {}).get("Oil Reserve", 0) or 0) * 24 / 20 * oil_per_drill}
