"""Farm-wide upgrades outside animals: skills of the other trees and crop items,
valued in FLOWER and coins per chapter from YOUR activity counters.

Every row is a small formula: (extra units per week) x (market price). Rates are
lifetime averages (farm counters / weeks played), so they lag behind a recent
change of habits. Assumptions, all from the game code unless noted:

  * Things you sell (stone, fruit, crops, salt) lose the marketplace tax; things
    you consume or buy (wood, iron, gold, crimstone, oil) count at full price.
  * A faster regrowth only pays when you come back in time to use it. You do not
    collect on every cycle, so speed boosts get `speed_credit` (default half) of
    their theoretical extra harvests.
  * Tool costs (game code): Axe 20 coins; Pickaxe 20 + 3 Wood; Iron Pickaxe 80 +
    3 Wood + 5 Iron (gold rocks); Gold Pickaxe 100 + 3 Wood + 3 Gold (crimstone);
    Rod 20 + 3 Wood + 1 Stone; Salt Rake 20 + 2 Wood + 1 Stone.
  * Fish, fertilisers, salt products and XP have no market price; those rows show
    units instead of FLOWER.
"""

BASIC_MEDIUM = ["Sunflower", "Potato", "Rhubarb", "Pumpkin", "Zucchini", "Carrot", "Yam", "Cabbage", "Broccoli",
                "Soybean", "Beetroot", "Pepper", "Cauliflower", "Parsnip"]
ADVANCED = ["Eggplant", "Corn", "Onion", "Radish", "Wheat", "Turnip", "Kale", "Artichoke", "Barley"]
FRUIT_SEED_COINS = {"Tomato": 5, "Lemon": 15, "Blueberry": 30, "Orange": 50, "Apple": 70, "Banana": 70}
FRUIT_SEED_ITEM = {"Banana": "Banana Plant"}
CROP_ITEMS = ["Nancy", "Scarecrow", "Lunar Calendar", "Green Amulet", "Sir Goldensnout", "Seed Specialist"]
LATER_TREES = ("Greenhouse", "Machinery")
NOW_MACHINERY = ("Oil Extraction", "Oil Rig", "Oil Be Back")   # oil reserves work without the crop machine


