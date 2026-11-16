"""Pull your farm (official Sunflower Land Community API when a key is set, else
sfl-manager) and, on request, P2P prices; boil them down to what the simulator needs. Writes Data/farm_<id>.json,
Data/prices_snapshot.json and Data/bounties_observed.json."""
import gzip
import json
import os
import time
import urllib.error
import urllib.request

from . import game as G

API = "https://sfl-manager.com/api"
OFFICIAL_BASE = "https://api.sunflower-land.com"
OFFICIAL = f"{OFFICIAL_BASE}/community/farms"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = {"User-Agent": "Mozilla/5.0 (MonteCarloAnalysisSunflowerLand)"}
TICKET = "Duende Cap"  # Cave Dwellers chapter ticket


CALLS = []   # every request this run, to keep the load on sfl-manager visible


def _get(url, tries=4):
    """GET JSON, backing off politely when the API rate-limits (HTTP 429)."""
    CALLS.append(url)
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code != 429 or i == tries - 1:
                raise
            time.sleep(5 * (i + 1))


def _api_key():
    """Community API key: env SFL_API_KEY, else the SFL_API_KEY line in .env (name in any case).
    Never printed or written anywhere else."""
    if os.environ.get("SFL_API_KEY"):
        return os.environ["SFL_API_KEY"].strip()
    path = os.path.join(ROOT, ".env")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                k, _, v = line.partition("=")
                if k.strip().upper() == "SFL_API_KEY" and v.strip():
                    return v.strip().strip("\"'")
    return None


