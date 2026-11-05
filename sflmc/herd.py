"""Chapter herd simulation: a full building of one animal type, a new bounty
board every week, and a player who sells to every bounty an awake animal
qualifies for (except kept animals), buying a level-0 replacement at once."""
import heapq
import random

from . import analysis as A
from . import game as G
from .sim import Pet

WEEK_H = 7 * 24.0
BUY_COINS = {"Chicken": 50, "Cow": 100, "Sheep": 120, "Pig": 100}


def make_board(rng, animal, counts, level_pool, coin_points, ticket_amount, gems):
    """One week of requests: [{level, kind, amount, open}]. Levels drawn from what boards have asked."""
    board = []
    for kind, n in counts.items():
        for _ in range(int(n)):
            lv = rng.choice(level_pool)
            if kind == "coins":
                amt = A.interp_bounty(coin_points, lv) or 0.0
            elif kind == "tickets":
                amt = ticket_amount
            else:
                amt = gems
            board.append({"level": lv, "kind": kind, "amount": amt, "open": True})
    return board


def simulate_herd(model, rng, *, start_xp, capacity, weeks, sell, counts, level_pool,
                  coin_points, ticket_amount, gems, live_board=None, stop_feeding_at=None):
    animal = model.animal
    horizon = weeks * WEEK_H
    xps = list(start_xp)[:capacity] + [0.0] * max(0, capacity - len(start_xp))
    # existing animals: unknown phase in their sleep -> stagger first wake over one sleep
    pets = [Pet(model, rng, xp=x, t=rng.random() * model.sleep) for x in xps]
    heap = [(p.next_time(), i) for i, p in enumerate(pets)]
    heapq.heapify(heap)

    W = weeks
    out = {k: [0.0] * W for k in ("coins", "gems", "tickets", "produce", "feed", "buy_coins", "sold")}
    offered = {"coins": 0, "gems": 0, "tickets": 0}
    filled = {"coins": 0, "gems": 0, "tickets": 0}
    sold_levels = []
    week, board = -1, []

    def new_week(w):
        nonlocal board
        board = ([dict(r, open=True) for r in live_board] if live_board else
                 make_board(rng, animal, counts, level_pool, coin_points, ticket_amount, gems))
        for r in board:
            offered[r["kind"]] += 1

    while heap:
        t, i = heapq.heappop(heap)
        if t > horizon:
            break
        w = int(t // WEEK_H)
        while week < w:
            week += 1
            new_week(week)
        p = pets[i]
        if p.awake(t) and sell:
            bl = p.bounty_level()
            # fill the hardest request this animal meets; tickets first on ties
            cands = [r for r in board if r["open"] and r["level"] <= bl]
            if cands:
                order = {"tickets": 0, "coins": 1, "gems": 2}
                r = max(cands, key=lambda r: (r["level"], -order[r["kind"]], r["amount"]))
                r["open"] = False
                filled[r["kind"]] += 1
                out[r["kind"]][w] += r["amount"]
                out["sold"][w] += 1
                sold_levels.append(bl)
                out["buy_coins"][w] += BUY_COINS[animal]
                p = pets[i] = Pet(model, rng, t=t)
        if stop_feeding_at is not None and p.awake(t) and not p.ready and p.level >= stop_feeding_at:
            # park it: awake, unfed, costs nothing; look again when the next board opens
            heapq.heappush(heap, ((w + 1) * WEEK_H + 1e-6, i))
            continue
        ev = p.act(t)
        if ev:
            out["produce"][w] += ev[2]
            out["feed"][w] += ev[3]
        heapq.heappush(heap, (p.next_time(), i))

    return {"weekly": out, "offered": offered, "filled": filled, "sold_levels": sold_levels}
