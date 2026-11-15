# Sim2Find

Built at HackUMass XIV by team Rescuers. Live demo: [sim2find.us](https://sim2find.us)

## Motivation

We wanted to work on missing person cases that go unsolved because the evidence is confusing or there's almost none. That was too big for 36 hours. But while reading, one group kept showing up: older people with dementia who walk away from home and get lost. They don't know they're lost, so they don't call for help or answer when people shout their name. They just keep walking.

A lot is already known about them. In Koester's dementia incident data (ISRID), most keep walking in one direction until something stops them, and 95% of those found within 24 hours were alive, versus 77% of those found later. (These are observed groups, not a causal estimate of search speed.) But when someone goes missing, the search often still starts with a circle around the house. We wanted to turn that knowledge, plus whatever clues come in, into a map that tells a team where to look first.

## Overview

You tell Sim2Find where and when the person was last seen. It simulates thousands of possible walks from that spot on the real Amherst map, based on how people with dementia usually behave. The result is a **heat map, not a pin**: red areas are where most walks ended, so that's where to look first.

When a clue comes in, the map updates. A sighting pulls the heat toward that place. A camera that saw nothing, or an area already searched, cools those spots down. You can type a witness report in plain words and an LLM turns it into a draft clue, but a person always checks it first. The walking itself is done by the agent-based model, not the LLM.

Scope: people with dementia, on foot, in Amherst, MA.

## Methodology

1. **Map:** real Amherst terrain on a 10 m grid, from OpenStreetMap, USGS 3DEP elevation, and NLCD 2021 land cover. Roads have traffic levels; the grid also has buildings, fences, woods, wetland, streams, and low ground.
2. **Walkers:** each one follows rules from Koester's lost-person research on dementia. Most go straight until stuck, 66% cross roads instead of following them, they tend to go downhill, they can stop at buildings, water, or rough terrain, and they can be spotted by the public on busy roads.
3. **Calibration:** 22 rule numbers tuned with Bayesian optimization (Optuna) until the walkers match 16 ISRID statistics: distances, find locations, and elevation change. Every rule is labeled DATA, EXPERT, or ASSUMPTION.
4. **Clues:** clues reweight the walkers, like a particle filter. A sighting also restarts new walkers from the sighting place (`infer.apply_clue`). "Still missing" lowers walkers that spent time on busy roads.
5. **Heat map:** probability per grid cell at a chosen time. 5% of the map always falls back to distance rings around the latest known place, so no area is ever zero.

## Results

### Calibration

The error score against the 16 ISRID statistics dropped from 9.9 (default rules) to 3.8. Distances (25/50/75% = 0.4/1.0/2.5 km vs ISRID 0.3/1.0/2.4), road, structure, and forest finds match. See `reports/calibration_report.md`.

### Benchmark (999 held-out cases)

The true location is placed only from ISRID statistics, never by our own walkers. Score = area searched before reaching the person, most likely cells first. See `reports/benchmark_report.md` and `images/benchmark.png`.

| | Circle search | Sim2Find |
|---|---|---|
| One sighting: total ground searched | 6,611 km² | **2,928 km² (56% less)** |
| One sighting: cases won (excluding ties) | | **83%** |
| One sighting, person > 3 km away (median) | 20.1 km² | **4.4 km²** |
| No clues: total ground searched | 23,126 km² | **19,381 km² (16% less)** |

### Sensitivity Analysis

Each rule number changed by ±50% (DATA values ±20%). Only 3 of 22 numbers move the fit much, and each is pinned by its own ISRID statistic. See `reports/sensitivity_report.md`.

## Limitations

- The demo case (Walter) is fictional.
- The benchmark cases are built from published ISRID statistics, not real case records.
- The map's probabilities are model estimates, not validated for real search decisions.
- The next-best-check suggestion is not implemented yet.

Next step: test it against real solved cases with a search team.

## Repository Structure

```
rescuers/
  data/            committed Amherst grid, calibrated rules, demo case; raw rasters ignored by git
  scripts/         data download and map viewing scripts
  docs/            APP_GUIDE.md: how the app calls the model
  images/          figures for the README and Devpost
  reports/         calibration, benchmark, and sensitivity reports
  rescuers/
    grid.py        builds the 10 m grid (+ road traffic layer)
    sim.py         the walkers (agent-based model)
    infer.py       clues -> walker weights -> heat map
    llm_clues.py   witness text -> draft clues
    calibrate.py   tunes rule numbers to ISRID (Optuna)
    diagnose.py    why walkers stop where they do
    benchmark.py   Sim2Find vs circle search on held-out cases
    sensitivity.py which rule numbers matter
  ui/              local web map, case forms, clue API, and server
  environment.yml  conda environment (full, for rebuilding data and calibration)
  requirements-ui.txt  minimal packages to run the UI
  render.yaml      Render deployment for sim2find.us
```

## Quick Start (Local)

The repo includes `data/grid.npz` and `data/calibrated_params.json`, so you don't need GIS files to try it. From the repo root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-ui.txt
python ui/serve.py --port 8002
```

Open http://127.0.0.1:8002/, use **Autofill demo data** in Case details, then click **Run 5,000 walkers**. Keep the terminal running; Ctrl+C stops it. If port 8002 is busy, pick another port and open the matching URL. An existing Python environment with NumPy and Pillow also works. See [ui/README.md](ui/README.md) for case and clue controls, optional Gemini setup, and troubleshooting.

Note: the UI currently runs 5,000 walkers. The benchmark used 20,000.

## Deployment (sim2find.us)

The root `render.yaml` creates a Python web service on Render's Free plan. It installs only the UI dependencies, serves on Render's assigned `PORT`, and checks `/api/health`. `.python-version` selects Python 3.12. The committed Amherst grid is enough to run the app.

1. Push the deployment files to the GitHub `main` branch.
2. In [Render](https://dashboard.render.com/), choose **New > Blueprint**, connect `srikar1209/rescuers`, select `main`, and apply the `render.yaml` Blueprint. Wait until the service says **Live**.
3. Open the `.onrender.com` URL Render shows. Check `/api/health` for `"grid": true`, then run the **Demo** case and confirm the heat map loads.
4. In the Render service's **Settings > Custom Domains**, add `sim2find.us`. Render also adds `www.sim2find.us` and redirects it to the root domain.
5. In Porkbun's DNS records for `sim2find.us`, set an **A** record with **Host** blank and **Answer** `216.24.57.1`, and a **CNAME** with **Host** `www` and **Answer** set to your service's `.onrender.com` hostname. Remove only conflicting old web or parking records for those two hosts; keep unrelated records such as MX or TXT. Don't change the nameservers.
6. Back in Render, click **Verify**. After DNS resolves, open `https://sim2find.us` and run the demo again.

Render Free services sleep after 15 minutes without traffic, so the first request can take about a minute. Runs live in memory and disappear when the server restarts. Anyone can create runs, so this is a hackathon demo, not an operational search service. Manual clues work without an AI key. To turn on Gemini extraction, add `GEMINI_API_KEY` in Render's **Environment** settings, never in Git; public use can consume your API quota.

## Reproducing the Results

Needs the full conda environment (`environment.yml`) and the source data (see [data/README.md](data/README.md)).

```
python -m rescuers.grid --traffic      # add the road traffic layer to the grid
python -m rescuers.calibrate           # ~20 min, writes calibrated_params.json + report
python -m rescuers.diagnose            # walker diagnostics
python -m rescuers.benchmark 1000      # ~1 h, pip install scikit-image first
python -m rescuers.sensitivity         # ~5 min
python -m rescuers.infer               # demo case, saves infer_preview.png
```

## References

- [Koester, Lost Person Behavior, dementia chapter](https://www.dbs-sar.com/LPB/Dementia.pdf) (ISRID statistics)
- [Koester and Stooksbury (1995)](https://www.dbs-sar.com/SAR_Research/WEM_article.htm), Virginia dementia search incidents
- [Northumbria Police dementia missing-person study](https://tcsr.org.uk/media/2wrpbu4k/2015-a-study-of-people-with-dementia-reported-as-missing-during-2012-and-2013-held-on-the-northumbria-police-integrated-computerised-communications-system.pdf), including a confirmed walking subset
- Data: OpenStreetMap contributors, USGS 3DEP, NLCD 2021
