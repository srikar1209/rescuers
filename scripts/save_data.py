# Download OpenStreetMap layers for ALL of Amherst plus a 3 km buffer, and save them to files.
# Run with:  python save_data.py
# Takes a few minutes. If the server is busy, it waits and retries on its own.

import time
import osmnx as ox

ox.settings.timeout = 300           # give the server more time for a big area
ox.settings.requests_timeout = 300

PLACE = "Amherst, Massachusetts, USA"
BUFFER_M = 3000

TAGS = {
    "highway": True,                  # roads, paths, sidewalks
    "waterway": True,                 # streams, rivers, ditches, drains
    "natural": ["wood", "scrub", "water", "wetland", "heath", "grassland", "tree_row"],
    "landuse": ["forest", "cemetery", "grass", "meadow", "farmland", "orchard", "construction"],
    "leisure": ["park", "golf_course", "nature_reserve"],
    "building": True,
    "barrier": True,                  # fences, walls, hedges
    "amenity": ["parking"],           # parking lots (open, often behind buildings)
}


def with_retry(fn, label, tries=5, wait=30):
    """Run fn(); if the server is busy, wait and try again (30s, 60s, 120s...)."""
    for attempt in range(1, tries + 1):
        try:
            return fn()
        except Exception as e:
            if attempt == tries:
                raise
            print(f"{label}: attempt {attempt} failed ({type(e).__name__}). Waiting {wait}s and retrying...")
            time.sleep(wait)
            wait *= 2


# 1. Town boundary + 3 km buffer
print("Getting Amherst town boundary...")
boundary = with_retry(lambda: ox.geocode_to_gdf(PLACE), "boundary")
utm = boundary.estimate_utm_crs()
area = boundary.to_crs(utm).buffer(BUFFER_M).to_crs(4326)
area_gdf = boundary.copy()
area_gdf["geometry"] = area.values
boundary.to_file("amherst_boundary.geojson", driver="GeoJSON")
area_gdf.to_file("amherst_area_buffered.geojson", driver="GeoJSON")
area_km2 = area.to_crs(utm).area.iloc[0] / 1e6
print(f"Study area: Amherst + {BUFFER_M/1000:.0f} km buffer = {area_km2:.0f} km2")

# 2. Map features
print("Downloading map features... (several minutes)")
polygon = area.iloc[0]
gdf = with_retry(lambda: ox.features_from_polygon(polygon, tags=TAGS), "features")

keep = [c for c in ["highway", "waterway", "natural", "landuse", "leisure",
                    "building", "barrier", "amenity", "name"] if c in gdf.columns]
gdf = gdf[keep + ["geometry"]].reset_index(drop=True)
for c in keep:
    gdf[c] = gdf[c].astype(str)

gdf.to_file("amherst_full_features.geojson", driver="GeoJSON")
print(f"Saved {len(gdf)} features to amherst_full_features.geojson")
for c in keep:
    if c != "name":
        print(f"  {c}: {(gdf[c] != 'nan').sum()}")

# 3. Walking network (optional; skipped if the server stays busy)
print("Downloading walking network (optional)...")
try:
    G = with_retry(lambda: ox.graph_from_polygon(polygon, network_type="walk"), "walk network", tries=3)
    ox.save_graphml(G, "amherst_full_walk.graphml")
    print("Saved walking network to amherst_full_walk.graphml")
except Exception as e:
    print(f"Skipped walking network ({type(e).__name__}). Not needed for the grid model.")

print("Done.")
