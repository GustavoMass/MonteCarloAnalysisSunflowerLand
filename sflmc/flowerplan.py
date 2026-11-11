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
         tz_offset_h=-3, awake=(6, 23), board_now=(), must_have=(), extend_days=0, keep_full=False):
    """Plan beds until the shown horizon (end of next week) and, unseen, extend_days more,
    so long goals are planned through; only the shown part is returned as the schedule.

    Goal progress is counted from flowers that exist (held + growing, minus parents
    reserved to be crossed away), handed out tier by tier, never from planting counters."""
    seeds, fl = flowers["seeds"], flowers["flowers"]
    inv = dict(farm.get("inventory", {}))
    stock = {n: int(inv.get(n, 0)) for n in fl}
    seed_stock = {s: int(inv.get(s, 0)) for s in seeds}
    season_now, s_start = farm["season"], farm["season_started"]
    prices = prices or {}
    target_start = target_start_ms or (s_start + 7 * DAY)
    horizon = target_start + target_days * DAY
    full = horizon + extend_days * DAY

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
    for i, m in enumerate(musts):
        m["_i"] = i
    # flowers a tier keeps (owed, parents, stock): a tier may not cross-breed them away below that count
    protect = [(m.get("tier", 1), m["flower"], m.get("keep", m.get("owed", m["count"])))
               for m in must_have if m.get("kind") != "grow"]

    need = {}

    def refresh_need():
        """Remaining need per goal: flowers that exist (held + growing, not reserved as a parent)
        handed out tier by tier; tier 1 only counts what is ready by its deadline.
        Chores ("grow") count fresh harvests planted in the plan."""
        have_now = dict(stock)
        late = {}
        for r, n in pending:
            have_now[n] = have_now.get(n, 0) + 1
        for p, _ in reserved.items():
            have_now[p] = have_now.get(p, 0) - 1
        left = dict(have_now)
        for m in musts:
            if m.get("kind") == "grow":
                need[m["_i"]] = max(0, m["count"] - m["done"])
                continue
            pool = left.get(m["flower"], 0)
            if m.get("tier", 1) == 1:      # only flowers ready by the deadline
                pool = min(pool, stock.get(m["flower"], 0) - sum(1 for p in reserved if p == m["flower"])
                           + sum(1 for r, n in pending if n == m["flower"] and next_awake(int(r)) <= m["by"]))
            owed = m.get("owed", m["count"])
            got = max(0, min(pool, owed))
            left[m["flower"]] = left.get(m["flower"], 0) - got
            need[m["_i"]] = owed - got

    intent = {}              # flower -> [(final flower, tier)]: an in-between step of a parent chain

    def tier_of(name):
        t = min((m.get("tier", 1) for m in musts if m["flower"] == name and need.get(m["_i"], 0) > 0), default=99)
        return min([t] + [tr for _, tr in intent.get(name, [])])

    def blocked(x):
        """x has only flower parents and you hold none of them."""
        return x in flower_only and all(have(p) == 0 for p in flower_only[x])

    def value(name, t):
        """Worth of one more of this flower now: its best unmet tier. Inside tier 1, least slack
        first so long grows still make the deadline; chores also by caps per bed-day."""
        v = 0
        for m in musts:
            done_at = next_awake(int(t + grow(name)))
            if m["flower"] == name and need.get(m["_i"], 0) > 0 and done_at <= m["by"]:
                tier = m.get("tier", 1)
                extra = max(0.0, 7 - (m["by"] - done_at) / DAY) if tier in (1, 5) else 0.0
                if tier == 5:
                    extra += min(5.0, 5 * m.get("tickets", 0) / max(1, m["count"] * grow(name) / DAY))
                v = max(v, TIER_BASE.get(tier, 0) + extra)
        for _, tr in intent.get(name, []):
            v = max(v, TIER_BASE.get(tr, 0) - 6)
        return v


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
            if m["flower"] == name and need.get(m["_i"], 0) > 0:
                return f"{m.get('tier', 1)} · {m.get('note') or TIER_NAME.get(m.get('tier', 1))}"
        return "spare"

    def chain(name, tier, t, depth, seen=()):
        """Ways to start growing name's missing parent: (flower to plant now, its option, the flower
        it is reserved for, grow time until name can be planted, steps)."""
        for parent, qty in fl[name].get("parents", []):
            if parent not in fl or qty != 1 or reserved.get(parent) or parent in seen or not plantable(parent, t):
                continue
            popt = direct_option(parent, tier)
            if popt:
                yield parent, popt, name, grow(parent), 1
            elif depth > 0:
                for q, qopt, tgt, g, d in chain(parent, tier, t, depth - 1, seen + (name,)):
                    yield q, qopt, tgt, g + grow(parent), d + 1

    schedule, shown_end, tier_done = [], None, {}

    def snapshot():
        out = dict(stock)
        for r, n in pending:
            out[n] = out.get(n, 0) + 1
        return out

    for _ in range(20000):
        bed = min(beds, key=lambda b: b["free"])
        t = next_awake(bed["free"])
        if t >= horizon and shown_end is None:
            shown_end = snapshot()
        if t >= full:
            break
        for r, n in [p for p in pending if p[0] <= t]:
            stock[n] += 1
            pending.remove((r, n))
        refresh_need()
        for tr in {m.get("tier", 1) for m in musts}:
            if tr not in tier_done and all(need[m["_i"]] == 0 for m in musts if m.get("tier", 1) == tr):
                tier_done[tr] = max([t] + [r for r, n in pending if any(m["flower"] == n and m.get("tier", 1) == tr
                                                                         for m in musts)])
        best = None
        for name in fl:
            v = value(name, t)
            if v <= 0:
                continue
            now_ok = plantable(name, t)
            opt = direct_option(name) if now_ok else None
            if opt:
                key = (v, -grow(name))
                if best is None or key > best[0]:
                    best = (key, name, opt, None)
                continue
            # needs a parent flower first: grow the nearest ancestor you can grow now (up to 3 steps),
            # each step reserved for the next. If a parent is already growing or planned, wait for it.
            if any(n == p for _, n in pending for p, _ in fl[name].get("parents", [])) or \
                    any(intent.get(p) for p, _ in fl[name].get("parents", [])):
                continue
            for q, qopt, tgt, g, depth in chain(name, tier_of(name), t, 2):
                if t + g + grow(name) > full:
                    continue
                # out of season now: grow its parent in the parent's own season, kept for later
                key = (v - 12 * depth - (0 if now_ok else 10), -(g + grow(name)))
                if best is None or key > best[0]:
                    best = (key, q, qopt, (tgt, name))
        if best is None:
            nxt = min([r for r, _ in pending if r > t] + [week_end(t), full])
            bed["free"] = max(nxt, t + H)
            continue
        _, name, (cost, parent, qty, buy), chained = best
        target = None
        if chained:                        # first step of a parent chain
            target, final = chained
            if target != final:
                intent.setdefault(target, []).append((final, tier_of(final)))
            why = f"{tier_of(final)} · parent for {final}" + (f" (via {target})" if target != final else "")
        elif intent.get(name) and tier_of(name) == min(tr for _, tr in intent[name]):
            final, tr = intent[name].pop(0)  # in-between step: reserved for the next flower in the chain
            if not intent[name]:
                del intent[name]
            target = final
            why = f"{tr} · parent for {final}"
        else:
            why = why_now(name, t)
        if parent in fl:
            stock[parent] -= qty
            if reserved.get(parent) == name:
                del reserved[parent]
        else:
            inv[parent] = max(0, inv.get(parent, 0) - qty)
        if target:
            reserved[name] = target
        if not target:                     # a parent grown to be crossed away counts toward no goal
            for m in musts:
                if (m.get("kind") == "grow" and m["flower"] == name and m["done"] < m["count"]
                        and next_awake(int(t + grow(name))) <= m["by"]):
                    m["done"] += 1
                    break
        ready = t + grow(name)
        goal = int(why.split(" ·")[0]) if why[0].isdigit() else 99
        pending.append((ready, name))
        schedule.append({"bed": bed["bed"], "plant": t, "ready": ready, "harvest": next_awake(int(ready)),
                         "flower": name, "cross": f"{qty} {parent}", "buy": buy,
                         "season": season_at(t), "tier": goal, "parent_for": target,
                         "why": why})
        bed["free"] = ready

    refresh_need()
    if shown_end is None:
        shown_end = snapshot()
    end_stock = shown_end
    readiness = []
    for x in sorted(flower_only):
        hold = [p for p in flower_only[x] if end_stock.get(p, 0) > 0]
        readiness.append({"flower": x, "season_only": season_only(x), "parents": flower_only[x], "held_after_plan": hold,
                          "held_now": [p for p in flower_only[x] if farm["inventory"].get(p)]})
    for m in musts:
        m["left_after_full"] = need.get(m["_i"], 0)
    shown = [x for x in schedule if x["plant"] < horizon]
    tiers = {}
    for m in musts:
        tr = m.get("tier", 1)
        d = tiers.setdefault(tr, {"done_at": tier_done.get(tr), "planted_shown": 0, "left_after_full": 0})
        d["left_after_full"] += m["left_after_full"]
    for x in shown:
        if x["tier"] in tiers and not x["parent_for"]:
            tiers[x["tier"]]["planted_shown"] += 1
    return {"speed": speed, "beds": beds, "schedule": shown, "target_start": target_start, "horizon": horizon,
            "full_until": full, "tiers": tiers, "planted_total": len(schedule),
            **({"schedule_full": schedule} if keep_full else {}),
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


def plan_week(farm, flowers, now_ms, prices=None, must_have=(), extend_days=0, **kw):
    """plan(), but a chore only pays when finished. Try every set of chores (most tickets
    first) and keep the first one whose chores all fit the week; chore harvests can feed
    each other (Purple Cosmos grown for one chore are parents for Blue Pansy)."""
    from itertools import combinations
    chores = [m for m in must_have if m.get("kind") == "grow" and m["count"] > 0]
    rest = [m for m in must_have if m not in chores]
    sets = [c for k in range(len(chores), -1, -1) for c in combinations(chores, k)]
    sets.sort(key=lambda c: -sum(m.get("tickets", 0) for m in c))
    pick = ()
    for chosen in sets:
        r = plan(farm, flowers, now_ms, prices, must_have=rest + list(chosen), **kw)
        if all(m["done"] >= m["count"] for m in r["must_have"] if m.get("kind") == "grow"):
            pick = chosen
            break
    r = plan(farm, flowers, now_ms, prices, must_have=rest + list(pick), extend_days=extend_days, **kw)
    r["dropped"] = [m for m in chores if m not in pick]
    return r
