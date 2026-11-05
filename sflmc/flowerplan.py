"""Flower-bed planner: what to plant in each bed, and when, to be ready for a
target week (the board and Raven), given when you are actually awake.

Game rules used: a seed can only be planted in a season that sells it
(plantFlower.ts); the colour comes from the seed plus the cross-breed item;
one harvest gives one flower; stored flowers keep. Bed speed is read from
your own beds (boostedTime / base time).

Planner rules:
  * You plant and harvest only while awake (local hours, configurable).
  * A cross-breed may use a crop you hold (or can buy), a flower you hold two
    of, or a flower grown earlier in the plan for that purpose. When a wanted
    flower needs a parent flower you lack, the parent is planted first and
    both grow times count.
  * Priorities for the target week: season-only flowers of that week's
    season (the board leans on them), then missing all-season colours, faster
    ones first (Cosmos and Pansy lead: Raven has asked for Cosmos), then
    spares. Season-only flowers of other weeks are only filler.
"""
import datetime as dt

SEASONS = ["spring", "summer", "autumn", "winter"]
H = 3600 * 1000
DAY = 24 * H
FAMILY_PRIORITY = {"Cosmos": 90, "Pansy": 80, "Daffodil": 70, "Balloon Flower": 65, "Carnation": 55, "Lotus": 50}
EPIC = ("Prism Petal", "Celestial Frostbloom", "Primula Enigma")


