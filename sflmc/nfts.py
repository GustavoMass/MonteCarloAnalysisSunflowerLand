"""Cheap NFTs (collectibles and wearables) that are not crop boosts: what each would pay on THIS farm.

Effects come from the game code (collectibleItemBuffs.ts / bumpkinItemBuffs.ts labels, en.json).
Rates are your lifetime averages per week (farm activity counters / weeks played):
  * flat bonus per harvest: extra = bonus x harvests per week (fruit: seeds planted x 3 harvests;
    honey: honey harvested, a full hive gives about 1; rocks, drills: their counters).
  * faster growth or production: extra = amount per week x (1/multiplier - 1) x speed_credit,
    because you do not come back on every shorter cycle.
  * animal NFTs: the herd Monte Carlo of the "Cheap boosts" section, per week.
NFTs can be sold again: "resale_weeks" pays back only the marketplace cut (price x tax), assuming the
floor holds. Sold goods (fruit, honey, stone, flowers) lose the marketplace tax; oil and crimstone are used, full price.
What has no market price or depends on server-side chances (sickness, treasure, fish) is listed, not valued.
"""

FRUITS = ("Apple", "Banana", "Orange", "Lemon", "Tomato", "Blueberry")
PLANTED = {"Banana": "Banana Plant Planted"}
FRUIT_HARVESTS = 3            # fruit seed harvests before the patch is empty (base)

# name: (effect, how) ; how = ("flat", resource|"fruit", bonus) | ("speed", resource|"fruit", mult)
#       | ("animal",) | ("note", text)
CATALOG = {
    "Bee Suit": ("+0.1 Honey per full beehive", ("flat", "Honey", 0.1)),
    "Ruins Flower": ("+0.05 Honey per full beehive", ("flat", "Honey", 0.05)),
    "Beekeeper Hat": ("+20% honey production speed", ("speed", "Honey", 1 / 1.2)),
    "Camel Onesie": ("+0.1 fruit per fruit patch harvest", ("flat", "fruit", 0.1)),
    "Macaw": ("+0.1 fruit per fruit patch harvest", ("flat", "fruit", 0.1)),
    "Fruit Tune Box": ("x0.8 fruit patch growth time", ("speed", "fruit", 0.8)),
    "Lady Bug": ("+0.25 Apple", ("flat", "Apple", 0.25)),
    "Banana Chicken": ("+0.1 Banana", ("flat", "Banana", 0.1)),
    "Banana Onesie": ("x0.8 Banana growth time", ("speed", "Banana", 0.8)),
    "Nana": ("x0.9 Banana growth time", ("speed", "Banana", 0.9)),
    "Banana Amulet": ("+0.5 Banana", ("flat", "Banana", 0.5)),
    "Reveling Lemon": ("+0.25 Lemon", ("flat", "Lemon", 0.25)),
    "Lemon Shark": ("+0.2 Lemon", ("flat", "Lemon", 0.2)),
    "Lemon Frog": ("x0.75 Lemon growth time", ("speed", "Lemon", 0.75)),
    "Squirrel Monkey": ("x0.5 Orange growth time", ("speed", "Orange", 0.5)),
    "Tunnel Mole": ("+0.25 Stone per rock", ("flat", "Stone", 0.25)),
    "Knight Chicken": ("+0.1 Oil per drill", ("flat", "Oil", 0.1)),
    "Battle Fish": ("+0.05 Oil per drill", ("flat", "Oil", 0.05)),
    "Crimstone Armor": ("+0.1 Crimstone per rock", ("flat", "Crimstone", 0.1)),
    "Crim Peckster": ("+0.1 Crimstone per rock", ("flat", "Crimstone", 0.1)),
    "Desert Rose": ("10% chance of +1 flower", ("flat", "flower", 0.1)),
    "Flower Fox": ("x0.9 flower growth time", ("speed", "flower", 0.9)),
    # animals: valued by the herd simulation
    "Dream Scarf": ("x0.8 Sheep sleep time", ("animal",)),
    "Spa Sheep": ("+5 Sheep XP from affection tools", ("animal",)),
    "Ascended Sheep": ("+0.05 Wool", ("animal",)),
    "Mermaid Sheep": ("x0.95 Sheep feed", ("animal",)),
    "Astronaut Sheep": ("+0.1 Wool", ("animal",)),
    "Merino Jumper": ("+1 Merino Wool", ("animal",)),
    "Ascended Cow": ("x0.975 Cow sleep time", ("animal",)),
    "Spa Cow": ("+0.1 Milk", ("animal",)),
    "Baby Cow": ("+10 Cow XP from affection tools", ("animal",)),
    "Longhorn Cowfish": ("+0.2 Milk", ("animal",)),
    "Mammoth": ("x0.75 Cow sleep time", ("animal",)),
    "Alien Chicken": ("+0.1 Feather", ("animal",)),
    "Ascended Chicken": ("+0.1 Egg", ("animal",)),
    # listed, not valued
    "Nurse Sheep": ("Sheep cannot get sick in summer", ("note", "sickness chance is server-side")),
    "Frozen Sheep": ("Sheep cannot get sick in winter", ("note", "sickness chance is server-side")),
    "Frozen Cow": ("Cows cannot get sick in winter", ("note", "sickness chance is server-side")),
    "Summer Chicken": ("Chickens cannot get sick in summer", ("note", "sickness chance is server-side")),
    "Anemone Flower": ("+1 fishing minigame attempt", ("note", "one more try at each map-piece puzzle")),
    "Reelmaster's Chair": ("+5 daily fishing reels", ("note", "+35 casts a week (fish are not tradeable)")),
    "Jellyfish": ("+1 fish per catch in summer", ("note", "fish are not tradeable")),
    "Pink Dolphin": ("+1 fish per catch in spring", ("note", "fish are not tradeable")),
    "Poseidon": ("+1 fish per catch in autumn", ("note", "fish are not tradeable")),
    "Pharaoh Chicken": ("+1 daily desert dig", ("note", "+7 digs a week; treasure is random")),
    "Heart of Davy Jones": ("+20 daily desert digs", ("note", "+140 digs a week; treasure is random")),
    "Crab Trap": ("+1 Crab when digging or drilling", ("note", "Crab has no market price")),
    "Observatory": ("x1.05 Bumpkin XP", ("note", "5% more XP from all food")),
    "Maneki Neko": ("1 free food per day", ("note", "random food")),
    "Architect Ruler": ("x0.75 crafting box time", ("note", "dolls for the board come out faster")),
    "Speed Trap": ("x0.8 crab/mariner pot time", ("note", "more crustaceans per day")),
    "Soil Krabby": ("x0.9 composter time", ("note", "fertiliser has no market price")),
    "Salt Bottle Onesie": ("+1 Spice Rack output", ("note", "salt products have no market price")),
    "Pet Bowls": ("+10 Pet XP per food request", ("note", "")),
    "Chef Apron": ("+20% cake delivery profit", ("note", "")),
    "Grain Grinder": ("x1.2 XP from cakes", ("note", "")),
    "Skill Shrimpy": ("x1.2 XP from fish", ("note", "")),
    "Swiss Whiskers": ("+500 XP from cheese recipes", ("note", "")),
    "Rooster": ("2x chance of a mutant chicken", ("note", "")),
}


