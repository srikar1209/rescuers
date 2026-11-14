"""
Build the 10 m terrain grid the walkers move on.

Run from the repo root:   python -m rescuers.grid
Output: data/grid.npz and grid_preview.png

Layers in the grid (one value per 10 m cell):
  cls        terrain class (see CLASSES)
  speed      walking speed factor, 1.0 = paved road (Soule & Goldman); 0 = cannot enter
  dem        elevation in meters (USGS 3DEP)
  slope      slope in degrees
  tpi        low-ground index: cell height minus the 210 m neighborhood mean
             (negative = lower than surroundings = drainage, ditch, valley)
  dist_road  meters to the nearest road or path
"""

import json
import numpy as np
import geopandas as gpd
import rasterio
from rasterio import features
from rasterio.transform import from_origin, rowcol
from rasterio.warp import reproject, Resampling
from scipy import ndimage
from pyproj import Transformer

D = "data/"
CELL = 10  # meters

# ---------------- terrain classes ----------------
OPEN, ROAD, PATH, BUILDING, WATER, BRUSH, WOODS, WETLAND, BARRIER, CEMETERY, DEV_OPEN = range(11)
OUTSIDE = 255

CLASSES = {
    OPEN: "Field / grass / farm",
    ROAD: "Road",
    PATH: "Path / trail / sidewalk",
    BUILDING: "Building",
    WATER: "Water",
    BRUSH: "Brush / shrub",
    WOODS: "Forest",
    WETLAND: "Wetland",
    BARRIER: "Fence / wall / hedge",
    CEMETERY: "Cemetery",
    DEV_OPEN: "Lawn / parking / developed",
}

# Speed factor = 1 / Soule & Goldman terrain coefficient (see Model Rules Spec, section 5)
SPEED = {
    OPEN: 0.91, ROAD: 1.00, PATH: 0.91, BUILDING: 0.0, WATER: 0.0,
    BRUSH: 0.67, WOODS: 0.83, WETLAND: 0.56, BARRIER: 0.0,
    CEMETERY: 0.91, DEV_OPEN: 1.00, OUTSIDE: 0.0,
}

# NLCD land cover code -> our class (fills every cell OpenStreetMap does not cover)
NLCD = {
    11: WATER, 21: DEV_OPEN, 22: DEV_OPEN, 23: DEV_OPEN, 24: DEV_OPEN, 31: OPEN,
    41: WOODS, 42: WOODS, 43: WOODS, 52: BRUSH, 71: OPEN, 81: OPEN, 82: OPEN,
    90: WETLAND, 95: WETLAND,
}

PATH_TAGS = {"footway", "path", "track", "cycleway", "steps", "bridleway", "pedestrian"}
ROAD_SKIP = {"proposed", "construction", "abandoned", "platform", "corridor"}
BARRIER_TAGS = {"fence", "wall", "hedge", "retaining_wall", "city_wall", "hedge_bank"}


# ---------------- helpers ----------------
def _tag(gdf, col, values=None):
    """Rows where `col` has a real value (optionally one of `values`); points dropped."""
    if col not in gdf.columns:
        return gdf.iloc[0:0]
    s = gdf[col].astype(str)
    m = s.notna() & ~s.isin(["nan", "None", ""])
    if values is not None:
        m &= s.isin(values)
    m &= ~gdf.geometry.geom_type.isin(["Point", "MultiPoint"])
    return gdf[m]


def _burn(geoms, shape, transform, all_touched=False):
    """Boolean mask of cells covered by the geometries."""
    geoms = [g for g in geoms if g is not None and not g.is_empty]
    if not geoms:
        return np.zeros(shape, bool)
    return features.rasterize(((g, 1) for g in geoms), out_shape=shape, transform=transform,
                              fill=0, all_touched=all_touched, dtype="uint8").astype(bool)


def _reproject(path, shape, transform, crs, resampling, dtype, nodata):
    out = np.full(shape, nodata, dtype=dtype)
    with rasterio.open(path) as src:
        reproject(rasterio.band(src, 1), out, dst_transform=transform, dst_crs=crs,
                  resampling=resampling, dst_nodata=nodata)
    return out


