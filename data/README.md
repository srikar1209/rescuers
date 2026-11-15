# Data

The 10 m Amherst `grid.npz` used by the UI is stored in git. Raw GIS inputs and
downloaded TIFFs are ignored by git. Recreate them from the project root:

```
python scripts/save_data.py      # amherst_full_features.geojson, amherst_boundary.geojson,
                                 # amherst_area_buffered.geojson, amherst_full_walk.graphml
python scripts/save_terrain.py   # amherst_elevation_10m.tif, amherst_landcover_2021.tif
```

`demo_case.json` (fictional demo case "Walter") is kept in git.

The scripts write into this `data/` folder. The map features and walking network
come from OpenStreetMap, elevation from USGS 3DEP, and land cover from NLCD.
These are data layers for a map and simulation, not a pre-rendered Google map.
OpenStreetMap attribution is required when displaying its data.
