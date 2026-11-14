# Draw the full Amherst study map: land cover + hillshade + OpenStreetMap layers + demo case points.
# Run from the project folder:   python view_map.py
# Output: amherst_full_map.png (opens automatically on Mac)

import json
import subprocess
import numpy as np
import geopandas as gpd
import rasterio
from rasterio.warp import reproject, Resampling
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.patches import Patch
from matplotlib.lines import Line2D

D = "data/"

# ---------- load ----------
feat = gpd.read_file(D + "amherst_full_features.geojson")
boundary = gpd.read_file(D + "amherst_boundary.geojson")
area = gpd.read_file(D + "amherst_area_buffered.geojson")
crs = area.estimate_utm_crs()           # meters, so the map is not stretched
feat, boundary, area = feat.to_crs(crs), boundary.to_crs(crs), area.to_crs(crs)

def has(col, values=None, lines_only=False):
    """Select features with a tag. Points (gates, bollards, crossings, lamps) are skipped."""
    if col not in feat.columns:
        return gpd.GeoDataFrame(geometry=[], crs=crs)
    s = feat[col].astype(str)
    m = s.notna() & (s != "nan") & (s != "None")
    if values is not None:
        m &= s.isin(values)
    gtype = feat.geometry.geom_type
    m &= ~gtype.isin(["Point", "MultiPoint"])
    if lines_only:
        m &= gtype.isin(["LineString", "MultiLineString"])
    return feat[m]

xmin, ymin, xmax, ymax = area.total_bounds

def to_grid(path, resampling):
    """Reproject a raster onto a grid matching the map extent (30 m cells)."""
    res = 30
    w, h = int((xmax - xmin) / res), int((ymax - ymin) / res)
    transform = rasterio.transform.from_origin(xmin, ymax, res, res)
    out = np.zeros((h, w), dtype="float32")
    with rasterio.open(path) as src:
        reproject(rasterio.band(src, 1), out, dst_transform=transform, dst_crs=crs,
                  resampling=resampling, dst_nodata=0)
    return out

lc = to_grid(D + "amherst_landcover_2021.tif", Resampling.nearest)
dem = to_grid(D + "amherst_elevation_10m.tif", Resampling.bilinear)

# ---------- land cover colors (simplified groups) ----------
groups = {  # NLCD code -> group id
    11: 1, 21: 2, 22: 3, 23: 3, 24: 4, 31: 5,
    41: 6, 42: 6, 43: 6, 52: 7, 71: 8, 81: 8, 82: 9, 90: 10, 95: 10,
}
g = np.zeros_like(lc, dtype=int)
for code, gid in groups.items():
    g[lc == code] = gid
colors = ["#ffffff", "#9ecae1", "#e8e3d3", "#d9c7b0", "#c9a98a", "#d4d4d4",
          "#9bc48a", "#c7d97a", "#ecebb0", "#e3d48a", "#8ec9b3"]
labels = ["", "Water", "Developed, open (lawns)", "Developed, low/med", "Developed, high",
          "Barren", "Forest", "Shrub / brush", "Grass / pasture", "Crops", "Wetland"]
cmap = ListedColormap(colors)
norm = BoundaryNorm(np.arange(-0.5, len(colors) + 0.5), cmap.N)

# ---------- hillshade from elevation ----------
dem_f = np.where(dem > 0, dem, np.nan)
gy, gx = np.gradient(np.nan_to_num(dem_f, nan=np.nanmean(dem_f)), 30)
slope = np.pi / 2 - np.arctan(np.hypot(gx, gy))
aspect = np.arctan2(-gx, gy)
az, alt = np.radians(315), np.radians(45)
shade = np.sin(alt) * np.sin(slope) + np.cos(alt) * np.cos(slope) * np.cos(az - aspect)

# ---------- draw ----------
fig, ax = plt.subplots(figsize=(16, 16), dpi=150)
extent = (xmin, xmax, ymin, ymax)
ax.imshow(g, cmap=cmap, norm=norm, extent=extent, interpolation="nearest", zorder=1)
ax.imshow(shade, cmap="gray", alpha=0.25, extent=extent, zorder=2)

