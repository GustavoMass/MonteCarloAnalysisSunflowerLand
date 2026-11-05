"""Pull a farm and P2P prices from the public sfl-manager API and boil them
down to what the simulator needs. Writes Data/farm_<id>.json,
Data/prices_snapshot.json and Data/bounties_observed.json."""
import json
import os
import time
import urllib.request

from . import game as G

API = "https://sfl-manager.com/api"
UA = {"User-Agent": "Mozilla/5.0 (MonteCarloAnalysisSunflowerLand)"}
TICKET = "Duende Cap"  # Cave Dwellers chapter ticket


def _get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def _placed(farm):
    """Every collectible with coordinates, wherever it is placed (farm, home, interior)."""
    found = set()

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "collectibles" and isinstance(v, dict):
                    for name, items in v.items():
                        if isinstance(items, list) and any(isinstance(i, dict) and i.get("coordinates") for i in items):
                            found.add(name)
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(farm)
    return found


def _wearables(farm):
    worn = set((farm.get("bumpkin") or {}).get("equipped", {}).values())
    for fh in ((farm.get("farmHands") or {}).get("bumpkins") or {}).values():
        worn |= set((fh.get("equipped") or {}).values())
    return worn


def parse_farm(raw, farm_id):
    f = raw["raw"]["farm"]
    inv = f.get("inventory", {})
    placed = _placed(f)
    for name in ("Barn Manager", "Wrangler"):  # inventory-only boosts
        if float(inv.get(name, 0) or 0) > 0:
            placed.add(name)
    worn = _wearables(f)
    buildings = {b: (f.get(key) or {}).get("level", 0) if b in (f.get("buildings") or {}) else 0
                 for b, key in (("Hen House", "henHouse"), ("Barn", "barn"), ("Pigpen", "pigpen"))}
    animals = {}
    for key in ("henHouse", "barn", "pigpen"):
        for a in ((f.get(key) or {}).get("animals") or {}).values():
            animals.setdefault(a["type"], []).append(float(a.get("experience", 0)))
    chapter_wearables = sorted(w for w in worn if w and w.startswith("Duende"))
    return {
        "farm_id": farm_id,
        "source": f"{API}/v3/land/{farm_id}",
        "fetched": time.strftime("%Y-%m-%d %H:%M"),
        "skills": {k: int(v) for k, v in (f.get("bumpkin") or {}).get("skills", {}).items()},
        "collectibles": sorted(placed),
        "wearables": sorted(w for w in worn if w),
        "buildings": buildings,
        "animal_xp": animals,
        "vip": bool((f.get("vip") or {}).get("expiresAt", 0) > time.time() * 1000),
        "island": (f.get("island") or {}).get("type"),
        "chapter_wearables": chapter_wearables,
        "coins": f.get("coins"),
    }


def parse_board(raw):
    """Animal bounties on the current exchange board."""
    f = raw["raw"]["farm"]
    board = {a: [] for a in G.ANIMALS}
    for r in (f.get("bounties") or {}).get("requests", []):
        if r.get("name") not in board:
            continue
        items = r.get("items") or {}
        if r.get("coins"):
            board[r["name"]].append({"level": r["level"], "kind": "coins", "amount": r["coins"]})
        elif TICKET in items:
            board[r["name"]].append({"level": r["level"], "kind": "tickets", "amount": items[TICKET]})
        elif "Gem" in items:
            board[r["name"]].append({"level": r["level"], "kind": "gems", "amount": items["Gem"]})
    return board


def refresh(data_dir, farm_id):
    raw = _get(f"{API}/v3/land/{farm_id}")
    prices = _get(f"{API}/v1/prices")["p2p"]
    farm = parse_farm(raw, farm_id)
    board = parse_board(raw)

    need = {"Egg", "Feather", "Milk", "Leather", "Wool", "Merino Wool", "Truffle", "Pig Bristles"}
    for r in G.FEED_RECIPES.values():
        need |= set(r)
    for o in G.SLOP_OPTIONS.values():
        need |= set(o)
    snap = {"source": f"{API}/v1/prices (p2p, FLOWER per unit)", "fetched": time.strftime("%Y-%m-%d"),
            "prices": {k: prices[k] for k in sorted(need) if prices.get(k)}}

    # keep coin history: merge this week's coin levels into what we have seen before
    bpath = os.path.join(data_dir, "bounties_observed.json")
    old = {}
    if os.path.exists(bpath):
        with open(bpath, encoding="utf-8") as fh:
            old = json.load(fh)
    coins = old.get("coins", {a: {} for a in G.ANIMALS})
    for a, reqs in board.items():
        for r in reqs:
            if r["kind"] == "coins":
                coins.setdefault(a, {})[str(r["level"])] = r["amount"]
    bounties = {**old, "source": "sfl-manager land API, merged across refreshes",
                "updated": time.strftime("%Y-%m-%d"), "coins": coins, "current_board": board}

    os.makedirs(data_dir, exist_ok=True)
    for name, obj in ((f"farm_{farm_id}.json", farm), ("prices_snapshot.json", snap), ("bounties_observed.json", bounties)):
        with open(os.path.join(data_dir, name), "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=1)
    return farm, snap, bounties