def _official_raw(farm_id, key):
    """Live farm from the official Community API (1 request), in sfl-manager's wrapper shape."""
    CALLS.append(f"{OFFICIAL}/{farm_id}")
    req = urllib.request.Request(f"{OFFICIAL}/{farm_id}",
                                 headers={**UA, "x-api-key": key, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
    d = json.loads(body.decode("utf-8"))
    return {"raw": {"farm": d["farm"]}, "fetched_at": time.time() * 1000, "updated_at": d.get("updatedAt")}


def _official_get(path, key):
    CALLS.append(f"{OFFICIAL_BASE}{path}")
    req = urllib.request.Request(f"{OFFICIAL_BASE}{path}", headers={**UA, "x-api-key": key, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            body = gzip.decompress(body)
    return json.loads(body.decode("utf-8"))


def _official_market(key):
    """Today's marketplace report (1 request): floor/latest sale in FLOWER of every tradeable item,
    keyed "<kind>-<game id>", plus the FLOWER price in USD."""
    d = _official_get("/community/data?type=marketplaceActivity", key)["data"]
    rep = d["reports"]
    day = max(rep)
    return rep[day]["items"], day, d.get("flowerPrice")


def _ids(data_dir, name):
    with open(os.path.join(data_dir, name), encoding="utf-8") as fh:
        return {v: k for k, v in json.load(fh)["ids"].items()}


def _official_prices(data_dir, items):
    """Collectible (resource) prices from the report, by name (Data/known_ids.json)."""
    by_id = _ids(data_dir, "known_ids.json")
    out = {}
    for k, v in items.items():
        kind, _, num = k.partition("-")
        name = by_id.get(int(num)) if kind == "collectibles" and num.isdigit() else None
        price = v.get("floor") or v.get("latestSale")
        if name and price:
            out[name] = price
    return out


def official_nfts(data_dir, items, day, usd):
    """NFT floors (collectibles + wearables) from the same report: no extra request. Only on --nft."""
    ids = {"collectibles": _ids(data_dir, "known_ids.json"), "wearables": _ids(data_dir, "wearable_ids.json")}
    out = {}
    for k, v in items.items():
        kind, _, num = k.partition("-")
        name = ids.get(kind, {}).get(int(num)) if num.isdigit() else None
        price = v.get("floor") or v.get("latestSale")
        if name and price:
            out[name] = {"price": price, "kind": kind[:-1], "listings": v.get("listingCount", 0),
                         "last_sale": v.get("latestSale"), "tradable": True}
    return {"fetched": day, "source": "official marketplace report", "flower_usd": usd, "items": out}


def _official_board(raw, data_dir):
    """This week's mega bounty board from bounties.requests (animals are handled by parse_board)."""
    b = raw["raw"]["farm"].get("bounties") or {}
    done = {c["id"] for c in b.get("completed", [])}
    try:
        with open(os.path.join(data_dir, "flowers.json"), encoding="utf-8") as fh:
            flowers = set(json.load(fh)["flowers"])
    except Exception:  # noqa: BLE001
        flowers = set()
    return [{"label": r["name"], "category": "Flowers" if r["name"] in flowers else "Other",
             "tickets": (r.get("items") or {}).get(TICKET), "done": r["id"] in done}
            for r in b.get("requests", []) if r["name"] not in G.ANIMALS]


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
        "experience": float((f.get("bumpkin") or {}).get("experience", 0) or 0),
        # open NPC chores ("Grow Blue Pansy 6 times") and open delivery orders, for the flower planner
        "chores": [{"npc": npc, "name": c.get("name"), "initial": c.get("initialProgress", 0), "reward": c.get("reward")}
                   for npc, c in ((f.get("choreBoard") or {}).get("chores") or {}).items() if not c.get("completedAt")],
        "orders": [{"from": o.get("from"), "items": o.get("items") or {}, "reward": o.get("reward") or {},
                    "ready_at": o.get("readyAt")}
                   for o in ((f.get("delivery") or {}).get("orders") or []) if not o.get("completedAt")],
        "inventory": {k: float(v) for k, v in inv.items()},
        "flower_beds": [{"name": (b.get("flower") or {}).get("name"), "planted_at": (b.get("flower") or {}).get("plantedAt"),
                         "boosted_ms": (b.get("flower") or {}).get("boostedTime", 0),
                         "base_duration_ms": (b.get("flower") or {}).get("baseDurationMs")}
                        for b in ((f.get("flowers") or {}).get("flowerBeds") or {}).values()],
        "season": (f.get("season") or {}).get("season"),
        "season_started": (f.get("season") or {}).get("startedAt"),
        # lifetime counters (trees chopped, stone mined, ...) and farm age, for per-week rates
        "activity": {k: v for k, v in (f.get("farmActivity") or {}).items() if isinstance(v, (int, float))},
        "plots": len(f.get("crops") or {}),
        # faction pet fed streak of the latest week (x1.5 Bumpkin XP the week after a streak of 8+)
        "pet_streak": next(((h.get("collectivePet") or {}).get("streak", 0)
                            for _, h in sorted(((f.get("faction") or {}).get("history") or {}).items(), reverse=True)), 0),
        "weeks_played": ((raw.get("fetched_at") or time.time() * 1000) - (f.get("createdAt") or 0)) / 6.048e8,
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
        CALLS.append(f"POST {API}/v3/land/{farm_id}/refresh")
        req = urllib.request.Request(f"{API}/v3/land/{farm_id}/refresh", data=b"", headers=UA, method="POST")
        with urllib.request.urlopen(req, timeout=60) as r:
            r.read()
    except Exception as e:  # noqa: BLE001
        print(f"  live reload not available ({e}); using sfl-manager's cached copy")


# How old (hours) the farm may be before it is fetched again.
MAX_AGE = {"land": 0.25}
# What a plain run fetches: only your farm (beds, inventory, orders) and the weekly board.
# Everything else is fetched only when asked for by name (run.py --prices / --nft / --info).
EXTRAS = ("prices", "nft", "info")


def _age_h(path):
    return (time.time() - os.path.getmtime(path)) / 3600 if os.path.exists(path) else 1e9


def refresh(data_dir, farm_id, nft_names=(), max_age=None, extras=()):
    """Daily refresh. With SFL_API_KEY: farm + today's market prices from the official API (2 calls).
    Without: farm + weekly board from sfl-manager (3 calls). extras adds "prices" (1 call),
    "info" (flower book + delivery catalog, 2 calls) or "nft" (official key: NFT floors from the same
    market report, no extra call; without a key: one sfl-manager call per NFT season, ~15)."""
    age = {**MAX_AGE, **(max_age or {})}
    extras = set(extras)
    del CALLS[:]
    if _age_h(os.path.join(data_dir, f"farm_{farm_id}.json")) < age["land"] and not extras:
        print(f"  farm fetched under {age['land'] * 60:.0f} min ago; not calling sfl-manager")
        return
    key = _api_key()
    if key:
        raw = _official_raw(farm_id, key)
    else:
        _ask_live_copy(farm_id)
        raw = _get(f"{API}/v3/land/{farm_id}")
    raw["official"] = bool(key)
    farm = parse_farm(raw, farm_id)
    board = parse_board(raw)
    files = []
    if key:                                          # daily: today's market report, 1 more request
        try:
            time.sleep(5)                            # Community API: about one request per 5 s
            items, day, usd = _official_market(key)
            snap = _price_snapshot(data_dir, _official_prices(data_dir, items), day, extra=_board_items(data_dir))
            snap["flower_usd"] = usd
            files.append(("prices_snapshot.json", snap))
            if "nft" in extras:                      # same report: no extra request
                files.append(("nft_prices.json", official_nfts(data_dir, items, day, usd)))
        except Exception as e:  # noqa: BLE001
            print(f"  prices not refreshed: {e}")
    elif "prices" in extras:
        files.append(("prices_snapshot.json", _price_snapshot(data_dir, _get(f"{API}/v1/prices")["p2p"])))

    _write(data_dir, files + _daily_files(data_dir, farm_id, raw, farm, board, nft_names, extras))
    print(f"  {len(CALLS)} requests this run: " + ", ".join(
        c.replace(API, "sfl-manager").replace(OFFICIAL, "official").replace(str(farm_id), "<farm>") for c in CALLS))
    return farm


def _write(data_dir, files):
    os.makedirs(data_dir, exist_ok=True)
    for name, obj in files:
        with open(os.path.join(data_dir, name), "w", encoding="utf-8") as fh:
            json.dump(obj, fh, indent=1)


def _board_items(data_dir):
    """Names whose price the weekly-board tab needs: crafting grids and crustacean chums."""
    names = set()
    try:
        with open(os.path.join(data_dir, "crafting_recipes.json"), encoding="utf-8") as fh:
            for k, cells in json.load(fh)["grids"].items():
                names |= {k} | {c for c in cells if c}
    except Exception:  # noqa: BLE001
        pass
    return (names | {c for t in G.CRUSTACEAN_CHUMS.values() for c in t} | set(G.EXOTIC_TICKETS)
            | {k for r in G.TRAP_RECIPES.values() for k in r["items"]})


def _price_snapshot(data_dir, prices, day=None, extra=()):
    need = {"Egg", "Feather", "Milk", "Leather", "Wool", "Merino Wool", "Truffle", "Pig Bristles",
            "Wood", "Stone", "Iron", "Gold", "Crimstone", "Oil", "Mud", "Salt", "Honey",
            "Apple", "Blueberry", "Orange", "Lemon", "Tomato", "Potato", "Pumpkin", "Carrot", "Cabbage", "Soybean",
            "Zucchini", "Yam", "Broccoli", "Rhubarb", "Corn", "Onion", "Turnip", "Wheat", "Artichoke", "Parsnip",
            "Sunflower", "Beetroot", "Cauliflower", "Radish", "Parsnip", "Kale", "Eggplant", "Blueberry",
            "Banana", "Apple", "Rhubarb", "Pepper", "Artichoke", "Onion", "Barley", "Obsidian"}
    for r in G.FEED_RECIPES.values():
        need |= set(r)
    for o in G.SLOP_OPTIONS.values():
        need |= set(o)
    need |= set(extra)
    try:
        with open(os.path.join(data_dir, "flowers.json"), encoding="utf-8") as fh:
            need |= set(json.load(fh)["flowers"])
    except Exception:  # noqa: BLE001
        pass
    src = "official marketplace report (floor, FLOWER per unit)" if day else f"{API}/v1/prices (p2p, FLOWER per unit)"
    snap = {"source": src, "fetched": day or time.strftime("%Y-%m-%d"),
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
    return snap


def _daily_files(data_dir, farm_id, raw, farm, board, nft_names, extras):
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

    files = [(f"farm_{farm_id}.json", farm), ("bounties_observed.json", bounties)]
    # optional extras: a failure here should not stop the simulation
    if "info" in extras:
        try:
            files.append(("flowers.json", _flowers(_get(f"{API}/v3/info/flowers"))))
        except Exception as e:  # noqa: BLE001
            print(f"  flowers not refreshed: {e}")
        try:
            files.append(("ticket_orders_history.json",
                          _merge_orders(os.path.join(data_dir, "ticket_orders_history.json"), _get(f"{API}/v3/info/deliveries"))))
        except Exception as e:  # noqa: BLE001
            print(f"  delivery orders not refreshed: {e}")
    if raw.get("official"):
        files.append(("board_week.json", {"fetched": time.strftime("%Y-%m-%d"), "season": farm["season"],
                                          "board": _official_board(raw, data_dir)}))
        return files
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
    if nft_names and "nft" in extras:
        try:
            files.append(("nft_prices.json", {"fetched": time.strftime("%Y-%m-%d"), "items": nft_prices(nft_names)}))
        except Exception as e:  # noqa: BLE001
            print(f"  NFT prices not refreshed: {e}")
    return files
