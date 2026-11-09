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
  * Priorities: (1) must-haves you set, e.g. a chore that needs a harvest
    by a deadline; (2) parent prep: hold one of every parent flower needed
    by flowers that have no crop recipe, so any flower can be finished
    inside the week it is asked for (season-only ones first, since their
    parents can only be grown in their own season); (3) colours you hold
    none of. Season-only flowers of other weeks are only filler.
"""
import datetime as dt
import re

SEASONS = ["spring", "summer", "autumn", "winter"]
H = 3600 * 1000
DAY = 24 * H
FAMILY_PRIORITY = {"Cosmos": 90, "Pansy": 80, "Daffodil": 70, "Balloon Flower": 65, "Carnation": 55, "Lotus": 50}
EPIC = ("Prism Petal", "Celestial Frostbloom", "Primula Enigma")


def plan(farm, flowers, now_ms, prices=None, target_start_ms=None, target_days=7,
         tz_offset_h=-3, awake=(6, 23), board_now=(), must_have=()):
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

    flower_only = {x: [p for p, _ in f.get("parents", []) if p in fl and p not in EPIC]
                   for x, f in fl.items() if x not in EPIC and not any(p not in fl for p, _ in f.get("parents", []))}
    musts = [dict(m, done=0) for m in must_have]
    protect = {}
    for m in must_have:
        if m.get("kind") == "deliver":
            protect[m["flower"]] = protect.get(m["flower"], 0) + m.get("owed", m["count"])

    def blocked(x):
        """x has only flower parents and you hold none of them."""
        return x in flower_only and all(have(p) == 0 for p in flower_only[x])

    def value(name, t):
        """How much one more of this flower is worth now."""
        v = 0
        for m in musts:
            done_at = next_awake(int(t + grow(name)))
            if m["flower"] == name and m["done"] < m["count"] and done_at <= m["by"]:
                # deliveries (tickets) before chores; within each, least slack first so long grows still fit
                slack = (m["by"] - done_at) / DAY
                rate = 40 * m.get("tickets", 0) / max(1, m["count"] * grow(name) / DAY)   # tickets per bed-day
                v = max(v, (160 if m.get("kind") == "deliver" else 150 + rate) + max(0.0, 7 - slack))
        h = have(name) - sum(1 for p, x in reserved.items() if p == name)
        if h == 0:
            unlocks = [x for x in flower_only if name in flower_only[x] and blocked(x)]
            if unlocks:
                v = max(v, max(75 if season_only(x) else 55 for x in unlocks) + 3 * (len(unlocks) - 1)
                        - 3 * seeds[fl[name]["seed"]]["days"])
        if season_only(name):
            if season_at(t) == season_at(target_start) and t >= target_start:
                v = max(v, 30 if h == 0 else 10 if h == 1 else 0)
            else:
                v = max(v, 8 if h == 0 else 0)
        elif h == 0:
            v = max(v, FAMILY_PRIORITY.get(family(name), 0) // 3 - 3 * seeds[fl[name]["seed"]]["days"])
        return v

    def is_must(name):
        return any(m["flower"] == name and m["done"] < m["count"] for m in musts)

    def direct_option(name):
        best = None
        for parent, qty in fl[name].get("parents", []):
            if parent in fl:
                keep = 0 if reserved.get(parent) == name or is_must(name) else 1
                keep += protect.get(parent, 0)       # never cross-breed away a flower you owe
                spare = stock.get(parent, 0) - keep
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

    def why_now(name, t):
        for m in musts:
            if m["flower"] == name and m["done"] < m["count"]:
                return m.get("note") or "must-have"
        if have(name) == 0:
            unlocks = [x for x in flower_only if name in flower_only[x] and blocked(x)]
            if unlocks:
                return "parent prep: lets you grow " + ", ".join(unlocks[:3]) + ("…" if len(unlocks) > 3 else "")
        if season_only(name):
            return "this week's season-only" if season_at(t) == season_at(target_start) and t >= target_start else "season-only stock"
        return "colour you hold none of" if have(name) == 0 else "spare"

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
            # needs a parent flower first: grow it now, the target after.
            # If a parent is already growing, wait for it instead.
            if any(n == p for _, n in pending for p, _ in fl[name].get("parents", [])):
                continue
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
        why = f"parent for {target}" if target else why_now(name, t)
        seed_stock[fl[name]["seed"]] -= 1
        if parent in fl:
            stock[parent] -= qty
            if reserved.get(parent) == name:
                del reserved[parent]
        else:
            inv[parent] = max(0, inv.get(parent, 0) - qty)
        if target:
            reserved[name] = target
        for m in musts:
            if m["flower"] == name and m["done"] < m["count"] and next_awake(int(t + grow(name))) <= m["by"]:
                m["done"] += 1
                break
        ready = t + grow(name)
        pending.append((ready, name))
        schedule.append({"bed": bed["bed"], "plant": t, "ready": ready, "harvest": next_awake(int(ready)),
                         "flower": name, "seed": fl[name]["seed"], "cross": f"{qty} {parent}", "buy": buy,
                         "season": season_at(t),
                         "why": why})
        bed["free"] = ready

    end_stock = dict(stock)
    for r, n in pending:
        end_stock[n] += 1
    readiness = []
    for x in sorted(flower_only):
        hold = [p for p in flower_only[x] if end_stock.get(p, 0) > 0]
        readiness.append({"flower": x, "season_only": season_only(x), "parents": flower_only[x], "held_after_plan": hold,
                          "held_now": [p for p in flower_only[x] if farm["inventory"].get(p)]})
    end_stock = dict(stock)
    for r, n in pending:
        end_stock[n] += 1
    return {"speed": speed, "beds": beds, "schedule": schedule, "target_start": target_start, "horizon": horizon,
            "tz_offset_h": tz_offset_h, "awake": list(awake), "readiness": readiness,
            "must_have": [{k: v for k, v in m.items()} for m in musts],
            "stock_now": {n: int(farm["inventory"].get(n, 0)) for n in fl if farm["inventory"].get(n)},
            "stock_end": {n: v for n, v in end_stock.items() if v},
            "seeds": {s: int(farm["inventory"].get(s, 0)) for s in seeds}}




def needs(farm, flowers, board, now_ms, ticket="Duende Cap"):
    """Flowers you owe right now, as planner must-haves due at the end of this week:
    weekly-board flowers not delivered yet and open delivery orders (minus the ones
    you hold), plus chores like "Grow Blue Pansy 6 times" (only fresh harvests count)."""
    fl = flowers["flowers"]
    s_start = farm["season_started"]
    by = s_start + (int((now_ms - s_start) // (7 * DAY)) + 1) * 7 * DAY - H
    inv = farm.get("inventory", {})
    owe, why = {}, {}
    for b in board.get("board", []):
        if b["category"] == "Flowers" and not b["done"] and b["label"] in fl:
            owe[b["label"]] = owe.get(b["label"], 0) + 1
            why.setdefault(b["label"], []).append("weekly board")
    for o in farm.get("orders", []):
        for item, q in o["items"].items():
            if item in fl:
                owe[item] = owe.get(item, 0) + q
                why.setdefault(item, []).append(f"{o['from'].title()} order")
    act = farm.get("activity", {})
    growing = {}
    for b in farm.get("flower_beds", []):
        if b.get("name") in fl and b.get("planted_at"):
            growing[b["name"]] = growing.get(b["name"], 0) + 1
    chores = []
    for c in farm.get("chores", []):
        m = re.match(r"Grow (.+?) (\d+) times?", c.get("name") or "")
        if m and m.group(1) in fl:
            done = act.get(f"{m.group(1)} Harvested", 0) - (c.get("initial") or 0)
            chores.append((c, m.group(1), int(m.group(2)), int(done)))
    out = []
    for c, f, n, done in chores:
        left = max(0, n - done - growing.get(f, 0))
        out.append({"flower": f, "count": left, "owed": n, "held": done, "growing": growing.get(f, 0), "by": by,
                    "kind": "grow", "note": f"{c['npc'].title()} chore: grow {f} {n}x", "reward": c.get("reward"),
                    "tickets": ((c.get("reward") or {}).get("items") or {}).get(ticket, 0)})
    for f, q in owe.items():
        # what you hold and what is already growing count; chore harvests do not, since a chore may not fit the week
        short = q - int(inv.get(f, 0)) - growing.get(f, 0)
        out.insert(0, {"flower": f, "count": max(0, short), "owed": q, "held": int(inv.get(f, 0)),
                       "growing": growing.get(f, 0), "by": by, "kind": "deliver", "note": " + ".join(why[f])})
    return out


def plan_week(farm, flowers, now_ms, prices=None, must_have=(), **kw):
    """plan(), but a chore only pays when finished. Try every set of chores (most tickets
    first) and keep the first one whose chores all fit the week; chore harvests can feed
    each other (Purple Cosmos grown for one chore are parents for Blue Pansy)."""
    from itertools import combinations
    chores = [m for m in must_have if m.get("kind") == "grow" and m["count"] > 0]
    rest = [m for m in must_have if m not in chores]
    sets = [c for k in range(len(chores), -1, -1) for c in combinations(chores, k)]
    sets.sort(key=lambda c: -sum(m.get("tickets", 0) for m in c))
    for chosen in sets:
        r = plan(farm, flowers, now_ms, prices, must_have=rest + list(chosen), **kw)
        if all(m["done"] >= m["count"] for m in r["must_have"] if m.get("kind") == "grow"):
            r["dropped"] = [m for m in chores if m not in chosen]
            return r
    return r
