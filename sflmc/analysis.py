"""Turn Monte Carlo runs into per-level distributions and chapter totals."""
import math
import statistics as st

from . import game as G

QS = (0.1, 0.25, 0.5, 0.75, 0.9)


def pct(values, q):
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def dist(values):
    """{p10, p25, p50, p75, p90, mean} or None."""
    if not values:
        return None
    d = {f"p{int(q * 100)}": pct(values, q) for q in QS}
    d["mean"] = st.mean(values)
    return d


def interp_bounty(points, level):
    """Log-linear interpolation of observed coin bounties (level -> coins).
    None outside the observed level range: no sale price is assumed there."""
    pts = sorted((int(k), float(v)) for k, v in points.items())
    if not pts or level < pts[0][0] or level > pts[-1][0]:
        return None
    for (l0, v0), (l1, v1) in zip(pts, pts[1:]):
        if l0 <= level <= l1:
            f = (level - l0) / (l1 - l0)
            return math.exp(math.log(v0) + f * (math.log(v1) - math.log(v0)))
    return pts[0][1]


def per_level(model, runs, buy_flower):
    """Distribution, per level, of: profit/day of the cycle ending at that level,
    cumulative net when first reaching it, day reached, pets in that cycle."""
    levels = []
    for L in range(1, G.MAX_LEVEL + 1):
        daily, cum_reach, day_reach, pets, feed, prod = [], [], [], [], [], []
        for ev in runs:
            cum, prev_t, seen = -buy_flower, None, False
            for t, lv, p, f, n in ev:
                cum += p - f
                if not seen and lv >= L:
                    seen = True
                    cum_reach.append(cum)
                    day_reach.append(t / 24)
                    if lv == L and prev_t is not None and t > prev_t:
                        daily.append((p - f) / ((t - prev_t) / 24))
                        pets.append(n)
                        feed.append(f)
                        prod.append(p)
                prev_t = t
        levels.append({"level": L, "profit_day": dist(daily), "cum_at_reach": dist(cum_reach),
                       "day_reached": dist(day_reach), "pets": st.mean(pets) if pets else None,
                       "feed": st.mean(feed) if feed else None, "produce": st.mean(prod) if prod else None})
    ss = []
    for ev in runs:
        l15 = [(t, p - f) for t, lv, p, f, _ in ev if lv == G.MAX_LEVEL]
        if len(l15) >= 3:
            ss.append(sum(x for _, x in l15[1:]) / ((l15[-1][0] - l15[0][0]) / 24))
    return {"levels": levels, "l15_day": dist(ss)}


def herd_totals(results, coins_per_flower):
    """Chapter totals across herd runs."""
    def tot(r, k):
        return sum(r["weekly"][k])
    keys = ("coins", "gems", "tickets", "produce", "feed", "buy_coins", "sold")
    out = {k: dist([tot(r, k) for r in results]) for k in keys}
    out["net_flower"] = dist([tot(r, "produce") - tot(r, "feed") for r in results])
    out["coins_net"] = dist([tot(r, "coins") - tot(r, "buy_coins") for r in results])
    weeks = len(results[0]["weekly"]["tickets"])
    out["weekly"] = {k: [dist([r["weekly"][k][w] for r in results]) for w in range(weeks)]
                     for k in ("tickets", "coins", "produce", "feed")}
    out["fill_rate"] = {k: (st.mean(r["filled"][k] / r["offered"][k] for r in results) if results[0]["offered"][k] else None)
                        for k in ("coins", "gems", "tickets")}
    lv = [x for r in results for x in r["sold_levels"]]
    out["sold_level_hist"] = {str(L): lv.count(L) / len(results) for L in range(16) if lv.count(L)}
    return out
