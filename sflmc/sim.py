"""Monte Carlo engine: one animal's life, driven by a player's login schedule.

Mechanics (from the game source):
  * An awake animal is fed in one click until it is "ready": the batch is
    ceil(xpUntilReady / favouriteFoodXp) feeds (feedAnimal.ts getFeedBatchSize).
  * Ready -> claim produce of the level reached -> sleeps (24h * boosts).
  * While asleep it can be loved twice: first slot opens at 1/3 of the sleep,
    the second 1/3 after the first love (loveAnimal.ts). The requested tool is
    random, weighted by level. Love XP can itself finish the level, in which
    case the animal wakes "ready" and needs no food that cycle.
  * XP never resets; at level 15 every 320/960/640/960 XP (chicken/cow/sheep/pig)
    is one more produce cycle.
"""
import math
import random
from dataclasses import dataclass

from . import farm as F
from . import game as G

# Login schedules (hour of day). "perfect" = player acts the moment anything opens.
SCHEDULES = {
    "1x/day": [20.0],
    "2x/day": [8.0, 20.0],
    "3x/day": [7.0, 15.0, 23.0],
    "4x/day": [7.0, 12.0, 17.0, 22.0],
    "perfect": None,
}


@dataclass
class Economy:
    prices: dict            # FLOWER per unit (P2P)
    sell_fee: float = 0.10  # marketplace cut when selling produce
    coins_per_flower: float = 320.0

    def unit(self, item):
        return float(self.prices.get(item) or 0.0)

    def food_cost(self, food):
        if food in G.FEED_RECIPES:
            return sum(self.unit(i) * q for i, q in G.FEED_RECIPES[food].items())
        opts = [self.unit(i) * q for i, q in G.SLOP_OPTIONS[food].items() if self.unit(i) > 0]
        return min(opts)

    def cheapest_slop_ingredient(self, food):
        return min(((i, self.unit(i) * q) for i, q in G.SLOP_OPTIONS[food].items() if self.unit(i) > 0),
                   key=lambda x: x[1])


class AnimalModel:
    """Pre-computes everything that depends only on (farm, animal, economy)."""

    def __init__(self, farm, animal, eco):
        self.animal = animal
        self.sleep = F.sleep_hours(farm, animal)
        self.food_qty = G.REQUIRED_FOOD_QTY[animal] * F.food_multiplier(farm, animal)
        self.xp_mult = F.feed_xp_multiplier(farm)
        self.love_xp = {i: F.love_xp(farm, animal, i) for i in G.LOVE_ITEMS}
        self.food_cost = {f: eco.food_cost(f) for f in set(G.FAVOURITE_FOOD[animal])}
        self.produce = []        # FLOWER (after fee) of produce at each level
        self.produce_units = []
        for lv in range(G.MAX_LEVEL + 1):
            units = {r: F.yield_amount(farm, animal, r, b) for r, b in G.DROPS[animal][lv].items()}
            self.produce_units.append(units)
            self.produce.append(sum(eco.unit(r) * a for r, a in units.items()) * (1 - eco.sell_fee))
        self.bristles = [F.yield_amount(farm, animal, "Pig Bristles", b) if b else 0.0
                         for b in G.PIG_BRISTLES_PER_LEVEL] if animal == "Pig" else [0.0] * 16
        self.bristle_value = [b * eco.unit("Pig Bristles") * (1 - eco.sell_fee) for b in self.bristles]


def _draw_item(rng, level):
    w = G.LOVE_WEIGHTS[level]
    tot = sum(w)
    if tot == 0:
        return "Petting Hand"
    x = rng.random() * tot
    for item, wt in zip(G.LOVE_ITEMS, w):
        if x < wt:
            return item
        x -= wt
    return G.LOVE_ITEMS[-1]


def simulate(model, schedule, days, rng, jitter_h=0.33):
    """Returns list of claim events: (t_hours, level, produce_flower, feed_flower_cycle, loves_cycle)."""
    a = model.animal
    T = model.sleep
    third = T / 3
    horizon = days * 24.0

    # login times
    if schedule is not None:
        logins = []
        for d in range(days + 2):
            for h in schedule:
                logins.append(d * 24 + h + rng.gauss(0, jitter_h))
        logins.sort()
        t0 = logins[0]
        logins = [t - t0 for t in logins]  # animal bought at first login
        it = iter(logins)
        next_login = lambda _t: next(it, None)  # noqa: E731
    else:
        next_login = None

    xp = 0.0
    asleep_at = -1e9
    wake_at = 0.0
    loved_at = -1e9
    loves = 0
    ready = False
    item = "Petting Hand"
    feed_acc = 0.0
    loves_acc = 0
    events = []

    t = 0.0
    while t is not None and t <= horizon:
        if t < wake_at:  # asleep
            if loves < G.MAX_LOVES_PER_SLEEP and t >= asleep_at + third and t >= loved_at + third:
                gained = model.love_xp[item]
                before = xp
                xp += gained
                loves += 1
                loves_acc += 1
                loved_at = t
                item = _draw_item(rng, G.level_for_xp(a, xp))
                if G.completed_cycle(a, before, gained):
                    ready = True
        else:  # awake
            if not ready:
                lv = G.level_for_xp(a, xp)
                fx = G.FAVOURITE_XP[lv] * model.xp_mult
                need = G.xp_until_ready(a, xp)
                feeds = max(1, math.ceil(need / fx - 1e-9))
                xp += feeds * fx
                feed_acc += feeds * model.food_qty * model.food_cost[G.FAVOURITE_FOOD[a][lv]]
            lv = G.level_for_xp(a, xp)
            events.append((t, lv, model.produce[lv], feed_acc, loves_acc))
            feed_acc = 0.0
            loves_acc = 0
            ready = False
            asleep_at, wake_at, loves = t, t + T, 0

        # next action time
        if schedule is not None:
            t = next_login(t)
        else:
            if loves < G.MAX_LOVES_PER_SLEEP:
                nxt = max(asleep_at + third, loved_at + third)
                t = nxt if nxt < wake_at else wake_at
            else:
                t = wake_at
    return events


def run_scenario(model, schedule_name, days=45, runs=1000, seed=7):
    rng = random.Random(seed)
    sched = SCHEDULES[schedule_name]
    return [simulate(model, sched, days, rng) for _ in range(runs)]
