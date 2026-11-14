# App guide (for the web app teammate)

## Setup
```
git clone <repo url>
cd rescuers
conda env create -f environment.yml
conda activate rescuers
python -m rescuers.infer        # test: should print the 4 clue stages and save infer_preview.png
```
Always run from the repo root (the folder with `data/`).

## Files you need (all in git)
- `rescuers/grid.py`   map grid (10 m cells), lat/lon <-> cell
- `rescuers/sim.py`    walkers (the ABM)
- `rescuers/infer.py`  clues -> weights -> heat map
- `data/grid.npz`      the Amherst map, already built
- `data/calibrated_params.json`  tuned walker rules (updated by calibration, no code change needed)
- `data/demo_case.json`          demo case "Walter" (start, 3 clues, hidden truth)

You do NOT need the big raw files (tif, geojson). Only grid.npz.

## The whole pipeline
```python
import numpy as np
from rescuers import grid as G, sim, infer

grid = G.load()                                   # load once, cache it (st.cache_resource)
start = G.latlon_to_cell(grid, lat, lon)          # last seen place
walks = sim.simulate(grid, start, n=20000, minutes=240,
                     params=sim.load_params())    # about 10-30 s, cache it

w = np.ones(20000)
for clue in clues:                                # same format as demo_case.json
    w = w * infer.clue_likelihood(grid, walks, clue, "18:30")   # "18:30" = last seen time
    if infer.ess(w) < 20000 / 2:
        walks, w = infer.resample(walks, w, np.random.default_rng(0))

heat = infer.heatmap(grid, walks, w, minute=150)  # 2D array, sums to 1. minute = minutes after last seen
```

## Drawing on a real map
```python
rows, cols = np.nonzero(heat > 0)
lat, lon = G.cell_to_latlon(grid, row, col)       # one cell -> lat/lon
```
Tip: show only the hottest cells holding 80% of the probability (see `save_preview` in infer.py).

## Clue formats
```json
{"id": 1, "type": "sighting", "lat": 42.37094, "lon": -72.53466, "time": "18:45"}
{"id": 2, "type": "camera_negative", "lat": 42.37198, "lon": -72.53340, "window": ["18:30", "19:30"]}
{"id": 3, "type": "area_searched", "lat": 42.37266, "lon": -72.55031, "radius_m": 150, "time": "21:00"}
```
The LLM part only turns witness text into one of these dicts.

## Good numbers for the demo
- No clues: 0.29 km2 to search before reaching the truth
- After the sighting: 0.04 km2 (7x smaller)

## Do not change
grid.py, sim.py, infer.py, calibrate.py. Srikar is working on these. Ask first.
