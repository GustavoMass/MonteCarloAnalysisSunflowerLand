"""Flower-bed planner: what to plant in each bed, and when.

Game rules (sunflower-land):
  * Grow time = the seed's base time x your permanent boosts (plantFlower.ts
    getFlowerTime): Flower Crown x0.5, Flower Fox x0.9, Blooming Boost
    x0.9/0.875/0.85, Flower Power x0.8/0.7/0.6, Flowery Abode x1.5/1.6/1.7.
    Temporary boosts (Blossom Hourglass, Moth Shrine) are not planned on.
  * A bed already growing is ready at plantedAt + baseDurationMs (speed-rate
    model) or, for older plantings, plantedAt + the base time (flowerBedReadiness.ts).
  * A seed can only be planted in a season that sells it; the colour comes
    from the seed plus the cross-breed item; one harvest gives one flower.

Planner rules:
  * You plant and harvest only while awake. One flower per bed at a time.
  * Goals come in strict tiers (needs() builds them, config flower_priorities):
    1 weekly board + delivery orders, 2 a parent for every flower that takes
    more than 5 days, 3 two of Guria's flowers and one of every seasonal one,
    4 Bloom Doll, 5 a second of every seasonal flower, 6 "Grow ..." chores,
    7 Floral Bed, 8 two of every flower.
    A free bed always takes the best tier it can start; tiers may be met in part.
  * Goal progress counts flowers that exist (held + growing), handed out tier by
    tier. A flower grown only to be crossed into another counts toward nothing.
  * A goal never crosses away a flower that an equal or higher tier keeps.
  * When a flower's parent is missing, the nearest ancestor you can grow is
    planted first (up to 3 steps), each step kept for the next; a parent from
    another season is grown in its own season and kept.
  * The plan runs on unseen (extend_days) so goal dates are real; only the
    first part (until the end of next week) is shown.
"""
import datetime as dt
import re
from itertools import combinations

SEASONS = ["spring", "summer", "autumn", "winter"]
H = 3600 * 1000
DAY = 24 * H
TIER_BASE = {1: 200, 2: 180, 3: 160, 4: 140, 5: 120, 6: 100, 7: 80, 8: 60}
TIER_NAME = {1: "board + orders", 2: "parents for 5+ day flowers", 3: "Guria + 1 of each seasonal",
             4: "Bloom Doll", 5: "2nd of each seasonal", 6: "weekly chores", 7: "Floral Bed", 8: "2 of every flower"}
SKILL_MULT = {"Blooming Boost": [0.9, 0.875, 0.85], "Flower Power": [0.8, 0.7, 0.6], "Flowery Abode": [1.5, 1.6, 1.7]}


# --------------------------------------------------------------------------- game rules
def grow_multiplier(farm):
    """Permanent flower grow-time multiplier and the boosts behind it (getFlowerTime)."""
    worn, placed, skills = set(farm.get("wearables", [])), set(farm.get("collectibles", [])), farm.get("skills", {})
    mult, used = 1.0, []
    if "Flower Crown" in worn:
        mult *= 0.5
        used.append("Flower Crown x0.5")
    if "Flower Fox" in placed:
        mult *= 0.9
        used.append("Flower Fox x0.9")
    for name, ranks in SKILL_MULT.items():
        r = skills.get(name, 0)
        if r:
            mult *= ranks[min(r, len(ranks)) - 1]
            used.append(f"{name} x{ranks[min(r, len(ranks)) - 1]}")
    return mult, used


def bed_ready(bed, flowers):
    """When a bed that is growing now is ready (getFlowerReadyAt)."""
    if bed.get("base_duration_ms") is not None:
        return bed["planted_at"] + bed["base_duration_ms"]
    seed = flowers["flowers"][bed["name"]]["seed"]
    return bed["planted_at"] + flowers["seeds"][seed]["days"] * DAY


