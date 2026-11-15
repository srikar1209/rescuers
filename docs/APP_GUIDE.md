# App guide (for the web app teammate)

## Setup
```
git pull
conda activate rescuers            # or lostfound312
pip install anthropic              # for the LLM step
export ANTHROPIC_API_KEY=...       # never commit this
python -m rescuers.infer           # test: prints 5 stages, saves infer_preview.png
```
Always run from the repo root (the folder with `data/`).

## Files
- `rescuers/grid.py`       map grid (10 m cells), lat/lon <-> cell
- `rescuers/sim.py`        walkers (the ABM)
- `rescuers/infer.py`      clues -> weights -> heat map
- `rescuers/llm_clues.py`  witness text -> clues (Claude Haiku)
- `data/grid.npz`          Amherst map, includes the road traffic layer
- `data/calibrated_params.json`  tuned walker rules (updated by calibration, no code change needed)
- `data/demo_case.json`    demo case "Walter"

## Inputs to collect in the UI
Required: last seen place (lat, lon), last seen time, current time.
Optional: direction he left in, a goal place (old home, old job, church).
Info only (NOT used by the model): name, age, photo, dementia severity.
Clues: free text from witnesses (LLM), or added by hand on the map.

## The whole pipeline
```python
import numpy as np
from rescuers import grid as G, sim, infer, llm_clues

grid = G.load()                                    # load once, cache it (st.cache_resource)

# 1. witness text -> clues (show each clue + its quote; let the user fix the place on the map)
raw = llm_clues.extract_clues(text, last_seen="18:30", now="21:00", description="79, gray coat")
clues, profile = llm_clues.to_model_clues(raw)     # clues with needs_location=True: ask the user

# 2. walkers. spotting=False: he is still missing, so "not seen on a road" is a clue (step 3)
start = G.latlon_to_cell(grid, lat, lon)
goal = G.latlon_to_cell(grid, g_lat, g_lon) if have_goal else None
walks = sim.simulate(grid, start, n=20000, minutes=240, params=sim.load_params(),
                     heading=profile["heading"], goal=goal, spotting=False)   # 10-30 s, cache it

# 3. clues -> walkers + weights. One call per clue, in time order.
#    Sightings restart walkers from the sighting place; other clues reweight.
#    ALWAYS add not_reported with the current time, last.
w = np.ones(len(walks.end))
center = start                                     # latest known place
for clue in clues + [{"type": "not_reported", "time": "21:00"}]:
    walks, w = infer.apply_clue(grid, walks, w, clue, "18:30")   # "18:30" = last seen time
    if clue["type"] == "sighting":
        center = G.latlon_to_cell(grid, clue["lat"], clue["lon"])

# 4. heat map at "now": minute = minutes after last seen (21:00 - 18:30 = 150)
#    center = latest sighting (or last seen); 5% of the map falls back to rings around it
heat = infer.heatmap(grid, walks, w, minute=150, center=center)   # 2D array, sums to 1
```
`minutes` in simulate must be larger than (now - last seen). Max useful: 720.

## Drawing on a real map
```python
lat, lon = G.cell_to_latlon(grid, row, col)        # one cell -> lat/lon
```
Show only the hottest cells holding 80% of the probability (see `save_preview` in infer.py).

## Clue formats
```json
{"id": 1, "type": "sighting", "lat": 42.37094, "lon": -72.53466, "time": "18:45", "reliability": 0.7}
{"id": 2, "type": "camera_negative", "lat": 42.37198, "lon": -72.53340, "window": ["18:30", "19:30"]}
{"id": 3, "type": "area_searched", "lat": 42.37266, "lon": -72.55031, "radius_m": 150, "time": "21:00"}
{"type": "not_reported", "time": "21:00"}
```
reliability: high 0.9, medium 0.7, low 0.4 (the LLM sets it; default 0.8).

## Speed
Simulate once per case (10-30 s, cache it). Most clues take about 1 s.
A sighting runs one extra simulation (10,000 walkers from the sighting place), so
it takes about as long as the first run: show a spinner. Redrawing the map is fast.

## Demo numbers (current calibration)
- No clues: 0.12 km2 to search before reaching the truth
- After the sighting: 0.002 km2 (top 0.3% of probability)

## Benchmark (999 test cases, see benchmark_report.md)
- One sighting: our model wins 83% of cases, 56% less total ground than circles
  around the sighting; truth > 3 km away: 4.4 vs 20.1 km2 median.
- No clues: 16% less total ground than circle search.

## Do not change
grid.py, sim.py, infer.py, calibrate.py, diagnose.py, benchmark.py. Srikar is working on these. Ask first.
