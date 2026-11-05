"""Aggregate Monte Carlo runs into per-level profitability and sell-timing tables."""
import math
import statistics as st

from . import game as G


def pct(values, q):
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * q
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def interp_bounty(points, level):
    """Log-linear interpolation of observed coin bounties (level -> coins).

    Returns None outside the observed level range: the board never asked for
    those levels, so no sale price is assumed there.
    """
    pts = sorted((int(k), float(v)) for k, v in points.items())
    if not pts or level < pts[0][0] or level > pts[-1][0]:
        return None
    for (l0, v0), (l1, v1) in zip(pts, pts[1:]):
        if l0 <= level <= l1:
            f = (level - l0) / (l1 - l0)
            return math.exp(math.log(v0) + f * (math.log(v1) - math.log(v0)))
    return pts[0][1]  # single observed point


def summarise(model, runs, days, buy_flower, bounty_flower_by_level):
    """bounty_flower_by_level[L] = FLOWER from selling at level L (coins + bristles)."""
    a = model.animal
    T = model.sleep
    # cumulative net FLOWER per day (percentile band)
    curves = []
    for ev in runs:
        daily = [0.0] * (days + 1)
        for t, lv, prod, feed, _ in ev:
            d = int(t // 24) + 1
            if d <= days:
                daily[d] += prod - feed
        cum, acc = [], -buy_flower
        for d in range(days + 1):
            acc += daily[d]
            cum.append(acc)
        curves.append(cum)
    band = {q: [pct([c[d] for c in curves], q) for d in range(days + 1)] for q in (0.1, 0.5, 0.9)}

    # per-level cycle economics and sell timing
    levels = []
    for L in range(1, G.MAX_LEVEL + 1):
        cyc_profit, cyc_dur, cyc_feed, cyc_prod, cyc_loves = [], [], [], [], []
        reach_t, reach_cum, sell_rate, sell_value, trade_rate = [], [], [], [], []
        for ev in runs:
            cum = -buy_flower
            prev_t = None
            seen = False
            for t, lv, prod, feed, loves in ev:
                cum += prod - feed
                if lv == L and prev_t is not None and not (lv == G.MAX_LEVEL and seen):
                    cyc_profit.append(prod - feed)
                    cyc_dur.append((t - prev_t) / 24)
                    cyc_feed.append(feed)
                    cyc_prod.append(prod)
                    cyc_loves.append(loves)
                if lv >= L and not seen:
                    seen = True
                    sell_t = (t + T) / 24  # sell when it wakes up again
                    reach_t.append(t / 24)
                    reach_cum.append(cum)
                    if bounty_flower_by_level[lv] is not None:
                        v = cum + bounty_flower_by_level[lv]
                        sell_value.append(v)
                        sell_rate.append(v / sell_t)
                    if model.bristle_value[lv] > 0:
                        v = cum + model.bristle_value[lv]
                        trade_rate.append(v / sell_t)
                prev_t = t
        dur = st.mean(cyc_dur) if cyc_dur else None
        levels.append({
            "level": L,
            "days_to_reach": st.mean(reach_t) if reach_t else None,
            "cycle_days": dur,
            "cycle_feed": st.mean(cyc_feed) if cyc_feed else None,
            "cycle_produce": st.mean(cyc_prod) if cyc_prod else None,
            "cycle_loves": st.mean(cyc_loves) if cyc_loves else None,
            "daily_profit": (st.mean(cyc_profit) / dur) if cyc_profit and dur else None,
            "daily_profit_p10": pct([p / d for p, d in zip(cyc_profit, cyc_dur) if d > 0], 0.1),
            "daily_profit_p90": pct([p / d for p, d in zip(cyc_profit, cyc_dur) if d > 0], 0.9),
            "bounty_flower": bounty_flower_by_level[L],
            "sell_value": st.mean(sell_value) if sell_value else None,
            "sell_value_p10": pct(sell_value, 0.1),
            "sell_value_p90": pct(sell_value, 0.9),
            "sell_rate": st.mean(sell_rate) if sell_rate else None,
            "tradein_rate": st.mean(trade_rate) if trade_rate else None,
            "cum_at_reach": st.mean(reach_cum) if reach_cum else None,
            "cum_at_reach_p10": pct(reach_cum, 0.1),
            "cum_at_reach_p90": pct(reach_cum, 0.9),
        })

    # steady state at max level: all L15 cycles after the first
    ss = []
    for ev in runs:
        l15 = [(t, p - f) for t, lv, p, f, _ in ev if lv == G.MAX_LEVEL]
        if len(l15) >= 3:
            span = (l15[-1][0] - l15[0][0]) / 24
            ss.append(sum(x for _, x in l15[1:]) / span)
    return {
        "band": {str(k): v for k, v in band.items()},
        "levels": levels,
        "steady_l15_daily": st.mean(ss) if ss else None,
    }
