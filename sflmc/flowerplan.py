"""Greedy flower-bed planner: what to plant in each bed, and when, so you hold
the flowers the board and Raven are likely to ask for.

Rules from the game: a seed can only be planted in a season that sells it
(plantFlower.ts); the flower's colour comes from the seed plus the
cross-breed item; one harvest gives one flower; stored flowers keep.
Bed speed is read from your own beds (boostedTime / base time).
"""
import datetime as dt

SEASONS = ["spring", "summer", "autumn", "winter"]
H = 3600 * 1000
# All-season families in order of how useful a spare is: Raven has asked for
# Cosmos; the board takes one or two all-season flowers a week.
FAMILY_PRIORITY = [("Cosmos", 90), ("Pansy", 80), ("Daffodil", 70), ("Balloon Flower", 65),
                   ("Carnation", 55), ("Lotus", 50)]
EPIC = ("Prism Petal", "Celestial Frostbloom", "Primula Enigma")


def season_at(ms, season_now, season_start_ms):
    weeks = int((ms - season_start_ms) // (7 * 24 * H))
    return SEASONS[(SEASONS.index(season_now) + weeks) % 4]


def week_end(ms, season_start_ms):
    weeks = int((ms - season_start_ms) // (7 * 24 * H))
    return season_start_ms + (weeks + 1) * 7 * 24 * H


def plan(farm, flowers, now_ms, horizon_days=11, prices=None):
    seeds, fl = flowers["seeds"], flowers["flowers"]
    inv = dict(farm.get("inventory", {}))
    stock = {n: int(inv.get(n, 0)) for n in fl}
    seed_stock = {s: int(inv.get(s, 0)) for s in seeds}
    season_now, s_start = farm["season"], farm["season_started"]
    prices = prices or {}

    # bed speed from what is planted now
    factors = []
    for b in farm.get("flower_beds", []):
        if b["name"] in fl:
            base = seeds[fl[b["name"]]["seed"]]["days"] * 24 * H
            factors.append(1 - (b.get("boosted_ms") or 0) / base)
    speed = min(factors) if factors else 1.0

    beds = []
    for i, b in enumerate(farm.get("flower_beds", [])):
        if b["name"] in fl and b.get("planted_at"):
            ready = b["planted_at"] + seeds[fl[b["name"]]["seed"]]["days"] * 24 * H * speed
            beds.append({"bed": i + 1, "free": max(now_ms, ready), "growing": b["name"], "ready": ready})
        else:
            beds.append({"bed": i + 1, "free": now_ms, "growing": None, "ready": None})
    pending = [(b["ready"], b["growing"]) for b in beds if b["growing"]]

    def family(name):
        return next((f for f, _ in FAMILY_PRIORITY if name.endswith(f)), None)

    def season_only(name):
        return len(seeds[fl[name]["seed"]]["seasons"]) == 1

    def score(name, t):
        s = stock[name] + sum(1 for r, n in pending if n == name)
        if season_only(name):
            if s == 0:
                return 100
            return 45 if s == 1 else 0
        fam = family(name)
        base = dict(FAMILY_PRIORITY).get(fam, 0)
        return base if s == 0 else (base - 60 if s == 1 else 0)

    def option(name):
        """Cheapest available cross-breed: a crop you hold (or can buy), or a spare flower (stock >= 2)."""
        best = None
        for parent, qty in fl[name].get("parents", []):
            if parent in fl:
                if stock.get(parent, 0) >= 2:
                    cand = (0.5, parent, qty, 0)
                else:
                    continue
            else:
                have = inv.get(parent, 0)
                buy = max(0, qty - have)
                cost = buy * (prices.get(parent) or 99)
                cand = (cost, parent, qty, buy)
            if best is None or cand[0] < best[0]:
                best = cand
        return best

    schedule, horizon = [], now_ms + horizon_days * 24 * H
    while True:
        bed = min(beds, key=lambda b: b["free"])
        t = bed["free"]
        if t >= horizon:
            break
        # harvest anything ready by now
        for r, n in [p for p in pending if p[0] <= t]:
            stock[n] += 1
            pending.remove((r, n))
        season = season_at(t, season_now, s_start)
        best = None
        for name in fl:
            if name in EPIC:
                continue
            sd = fl[name]["seed"]
            if season not in seeds[sd]["seasons"] or seed_stock.get(sd, 0) <= 0:
                continue
            sc = score(name, t)
            if sc <= 0:
                continue
            grow = seeds[sd]["days"] * 24 * H * speed
            if season_only(name) and stock[name] == 0 and t + grow > week_end(t, s_start):
                sc -= 30  # not ready inside its own week: still stock for next time
            opt = option(name)
            if not opt:
                continue
            key = (sc, -grow, -opt[0])
            if best is None or key > best[0]:
                best = (key, name, sd, grow, opt)
        if best is None:
            # nothing worth planting now: wait for next harvest or next season
            nxt = min([r for r, _ in pending if r > t] + [week_end(t, s_start)])
            bed["free"] = max(nxt, t + H)
            continue
        _, name, sd, grow, (cost, parent, qty, buy) = best
        seed_stock[sd] -= 1
        if parent in fl:
            stock[parent] -= qty
        else:
            inv[parent] = max(0, inv.get(parent, 0) - qty)
        ready = t + grow
        pending.append((ready, name))
        schedule.append({"bed": bed["bed"], "plant": t, "ready": ready, "flower": name, "seed": sd,
                         "cross": f"{qty} {parent}", "buy": buy, "buy_item": parent if buy else None,
                         "season": season, "why": why(name, season_only(name), stock, pending)})
        bed["free"] = ready

    end_stock = dict(stock)
    for r, n in pending:
        end_stock[n] += 1
    return {"speed": speed, "beds": beds, "schedule": schedule,
            "stock_now": {n: int(inv_v) for n, inv_v in ((n, farm["inventory"].get(n, 0)) for n in fl) if inv_v},
            "stock_end": {n: v for n, v in end_stock.items() if v},
            "seeds": {s: int(farm["inventory"].get(s, 0)) for s in seeds}}


def why(name, so, stock, pending):
    have = stock[name] + sum(1 for _, n in pending if n == name) - 1
    if so:
        return "season-only, none in stock" if have <= 0 else "season-only spare"
    return "none in stock" if have <= 0 else "second copy"


def fmt(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%a %d %b %H:%M UTC")
