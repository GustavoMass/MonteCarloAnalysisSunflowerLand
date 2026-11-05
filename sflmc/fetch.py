"""Pull a farm and P2P prices from the public sfl-manager API and boil them
down to what the simulator needs. Writes Data/farm_<id>.json,
Data/prices_snapshot.json and Data/bounties_observed.json."""
import json
import os
import time
import urllib.error
import urllib.request

from . import game as G

API = "https://sfl-manager.com/api"
UA = {"User-Agent": "Mozilla/5.0 (MonteCarloAnalysisSunflowerLand)"}
TICKET = "Duende Cap"  # Cave Dwellers chapter ticket


def _get(url, tries=4):
    """GET JSON, backing off politely when the API rate-limits (HTTP 429)."""
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code != 429 or i == tries - 1:
                raise
            time.sleep(5 * (i + 1))


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
        "inventory": {k: float(v) for k, v in inv.items()},
        "flower_beds": [{"name": (b.get("flower") or {}).get("name"), "planted_at": (b.get("flower") or {}).get("plantedAt"),
                         "boosted_ms": (b.get("flower") or {}).get("boostedTime", 0)}
                        for b in ((f.get("flowers") or {}).get("flowerBeds") or {}).values()],
        "season": (f.get("season") or {}).get("season"),
        "season_started": (f.get("season") or {}).get("startedAt"),
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


def _flowers(api):
    """Seeds (time, seasons) and the cheapest known breeding path for every flower."""
    p = api["payload"]
    seeds = {s["name"]: {"days": s["seconds"] / 86400, "seasons": s["seasons"], "flowers": s["flowers"]}
             for s in p["seeds"]}
    flowers = {}
    for name, src in p["sources"].items():
        fl = src.get("flower")
        if not fl:
            continue
        best = fl.get("best") or {}
        flowers[name] = {"seed": fl["seed"], "days": best.get("days"),
                         "parents": [(x["name"], x.get("qty") or 1) for x in fl.get("parents", [])],
                         "steps": [(s["name"], s.get("qty"), s.get("days")) for s in best.get("steps", [])]}
    return {"fetched": p.get("fetched_at"), "seeds": seeds, "flowers": flowers}


def _merge_orders(path, api):
    """Keep every ticket-NPC order ever seen, so request patterns build up over time."""
    hist = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            hist = json.load(fh)
    for sec in api["payload"]["sections"]:
        if sec["kind"] != "tickets":
            continue
        for n in sec["npcs"]:
            known = hist.setdefault(n["npc"], {"base": n.get("ticket_base"), "orders": {}})
            for o in n.get("orders", []):
                key = " + ".join(f'{i["qty"]} {i["name"]}' for i in o["items"])
                rec = known["orders"].setdefault(key, {"reward": o.get("reward"), "cost": o.get("cost"),
                                                       "cost_ok": o.get("cost_ok"), "days": []})
                rec["days"] = sorted(set(rec["days"]) | set(o.get("days", [])))
                rec["cost"] = o.get("cost")
    return hist


def nft_prices(names):
    """Floor price (FLOWER) of named NFTs from the sfl-manager catalog, all chapters."""
    names, found = set(names), {}
    for idx in _get(f"{API}/v3/nft").get("seasons", []):
        cat = _get(f"{API}/v3/nft/{idx['slug']}")
        for sec in cat.get("sections", []):
            for it in sec.get("items", []):
                if it["name"] in names and it.get("price") is not None:
                    found[it["name"]] = {"price": it["price"], "last_sale": it.get("last_sale"),
                                         "chapter": idx["chapter"], "tradable": it.get("tradable")}
    return found


def _ask_live_copy(farm_id):
    """sfl-manager serves a cached copy (can be hours old). Its own land page asks
    for a live reload with this POST before reading; do the same, ignore failures."""
    try:
        req = urllib.request.Request(f"{API}/v3/land/{farm_id}/refresh", data=b"", headers=UA, method="POST")
        with urllib.request.urlopen(req, timeout=60) as r:
            r.read()
    except Exception as e:  # noqa: BLE001
        print(f"  live reload not available ({e}); using sfl-manager's cached copy")