# ---------------- build ----------------
def build(save=True, preview=True):
    area = gpd.read_file(D + "amherst_area_buffered.geojson")
    crs = area.estimate_utm_crs()
    area = area.to_crs(crs)

    xmin, ymin, xmax, ymax = area.total_bounds
    xmin, ymin = np.floor([xmin / CELL, ymin / CELL]) * CELL
    xmax, ymax = np.ceil([xmax / CELL, ymax / CELL]) * CELL
    W, H = int((xmax - xmin) / CELL), int((ymax - ymin) / CELL)
    transform = from_origin(xmin, ymax, CELL, CELL)
    shape = (H, W)
    print(f"Grid: {W} x {H} cells at {CELL} m = {W * CELL / 1000:.1f} x {H * CELL / 1000:.1f} km")

    # 1. Base layer from NLCD land cover
    print("Land cover...")
    lc = _reproject(D + "amherst_landcover_2021.tif", shape, transform, crs,
                    Resampling.nearest, "uint8", 0)
    cls = np.full(shape, OPEN, dtype="uint8")
    for code, c in NLCD.items():
        cls[lc == code] = c

    # 2. OpenStreetMap on top, in order (later layers overwrite earlier ones)
    print("OpenStreetMap layers...")
    f = gpd.read_file(D + "amherst_full_features.geojson").to_crs(crs)
    layers = [
        (OPEN,     _tag(f, "landuse", ["grass", "meadow", "farmland", "orchard"]), False),
        (OPEN,     _tag(f, "natural", ["grassland", "heath"]), False),
        (OPEN,     _tag(f, "leisure", ["park", "golf_course"]), False),
        (WOODS,    _tag(f, "natural", ["wood", "tree_row"]), False),
        (WOODS,    _tag(f, "landuse", ["forest"]), False),
        (BRUSH,    _tag(f, "natural", ["scrub"]), False),
        (WETLAND,  _tag(f, "natural", ["wetland"]), False),
        (CEMETERY, _tag(f, "landuse", ["cemetery"]), False),
        (DEV_OPEN, _tag(f, "amenity", ["parking"]), False),
        (WATER,    _tag(f, "natural", ["water"]), False),
        (WATER,    _tag(f, "waterway"), True),
    ]
    hw = _tag(f, "highway")
    hw = hw[hw.geometry.geom_type.isin(["LineString", "MultiLineString"])]
    hw_type = hw["highway"].astype(str)
    hw = hw[~hw_type.isin(ROAD_SKIP)]
    hw_type = hw["highway"].astype(str)
    layers += [
        (PATH,     hw[hw_type.isin(PATH_TAGS)], True),
        (ROAD,     hw[~hw_type.isin(PATH_TAGS)], True),   # roads over water = bridges
        (BUILDING, _tag(f, "building"), False),
        (BARRIER,  _tag(f, "barrier", BARRIER_TAGS), True),
    ]
    nlcd_wetland = np.isin(lc, [90, 95])
    for c, gdf, touched in layers:
        m = _burn(gdf.geometry, shape, transform, all_touched=touched)
        if c in (WOODS, OPEN):
            m &= ~nlcd_wetland   # OSM often tags wooded swamps as "wood"; keep NLCD wetland
        cls[m] = c

    # 3. Outside the study area
    inside = _burn(area.geometry, shape, transform)
    cls[~inside] = OUTSIDE

    # 4. Speed factor
    speed = np.zeros(shape, dtype="float32")
    for c, s in SPEED.items():
        speed[cls == c] = s

    # 5. Elevation, slope, low ground
    print("Elevation...")
    dem = _reproject(D + "amherst_elevation_10m.tif", shape, transform, crs,
                     Resampling.bilinear, "float32", np.nan)
    dem_filled = np.where(np.isnan(dem), np.nanmean(dem), dem)
    gy, gx = np.gradient(dem_filled, CELL)
    slope = np.degrees(np.arctan(np.hypot(gx, gy))).astype("float32")
    tpi = (dem_filled - ndimage.uniform_filter(dem_filled, size=21)).astype("float32")

    # 6. Distance to nearest road or path
    road_like = (cls == ROAD) | (cls == PATH)
    dist_road = (ndimage.distance_transform_edt(~road_like) * CELL).astype("float32")

    grid = dict(cls=cls, speed=speed, dem=dem, slope=slope, tpi=tpi, dist_road=dist_road,
                transform=np.array(transform)[:6], crs=crs.to_wkt(), cell=CELL)

    report(grid)
    if save:
        np.savez_compressed(D + "grid.npz", **grid)
        print("Saved data/grid.npz")
    if preview:
        save_preview(grid)
    return grid


# ---------------- load and coordinates ----------------
def load(path=D + "grid.npz"):
    z = np.load(path, allow_pickle=False)
    g = {k: z[k] for k in z.files}
    g["crs"] = str(g["crs"])
    g["cell"] = int(g["cell"])
    return g


