"""Game constants mirrored from the Sunflower Land source code.

Source: https://github.com/sunflower-land/sunflower-land (main, Nov 2026)
  - src/features/game/types/animals.ts            levels, food XP, drops
  - src/features/game/events/landExpansion/feedAnimal.ts   feed qty, sleep
  - src/features/game/events/landExpansion/loveAnimal.ts   love items/XP
  - src/features/game/lib/animals.ts             yield / food / sleep boosts
  - src/features/game/types/bumpkinSkills.ts     skill ranks
  - src/features/game/types/pigFeeds.ts          slop recipes
"""

ANIMALS = ("Chicken", "Cow", "Sheep", "Pig")

ANIMAL_LEVELS = {
    "Chicken": [0, 60, 120, 240, 360, 480, 660, 840, 1020, 1200, 1440, 1680, 1920, 2160, 2400, 2720],
    "Cow": [0, 180, 360, 720, 1080, 1440, 1980, 2520, 3060, 3600, 4320, 5040, 5760, 6480, 7200, 8160],
    "Sheep": [0, 120, 240, 480, 720, 960, 1320, 1680, 2040, 2400, 2880, 3360, 3840, 4320, 4800, 5440],
    "Pig": [0, 180, 360, 720, 1080, 1440, 1980, 2520, 3060, 3600, 4320, 5040, 5760, 6480, 7200, 8160],
}
MAX_LEVEL = 15

# Favourite food per level band. Favourite gives 60 XP (80 XP from level 10).
FAVOURITE_FOOD = {
    "Chicken": ["Kernel Blend"] * 3 + ["Hay"] * 3 + ["NutriBarley"] * 4 + ["Mixed Grain"] * 6,
    "Cow": ["Kernel Blend"] * 3 + ["Hay"] * 3 + ["NutriBarley"] * 4 + ["Mixed Grain"] * 6,
    "Sheep": ["Kernel Blend"] * 3 + ["Hay"] * 3 + ["NutriBarley"] * 4 + ["Mixed Grain"] * 6,
    "Pig": ["Basic Slop"] * 3 + ["Hearty Slop"] * 3 + ["Rich Slop"] * 4 + ["Gourmet Slop"] * 6,
}
FAVOURITE_XP = [60] * 10 + [80] * 6

# Units of food per single feed (feedAnimal.ts REQUIRED_FOOD_QTY).
REQUIRED_FOOD_QTY = {"Chicken": 1, "Sheep": 3, "Cow": 5, "Pig": 1}

# Crafted animal feeds (types/animals.ts ANIMAL_FOODS).
FEED_RECIPES = {
    "Kernel Blend": {"Corn": 1},
    "Hay": {"Wheat": 1},
    "NutriBarley": {"Barley": 1},
    "Mixed Grain": {"Wheat": 1, "Corn": 1, "Barley": 1},
}

# Pig slops: ONE ingredient of the tier, chosen when mixing (pigFeeds.ts).
# Only market-tradeable options are listed; fish/crustaceans also work for
# Rich/Gourmet but have no P2P price, so they are left out.
SLOP_OPTIONS = {
    "Basic Slop": {"Sunflower": 800, "Potato": 150, "Rhubarb": 100, "Pumpkin": 60, "Zucchini": 60,
                   "Carrot": 25, "Yam": 25, "Cabbage": 15, "Broccoli": 15, "Soybean": 9},
    "Hearty Slop": {"Beetroot": 15, "Pepper": 15, "Cauliflower": 8, "Parsnip": 5, "Tomato": 20,
                    "Lemon": 4, "Blueberry": 4},
    "Rich Slop": {"Eggplant": 6, "Wheat": 6, "Turnip": 6, "Corn": 5, "Onion": 5, "Radish": 5, "Kale": 4,
                  "Artichoke": 4, "Barley": 3, "Orange": 3, "Apple": 2, "Banana": 2},
    "Gourmet Slop": {"Rice": 1, "Olive": 1, "Grape": 1, "Celestine": 1, "Lunara": 1, "Duskberry": 1},
}

# Produce on claim, indexed by the level reached (ANIMAL_RESOURCE_DROP).
def _drops(pairs):
    return [dict(p) for p in pairs]

DROPS = {
    "Chicken": [{}] + [{"Egg": e, **({"Feather": f} if f else {})} for e, f in
                       [(1, 0), (1, 0), (1, 1), (2, 1), (2, 1), (2, 1), (2, 1), (3, 1), (3, 2), (3, 2),
                        (3, 2), (3, 2), (4, 2), (4, 2), (5, 3)]],
    "Cow": [{}] + [{"Milk": m, "Leather": l} for m, l in
                   [(1, 1), (1, 1), (1, 1), (2, 1), (2, 1), (2, 2), (2, 2), (3, 2), (3, 2), (3, 3),
                    (3, 3), (3, 3), (3, 3), (3, 3), (4, 4)]],
    "Sheep": [{}] + [{"Wool": w, "Merino Wool": m} for w, m in
                     [(1, 1), (1, 1), (1, 1), (2, 1), (2, 1), (2, 2), (2, 2), (3, 2), (3, 2), (3, 3),
                      (3, 3), (3, 3), (3, 3), (3, 3), (4, 4)]],
    "Pig": [{}] + [{"Truffle": t} for t in [1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 3, 4]],
}

PIG_BRISTLES_PER_LEVEL = [0, 0, 0, 1, 1, 2, 3, 3, 4, 5, 6, 6, 7, 8, 9, 12]

