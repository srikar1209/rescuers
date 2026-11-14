# Rescuers: Lost & Found

**Tell us the clues. We tell you where to look first.**

When a person with dementia goes missing, about 95% found within 24 hours survive; after that, survival drops. Most are found close by, in places searchers walked past. Lost & Found simulates thousands of possible walks of the missing person on real terrain, turns them into a search heat map, and updates that map live as clues come in.

Built at HackUMass XIV by team Rescuers.

## How it works

1. **Map:** real Amherst terrain from OpenStreetMap, USGS elevation and NLCD land cover, on a 10 m grid.
2. **Simulate:** 5,000 walkers start at the last seen point and follow dementia behavior rules calibrated to the International Search and Rescue Incident Database (ISRID).
3. **Heat map:** where walkers end up is where to search first.
4. **Clues:** each clue (sighting, camera with no sighting, area searched) reweights walkers, so the hot zone shrinks.
5. **Next best check:** suggests the spot or camera that would narrow the search most.
6. **LLM:** turns free-text clues into structured input. The walking itself is done by the agent-based model.

Scope: people with dementia on foot.

## Project structure

```
rescuers/
  data/            map data (not in git, see data/README.md)
  scripts/         data download and map viewing scripts
  rescuers/        model code (grid, sim, clues, infer, llm)
  app.py           Streamlit app
  environment.yml  conda environment
```

## Setup

```
conda env create -f environment.yml
conda activate rescuers
python scripts/save_data.py      # OpenStreetMap layers for Amherst + 3 km
python scripts/save_terrain.py   # elevation and land cover
python scripts/view_map.py       # draw the full map
```

## Key sources

- Koester, *Lost Person Behavior*, dementia chapter (ISRID statistics)
- Soule and Goldman (1972) terrain coefficients; Tobler's hiking function
- Hashimoto et al. (2022), agent-based model of lost person behavior, Scientific Reports

The demo case (Walter) is fictional.
