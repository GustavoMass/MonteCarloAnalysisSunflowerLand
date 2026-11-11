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
  * Strict priority tiers (needs() builds them, config flower_priorities):
    1 weekly board + delivery orders, 2 a parent for every flower that takes
    more than 5 days, 3 two of Guria's flowers and of every seasonal one,
    4 Bloom Doll, 5 "Grow ..." chores, 6 two of every flower, 7 Floral Bed.
    A tier never uses a flower that an equal or higher tier keeps as a parent.
    Epic flowers have fixed recipes like the rest (sfl.world/info/flowers):
    Prism Petal = Sunpetal + Blue Lotus, Celestial Frostbloom = Bloom + White
    Pansy, Primula Enigma = Lily + Purple Balloon Flower.
"""
import datetime as dt
import re

SEASONS = ["spring", "summer", "autumn", "winter"]
H = 3600 * 1000
DAY = 24 * H
FAMILY_PRIORITY = {"Cosmos": 90, "Pansy": 80, "Daffodil": 70, "Balloon Flower": 65, "Carnation": 55, "Lotus": 50}
TIER_BASE = {1: 200, 2: 180, 3: 160, 4: 140, 5: 120, 6: 100, 7: 80}
TIER_NAME = {1: "board + orders", 2: "parents for 5+ day flowers", 3: "Guria + seasonal stock",
             4: "Bloom Doll", 5: "weekly chores", 6: "2 of every flower", 7: "Floral Bed"}


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

    flower_only = {x: [p for p, _ in f.get("parents", []) if p in fl]
                   for x, f in fl.items() if not any(p not in fl for p, _ in f.get("parents", []))}
    musts = sorted((dict(m, done=0) for m in must_have), key=lambda m: m.get("tier", 1))
    # flowers a tier keeps (owed, parents, stock): a tier may not cross-breed them away below that count
    protect = [(m.get("tier", 1), m["flower"], m.get("keep", m.get("owed", m["count"])))
               for m in must_have if m.get("kind") != "grow"]

    def tier_of(name):
        return min((m.get("tier", 1) for m in musts if m["flower"] == name and m["done"] < m["count"]), default=99)

    def blocked(x):
        """x has only flower parents and you hold none of them."""
        return x in flower_only and all(have(p) == 0 for p in flower_only[x])

    def value(name, t):
        """Worth of one more of this flower now: its best unmet tier. Inside tier 1, least slack
        first so long grows still make the deadline; chores also by caps per bed-day."""
        v = 0
        for m in musts:
            done_at = next_awake(int(t + grow(name)))
            if m["flower"] == name and m["done"] < m["count"] and done_at <= m["by"]:
                tier = m.get("tier", 1)
                extra = max(0.0, 7 - (m["by"] - done_at) / DAY) if tier in (1, 5) else 0.0
                if tier == 5:
                    extra += min(5.0, 5 * m.get("tickets", 0) / max(1, m["count"] * grow(name) / DAY))
                v = max(v, TIER_BASE.get(tier, 0) + extra)
        return v

    def is_must(name):
        return any(m["flower"] == name and m["done"] < m["count"] for m in musts)

    def direct_option(name, tier=None):
        tier = tier_of(name) if tier is None else tier
        best = None
        for parent, qty in fl[name].get("parents", []):
            if parent in fl:
                if reserved.get(parent) == name:       # grown for this very flower
                    keep = 0
                else:
                    keep = sum(q for tr, f, q in protect if f == parent and tr <= tier)
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
        return season_at(t) in seeds[sd]["seasons"]

    def why_now(name, t):
        for m in musts:
            if m["flower"] == name and m["done"] < m["count"]:
                return f"{m.get('tier', 1)} · {m.get('note') or TIER_NAME.get(m.get('tier', 1))}"
        return "spare"

    schedule = []
    for _ in range(1500):
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
                popt = direct_option(parent, tier_of(name))
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
        why = f"{tier_of(target)} · parent for {target}" if target else why_now(name, t)
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
                         "flower": name, "cross": f"{qty} {parent}", "buy": buy,
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
            "stock_end": {n: v for n, v in end_stock.items() if v}}




def needs(farm, flowers, board, now_ms, ticket="Duende Cap", prio=None):
    """Your flower goals as planner must-haves, in strict priority tiers (see module doc).

    Held and growing flowers are handed out tier by tier: what tier 1 owes uses them first,
    the rest counts toward the stock tiers below it. Chores count only fresh harvests."""
    prio = prio or {}
    fl = flowers["flowers"]
    s_start = farm["season_started"]
    by = s_start + (int((now_ms - s_start) // (7 * DAY)) + 1) * 7 * DAY - H
    far = by + 400 * DAY
    inv = farm.get("inventory", {})
    growing = {}
    for b in farm.get("flower_beds", []):
        if b.get("name") in fl and b.get("planted_at"):
            growing[b["name"]] = growing.get(b["name"], 0) + 1
    avail = {f: int(inv.get(f, 0)) + growing.get(f, 0) for f in fl}
    out = []

    def add(tier, f, q, note, kind="stock", deadline=far, **kw):
        if f not in fl or q <= 0:
            return
        cover = min(avail.get(f, 0), q)
        avail[f] = avail.get(f, 0) - cover
        out.append({"flower": f, "count": q - cover, "owed": q, "keep": q, "held": int(inv.get(f, 0)),
                    "growing": growing.get(f, 0), "covered": cover, "by": deadline, "kind": kind, "tier": tier,
                    "note": note, **kw})

    # 1: weekly board (mega bounty) + open delivery orders
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
    for f, q in owe.items():
        add(1, f, q, " + ".join(why[f]), kind="deliver", deadline=by)
    # 2: one parent for every flower that takes more than N days (whole path, from flowers.json)
    over = prio.get("parents_over_days", 5)
    parents = {}
    for x, d in fl.items():
        if d.get("days", 0) <= over:
            continue
        steps = d.get("steps") or []
        par = steps[-2][0] if len(steps) >= 2 else None
        if par in fl:
            parents.setdefault(par, []).append(x)
    for par, xs in sorted(parents.items()):
        add(2, par, 1, "parent for " + ", ".join(xs[:3]) + ("…" if len(xs) > 3 else ""))
    # 3: Guria's flowers and every seasonal one
    for f in prio.get("guria", []):
        add(3, f, prio.get("guria_each", 2), "Guria asks for it")
    seeds = flowers.get("seeds", {})
    for f in sorted(fl):
        if len(seeds.get(fl[f].get("seed"), {}).get("seasons", [1, 2])) == 1:
            add(3, f, prio.get("seasonal_each", 2), f"seasonal ({seeds[fl[f]['seed']]['seasons'][0]})")
    # 4: Bloom Doll
    for f, q in prio.get("bloom_doll", {}).items():
        add(4, f, q, "Bloom Doll")
    # 5: chores
    act = farm.get("activity", {})
    for c in farm.get("chores", []):
        m = re.match(r"Grow (.+?) (\d+) times?", c.get("name") or "")
        if m and m.group(1) in fl:
            f, n = m.group(1), int(m.group(2))
            done = int(act.get(f"{f} Harvested", 0) - (c.get("initial") or 0))
            left = max(0, n - done - growing.get(f, 0))
            out.append({"flower": f, "count": left, "owed": n, "held": done, "growing": growing.get(f, 0), "by": by,
                        "kind": "grow", "tier": 5, "note": f"{c['npc'].title()} chore: grow {f} {n}x",
                        "reward": c.get("reward"),
                        "tickets": ((c.get("reward") or {}).get("items") or {}).get(ticket, 0)})
    # 6: two of every flower
    for f in sorted(fl):
        add(6, f, prio.get("every_each", 2), "2 of every flower")
    # 7: Floral Bed (flowers only)
    for f, q in prio.get("floral_bed", {}).items():
        add(7, f, q, "Floral Bed")
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
