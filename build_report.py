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
    data = json.dumps(rnd(res), separators=(",", ":"))
    with open(os.path.join(HERE, "report", "template.html"), encoding="utf-8") as f:
        html = f.read()
    path = os.path.join(HERE, "report", "index.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html.replace("/*__DATA__*/null", data))
    print(f"report/index.html written ({len(data) / 1024:.0f} KB data)")
    return path


if __name__ == "__main__":
    main()
