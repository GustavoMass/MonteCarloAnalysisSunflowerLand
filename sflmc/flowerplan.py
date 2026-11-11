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
    more than 5 days, 3 two of Guria's flowers and of every seasonal one,
    4 Bloom Doll, 5 "Grow ..." chores, 6 two of every flower, 7 Floral Bed.
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
TIER_BASE = {1: 200, 2: 180, 3: 160, 4: 140, 5: 120, 6: 100, 7: 80}
TIER_NAME = {1: "board + orders", 2: "parents for 5+ day flowers", 3: "Guria + seasonal stock",
             4: "Bloom Doll", 5: "weekly chores", 6: "2 of every flower", 7: "Floral Bed"}
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
        self.reserved = {}                         # flower -> the flower it will be crossed into
        self.intent = {}                           # flower -> [(final flower, tier)]: middle step of a chain
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
        for p in self.reserved:
            left[p] = left.get(p, 0) - 1
        for m in self.musts:
            if m.get("kind") == "grow":
                self.need[m["_i"]] = max(0, m["count"] - m["done"])
                continue
            owed = m.get("owed", m["count"])
            pool = left.get(m["flower"], 0)
            if m.get("tier", 1) == 1:              # only what is ready by the deadline
                on_time = (self.stock.get(m["flower"], 0) - sum(1 for p in self.reserved if p == m["flower"])
                           + sum(1 for r, n in self.pending if n == m["flower"] and self.next_awake(r) <= m["by"]))
                pool = min(pool, on_time)
            got = max(0, min(pool, owed))
            left[m["flower"]] = left.get(m["flower"], 0) - got
            self.need[m["_i"]] = owed - got

    def tier_of(self, name):
        t = min((m.get("tier", 1) for m in self.by_flower.get(name, []) if self.need.get(m["_i"], 0) > 0), default=99)
        return min([t] + [tr for _, tr in self.intent.get(name, [])])

    def value(self, name, t):
        """Worth of one more of this flower planted at t: its best unmet tier."""
        v, done_at = 0.0, self.next_awake(t + self.grow(name))
        for m in self.by_flower.get(name, []):
            if self.need.get(m["_i"], 0) > 0 and done_at <= m["by"]:
                tier = m.get("tier", 1)
                extra = max(0.0, 7 - (m["by"] - done_at) / DAY) if tier in (1, 5) else 0.0
                if tier == 5:
                    extra += min(5.0, 5 * m.get("tickets", 0) / max(1, m["count"] * self.grow(name) / DAY))
                v = max(v, TIER_BASE.get(tier, 0) + extra)
        for _, tr in self.intent.get(name, []):
            v = max(v, TIER_BASE.get(tr, 0) - 6)
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
                if self.reserved.get(parent) == name:
                    keep = 0
                else:
                    keep = sum(q for tr, q in self.protect.get(parent, []) if tr <= tier)
                if self.stock.get(parent, 0) - keep < qty:
                    continue
                cand = (0.0 if self.reserved.get(parent) == name else 0.5, parent, qty, 0)
            else:
                buy = max(0, qty - self.inv.get(parent, 0))
                cand = (buy * (self.prices.get(parent) or 99), parent, qty, buy)
            if best is None or cand[0] < best[0]:
                best = cand
        return best

    def chain(self, name, tier, t, depth, seen=()):
        """Ways to start a missing parent of name: (plant now, option, kept for, grow until name, steps)."""
        for parent, qty in self.fl[name].get("parents", []):
            if parent not in self.fl or qty != 1 or self.reserved.get(parent) or parent in seen or not self.plantable(parent, t):
                continue
            opt = self.option(parent, tier)
            if opt:
                yield parent, opt, name, self.grow(parent), 1
            elif depth > 0:
                for q, qopt, tgt, g, d in self.chain(parent, tier, t, depth - 1, seen + (name,)):
                    yield q, qopt, tgt, g + self.grow(parent), d + 1

    def waiting_on_parent(self, name):
        ps = [p for p, _ in self.fl[name].get("parents", [])]
        return any(n in ps for _, n in self.pending) or any(self.intent.get(p) for p in ps)

    # ---- one bed decision
    def pick(self, t):
        best = None
        for name in self.fl:
            v = self.value(name, t)
            if v <= 0:
                continue
            now_ok = self.plantable(name, t)
            opt = self.option(name, self.tier_of(name)) if now_ok else None
            if opt:
                key = (v, -self.grow(name))
                if best is None or key > best[0]:
                    best = (key, name, opt, None)
                continue
            if self.waiting_on_parent(name):
                continue
            for q, qopt, tgt, g, depth in self.chain(name, self.tier_of(name), t, 2):
                if t + g + self.grow(name) > self.full_until:
                    continue
                key = (v - 12 * depth - (0 if now_ok else 10), -(g + self.grow(name)))
                if best is None or key > best[0]:
                    best = (key, q, qopt, (tgt, name))
        return best

    def plant(self, bed, t, choice):
        _, name, (cost, parent, qty, buy), chained = choice
        target = None
        if chained:
            target, final = chained
            if target != final:
                self.intent.setdefault(target, []).append((final, self.tier_of(final)))
            why = f"{self.tier_of(final)} · parent for {final}" + (f" (via {target})" if target != final else "")
        elif self.intent.get(name) and self.tier_of(name) == min(tr for _, tr in self.intent[name]):
            final, tr = self.intent[name].pop(0)
            if not self.intent[name]:
                del self.intent[name]
            target, why = final, f"{tr} · parent for {final}"
        else:
            why = self.why(name)
        if parent in self.fl:
            self.stock[parent] -= qty
            if self.reserved.get(parent) == name:
                del self.reserved[parent]
        else:
            self.inv[parent] = max(0, self.inv.get(parent, 0) - qty)
        if target:
            self.reserved[name] = target
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
