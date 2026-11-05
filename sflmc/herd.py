"""Chapter herd simulation for one animal type.

Each week a new bounty board opens. The player sells every awake animal that
meets an open request (hardest request first), keeps a herd sized to the
board plus a buffer, and stops feeding animals once they reach a cap level
(they then wait awake for a request, which is when sickness can hit).
Pigs can also be traded in for Pig Bristles at a set level.
"""
import heapq

from . import analysis as A
from .sim import Pet

WEEK_H = 7 * 24.0
BUY_COINS = {"Chicken": 50, "Cow": 100, "Sheep": 120, "Pig": 100}
KINDS = ("tickets", "coins", "gems")


def make_board(rng, counts, level_pool, coin_points, ticket_amount, gems):
    board = []
    for kind, n in counts.items():
        for _ in range(int(n)):
            lv = rng.choice(level_pool)
            amt = (A.interp_bounty(coin_points, lv) or 0.0) if kind == "coins" else ticket_amount if kind == "tickets" else gems
            board.append({"level": lv, "kind": kind, "amount": amt, "open": True})
    return board


def simulate_herd(model, rng, *, start_xp, weeks, schedule, sell=True, buffer=None,
                  level_pool, coin_points, ticket_amount, gems, coin_mult=1.0,
                  stop_feeding_at=None, trade_in_at=None, no_ticket_weeks=(), live_board=None, sell_order=None):
    """schedule[w] = (capacity, {"coins": n, "gems": n, "tickets": n}) for week w.
    buffer=None keeps the building full; an int keeps (requests this week + buffer) animals.
    sell_order: None sells whichever qualifying animal wakes first; "lowest" (or
    "highest") holds an animal back while another one with a lower (higher)
    level could fill the same request, so that one is sold instead."""
    animal = model.animal
    horizon = weeks * WEEK_H
    pets, heap = {}, []
    nid = 0

    def add(xp=0.0, t=0.0, stagger=False):
        nonlocal nid
        p = Pet(model, rng, xp=xp, t=t + (rng.random() * model.sleep if stagger else 0.0))
        pets[nid] = p
        heapq.heappush(heap, (p.next_time(), nid))
        nid += 1

    def target(w):
        cap, counts = schedule[min(w, len(schedule) - 1)]
        return cap if buffer is None else min(cap, sum(counts.values()) + buffer)

    for x in list(start_xp)[:target(0)]:
        add(x, 0.0, stagger=True)
    while len(pets) < target(0):
        add()

    out = {k: [0.0] * weeks for k in ("coins", "gems", "tickets", "produce", "feed", "buy_coins", "sold",
                                      "traded", "bristles", "parked_days", "herd")}
    offered = dict.fromkeys(KINDS, 0)
    filled = dict.fromkeys(KINDS, 0)
    sold_levels = []
    week, board = -1, []
    parked_since = {}

    def open_week(w):
        nonlocal board
        cap, counts = schedule[min(w, len(schedule) - 1)]
        counts = dict(counts)
        if w in no_ticket_weeks and counts.get("tickets"):
            counts["coins"] = counts.get("coins", 0) + counts.pop("tickets")
        board = ([dict(r, open=True) for r in live_board] if live_board and w == 0 else
                 make_board(rng, counts, level_pool, coin_points, ticket_amount, gems))
        for r in board:
            offered[r["kind"]] += 1
        while len(pets) < target(w):   # building upgrade or new target: top up
            add(0.0, w * WEEK_H)
        out["herd"][w] = len(pets)

    def remove(i, t, w):
        if i in parked_since:
            out["parked_days"][w] += (t - parked_since.pop(i)) / 24
        del pets[i]
        if len(pets) < target(w):
            add(0.0, t)
            out["buy_coins"][w] += BUY_COINS[animal]

    while heap:
        t, i = heapq.heappop(heap)
        if t >= horizon:
            break
        if i not in pets:
            continue
        w = int(t // WEEK_H)
        while week < w:
            week += 1
            open_week(week)
        p = pets[i]
        if p.awake(t):
            bl = p.bounty_level()
            cands = [r for r in board if r["open"] and r["level"] <= bl] if sell else []
            if cands:
                order = {"tickets": 0, "coins": 1, "gems": 2}
                r = max(cands, key=lambda r: (r["level"], -order[r["kind"]], r["amount"]))
                others = [q.bounty_level() for j, q in pets.items() if j != i]
                lower = any(r["level"] <= b < bl for b in others)
                higher = any(b > bl for b in others)
                if (sell_order == "lowest" and lower) or (sell_order == "highest" and higher):
                    cands = []
            if cands:
                r["open"] = False
                filled[r["kind"]] += 1
                out[r["kind"]][w] += r["amount"] * (coin_mult if r["kind"] == "coins" else 1)
                out["sold"][w] += 1
                out["bristles"][w] += model.bristle_value[bl]
                sold_levels.append(bl)
                remove(i, t, w)
                continue
            if trade_in_at is not None and bl >= trade_in_at and model.bristle_value[bl] > 0:
                out["traded"][w] += 1
                out["bristles"][w] += model.bristle_value[bl]
                remove(i, t, w)
                continue
            if stop_feeding_at is not None and not p.ready and p.level >= stop_feeding_at:
                parked_since.setdefault(i, t)
                heapq.heappush(heap, ((w + 1) * WEEK_H + 1e-6, i))   # look again when the next board opens
                continue
            if i in parked_since:
                out["parked_days"][w] += (t - parked_since.pop(i)) / 24
        ev = p.act(t)
        if ev:
            out["produce"][w] += ev[2]
            out["feed"][w] += ev[3]
        heapq.heappush(heap, (p.next_time(), i))

    return {"weekly": out, "offered": offered, "filled": filled, "sold_levels": sold_levels}
