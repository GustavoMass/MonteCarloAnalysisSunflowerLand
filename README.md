# MonteCarloAnalysisSunflowerLand

Monte Carlo analysis of animal profitability in [Sunflower Land](https://github.com/sunflower-land/sunflower-land):
chickens, cows, sheep and pigs, level by level and skill build by skill build, plus a full-chapter
simulation of selling to the bounty board and a Duende Cap (chapter ticket) projection.

## Run it yourself

1. Install [Python 3.10+](https://www.python.org/downloads/) (tick "Add python.exe to PATH"). No packages needed.
2. Double-click `run.bat` (Windows), or in a terminal:

```bash
python run.py
```

That pulls your farm, the bounty board and P2P prices from the public sfl-manager API, runs the
simulation (about 2 minutes) and opens `report/index.html` in your browser.

```bash
python run.py --offline   # reuse the data already in Data/
python run.py --no-open   # don't open the browser
python -m unittest discover -s tests -t .
```

## Change the assumptions

Everything you may want to tweak is in `config.json`:

| Key | What it is |
| --- | --- |
| `farm_id` | Your farm |
| `sell_fee` | Marketplace cut on produce (0.125 = VIP on desert island) |
| `builds` | Skill builds to compare: skills to remove and `{skill: rank}` to add, on top of your live skills |
| `keep_animals` | Animals you never sell (default: Pig) |
| `stop_feeding_at` | Stop feeding at this level and wait for a bounty (`"auto"` = highest level boards ask) |
| `compare_barn_levels`, `building_levels` | Building levels to simulate |
| `board_per_week` | Coin / gem / ticket bounties per week per building level |
| `ticket_base` | Base Duende Caps per animal ticket bounty (guess until the board shows them; the live board overrides it) |
| `ticket_npcs` | Each ticket NPC's base reward and how often you deliver (`freq`, share of days) |
| `board_bonus` | Whether you sell the whole non-animal board for +100 a week |

## What is simulated

Rules follow the game source (`src/features/game`):

- Feeding is one click that feeds the favourite food until the next level; the level-up makes it ready.
- Claiming gives the drop table of the level reached and puts the animal to sleep (24 h × boosts).
- During each sleep it can be petted twice: first slot at ⅓ of the sleep, second ⅓ after the first pet.
  The tool asked for is random, weighted by level. Petting only needs the animal asleep, so a
  "ready" animal still takes pets and the XP carries over to the next level.
- At level 15 it produces again every full cycle of the last level's XP.
- You pet every slot the moment it opens and feed on waking.

**Per-level bars:** one animal from level 0, many runs; distribution of profit per day, running total
and days to reach each level.

**Chapter herd:** a full building for 12 weeks. Each week a new board (bounty levels drawn from what
boards have asked); every awake animal that meets an open request is sold (hardest request first) and
replaced with a level-0 animal.

## Layout

| Path | Purpose |
| --- | --- |
| `run.py`, `run.bat` | One-command runner |
| `config.json` | Your assumptions |
| `sflmc/game.py` | Constants copied from the game source |
| `sflmc/farm.py` | Farm → sleep time, feed multiplier, yields (mirrors `lib/animals.ts`) |
| `sflmc/sim.py` | One animal, pet by pet |
| `sflmc/herd.py` | A building over the chapter with weekly bounty boards |
| `sflmc/fetch.py` | sfl-manager API → `Data/` |
| `sflmc/analysis.py` | Percentiles and totals |
| `report/template.html` | Report (Chart.js); `build_report.py` fills in the data |

## Not modelled

Sickness (rolled server-side), Buckaroo multipliers, shrines, treats, mud, chores, gem value.
Coins are reported as coins.