def _rates(farm):
    act, wk = farm.get("activity", {}), max(farm.get("weeks_played") or 1, 1)
    return lambda k: act.get(k, 0) / wk                                  # noqa: E731


def evaluate(farm, prices, nfts, boosts, flower_names, usd, cap_usd=30, tax=0.125, speed_credit=0.5, chapter_weeks=12,
             max_resale_weeks=None):
    """Rows for every NFT in CATALOG that costs <= cap_usd and you do not own, cheapest payback first."""
    r = _rates(farm)
    p = lambda k: prices.get(k) or 0.0                                   # noqa: E731
    used = {"Oil", "Crimstone"}
    val = lambda res, q: q * p(res) * (1 if res in used else 1 - tax)    # noqa: E731
    own = set(farm.get("collectibles", [])) | set(farm.get("wearables", []))
    sim = {b["name"]: b for b in boosts}
    fl_amt = {f: r(f"{f} Harvested") for f in flower_names if r(f"{f} Harvested")}

    def flat(res, bonus):
        if res == "fruit":
            return sum(val(f, bonus * r(PLANTED.get(f, f"{f} Seed Planted")) * FRUIT_HARVESTS) for f in FRUITS)
        if res == "flower":
            return sum(val(f, bonus * a) for f, a in fl_amt.items())
        events = {"Honey": r("Honey Harvested"), "Stone": r("Stone Rock Mined"), "Oil": r("Oil Drilled"),
                  "Crimstone": r("Crimstone Mined")}.get(res)
        if events is None:                                               # a single fruit
            events = r(PLANTED.get(res, f"{res} Seed Planted")) * FRUIT_HARVESTS
        return val(res, bonus * events)

    def speed(res, mult):
        extra = (1 / mult - 1) * speed_credit
        if res == "fruit":
            return sum(val(f, r(f"{f} Harvested") * extra) for f in FRUITS)
        if res == "flower":
            return sum(val(f, a * extra) for f, a in fl_amt.items())
        return val(res, r(f"{res} Harvested") * extra)

    rows = []
    for name, (effect, how) in CATALOG.items():
        info = nfts.get(name) or {}
        price = info.get("price")
        if name in own or not price or price * usd > cap_usd:
            continue
        week, note = None, ""
        if how[0] == "flat":
            week = flat(how[1], how[2])
        elif how[0] == "speed":
            week = speed(how[1], how[2])
        elif how[0] == "animal":
            b = sim.get(name)
            week = b["flower"] / chapter_weeks if b else None
            note = "herd simulation" + ("; costs more feed than it saves" if b and b["flower"] < 0 else "")
        else:
            note = how[1]
        rows.append({"name": name, "kind": info.get("kind", ""), "effect": effect, "price": price,
                     "usd": price * usd, "listings": info.get("listings"), "week": week,
                     "payback_weeks": price / week if week and week > 0 else None,
                     "resale_weeks": price * tax / week if week and week > 0 else None, "note": note})
    if max_resale_weeks:
        rows = [x for x in rows if x["resale_weeks"] is not None and x["resale_weeks"] <= max_resale_weeks]
    rows.sort(key=lambda x: (x["payback_weeks"] is None, x["payback_weeks"] or x["price"]))
    return rows