def _tier_unlocked(tree_skills, owned):
    """Highest tier open in each tree (choseSkill.ts getUnlockedTierForTree)."""
    out = {}
    for tree, sk in tree_skills.items():
        t1 = sorted(s["points"] for s in sk if s["tier"] == 1)
        need2 = sum(t1[:len(t1) // 2])
        need3 = sum(t1) + 1
        used = sum(s["points"] for s in sk if s["name"] in owned and s["tier"] != 3)
        out[tree] = 3 if used >= need3 else 2 if used >= need2 else 1
    return out


def evaluate(farm, prices, skill_tree, nfts, tax=0.125, speed_credit=0.8, coins_per_flower=1000, weeks=12,
             item_prices=None, crop_plan=None, crop_yield=None):
    """crop_plan {crop: cycles per week on every plot}; crop_yield {"boosted_plots", "boosted", "other"}
    = crops per harvest. Without a plan, the lifetime harvest counters at 1 crop per harvest are used."""
    act, wk = farm.get("activity", {}), max(farm.get("weeks_played") or 1, 1)
    r = lambda k: act.get(k, 0) / wk                                   # noqa: E731  per week
    p = lambda k: prices.get(k) or 0.0                                 # noqa: E731
    sold = lambda item, q: q * p(item) * (1 - tax)                     # noqa: E731
    used = lambda item, q: q * p(item)                                 # noqa: E731
    owned = set(farm.get("skills", {}))
    have = set(farm.get("collectibles", [])) | set(farm.get("wearables", []))
    by_tree = {}
    for s in skill_tree:
        by_tree.setdefault(s["tree"], []).append(s)
    tier = _tier_unlocked(by_tree, owned)
    info = {s["name"]: s for s in skill_tree}
    sp = lambda mult: (1 / mult - 1) * speed_credit                    # noqa: E731  extra share of harvests

    # your current yields per action (base 1 + what you own; see stoneMine.ts, mineGold.ts, chop.ts)
    stone_y = 1 + 1 + 0.1 + 0.1          # Rocky Favor, Rock'N'Roll, Stone Beetle
    gold_y = 1 + 0.5 + 0.1               # Golden Touch, Gold Beetle
    crim_y = 1 + 0.2                     # Fire Kissed: +1 on every 5th
    wood_y = 1.2 * (1 + 0.2) + 0.3       # Woody x1.2, Tough Tree 10% x3, +0.1 x3
    fruit_y = 1 + 0.1 + 0.2              # Fruitful Fumble, Macaw x2 (Loyal Macaw)
    chops, mines, gold_m, crim_m = r("Tree Chopped"), r("Stone Mined"), r("Gold Mined"), r("Crimstone Mined")
    fruit = {f: r(f"{f} Harvested") for f in FRUIT_SEED_COINS}
    plots = farm.get("plots") or 60
    if crop_plan:
        cy = crop_yield or {}
        nb = min(plots, cy.get("boosted_plots", 0))
        y = (nb * cy.get("boosted", 1) + (plots - nb) * cy.get("other", 1)) / plots
        harv = {c: n * plots for c, n in crop_plan.items()}
    else:
        y, harv = 1.0, {c: r(f"{c} Harvested") for c in BASIC_MEDIUM + ADVANCED}
    crop_val = sum(sold(c, q * y) for c, q in harv.items())           # what your crops sell for a week
    base_val = sum(sold(c, q) for c, q in harv.items())               # one crop per harvest: what x-multipliers act on
    per_stone_mine = sold("Stone", stone_y) - used("Wood", 3)
    per_gold_mine = used("Gold", gold_y) - used("Iron", 5) - used("Wood", 3)
    per_crim_mine = used("Crimstone", crim_y) - used("Gold", 3) - used("Wood", 3)
    rows = []

    def add(group, name, flower_wk=0.0, coins_wk=0.0, other="", note="", price=None):
        s = info.get(name)
        row = {"group": group, "name": name, "flower": flower_wk * weeks, "coins": coins_wk * weeks,
               "other": other, "note": note}
        if s:
            row.update(kind="skill", tree=s["tree"], tier=s["tier"], points=s["points"], desc=s["desc"],
                       open=tier.get(s["tree"], 1) >= s["tier"], owned=name in owned)
        else:
            row.update(kind="item", price=price, owned=name in have)
        row["total"] = row["flower"] + (row["coins"] / coins_per_flower if coins_per_flower else 0)
        rows.append(row)

    # ---- trees
    add("Trees", "Tree Charge", flower_wk=chops * sp(0.9) * used("Wood", wood_y), coins_wk=-chops * sp(0.9) * 20,
        note="more chops; each extra chop costs an Axe")
    add("Trees", "Feller's Discount", coins_wk=r("Axe Crafted") * 20 * 0.2, note=f"{r('Axe Crafted'):.0f} axes a week")
    add("Trees", "Money Tree", coins_wk=chops * 0.01 * 200, note=f"{chops:.0f} chops a week x 1% x 200")
    # ---- mining (iron left out: you mine stone and buy iron)
    add("Mining", "Speed Miner", flower_wk=mines * sp(0.8) * per_stone_mine, coins_wk=-mines * sp(0.8) * 20,
        note=f"{per_stone_mine:.3f} FLOWER per extra stone mine after wood")
    picks = r("Pickaxe Crafted") * 20 + r("Stone Pickaxe Crafted") * 20 + r("Iron Pickaxe Crafted") * 80 + r("Gold Pickaxe Crafted") * 100
    add("Mining", "Frugal Miner", coins_wk=picks * 0.2, note="all pickaxes 20% cheaper")
    for name, m in (("Midas Sprint", 0.9), ("Midas Rush", 0.8)):
        add("Mining", name, flower_wk=gold_m * sp(m) * per_gold_mine, coins_wk=-gold_m * sp(m) * 80,
            note=f"{per_gold_mine:.3f} FLOWER per extra gold mine after 5 Iron + 3 Wood")
    add("Mining", "Fireside Alchemist", flower_wk=crim_m * sp(0.85) * per_crim_mine, coins_wk=-crim_m * sp(0.85) * 100,
        note=f"{per_crim_mine:.3f} FLOWER per extra crimstone mine after 3 Gold + 3 Wood")
    # ---- fruit
    fruit_val = sum(sold(f, q * fruit_y) for f, q in fruit.items())
    add("Fruit", "Generous Orchard", flower_wk=sum(sold(f, q * 0.2) for f, q in fruit.items()),
        note="20% chance of +1 fruit on every harvest")
    add("Fruit", "Catchup", flower_wk=fruit_val * sp(0.9), note="fruit regrows 10% faster")
    add("Fruit", "Zesty Vibes", flower_wk=sold("Tomato", fruit["Tomato"]) + sold("Lemon", fruit["Lemon"])
        - sum(sold(f, q * 0.25) for f, q in fruit.items() if f not in ("Tomato", "Lemon")),
        note="+1 Tomato/Lemon, -0.25 every other fruit")
    for name, fast in (("Long Pickings", ("Apple", "Banana")), ("Short Pickings", ("Blueberry", "Orange"))):
        add("Fruit", name, flower_wk=sum(sold(f, q * fruit_y) * (sp(0.75) if f in fast else -(1 - 1 / 1.1) * speed_credit)
                                         for f, q in fruit.items()),
            note=f"{'/'.join(fast)} 25% faster, the rest 10% slower")
    seed_coins = sum(r(f"{FRUIT_SEED_ITEM.get(f, f + ' Seed')} Bought") * c for f, c in FRUIT_SEED_COINS.items())
    add("Fruit", "Fruity Heaven", coins_wk=seed_coins * 0.1, note=f"{seed_coins:.0f} coins of fruit seeds a week")
    add("Fruit", "Pear Turbocharge", coins_wk=seed_coins / 6, note="one more harvest per seed (5 -> 6): fewer seeds to buy")
    add("Fruit", "Crime Fruit", other="+10 Tomato and Lemon seeds per restock", note="only helps if you run out of those seeds")
    # ---- fishing (fish have no market price)
    add("Fishing", "Reel Deal", coins_wk=r("Rod Crafted") * 10, note=f"{r('Rod Crafted'):.0f} rods a week, half price")
    add("Fishing", "Fishy Chance", other=f"about +{0.1 * r('Rod Crafted'):.0f} basic fish a week (10% of casts)")
    add("Fishing", "Fisherman's 10 Fold", other="+70 casts a week (needs bait)")
    add("Fishing", "More With Less", other="+70 casts a week (needs bait)")
    add("Fishing", "Fishy Fortune", other="Corale coin deliveries x2", note="depends on how often you deliver to Corale")
    add("Fishing", "Frenzied Fish", other="+1 to +1.5 fish per cast during a frenzy")
    add("Fishing", "Fishy Feast", other="x1.2 XP when you eat fish")
    # ---- salt and aging
    add("Salt and aging", "Wide Rakes", flower_wk=sold("Salt", 2 * r("Salt Harvested")), note=f"{r('Salt Harvested'):.0f} salt harvests a week")
    add("Salt and aging", "Cheap Rakes", coins_wk=r("Salt Rake Crafted") * 4)
    add("Salt and aging", "Salty Seas", other="salt nodes recharge 10% faster")
    add("Salt and aging", "Speedy Aging", other="fish age 10% faster")
    add("Salt and aging", "Fish Smoking", other="twice the chance of Prime Aged fish")
    add("Salt and aging", "Refiner", other="15% chance of +1 Refined Salt")
    add("Salt and aging", "Sea Blessed", other="5% chance to restore 1 charge to 4 salt nodes")
    add("Salt and aging", "Ager", other="2x output and 2x inputs on Aging Shed racks")
    # ---- cooking (XP and time, no FLOWER)
    add("Cooking", "Double Nom", other="+1 food per cook for 2x ingredients: same cost per food, twice the food per hour")
    add("Cooking", "Juicy Boost", other="x1.1 XP from drinks (Smoothie Shack)")
    add("Cooking", "Frosted Cakes", other="cakes 10% faster (Lemon Cheesecake)")
    add("Cooking", "Swift Sizzle", other=f"Fire Pit 40% faster, 1 Oil per cook ({p('Oil'):.3f} FLOWER)")
    add("Cooking", "Turbo Fry", other=f"Kitchen 50% faster, 1 Oil per cook ({p('Oil'):.3f} FLOWER)")
    add("Cooking", "Fry Frenzy", other=f"Deli 60% faster, 1 Oil per cook ({p('Oil'):.3f} FLOWER)")
    # ---- compost (fertilisers have no market price)
    add("Compost", "Efficient Bin", other=f"+{5 * r('Compost Bin Collected'):.0f} Sprout Mix a week")
    add("Compost", "Turbo Charged", other=f"+{5 * r('Turbo Composter Collected'):.0f} Fruitful Blend a week")
    add("Compost", "Premium Worms", other=f"+{10 * r('Premium Composter Collected'):.0f} Rapid Root a week")
    # ---- oil (works now, no crop machine needed)
    drills = r("Oil Drilled")
    add("Oil", "Oil Extraction", flower_wk=used("Oil", drills), note=f"+1 Oil on each of your {drills:.0f} drills a week")
    add("Oil", "Oil Rig", flower_wk=drills * (used("Leather", 10) - used("Wool", 20)), note="Oil Drill takes 20 Wool instead of 10 Leather")
    add("Oil", "Oil Be Back", other="reserves refill 20% faster", note=f"you drill {drills:.0f} a week, below what 2 reserves allow, so no gain now")
    # ---- crop items (one growth slot: Nancy, Scarecrow and Kuebiko do not stack)
    def price(n):   # your own price in config wins; these items are not in the sfl-manager catalog
        return (item_prices or {}).get(n) or (nfts.get(n) or {}).get("price")
    add("Crop items", "Nancy", flower_wk=crop_val * sp(0.85), price=price("Nancy"), note="crops grow 15% faster")
    add("Crop items", "Scarecrow", flower_wk=crop_val * sp(0.85) + base_val * 0.2, price=price("Scarecrow"), note="15% faster and x1.2 on the base crop (before the +yield bonuses)")
    add("Crop items", "Lunar Calendar", flower_wk=crop_val * sp(0.9), price=price("Lunar Calendar"), note="crops grow 10% faster")
    add("Crop items", "Seed Specialist", flower_wk=crop_val * sp(0.9), price=price("Seed Specialist"), note="crops grow 10% faster")
    add("Crop items", "Green Amulet", flower_wk=base_val * 0.9, price=price("Green Amulet"), note="10% chance of x10 on the base crop of every harvest")
    add("Crop items", "Sir Goldensnout", flower_wk=crop_val / y * 0.5 * 8 / plots, price=price("Sir Goldensnout"),
        note="+0.5 crop on the ~8 plots around it")

    out = [x for x in rows if not x.get("owned")]
    rates = {"chops": chops, "stone_mines": mines, "gold_mines": gold_m, "crimstone_mines": crim_m,
             "fruit_harvests": sum(fruit.values()), "crop_value_week": crop_val, "crop_yield": y, "crop_harvests_week": sum(harv.values()),
             "crop_plan": crop_plan, "plots": plots, "weeks_played": wk,
             "per_stone_mine": per_stone_mine, "per_gold_mine": per_gold_mine, "per_crim_mine": per_crim_mine,
             "wood_per_chop": wood_y, "wood_price": used("Wood", 1),
             "fruit_value_week": sum(sold(f, q * fruit_y) for f, q in fruit.items())}
    return {"rows": out, "rates": rates, "speed_credit": speed_credit, "coins_per_flower": coins_per_flower}