# OSM layers
has("natural", ["wood"]).plot(ax=ax, color="#5f9e4f", alpha=0.5, linewidth=0, zorder=3)
has("landuse", ["forest"]).plot(ax=ax, color="#5f9e4f", alpha=0.5, linewidth=0, zorder=3)
has("natural", ["scrub", "heath"]).plot(ax=ax, color="#a8b545", alpha=0.7, linewidth=0, zorder=3)
has("natural", ["wetland"]).plot(ax=ax, color="#4fa38a", alpha=0.6, linewidth=0, zorder=3)
has("landuse", ["cemetery"]).plot(ax=ax, color="#8e6bbf", alpha=0.8, linewidth=0, zorder=4)
has("natural", ["water"]).plot(ax=ax, color="#3d85c6", linewidth=0, zorder=4)
has("waterway", lines_only=True).plot(ax=ax, color="#3d85c6", linewidth=0.8, zorder=5)
has("building").plot(ax=ax, color="#444444", linewidth=0, zorder=6)
roads = has("highway", lines_only=True)
major = roads[roads["highway"].astype(str).isin(
    ["motorway", "trunk", "primary", "secondary", "tertiary"])]
minor = roads.drop(major.index)
minor.plot(ax=ax, color="#ffffff", linewidth=0.4, zorder=7)
major.plot(ax=ax, color="#f2a541", linewidth=1.6, zorder=8)
has("barrier", lines_only=True).plot(ax=ax, color="#c0392b", linewidth=0.8, zorder=9)

boundary.boundary.plot(ax=ax, color="black", linewidth=1.5, linestyle="--", zorder=10)

# demo case points
try:
    case = json.load(open(D + "demo_case.json"))
    pts = {
        "Start (care home)": (case["start"]["lon"], case["start"]["lat"], "#d62728", "*"),
        "Hidden truth (bush)": (case["hidden_truth"]["lon"], case["hidden_truth"]["lat"], "#000000", "X"),
        "Decoy (cemetery)": (case["decoy"]["lon"], case["decoy"]["lat"], "#8e6bbf", "D"),
    }
    for name, (lon, lat, c, m) in pts.items():
        p = gpd.GeoSeries(gpd.points_from_xy([lon], [lat]), crs=4326).to_crs(crs)
        ax.scatter(p.x, p.y, s=260, c=c, marker=m, edgecolors="white", linewidths=1.5,
                   zorder=12, label=name)
except FileNotFoundError:
    print("WARNING: data/demo_case.json not found, so Walter's points are not shown.")

ax.set_xlim(xmin, xmax); ax.set_ylim(ymin, ymax)
ax.set_xticks([]); ax.set_yticks([])
ax.set_title("Amherst study area: land cover, terrain and OpenStreetMap layers", fontsize=18)

legend = [Patch(color=colors[i], label=labels[i]) for i in range(1, len(colors))]
legend += [
    Line2D([0], [0], color="#f2a541", lw=2, label="Major road"),
    Line2D([0], [0], color="#ffffff", lw=1, label="Minor road / path"),
    Line2D([0], [0], color="#3d85c6", lw=1.5, label="Stream / river"),
    Patch(color="#444444", label="Building"),
    Line2D([0], [0], color="#c0392b", lw=1, label="Fence / wall / hedge"),
    Patch(color="#8e6bbf", label="Cemetery"),
    Line2D([0], [0], color="black", lw=1.5, ls="--", label="Amherst town line"),
]
h, l = ax.get_legend_handles_labels()
ax.legend(handles=legend + h, loc="lower left", fontsize=10, framealpha=0.9)

# 1 km scale bar
sx, sy = xmax - 2500, ymin + 600
ax.plot([sx, sx + 1000], [sy, sy], color="black", lw=4, zorder=13)
ax.text(sx + 500, sy + 200, "1 km", ha="center", fontsize=12, zorder=13)

plt.tight_layout()
plt.savefig("amherst_full_map.png")
print("Saved amherst_full_map.png")
subprocess.run(["open", "amherst_full_map.png"])
