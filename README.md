# MonteCarloAnalysisSunflowerLand

Monte Carlo analysis of animal profitability in [Sunflower Land](https://github.com/sunflower-land/sunflower-land):
chickens, cows, sheep and pigs, per level, per skill build and per login schedule, plus a
chapter-ticket projection for the Cave Dwellers chapter.

Open `report/index.html` (or the published artifact) for the interactive report.

## What is simulated

Each run follows one animal from level 0 for 45 days, mirroring the game source:

- Feeding is one click that feeds the favourite food until the next level
  (`ceil(xpUntilReady / foodXp)` feeds); the level-up makes it "ready".
- Claiming produce gives the drop table of the level reached and puts the animal
  to sleep for 24 h × boosts.
- During each sleep it can be petted twice: the first slot opens ⅓ into the
  sleep, the second ⅓ after the first pet. The requested tool (Petting Hand /
  Brush / Music Box) is random, weighted by level. Pets can complete a level on
  their own, so that cycle needs no food.
- At level 15 it keeps producing every full cycle of the last level's XP.

The player logs in on a fixed schedule (1×–4× a day, ±20 min jitter) or
"perfect" (acts the moment any timer opens). That is where most of the
randomness and most of the difference comes from.

Boosts, skills, NFTs and prices come from farm `3621107187220366` (sfl-manager API)
and are stored in `Data/`.

## Run it

Python 3.10+, standard library only.

```bash
python run_analysis.py --runs 1000 --days 45   # writes results/results.json
python build_report.py                          # writes report/index.html
python -m unittest discover -s tests -t .
```

To try another farm, edit `Data/farm_<id>.json` (skills with ranks, placed
collectibles, wearables). To try other skill builds, edit `BUILDS` in
`run_analysis.py`. Refresh prices in `Data/prices_snapshot.json` and coin
bounties in `Data/bounties_observed.json`.

## Layout

| Path | Purpose |
| --- | --- |
| `sflmc/game.py` | Constants copied from the game source (levels, food XP, drops, love weights, skill ranks) |
| `sflmc/farm.py` | Farm profile → sleep time, feed multiplier, yields (mirrors `lib/animals.ts`) |
| `sflmc/sim.py` | Monte Carlo engine and login schedules |
| `sflmc/analysis.py` | Per-level profit, sell timing, percentile bands |
| `report/template.html` | Interactive report (Chart.js); `build_report.py` injects the data |
| `Data/ChickenStats.csv`, `Data/SFLValue.csv` | Original hand-collected chicken data |

## Not modelled

Sickness (rolled server-side), Buckaroo multipliers, shrines, treats, mud and
gem bounties. Coin bounties are valued at the 1:320 coin purchase rate, an upper
bound because coins cannot be sold. Ticket-bounty sizes for Cave Dwellers are
not public until 9 Nov 2026, so the ticket calculator takes them as inputs.