def latlon_to_cell(grid, lat, lon):
    """(lat, lon) -> (row, col) in the grid."""
    t = Transformer.from_crs(4326, grid["crs"], always_xy=True)
    x, y = t.transform(lon, lat)
    r, c = rowcol(rasterio.Affine(*grid["transform"]), x, y)
    return int(r), int(c)


def cell_to_latlon(grid, row, col):
    """(row, col) -> (lat, lon) of the cell center. Works on arrays too."""
    a = rasterio.Affine(*grid["transform"])
    x = a.c + (np.asarray(col) + 0.5) * a.a
    y = a.f + (np.asarray(row) + 0.5) * a.e
    t = Transformer.from_crs(grid["crs"], 4326, always_xy=True)
    lon, lat = t.transform(x, y)
    return lat, lon


# ---------------- checks ----------------
def report(grid):
    cls = grid["cls"]
    inside = cls != OUTSIDE
    n = inside.sum()
    print(f"\nCells inside study area: {n:,} ({n * CELL * CELL / 1e6:.0f} km2)")
    print("Terrain share:")
    for c, name in CLASSES.items():
        print(f"  {name:<28} {(cls == c).sum() / n * 100:5.1f}%")

    try:
        case = json.load(open(D + "demo_case.json"))
    except FileNotFoundError:
        return
    print("\nDemo case points:")
    pts = [("Start", case["start"]), ("Hidden truth", case["hidden_truth"]), ("Decoy", case["decoy"])]
    pts += [(f"Clue {c['id']}", c) for c in case["clues"]]
    for name, p in pts:
        r, c = latlon_to_cell(grid, p["lat"], p["lon"])
        k = int(grid["cls"][r, c])
        print(f"  {name:<13} cell ({r},{c})  {CLASSES.get(k, 'outside'):<26} "
              f"elev {grid['dem'][r, c]:.0f} m  road {grid['dist_road'][r, c]:.0f} m away")

    # What surrounds the hidden truth (within 50 m), to check it sits in a stuck-type spot
    r, c = latlon_to_cell(grid, case["hidden_truth"]["lat"], case["hidden_truth"]["lon"])
    win = grid["cls"][r - 5:r + 6, c - 5:c + 6]
    print("\nTerrain within 50 m of the hidden truth:")
    for k, name in CLASSES.items():
        share = (win == k).mean() * 100
        if share > 0:
            print(f"  {name:<28} {share:5.1f}%")
    for kind in (BRUSH, WOODS, WETLAND):
        rr, cc = np.where(win == kind)
        if len(rr):
            d = np.hypot(rr - 5, cc - 5)
            i = d.argmin()
            lat, lon = cell_to_latlon(grid, r - 5 + rr[i], c - 5 + cc[i])
            print(f"  Nearest {CLASSES[kind].lower()}: {d[i] * CELL:.0f} m away at {lat:.5f}, {lon:.5f}")


def save_preview(grid, out="grid_preview.png"):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap, BoundaryNorm
    from matplotlib.patches import Patch

    colors = ["#ecebb0", "#f2a541", "#ffffff", "#333333", "#3d85c6", "#c7d97a",
              "#7fb069", "#6fb7a0", "#c0392b", "#8e6bbf", "#e3dccb"]
    cls = grid["cls"].astype(float)
    cls[grid["cls"] == OUTSIDE] = np.nan
    cmap = ListedColormap(colors)
    norm = BoundaryNorm(np.arange(-0.5, len(colors) + 0.5), cmap.N)

    fig, ax = plt.subplots(figsize=(14, 18), dpi=120)
    ax.imshow(cls, cmap=cmap, norm=norm, interpolation="nearest")
    try:
        case = json.load(open(D + "demo_case.json"))
        for p, m, col in [(case["start"], "*", "#d62728"),
                          (case["hidden_truth"], "X", "black"),
                          (case["decoy"], "D", "#8e6bbf")]:
            r, c = latlon_to_cell(grid, p["lat"], p["lon"])
            ax.scatter(c, r, s=250, marker=m, c=col, edgecolors="white", linewidths=1.5, zorder=5)
    except FileNotFoundError:
        pass
    ax.legend(handles=[Patch(color=colors[k], label=v) for k, v in CLASSES.items()],
              loc="lower left", fontsize=10, framealpha=0.9)
    ax.set_title("Walker grid: 10 m terrain classes", fontsize=16)
    ax.axis("off")
    plt.tight_layout()
    plt.savefig(out)
    print(f"Saved {out}")


if __name__ == "__main__":
    build()