# --------------------------------------------------------------------------- planner
class _Planner:
    def __init__(self, farm, flowers, now_ms, prices, musts, tz_offset_h, awake, show_until, full_until):
        self.farm, self.seeds, self.fl = farm, flowers["seeds"], flowers["flowers"]
        self.prices = prices or {}
        self.tz, self.awake = tz_offset_h, awake
        self.show_until, self.full_until = show_until, full_until
        self.season_now, self.s_start = farm["season"], farm["season_started"]
        self.mult, self.boosts = grow_multiplier(farm)
        self.inv = dict(farm.get("inventory", {}))
        self.stock = {n: int(self.inv.get(n, 0)) for n in self.fl}
        self.beds, self.pending = [], []          # pending: (ready_ms, flower)
        for i, b in enumerate(farm.get("flower_beds", [])):
            if b.get("name") in self.fl and b.get("planted_at"):
                ready = bed_ready(b, flowers)
                self.beds.append({"bed": i + 1, "free": max(now_ms, ready), "growing": b["name"], "ready": ready})
                self.pending.append((ready, b["name"]))
            else:
                self.beds.append({"bed": i + 1, "free": now_ms, "growing": None, "ready": None})
        self.musts = sorted((dict(m, done=0) for m in musts), key=lambda m: m.get("tier", 1))
        for i, m in enumerate(self.musts):
            m["_i"] = i
        self.by_flower = {}
        for m in self.musts:
            self.by_flower.setdefault(m["flower"], []).append(m)
        # flowers a tier keeps (owed, parents, stock): no equal-or-lower tier may cross them away
        self.protect = {}
        for m in self.musts:
            if m.get("kind") != "grow":
                self.protect.setdefault(m["flower"], []).append((m.get("tier", 1), m.get("keep", m.get("owed", m["count"]))))
        self.reserved = {}                         # (flower, flower it will be crossed into) -> count
        self.intent = {}                           # flower -> [(next flower, final flower, tier)]: chain middle steps
        self.need = {}
        self.schedule = []

    # ---- time
    def grow(self, name):
        return self.seeds[self.fl[name]["seed"]]["days"] * DAY * self.mult

    def season_at(self, ms):
        return SEASONS[(SEASONS.index(self.season_now) + int((ms - self.s_start) // (7 * DAY))) % 4]

    def week_end(self, ms):
        return self.s_start + (int((ms - self.s_start) // (7 * DAY)) + 1) * 7 * DAY

    def next_awake(self, ms):
        local = dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc) + dt.timedelta(hours=self.tz)
        if self.awake[0] <= local.hour < self.awake[1]:
            return int(ms)
        wake = local.replace(hour=self.awake[0], minute=0, second=0, microsecond=0)
        if local.hour >= self.awake[1]:
            wake += dt.timedelta(days=1)
        return int((wake - dt.timedelta(hours=self.tz)).timestamp() * 1000)

    def plantable(self, name, t):
        return self.season_at(t) in self.seeds[self.fl[name]["seed"]]["seasons"]

    # ---- goals
    def refresh_need(self):
        """Remaining need per goal from flowers that exist, handed out tier by tier."""
        left = dict(self.stock)
        for _, n in self.pending:
            left[n] = left.get(n, 0) + 1
        for (p, _), k in self.reserved.items():
            left[p] = left.get(p, 0) - k
        for m in self.musts:
            if m.get("kind") == "grow":
                self.need[m["_i"]] = max(0, m["count"] - m["done"])
                continue
            owed = m.get("owed", m["count"])
            pool = left.get(m["flower"], 0)
            if m.get("tier", 1) == 1:              # only what is ready by the deadline
                on_time = (self.stock.get(m["flower"], 0) - self.kept(m["flower"])
                           + sum(1 for r, n in self.pending if n == m["flower"] and self.next_awake(r) <= m["by"]))
                pool = min(pool, on_time)
            got = max(0, min(pool, owed))
            left[m["flower"]] = left.get(m["flower"], 0) - got
            self.need[m["_i"]] = owed - got

    def kept(self, flower, target=None):
        """How many of flower are kept to be crossed (into target, or into anything)."""
        return sum(k for (f, tg), k in self.reserved.items() if f == flower and (target is None or tg == target))

    def tier_of(self, name):
        t = min((m.get("tier", 1) for m in self.by_flower.get(name, []) if self.need.get(m["_i"], 0) > 0), default=99)
        return min([t] + [tr for _, _, tr in self.intent.get(name, [])])

    def value(self, name, t):
        """Worth of one more of this flower planted at t: its best unmet tier."""
        v, done_at = 0.0, self.next_awake(t + self.grow(name))
        for m in self.by_flower.get(name, []):
            if self.need.get(m["_i"], 0) > 0 and done_at <= m["by"]:
                tier = m.get("tier", 1)
                chore = m.get("kind") == "grow"
                extra = max(0.0, 7 - (m["by"] - done_at) / DAY) if tier == 1 or chore else 0.0
                if chore:
                    extra += min(5.0, 5 * m.get("tickets", 0) / max(1, m["count"] * self.grow(name) / DAY))
                v = max(v, TIER_BASE.get(tier, 0) + extra)
        for _, _, tr in self.intent.get(name, []):  # a chain already started goes on first
            v = max(v, TIER_BASE.get(tr, 0) + 1)
        return v

    def why(self, name):
        for m in self.by_flower.get(name, []):
            if self.need.get(m["_i"], 0) > 0:
                return f"{m.get('tier', 1)} · {m.get('note') or TIER_NAME.get(m.get('tier', 1))}"
        return "spare"

    # ---- cross-breeding
    def option(self, name, tier):
        """Cheapest cross-breed for name right now: (cost, item, qty, to buy) or None."""
        best = None
        for parent, qty in self.fl[name].get("parents", []):
            if parent in self.fl:
                mine = self.kept(parent, name)          # grown for this very flower
                ready_mine = min(mine, self.stock.get(parent, 0))
                if ready_mine >= qty:
                    cand = (0.0, parent, qty, 0)
                else:
                    keep = sum(q for tr, q in self.protect.get(parent, []) if tr <= tier) + self.kept(parent)
                    if self.stock.get(parent, 0) - keep < qty:
                        continue
                    cand = (0.5, parent, qty, 0)
            else:
                buy = max(0, qty - self.inv.get(parent, 0))
                cand = (buy * (self.prices.get(parent) or 99), parent, qty, buy)
            if best is None or cand[0] < best[0]:
                best = cand
        return best

    def chain(self, name, tier, t, depth, seen=()):
        """Paths to grow a missing parent of name, as [flower to plant now, ..., name], with the
        option for the first flower and the grow time until name can be planted."""
        for parent, qty in self.fl[name].get("parents", []):
            if parent not in self.fl or qty != 1 or parent in seen or not self.plantable(parent, t):
                continue
            opt = self.option(parent, tier)
            if opt and opt[1] in seen + (name,):    # crossing the very flower we are making: a pointless swap
                opt = None
            if opt:
                yield [parent, name], opt, self.grow(parent)
            elif depth > 0:
                for path, qopt, g in self.chain(parent, tier, t, depth - 1, seen + (name,)):
                    yield path + [name], qopt, g + self.grow(parent)

    def coming(self, name):
        """How many of name are on their way through chains (parent kept for it, or a step planned)."""
        return sum(k for (_, tg), k in self.reserved.items() if tg == name) + \
            sum(1 for lst in self.intent.values() for nxt, _, _ in lst if nxt == name)

    def waiting_on_parent(self, name):
        """Enough chains for name already running? One per flower still needed, side by side
        (3 Primula Enigma = 3 chains at once, bed room permitting)."""
        tr = self.tier_of(name)                     # only the copies of the goal being served now
        wanted = sum(self.need.get(m["_i"], 0) for m in self.by_flower.get(name, []) if m.get("tier", 1) == tr) +             len(self.intent.get(name, []))
        return self.coming(name) >= wanted

    # ---- one bed decision
    def pick(self, t):
        """Best planting for a free bed: highest goal first; inside a goal, the flower whose
        (shortest) path is longest starts first, so the goal is done soonest."""
        best = None
        for name in self.fl:
            v = self.value(name, t)
            if v <= 0:
                continue
            now_ok = self.plantable(name, t)
            opt = self.option(name, self.tier_of(name)) if now_ok else None
            if opt:
                key = (v, self.grow(name))
                if best is None or key > best[0]:
                    best = (key, name, opt, None)
                continue
            if self.waiting_on_parent(name):
                continue
            paths = [(g, path, qopt) for path, qopt, g in self.chain(name, self.tier_of(name), t, 2)
                     if t + g + self.grow(name) <= self.full_until]
            if not paths:
                continue
            g, path, qopt = min(paths, key=lambda x: (x[0], len(x[1])))     # shortest way there
            key = (v - (0 if now_ok else 10), g + self.grow(name))
            if best is None or key > best[0]:
                best = (key, path[0], qopt, path)
        return best

    def plant(self, bed, t, choice):
        _, name, (cost, parent, qty, buy), path = choice
        target = None
        if path:                                   # first step of a chain: keep each step for the next
            final = path[-1]                       # label with the goal itself, not a chain passing through
            tier = min((m.get("tier", 1) for m in self.by_flower.get(final, []) if self.need.get(m["_i"], 0) > 0),
                       default=self.tier_of(final))
            target = path[1]
            for a, b in zip(path[1:-1], path[2:]):
                self.intent.setdefault(a, []).append((b, final, tier))
            why = f"{tier} · parent for {final}" + (f" (via {', '.join(path[1:-1])})" if len(path) > 2 else "")
        elif self.intent.get(name) and self.tier_of(name) == min(tr for _, _, tr in self.intent[name]):
            nxt, final, tr = self.intent[name].pop(0)  # a middle step: kept for the next flower
            if not self.intent[name]:
                del self.intent[name]
            target = nxt
            why = f"{tr} · parent for {final}" + (f" (via {nxt})" if nxt != final else "")
        else:
            why = self.why(name)
        if parent in self.fl:
            self.stock[parent] -= qty
            k = self.kept(parent, name)
            if k:
                self.reserved[(parent, name)] = k - min(k, qty)
                if not self.reserved[(parent, name)]:
                    del self.reserved[(parent, name)]
        else:
            self.inv[parent] = max(0, self.inv.get(parent, 0) - qty)
        if target:
            self.reserved[(name, target)] = self.reserved.get((name, target), 0) + 1
        else:                                       # chores count fresh harvests
            for m in self.by_flower.get(name, []):
                if m.get("kind") == "grow" and m["done"] < m["count"] and self.next_awake(t + self.grow(name)) <= m["by"]:
                    m["done"] += 1
                    break
        ready = t + self.grow(name)
        self.pending.append((ready, name))
        self.schedule.append({"bed": bed["bed"], "plant": int(t), "ready": int(ready),
                              "harvest": self.next_awake(ready), "flower": name, "cross": f"{qty} {parent}",
                              "buy": buy, "season": self.season_at(t), "parent_for": target, "why": why,
                              "tier": int(why.split(" ·")[0]) if why[0].isdigit() else 99})
        bed["free"] = ready

    def snapshot(self):
        out = dict(self.stock)
        for _, n in self.pending:
            out[n] = out.get(n, 0) + 1
        return out

    def run(self):
        shown_end, tier_done = None, {}
        tiers = {m.get("tier", 1) for m in self.musts}
        for _ in range(20000):
            bed = min(self.beds, key=lambda b: b["free"])
            t = self.next_awake(bed["free"])
            if t >= self.show_until and shown_end is None:
                shown_end = self.snapshot()
            if t >= self.full_until:
                break
            for r, n in [p for p in self.pending if p[0] <= t]:
                self.stock[n] += 1
                self.pending.remove((r, n))
            self.refresh_need()
            for tr in tiers - set(tier_done):
                if all(self.need[m["_i"]] == 0 for m in self.musts if m.get("tier", 1) == tr):
                    tier_done[tr] = max([t] + [r for r, n in self.pending
                                               if any(m.get("tier", 1) == tr for m in self.by_flower.get(n, []))])
            choice = self.pick(t)
            if choice is None:                     # nothing to start: wait for a harvest or a new week
                nxt = min([r for r, _ in self.pending if r > t] + [self.week_end(t), self.full_until])
                bed["free"] = max(nxt, t + H)
                continue
            self.plant(bed, t, choice)
        self.refresh_need()
        return shown_end or self.snapshot(), tier_done


def plan(farm, flowers, now_ms, prices=None, target_start_ms=None, target_days=7,
         tz_offset_h=-3, awake=(6, 23), board_now=(), must_have=(), extend_days=0, keep_full=False):
    """Plan the beds until the end of next week (shown) and extend_days more (unseen)."""
    target_start = target_start_ms or (farm["season_started"] + 7 * DAY)
    horizon = target_start + target_days * DAY
    p = _Planner(farm, flowers, now_ms, prices, must_have, tz_offset_h, awake, horizon, horizon + extend_days * DAY)
    end_stock, tier_done = p.run()
    for m in p.musts:
        m["left_after_full"] = p.need.get(m["_i"], 0)
    shown = [x for x in p.schedule if x["plant"] < horizon]
    tiers = {}
    for m in p.musts:
        d = tiers.setdefault(m.get("tier", 1), {"done_at": tier_done.get(m.get("tier", 1)), "planted_shown": 0,
                                                "left_after_full": 0})
        d["left_after_full"] += m["left_after_full"]
    for x in shown:
        if x["tier"] in tiers and not x["parent_for"]:
            tiers[x["tier"]]["planted_shown"] += 1
    fl = p.fl
    flower_only = {x: [q for q, _ in f.get("parents", []) if q in fl]
                   for x, f in fl.items() if not any(q not in fl for q, _ in f.get("parents", []))}
    readiness = [{"flower": x, "season_only": len(p.seeds[fl[x]["seed"]]["seasons"]) == 1, "parents": ps,
                  "held_after_plan": [q for q in ps if end_stock.get(q, 0) > 0],
                  "held_now": [q for q in ps if farm["inventory"].get(q)]} for x, ps in sorted(flower_only.items())]
    return {"speed": p.mult, "boosts": p.boosts, "beds": p.beds, "schedule": shown, "target_start": target_start,
            "horizon": horizon, "full_until": p.full_until, "tiers": tiers, "planted_total": len(p.schedule),
            **({"schedule_full": p.schedule} if keep_full else {}),
            "tz_offset_h": tz_offset_h, "awake": list(awake), "readiness": readiness,
            "must_have": [{k: v for k, v in m.items()} for m in p.musts],
            "stock_now": {n: int(farm["inventory"].get(n, 0)) for n in fl if farm["inventory"].get(n)},
            "stock_end": {n: v for n, v in end_stock.items() if v}}


# --------------------------------------------------------------------------- goals
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
    # 2: one parent for every flower whose whole path takes more than N days (flowers.json)
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
    # 3: Guria's flowers and one of every seasonal one
    for f in prio.get("guria", []):
        add(3, f, prio.get("guria_each", 2), "Guria asks for it")
    seeds = flowers.get("seeds", {})
    seasonal = [f for f in sorted(fl) if len(seeds.get(fl[f].get("seed"), {}).get("seasons", [1, 2])) == 1]
    first = min(prio.get("seasonal_first", 1), prio.get("seasonal_each", 2))
    for f in seasonal:
        add(3, f, first, f"seasonal ({seeds[fl[f]['seed']]['seasons'][0]})")
    # 4: Bloom Doll
    for f, q in prio.get("bloom_doll", {}).items():
        add(4, f, q, "Bloom Doll")
    # 5: the rest of every seasonal one (on top of tier 3's)
    for f in seasonal:
        add(5, f, prio.get("seasonal_each", 2) - first, f"seasonal ({seeds[fl[f]['seed']]['seasons'][0]}), 2nd")
    # 6: chores
    act = farm.get("activity", {})
    for c in farm.get("chores", []):
        m = re.match(r"Grow (.+?) (\d+) times?", c.get("name") or "")
        if m and m.group(1) in fl:
            f, n = m.group(1), int(m.group(2))
            done = int(act.get(f"{f} Harvested", 0) - (c.get("initial") or 0))
            left = max(0, n - done - growing.get(f, 0))
            out.append({"flower": f, "count": left, "owed": n, "held": done, "growing": growing.get(f, 0), "by": by,
                        "kind": "grow", "tier": 6, "note": f"{c['npc'].title()} chore: grow {f} {n}x",
                        "reward": c.get("reward"),
                        "tickets": ((c.get("reward") or {}).get("items") or {}).get(ticket, 0)})
    # 7: Floral Bed (flowers only)
    for f, q in prio.get("floral_bed", {}).items():
        add(7, f, q, "Floral Bed")
    # 8: two of every flower
    for f in sorted(fl):
        add(8, f, prio.get("every_each", 2), "2 of every flower")
    return out


def plan_week(farm, flowers, now_ms, prices=None, must_have=(), extend_days=0, **kw):
    """plan(), but a chore only pays when finished: try sets of chores (most caps first) on the
    shown weeks and keep the first whose chores all finish; then plan that set for the long run."""
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
