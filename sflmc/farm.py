"""Farm profile -> per-animal modifiers, mirroring lib/animals.ts boost code."""
from dataclasses import dataclass, field

from . import game as G


@dataclass
class Farm:
    skills: dict = field(default_factory=dict)       # {skill name: rank}
    collectibles: set = field(default_factory=set)   # placed NFTs / items
    wearables: set = field(default_factory=set)      # equipped wearables

    def rank(self, skill):
        return int(self.skills.get(skill, 0))

    def with_skills(self, add=None, remove=()):
        skills = {k: v for k, v in self.skills.items() if k not in remove}
        skills.update(add or {})
        return Farm(skills, set(self.collectibles), set(self.wearables))


def _r(farm, skill, key):
    rank = farm.rank(skill)
    return G.SKILLS[skill][key][rank - 1] if rank else None


def sleep_hours(farm, animal):
    h = G.BASE_SLEEP_HOURS
    c = farm.collectibles
    if animal == "Chicken":
        if "El Pollo Veloz" in c:
            h -= 2
        for name, m in (("Speed Chicken", 0.9), ("Janitor Chicken", 0.95), ("Flamingo Chicken", 0.975)):
            if name in c:
                h *= m
    if animal == "Sheep":
        if "Dream Scarf" in farm.wearables:
            h *= 0.8
        for name, m in (("Farm Dog", 0.75), ("Beetle Sheep", 0.925)):
            if name in c:
                h *= m
    if animal == "Cow":
        for name, m in (("Mammoth", 0.75), ("Ascended Cow", 0.975)):
            if name in c:
                h *= m
    if "Wrangler" in c:
        h *= 0.9
    v = _r(farm, "Restless Animals", "sleep")
    if v:
        h *= v
    return h


def food_multiplier(farm, animal):
    """getBoostedFoodQuantity multiplier on REQUIRED_FOOD_QTY per feed."""
    m = 1.0
    c = farm.collectibles
    if animal == "Chicken" and "Fat Chicken" in c:
        m *= 0.9
    if animal == "Cow" and "Dr Cow" in c:
        m *= 0.95
    if animal == "Sheep" and "Mermaid Sheep" in c:
        m *= 0.95
    if animal == "Chicken" and "Cluckulator" in c:
        m *= 0.75
    if animal in ("Sheep", "Cow") and "Infernal Bullwhip" in farm.wearables:
        m *= 0.5
    v = _r(farm, "Efficient Feeding", "feed")
    if v:
        m *= v
    for skill in G.DIET_SKILLS:
        rank = farm.rank(skill)
        if rank:
            eff = G.SKILLS[skill]
            m *= eff["buff"][rank - 1] if eff["animal"] == animal else eff["debuff"][rank - 1]
    v = _r(farm, "Chonky Feed", "feed")
    if v:
        m *= v
    return m


def feed_xp_multiplier(farm):
    return _r(farm, "Chonky Feed", "xp") or 1.0


def love_xp(farm, animal, item):
    xp = G.LOVE_XP[item]
    if animal == "Cow" and "Baby Cow" in farm.collectibles:
        xp += 10
    if animal == "Sheep" and "Spa Sheep" in farm.collectibles:
        xp += 5
    return xp * (1 + (_r(farm, "Heartwarming Instruments", "love") or 0))


def _fibre(farm, resource):
    b = _r(farm, "Fine Fibers", "fibre") or 0
    for skill, res in G.FIBRE_SKILLS.items():
        rank = farm.rank(skill)
        if rank:
            eff = G.SKILLS[skill]
            b += eff["buff"][rank - 1] if res == resource else -eff["debuff"][rank - 1]
    return b


def yield_amount(farm, animal, resource, base):
    """getResourceDropAmount: multipliers on base first, then flat bonuses."""
    c, w = farm.collectibles, farm.wearables
    amt = float(base)
    if resource == "Truffle":
        amt *= 1 + (_r(farm, "Truffle Yield", "mult") or 0)
    if resource == "Pig Bristles":
        amt *= 1 + (_r(farm, "Bristle Payout", "mult") or 0)
    flat = 0.0
    ah = _r(farm, "Abundant Harvest", "yield") or 0
    if resource == "Egg":
        flat += sum(v for k, v in (("Chicken Coop", 1), ("Rich Chicken", 0.1), ("Undead Rooster", 0.1),
                                   ("Ayam Cemani", 0.2), ("Squid Chicken", 0.1), ("Ascended Chicken", 0.1)) if k in c)
        flat += ah
    elif resource == "Feather":
        flat += (1 if "Chicken Suit" in w else 0) + (0.1 if "Alien Chicken" in c else 0) + _fibre(farm, "Feather")
    elif resource == "Wool":
        flat += (2 if "Black Sheep Onesie" in w else 0) + (0.25 if "White Sheep Onesie" in w else 0)
        flat += (0.1 if "Astronaut Sheep" in c else 0) + (0.05 if "Ascended Sheep" in c else 0) + ah
    elif resource == "Merino Wool":
        flat += (1 if "Merino Jumper" in w else 0) + (0.1 if "Toxic Tuft" in c else 0) + _fibre(farm, "Merino Wool")
    elif resource == "Milk":
        flat += sum(v for k, v in (("Longhorn Cowfish", 0.2), ("Spa Cow", 0.1)) if k in c)
        flat += (0.5 if "Milk Apron" in w else 0) + (2 if "Cowbell Necklace" in w else 0) + ah
    elif resource == "Leather":
        flat += (0.25 if "Moo-ver" in c else 0) + (0.1 if "Mootant" in c else 0) + _fibre(farm, "Leather")
        flat += 1 if "Training Whistle" in w else 0
    if "Bale" in c:
        bale = 0.1 * (_r(farm, "Double Bale", "bale") or 1)
        if resource == "Egg" or ("Bale Economy" in farm.skills and resource in ("Wool", "Milk")):
            flat += bale
    if "Cattlegrim" in w:
        flat += 0.25
    if "Barn Manager" in c:
        flat += 0.1
    return round(max(amt + flat, 0.0), 2)


def bounty_coin_multiplier(farm):
    return 1 + (_r(farm, "Bountiful Bounties", "coins") or 0)