# Love: weighted tool request by level, XP per tool (loveAnimal.ts).
LOVE_WEIGHTS = [  # Petting Hand, Brush, Music Box
    (0, 0, 0), (10, 0, 0), (8, 2, 0), (7, 3, 0), (6, 3, 1), (5, 4, 1), (5, 3, 2), (4, 4, 2),
    (4, 3, 3), (3, 4, 3), (3, 3, 4), (2, 4, 4), (2, 3, 5), (1, 4, 5), (1, 3, 6), (1, 2, 7),
]
LOVE_ITEMS = ("Petting Hand", "Brush", "Music Box")
LOVE_XP = {"Petting Hand": 25, "Brush": 40, "Music Box": 50}
MAX_LOVES_PER_SLEEP = 2

BASE_SLEEP_HOURS = 24.0

# Skill ranks (bumpkinSkills.ts). Index = rank - 1.
SKILLS = {
    "Efficient Feeding": {"feed": [0.95, 0.94, 0.925]},
    "Restless Animals": {"sleep": [0.9, 0.85, 0.8]},
    "Fine Fibers": {"fibre": [0.1, 0.15, 0.2]},
    "Bountiful Bounties": {"coins": [0.5, 0.75, 1.0]},
    "Double Bale": {"bale": [2, 2.5, 3]},
    "Featherweight": {"buff": [0.35, 0.45, 0.55], "debuff": [0.1, 0.15, 0.2]},
    "Abundant Harvest": {"yield": [0.2, 0.35, 0.5]},
    "Heartwarming Instruments": {"love": [0.5, 0.6, 0.7]},
    "Merino Whisperer": {"buff": [0.35, 0.6, 0.9], "debuff": [0.1, 0.15, 0.2]},
    "Truffle Yield": {"mult": [0.1, 0.2, 0.3]},
    "Clucky Grazing": {"animal": "Chicken", "buff": [0.75, 0.65, 0.5], "debuff": [1.5, 1.55, 1.65]},
    "Sheepwise Diet": {"animal": "Sheep", "buff": [0.75, 0.65, 0.5], "debuff": [1.5, 1.55, 1.65]},
    "Cow-Smart Nutrition": {"animal": "Cow", "buff": [0.75, 0.65, 0.5], "debuff": [1.5, 1.55, 1.65]},
    "Swill Savvy": {"animal": "Pig", "buff": [0.75, 0.65, 0.5], "debuff": [1.5, 1.55, 1.65]},
    "Bristle Payout": {"mult": [0.1, 0.2, 0.3]},
    "Chonky Feed": {"xp": [2, 2.5, 3], "feed": [1.5, 1.75, 2]},
    "Leathercraft Mastery": {"buff": [0.35, 0.6, 0.8], "debuff": [0.1, 0.15, 0.2]},
}
DIET_SKILLS = ("Clucky Grazing", "Sheepwise Diet", "Cow-Smart Nutrition", "Swill Savvy")
FIBRE_SKILLS = {"Featherweight": "Feather", "Merino Whisperer": "Merino Wool", "Leathercraft Mastery": "Leather"}


def level_for_xp(animal, xp):
    lv = 0
    for i, t in enumerate(ANIMAL_LEVELS[animal]):
        if xp + 1e-9 >= t:
            lv = i
        else:
            break
    return lv


def cycle_xp(animal):
    lv = ANIMAL_LEVELS[animal]
    return lv[MAX_LEVEL] - lv[MAX_LEVEL - 1]


def xp_until_ready(animal, xp):
    """getXpUntilReady: XP to next level, or to end of the max-level cycle."""
    lv = ANIMAL_LEVELS[animal]
    if xp < lv[MAX_LEVEL]:
        return lv[level_for_xp(animal, xp) + 1] - xp
    c = cycle_xp(animal)
    return c - ((xp - lv[MAX_LEVEL]) % c)


def completed_cycle(animal, before, gained):
    """hasAnimalCompletedCycle: level-up, or a full cycle at max level."""
    lv = ANIMAL_LEVELS[animal]
    if before < lv[MAX_LEVEL]:
        return level_for_xp(animal, before) != level_for_xp(animal, before + gained)
    c = cycle_xp(animal)
    return ((before - lv[MAX_LEVEL]) % c) + gained >= c


# Building construction (level 1, types/buildings.ts) and upgrades
# (events/landExpansion/upgradeBuilding.ts): coins + items.
BUILDING_COSTS = {
    "Barn": {
        1: {"coins": 200, "items": {"Wood": 150, "Iron": 10, "Gold": 10}},
        2: {"coins": 10000, "items": {"Wood": 1000, "Iron": 100, "Gold": 75, "Crimstone": 30}},
        3: {"coins": 75000, "items": {"Wood": 5000, "Iron": 300, "Gold": 200, "Crimstone": 125, "Oil": 250}},
    },
    "Pigpen": {
        1: {"coins": 200, "items": {"Wood": 150, "Iron": 10, "Gold": 10, "Mud": 10}},
        2: {"coins": 5000, "items": {"Wood": 450, "Iron": 45, "Gold": 35, "Crimstone": 12, "Mud": 25}},
        3: {"coins": 37500, "items": {"Wood": 2250, "Iron": 135, "Gold": 90, "Crimstone": 50, "Oil": 100, "Mud": 100}},
    },
}
