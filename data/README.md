# Data

Large files are not stored in git. Recreate them from the project root:

```
python scripts/save_data.py      # amherst_full_features.geojson, amherst_boundary.geojson,
                                 # amherst_area_buffered.geojson, amherst_full_walk.graphml
python scripts/save_terrain.py   # amherst_elevation_10m.tif, amherst_landcover_2021.tif
```

`demo_case.json` (fictional demo case "Walter") is kept in git.
