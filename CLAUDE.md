# Sunflower Land Monte Carlo: working rules

## Data sources (what the game allows)
- **Primary: the official Community API** (`api.sunflower-land.com`, key `SFL_API_KEY` in `.env`, header `x-api-key`; VIP + level 50+). About one request per 5 s.
  - Farm (`/community/farms/{id}`): beds, inventory, orders, weekly board (`bounties.requests` / `completed`), season. Live.
  - Prices (`/community/data?type=marketplaceActivity`): one request, floor of every tradeable item, keyed by game ids (`Data/known_ids.json`).
- **Daily run = 2 requests**: farm + market report. Nothing else.
- **Support only**: sfl-manager (fallback when there is no key) and sfl.world (crafting grids → `Data/crafting_recipes.json`, flower/crafting recipes, fish market baits). Never use other third-party sites.
- **Never refresh NFT prices** unless the user asks (`--nft`). With the key, `--nft` reads collectible + wearable floors from the same market report (no extra request; wearable ids in `Data/wearable_ids.json`). The report also gives the FLOWER price in USD. Flower book / delivery catalog only with `--info`.
- Game rules come from the game code (sunflower-land repo); say so when something is server-side and cannot be verified.

## What the user reads daily (keep at the top of the report, in this order)
1. Animal profitability by level.
2. Flower plan.
3. Weekly board: only what is still open — crafting grids (3×3) with FLOWER cost, crustaceans (trap + chum + pot cost + FLOWER per cap), flowers, fish, exotic crops. Animals, Obsidian and giant fruit (daily village help) are left out.
Everything else is secondary.

## Flowers
- 4 beds. Real grow times (`getFlowerTime`). Seasons and the weekly board turn Monday 00:00 UTC (Sunday 21:00 Brasília); a board delivery that cannot be ready by then is dropped and beds go to the next goal.
- Show which seed + which crop/fruit to plant, and every other crop/fruit that gives the same flower. Never show seed stock or seed cost.
- Epic flowers have fixed recipes (sfl.world).

## Player habits (config.json; respect them in every section)
- Trees on 2 h, stones on 4 h: never plan Tree Charge or Speed Miner (`growth.skip_skills`).
- Skill order for the levels the Pizza feast buys is `growth.skill_plan` (the player's own picks first). Feast and skills sit next to each other in the report.
- Checks every 2 h, 06:00–22:00 (`tools`): node refills are worth only what fits between checks (Midas rank 1 gives nothing at these hours).
- Crop items get 100% of their speed (`farmwide.crop_speed_credit`).
- Sheep question: Barn L3 with 11 / 12 / 15 sheep kept forever (`sheep_fixed`).
- Iron is bought, not mined (Rocky Favor makes iron mining a loss).