def plan(farm, flowers, now_ms, prices=None, target_start_ms=None, target_days=7,
         tz_offset_h=-3, awake=(6, 23), board_now=()):
    seeds, fl = flowers["seeds"], flowers["flowers"]
    inv = dict(farm.get("inventory", {}))
    stock = {n: int(inv.get(n, 0)) for n in fl}
    seed_stock = {s: int(inv.get(s, 0)) for s in seeds}
    season_now, s_start = farm["season"], farm["season_started"]
    prices = prices or {}
    target_start = target_start_ms or (s_start + 7 * DAY)
    horizon = target_start + target_days * DAY

    def season_at(ms):
        return SEASONS[(SEASONS.index(season_now) + int((ms - s_start) // (7 * DAY))) % 4]

    def week_end(ms):
        return s_start + (int((ms - s_start) // (7 * DAY)) + 1) * 7 * DAY

    def next_awake(ms):
        local = dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc) + dt.timedelta(hours=tz_offset_h)
        if awake[0] <= local.hour < awake[1]:
            return ms
        wake = local.replace(hour=awake[0], minute=0, second=0, microsecond=0)
        if local.hour >= awake[1]:
            wake += dt.timedelta(days=1)
        return int((wake - dt.timedelta(hours=tz_offset_h)).timestamp() * 1000)

    factors = [1 - (b.get("boosted_ms") or 0) / (seeds[fl[b["name"]]["seed"]]["days"] * DAY)
               for b in farm.get("flower_beds", []) if b.get("name") in fl]
    speed = min(factors) if factors else 1.0

    def grow(name):
        return seeds[fl[name]["seed"]]["days"] * DAY * speed

    beds, pending = [], []
    for i, b in enumerate(farm.get("flower_beds", [])):
        if b.get("name") in fl and b.get("planted_at"):
            ready = b["planted_at"] + grow(b["name"])
            beds.append({"bed": i + 1, "free": max(now_ms, ready), "growing": b["name"], "ready": ready})
            pending.append((ready, b["name"]))
        else:
            beds.append({"bed": i + 1, "free": now_ms, "growing": None, "ready": None})

    reserved = {}            # parent flower -> target it was grown for
    family = lambda n: next((f for f in FAMILY_PRIORITY if n.endswith(f)), None)  # noqa: E731
    season_only = lambda n: len(seeds[fl[n]["seed"]]["seasons"]) == 1  # noqa: E731

    def have(n):
        return stock[n] + sum(1 for _, p in pending if p == n)

    def value(name, t):
        """How much having one more of this flower is worth for the target week."""
        h = have(name) - sum(1 for p, x in reserved.items() if p == name)
        if season_only(name):
            if season_at(t) != season_at(target_start) or t < target_start:
                return 12 if h == 0 else 0           # stock for a later week: filler
            return 85 if h == 0 else 40 if h == 1 else 0
        base = FAMILY_PRIORITY.get(family(name), 0)
        days = seeds[fl[name]["seed"]]["days"]
        if h == 0:
            return base - 6 * days
        return base - 55 - 6 * days if h == 1 else 0

    def direct_option(name):
        best = None
        for parent, qty in fl[name].get("parents", []):
            if parent in fl:
                spare = stock.get(parent, 0) - (0 if reserved.get(parent) == name else 1)
                if spare < qty:
                    continue
                cand = (0.5 if reserved.get(parent) != name else 0.0, parent, qty, 0)
            else:
                buy = max(0, qty - inv.get(parent, 0))
                cand = (buy * (prices.get(parent) or 99), parent, qty, buy)
            if best is None or cand[0] < best[0]:
                best = cand
        return best

    def plantable(name, t):
        sd = fl[name]["seed"]
        return name not in EPIC and season_at(t) in seeds[sd]["seasons"] and seed_stock.get(sd, 0) > 0

    schedule = []
    for _ in range(400):
        bed = min(beds, key=lambda b: b["free"])
        t = next_awake(bed["free"])
        if t >= horizon:
            break
        for r, n in [p for p in pending if p[0] <= t]:
            stock[n] += 1
            pending.remove((r, n))
        best = None
        for name in fl:
            if not plantable(name, t):
                continue
            v = value(name, t)
            if v <= 0:
                continue
            opt = direct_option(name)
            if opt:
                key = (v, -grow(name))
                if best is None or key > best[0]:
                    best = (key, name, opt, None)
                continue
            # needs a parent flower first: grow it now, the target after
            for parent, qty in fl[name].get("parents", []):
                if parent not in fl or qty != 1 or reserved.get(parent) or not plantable(parent, t):
                    continue
                popt = direct_option(parent)
                done = t + grow(parent) + grow(name)
                if not popt or done > horizon:
                    continue
                key = (v - 12, -(grow(parent) + grow(name)))
                if best is None or key > best[0]:
                    best = (key, parent, popt, name)
        if best is None:
            nxt = min([r for r, _ in pending if r > t] + [week_end(t), horizon])
            bed["free"] = max(nxt, t + H)
            continue
        _, name, (cost, parent, qty, buy), target = best
        seed_stock[fl[name]["seed"]] -= 1
        if parent in fl:
            stock[parent] -= qty
            if reserved.get(parent) == name:
                del reserved[parent]
        else:
            inv[parent] = max(0, inv.get(parent, 0) - qty)
        if target:
            reserved[name] = target
        ready = t + grow(name)
        pending.append((ready, name))
        schedule.append({"bed": bed["bed"], "plant": t, "ready": ready, "harvest": next_awake(int(ready)),
                         "flower": name, "seed": fl[name]["seed"], "cross": f"{qty} {parent}", "buy": buy,
                         "season": season_at(t),
                         "why": f"parent for {target}" if target else reason(name, season_only(name), have(name) - 1,
                                                                               season_at(t) == season_at(target_start) and t >= target_start)})
        bed["free"] = ready

    end_stock = dict(stock)
    for r, n in pending:
        end_stock[n] += 1
    return {"speed": speed, "beds": beds, "schedule": schedule, "target_start": target_start, "horizon": horizon,
            "tz_offset_h": tz_offset_h, "awake": list(awake),
            "stock_now": {n: int(farm["inventory"].get(n, 0)) for n in fl if farm["inventory"].get(n)},
            "stock_end": {n: v for n, v in end_stock.items() if v},
            "seeds": {s: int(farm["inventory"].get(s, 0)) for s in seeds}}


def reason(name, so, had, in_target_week):
    if so:
        if not in_target_week:
            return "season-only, stock for its next week"
        return "this week's season-only, none in stock" if had <= 0 else "this week's season-only, spare"
    return "none in stock" if had <= 0 else "second copy"
