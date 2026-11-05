"""Inject results/results.json into report/template.html -> report/index.html."""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def rnd(x):
    if isinstance(x, float):
        return round(x, 4)
    if isinstance(x, list):
        return [rnd(v) for v in x]
    if isinstance(x, dict):
        return {k: rnd(v) for k, v in x.items()}
    return x


def main():
    with open(os.path.join(HERE, "results", "results.json"), encoding="utf-8") as f:
        res = json.load(f)
    slim = {
        "meta": {k: res["meta"][k] for k in ("runs", "days", "generated", "coins_per_flower", "sell_fee",
                                               "schedules", "slops")},
        "farm": res["meta"]["farm"],
        "prices": res["meta"]["prices"],
        "bounties": res["meta"]["bounties"],
        "builds": list(res["meta"]["builds"]),
        "scenarios": [
            {k: s[k] for k in ("build", "animal", "schedule", "sleep_h", "food_qty_per_feed", "xp_mult",
                               "band", "levels", "steady_l15_daily", "produce_units")}
            for s in res["scenarios"]
        ],
    }
    data = json.dumps(rnd(slim), separators=(",", ":"))
    with open(os.path.join(HERE, "report", "template.html"), encoding="utf-8") as f:
        html = f.read()
    with open(os.path.join(HERE, "report", "index.html"), "w", encoding="utf-8") as f:
        f.write(html.replace("/*__DATA__*/null", data))
    print(f"report/index.html written ({len(data) / 1024:.0f} KB data)")


if __name__ == "__main__":
    main()