def refresh(data_dir, farm_id, nft_names=()):
    _ask_live_copy(farm_id)
    raw = _get(f"{API}/v3/land/{farm_id}")
    prices = _get(f"{API}/v1/prices")["p2p"]
    farm = parse_farm(raw, farm_id)
    board = parse_board(raw)

    need = {"Egg", "Feather", "Milk", "Leather", "Wool", "Merino Wool", "Truffle", "Pig Bristles",
            "Wood", "Stone", "Iron", "Gold", "Crimstone", "Oil", "Mud",
            "Sunflower", "Beetroot", "Cauliflower", "Radish", "Parsnip", "Kale", "Eggplant", "Blueberry",
            "Banana", "Apple", "Rhubarb", "Pepper", "Artichoke", "Onion", "Barley"}
    for r in G.FEED_RECIPES.values():
        need |= set(r)
    for o in G.SLOP_OPTIONS.values():
        need |= set(o)
    snap = {"source": f"{API}/v1/prices (p2p, FLOWER per unit)", "fetched": time.strftime("%Y-%m-%d"),
            "prices": {k: prices[k] for k in sorted(need) if prices.get(k)}}
    # An item with no listing right now comes back empty; keep its last known price
    # instead of treating it as worthless (e.g. Truffle and Pig Bristles, Nov 2026).
    ppath = os.path.join(data_dir, "prices_snapshot.json")
    if os.path.exists(ppath):
        with open(ppath, encoding="utf-8") as fh:
            prev = json.load(fh)
        kept = {k: v for k, v in prev.get("prices", {}).items() if k in need and k not in snap["prices"] and v}
        if kept:
            snap["prices"].update(kept)
            snap["stale"] = {k: prev.get("stale", {}).get(k, prev.get("fetched")) for k in sorted(kept)}
            print(f"  no current price for {', '.join(sorted(kept))}; using the last known one")

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
    files = [(f"farm_{farm_id}.json", farm), ("prices_snapshot.json", snap), ("bounties_observed.json", bounties)]
    # optional extras: a failure here should not stop the simulation
    try:
        files.append(("flowers.json", _flowers(_get(f"{API}/v3/info/flowers"))))
    except Exception as e:  # noqa: BLE001
        print(f"  flowers not refreshed: {e}")
    try:
        files.append(("ticket_orders_history.json",
                      _merge_orders(os.path.join(data_dir, "ticket_orders_history.json"), _get(f"{API}/v3/info/deliveries"))))
    except Exception as e:  # noqa: BLE001
        print(f"  delivery orders not refreshed: {e}")
    try:
        st = _get(f"{API}/v3/tools/season-tickets/farm/{farm_id}")
        tickets = {r["id"]: r["items"].get(TICKET) for r in (raw["raw"]["farm"].get("bounties") or {}).get("requests", [])
                   if TICKET in (r.get("items") or {})}
        board_items = [{"label": b["label"], "category": b["detail"], "tickets": tickets.get(b["id"]), "done": b["done"]}
                       for b in st["weekly"]["board"]]
        files.append(("board_week.json", {"fetched": time.strftime("%Y-%m-%d"), "season": farm["season"],
                                          "double_dates": st.get("double_dates", []), "board": board_items}))
    except Exception as e:  # noqa: BLE001
        print(f"  board not refreshed: {e}")
    if nft_names:
        try:
            files.append(("nft_prices.json", {"fetched": time.strftime("%Y-%m-%d"), "items": nft_prices(nft_names)}))
        except Exception as e:  # noqa: BLE001
            print(f"  NFT prices not refreshed: {e}")
    for name, obj in files:
        with open(os.path.join(data_dir, name), "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=1)
    return farm, snap, bounties
