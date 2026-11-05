"""Monte Carlo engine for one animal.

Mechanics (from the game source):
  * An awake animal is fed in one click until it is "ready": the batch is
    ceil(xpUntilReady / favouriteFoodXp) feeds (feedAnimal.ts getFeedBatchSize).
  * Ready -> claim produce of the level reached -> sleeps (24h * boosts).
  * While asleep it can be petted twice: first slot opens at 1/3 of the sleep,
    the second 1/3 after the first pet (loveAnimal.ts). Petting only needs the
    animal asleep: a "ready" animal can still be petted and the XP carries over.
    The requested tool is random, weighted by level.
  * XP never resets; at level 15 every 320/960/640/960 XP (chicken/cow/sheep/pig)
    is one more produce cycle.

The player is "perfect": pets the moment a slot opens and feeds on waking.
"""
import math
import random
from dataclasses import dataclass

from . import farm as F
from . import game as G


@dataclass
class Economy:
    prices: dict            # FLOWER per unit (P2P)
    sell_fee: float = 0.125  # marketplace cut when selling produce
    coins_per_flower: float = 0.0  # 0 = coins count as nothing in FLOWER totals

    def coin_flower(self, coins):
        """Coins expressed in FLOWER; 0 when coins are not counted."""
        return coins / self.coins_per_flower if self.coins_per_flower else 0.0

    def unit(self, item):
        return float(self.prices.get(item) or 0.0)

    def food_cost(self, food):
        if food in G.FEED_RECIPES:
            return sum(self.unit(i) * q for i, q in G.FEED_RECIPES[food].items())
        return self.cheapest_slop_ingredient(food)[1]

    def cheapest_slop_ingredient(self, food):
        return min(((i, self.unit(i) * q) for i, q in G.SLOP_OPTIONS[food].items() if self.unit(i) > 0),
                   key=lambda x: x[1])


class AnimalModel:
    """Everything that depends only on (farm, animal, economy)."""

    def __init__(self, farm, animal, eco):
        self.animal = animal
        self.sleep = F.sleep_hours(farm, animal)
        self.food_qty = G.REQUIRED_FOOD_QTY[animal] * F.food_multiplier(farm, animal)
        self.xp_mult = F.feed_xp_multiplier(farm)
        self.love_xp = {i: F.love_xp(farm, animal, i) for i in G.LOVE_ITEMS}
        self.food_cost = {f: eco.food_cost(f) for f in set(G.FAVOURITE_FOOD[animal])}
        self.produce, self.produce_units = [], []
        for lv in range(G.MAX_LEVEL + 1):
            units = {r: F.yield_amount(farm, animal, r, b) for r, b in G.DROPS[animal][lv].items()}
            self.produce_units.append(units)
            self.produce.append(sum(eco.unit(r) * a for r, a in units.items()) * (1 - eco.sell_fee))
        self.bristles = [F.yield_amount(farm, animal, "Pig Bristles", b) if b else 0.0
                         for b in G.PIG_BRISTLES_PER_LEVEL] if animal == "Pig" else [0.0] * 16
        self.bristle_value = [b * eco.unit("Pig Bristles") * (1 - eco.sell_fee) for b in self.bristles]


def draw_item(rng, level):
    w = G.LOVE_WEIGHTS[level]
    x = rng.random() * (sum(w) or 1)
    for item, wt in zip(G.LOVE_ITEMS, w):
        if x < wt:
            return item
        x -= wt
    return "Petting Hand"


class Pet:
    """One animal's state, advanced event by event by a perfect player."""

    def __init__(self, model, rng, xp=0.0, t=0.0):
        self.m, self.rng = model, rng
        self.xp = xp
        self._lv_xp, self._lv = None, 0
        self.asleep_at, self.wake_at, self.loved_at = -1e9, t, -1e9
        self.loves, self.ready = 0, False
        self.item = draw_item(rng, G.level_for_xp(model.animal, xp))
        self.feed_acc, self.loves_acc = 0.0, 0

    @property
    def level(self):
        if self.xp != self._lv_xp:          # cached: XP changes far less often than level is read
            self._lv_xp, self._lv = self.xp, G.level_for_xp(self.m.animal, self.xp)
        return self._lv

    def bounty_level(self):
        lv = self.level
        return lv - 1 if self.ready and lv < G.MAX_LEVEL else lv

    def next_time(self):
        third = self.m.sleep / 3
        if self.loves < G.MAX_LOVES_PER_SLEEP:
            nxt = max(self.asleep_at + third, self.loved_at + third)
            if nxt < self.wake_at:
                return nxt
        return self.wake_at

    def awake(self, t):
        return t >= self.wake_at - 1e-9

    def pet(self, t):
        gained = self.m.love_xp[self.item]
        before = self.xp
        self.xp += gained
        self.loves += 1
        self.loves_acc += 1
        self.loved_at = t
        self.item = draw_item(self.rng, self.level)
        if G.completed_cycle(self.m.animal, before, gained):
            self.ready = True

    def feed_and_claim(self, t):
        """Feed to ready if needed, claim produce, go to sleep. Returns claim event."""
        a, m = self.m.animal, self.m
        if not self.ready:
            lv = self.level
            fx = G.FAVOURITE_XP[lv] * m.xp_mult
            feeds = max(1, math.ceil(G.xp_until_ready(a, self.xp) / fx - 1e-9))
            self.xp += feeds * fx
            self.feed_acc += feeds * m.food_qty * m.food_cost[G.FAVOURITE_FOOD[a][lv]]
        lv = self.level
        ev = (t, lv, m.produce[lv], self.feed_acc, self.loves_acc)
        self.feed_acc, self.loves_acc, self.ready = 0.0, 0, False
        self.asleep_at, self.wake_at, self.loves = t, t + m.sleep, 0
        return ev

    def act(self, t):
        """Do whatever is due at time t. Returns a claim event or None."""
        if not self.awake(t):
            self.pet(t)
            return None
        return self.feed_and_claim(t)


def simulate(model, days, rng):
    """Claim events (t_hours, level, produce_flower, feed_flower, pets) for one animal from level 0."""
    pet = Pet(model, rng)
    events, t, horizon = [], 0.0, days * 24.0
    while t <= horizon:
        ev = pet.act(t)
        if ev:
            events.append(ev)
        t = pet.next_time()
    return events


def run_scenario(model, days=30, runs=1000, seed=7):
    rng = random.Random(seed)
    return [simulate(model, days, rng) for _ in range(runs)]
