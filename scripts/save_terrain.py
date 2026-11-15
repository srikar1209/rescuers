# Download land cover (NLCD, 30 m) and elevation (USGS 3DEP, 10 m) for the Amherst study area.
# First install once:   pip install py3dep pygeohydro
# Then run:             python save_terrain.py
# Needs amherst_area_buffered.geojson (made by save_data.py) in the same folder.

import geopandas as gpd
import py3dep
import pygeohydro as gh
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

area = gpd.read_file(DATA / "amherst_area_buffered.geojson").to_crs(4326)
geom = area.geometry.iloc[0]

# 1. Elevation, 10 m cells (for downhill rule and finding drainages)
print("Downloading elevation (10 m)...")
dem = py3dep.get_dem(geom, resolution=10, crs=4326)
dem.rio.to_raster(DATA / "amherst_elevation_10m.tif")
print(f"Saved amherst_elevation_10m.tif  shape={dem.shape}  "
      f"min={float(dem.min()):.0f} m  max={float(dem.max()):.0f} m")

# 2. Land cover, 30 m cells (fills gaps in OpenStreetMap: forest, shrub, wetland, grass...)
print("Downloading NLCD land cover (30 m)...")
lc = gh.nlcd_bygeom(area, resolution=30, years={"cover": [2021]})
cover = lc[list(lc.keys())[0]]["cover_2021"]
cover.rio.to_raster(DATA / "amherst_landcover_2021.tif")
print("Saved amherst_landcover_2021.tif")

# Show what land cover classes are in the area
names = {
    11: "Open water", 21: "Developed, open space", 22: "Developed, low",
    23: "Developed, medium", 24: "Developed, high", 31: "Barren",
    41: "Deciduous forest", 42: "Evergreen forest", 43: "Mixed forest",
    52: "Shrub/scrub", 71: "Grassland", 81: "Pasture/hay", 82: "Crops",
    90: "Woody wetland", 95: "Herbaceous wetland",
}
vals = cover.values.ravel()
vals = vals[(vals > 0) & (vals < 255)]
total = len(vals)
print("\nLand cover share of area:")
for code in sorted(set(vals.tolist())):
    share = (vals == code).sum() / total * 100
    print(f"  {code:>3} {names.get(int(code), 'other'):<25} {share:5.1f}%")

print("\nDone.")
