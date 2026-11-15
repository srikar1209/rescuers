"""
Walker simulation: N possible walks of one missing person with dementia.

Run from the repo root:   python -m rescuers.sim
Output: stats vs ISRID targets, and sim_preview.png

All rule values come from the Model Rules Spec. Each one is labeled:
  DATA        published number, never tuned
  EXPERT      described behavior; number chosen by us
  ASSUMPTION  our choice; tuned in calibration
"""

from dataclasses import dataclass, field, asdict
import json
import time
import numpy as np

from rescuers import grid as G

# ---------------- parameters ----------------
@dataclass
class Params:
    # walker mix (EXPERT behavior, shares tuned)
    share_direction: float = 0.60
    share_random: float = 0.25
    share_goal: float = 0.15
    # heading wobble per step, degrees (ASSUMPTION, tuned)
    wobble_direction: float = 10.0
    wobble_random: float = 45.0
    wobble_goal: float = 20.0
    # speed on flat paved ground, m/s (DATA: 309 people with cognitive impairment)
    speed_mean: float = 0.62
    speed_sd: float = 0.23
    speed_min: float = 0.25
    speed_max: float = 1.10
    # slope choice (EXPERT: "path of least resistance"; tuned to 42 / 39 / 19 %).
    # Two separate knobs, so walkers can avoid climbing without rushing downhill.
    down_pref: float = 0.30    # a downhill step is (1 + down_pref) times more likely
    up_avoid: float = 0.30     # an uphill step is (1 - up_avoid) times as likely
    # roads (DATA, per person: 66% cross or leave roads, so 34% stay on them = Koester's
    # "route traveling"). Each walker decides once, at the first road it meets.
    p_cross_road: float = 0.66
    road_stick: float = 8.0    # how strongly road followers prefer road cells (ASSUMPTION, tuned)
    # stopping (EXPERT + ASSUMPTION, tuned to ISRID find locations)
    p_struct: float = 0.30     # stop when blocked by a building
    # Rivers, ponds, lakes: each person decides ONCE, at the first water they reach: go in
    # (and stop there) with chance p_water, or treat water as a wall for the rest of the walk.
    p_water: float = 0.80      # (EXPERT, tuned)
    p_stream: float = 0.05     # stop on entering a small stream or ditch (crossable; tuned)
    water_attract: float = 1.5 # how much more likely a step toward water is (EXPERT, tuned)
    # per 10 m step; small because it compounds: 0.005 per step = about 40% stuck within 1 km
    p_wet: float = 0.010       # per step in wetland
    p_brush: float = 0.020     # per step in brush
    p_woods: float = 0.002     # per step in forest
    p_drain: float = 0.005     # per step in low ground (drainage)
    drain_tpi: float = -1.0    # meters below neighborhood = drainage
    max_slope: float = 30.0    # degrees; steeper = blocked (ASSUMPTION)
    goal_radius_m: float = 30.0
    struct_min_m: float = 50.0 # no "stopped at building" this close to home (ASSUMPTION, tuned)
    # Direction walkers go AROUND obstacles: after a bounce they turn back toward their
    # original direction by up to this many degrees per step (EXPERT: direction traveling
    # = keep the same course until truly stuck; number tuned). 0 = never turn back.
    return_deg: float = 10.0
    # Seen by the public: chance per minute of being spotted (and found) while on a road or
    # path, times the road's traffic (0 to 1, from the road type). Explains ISRID's road and
    # linear finds. ASSUMPTION, tuned. In the app it becomes the "not reported" clue instead.
    p_spot: float = 0.02
    # Walking time before the person stops moving (lognormal). ISRID has two samples that
    # disagree: mobility hours (n = 42) are far more spread out than distances (n = 175).
    # We trust the larger sample: these two knobs are tuned so distances match ISRID.
    # The n = 42 mobility hours are kept below as a check, not as an input. ASSUMPTION.
    walk_median_min: float = 90.0   # median walking time, minutes
    walk_sigma: float = 1.2         # spread (SD of log time)


# ISRID temperate dementia mobility (hours) at percentiles 25/50/75/95 (DATA, n = 42).
# Used only as a CHECK now (see walk_median_min). 0 h is treated as "about 2 minutes".
MOBILITY_P = np.array([0.00, 0.25, 0.50, 0.75, 0.95, 1.00])
MOBILITY_H = np.array([0.005, 0.033, 0.25, 3.8, 18.0, 24.0])

# Stop reasons
ACTIVE, STUCK, STRUCTURE, IN_WATER, TIRED, GOAL, LEFT_MAP, OUT_OF_TIME, SPOTTED = range(9)
REASONS = ["active", "stuck in terrain", "stopped at building", "in water",
           "mobility time over", "reached goal", "left map", "simulation time over",
           "spotted by public"]

BLOCKED = {G.BUILDING, G.BARRIER, G.OUTSIDE}

# "Same elevation" band for the downhill / same / uphill statistic. 2 m is inside normal noise of a
# 10 m elevation map plus small bumps; 5 m is a meaningful change. ASSUMPTION (ISRID gives no band).
ELEV_SAME_M = 5.0

# Drainage = low ground (tpi < drain_tpi) that is ALSO within this distance of a stream, ditch,
# river or pond: creek beds, ditches, ravines (ISRID's meaning). ASSUMPTION.
DRAIN_STREAM_M = 50.0


def traffic_layer(grid):
    """Road traffic 0-1. Old grids without the layer: roads 0.3, paths 0.1 (rough fallback)."""
    if "traffic" not in grid:
        cls = grid["cls"]
        grid["traffic"] = np.where(cls == G.ROAD, 0.3, np.where(cls == G.PATH, 0.1, 0.0)).astype("float32")
    return grid["traffic"]


def drainage_mask(grid, drain_tpi):
    """True where a cell counts as drainage. The near-stream part is computed once per grid."""
    if "near_stream" not in grid:
        source = np.isin(grid["cls"], [G.STREAM, G.WATER])
        radius = DRAIN_STREAM_M / float(grid["cell"])
        try:
            from scipy import ndimage
            grid["near_stream"] = ndimage.distance_transform_edt(~source) <= radius
        except ImportError:
            # Exact disk dilation at the grid's cell resolution for UI environments
            # that have NumPy but not the GIS/calibration environment's SciPy.
            h, w = source.shape
            near = np.zeros_like(source)
            edge = int(np.floor(radius))
            for dr in range(-edge, edge + 1):
                for dc in range(-edge, edge + 1):
                    if dr * dr + dc * dc > radius * radius:
                        continue
                    r0, r1 = max(0, -dr), min(h, h - dr)
                    c0, c1 = max(0, -dc), min(w, w - dc)
                    near[r0:r1, c0:c1] |= source[r0 + dr:r1 + dr, c0 + dc:c1 + dc]
            grid["near_stream"] = near
    return (grid["tpi"] < drain_tpi) & grid["near_stream"]


@dataclass
class Walks:
    pos: np.ndarray          # (n, T+1, 2) row, col every minute (float32)
    end: np.ndarray          # (n, 2) final row, col (int)
    reason: np.ndarray       # (n,) stop reason
    kind: np.ndarray         # (n,) 0 direction, 1 random, 2 goal
    speed: np.ndarray        # (n,) m/s
    mobility_min: np.ndarray # (n,) minutes
    heading0: np.ndarray     # (n,) start heading, degrees
    minutes: int
    start: tuple
    params: dict = field(default_factory=dict)
    bounces: np.ndarray = None  # (n,) times the walker was fully blocked and turned (diagnostics)


PARAMS_FILE = "data/calibrated_params.json"


def load_params(path=PARAMS_FILE, verbose=True):
    """Calibrated parameters if calibrate.py has been run, else the defaults."""
    try:
        d = json.load(open(path))
        if "downhill" in d and "down_pref" not in d:     # older files had one slope knob
            d["down_pref"] = d["up_avoid"] = d["downhill"]
        if verbose:
            print(f"Using calibrated parameters from {path}")
        return Params(**{k: v for k, v in d.items() if k in Params.__dataclass_fields__})
    except FileNotFoundError:
        if verbose:
            print("Using default parameters (run python -m rescuers.calibrate to tune them)")
        return Params()


def sample_walk_minutes(rng, n, p):
    """Lognormal walking time in minutes (see Params.walk_median_min)."""
    return np.exp(np.log(p.walk_median_min) + p.walk_sigma * rng.standard_normal(n))


def sample_mobility_minutes(rng, n):
    """ISRID mobility hours (n = 42) as minutes. Not used by simulate(); kept for comparison."""
    u = rng.random(n)
    log_h = np.interp(u, MOBILITY_P, np.log(MOBILITY_H))
    return np.exp(log_h) * 60.0


def simulate(grid, start, n=5000, params=None, minutes=240, heading=None,
             heading_sd=30.0, goal=None, seed=42, spotting=True):
    """
    grid     from grid.load()
    start    (row, col) of the last seen point
    heading  known exit direction in degrees (0 = north, 90 = east), or None for random
    goal     (row, col) of a former home or favorite place, or None
    spotting True for calibration (people seen on roads are found there). The app uses False,
             because the person is still missing; it applies the "not_reported" clue instead.
    """
    p = params or Params()
    rng = np.random.default_rng(seed)
    cls, spd_f, dem, slope, tpi = grid["cls"], grid["speed"], grid["dem"], grid["slope"], grid["tpi"]
    dem = np.where(np.isnan(dem), np.nanmean(dem), dem)
    drain = drainage_mask(grid, p.drain_tpi)
    traffic = traffic_layer(grid)
    H, W = cls.shape
    cell = float(grid["cell"])

    # ---- walker profiles ----
    shares = np.array([p.share_direction, p.share_random, p.share_goal if goal else 0.0])
    shares = shares / shares.sum()
    kind = rng.choice(3, size=n, p=shares)
    speed = np.clip(rng.normal(p.speed_mean, p.speed_sd, n), p.speed_min, p.speed_max)
    mobility_s = sample_walk_minutes(rng, n, p) * 60.0
    if heading is None:
        head = rng.uniform(0, 360, n)
    else:
        head = (heading + rng.normal(0, heading_sd, n)) % 360
    heading0 = head.copy()
    wobble = np.array([p.wobble_direction, p.wobble_random, p.wobble_goal])[kind]

    # ---- state ----
    pos = np.tile(np.array(start, dtype=float), (n, 1))
    t = np.zeros(n)
    reason = np.zeros(n, dtype=np.int8)
    road_mode = np.zeros(n, dtype=np.int8)        # 0 no road yet, 1 crosser, 2 road follower
    water_mode = np.zeros(n, dtype=np.int8)       # 0 no water yet, 1 goes in, 2 avoids water
    on_road_prev = np.isin(cls[start], [G.ROAD, G.PATH]).repeat(n)
    T = minutes
    rec = np.zeros((n, T + 1, 2), dtype=np.float32)
    rec[:, 0] = pos
    last_min = np.zeros(n, dtype=int)
    bounces = np.zeros(n, dtype=np.int32)
    t_max = minutes * 60.0

    offsets = np.radians(np.array([-45.0, 0.0, 45.0]))
    base_w = np.array([0.25, 0.5, 0.25])
    goal_rc = np.array(goal, dtype=float) if goal else None
    goal_cells = p.goal_radius_m / cell

    # walkers that never start moving
    reason[mobility_s <= 0] = TIRED

    for _ in range(100000):
        act = np.where(reason == ACTIVE)[0]
        if act.size == 0:
            break
        m = act.size
        r0 = np.rint(pos[act, 0]).astype(int)
        c0 = np.rint(pos[act, 1]).astype(int)

        # 1. desired heading
        h = head[act] + rng.normal(0, 1, m) * wobble[act]
        g = kind[act] == 2
        if g.any():
            dr = goal_rc[0] - pos[act[g], 0]
            dc = goal_rc[1] - pos[act[g], 1]
            h[g] = np.degrees(np.arctan2(dc, -dr)) + rng.normal(0, p.wobble_goal, g.sum())
        h %= 360

        # 2. three candidate cells ahead
        ang = np.radians(h)[:, None] + offsets[None, :]            # (m, 3)
        cr = pos[act, 0][:, None] - np.cos(ang)
        cc = pos[act, 1][:, None] + np.sin(ang)
        ri = np.rint(cr).astype(int)
        ci = np.rint(cc).astype(int)
        outside = (ri < 0) | (ri >= H) | (ci < 0) | (ci >= W)
        ri_c, ci_c = np.clip(ri, 0, H - 1), np.clip(ci, 0, W - 1)
        k = np.where(outside, G.OUTSIDE, cls[ri_c, ci_c])

        # 3. weight candidates
        w = np.tile(base_w, (m, 1))
        dz = dem[ri_c, ci_c] - dem[r0, c0][:, None]
        w = np.where(dz < -0.2, w * (1 + p.down_pref), w)
        w = np.where(dz > 0.2, w * (1 - p.up_avoid), w)
        # drawn to water, but only from dry land (no wading along streams)
        on_land = ~np.isin(cls[r0, c0], [G.WATER, G.STREAM])[:, None]
        w = np.where(((k == G.WATER) | (k == G.STREAM)) & on_land, w * p.water_attract, w)
        fol = road_mode[act] == 2
        if fol.any():
            road_c = np.isin(k, [G.ROAD, G.PATH])
            w[fol] = np.where(road_c[fol], w[fol] * p.road_stick, w[fol])
        blocked = np.isin(k, list(BLOCKED)) | (slope[ri_c, ci_c] > p.max_slope)
        # rivers and ponds: decided once per person, at the first water they reach.
        # 1 = will go in (and stop there), 2 = treats water as a wall. No wading across.
        meets = (k == G.WATER).any(1) & (water_mode[act] == 0)
        if meets.any():
            water_mode[act[meets]] = np.where(rng.random(meets.sum()) < p.p_water, 1, 2)
        enters_water = (water_mode[act] == 1)[:, None]
        blocked |= (k == G.WATER) & ~enters_water
        w = np.where(blocked, 0.0, w)

        # 4. all three blocked: stop at a building, leave the map, or deflect
        dead = w.sum(1) == 0
        if dead.any():
            ia = act[dead]
            bounces[ia] += 1
            out_any = (k[dead] == G.OUTSIDE).any(1)
            bld_any = (k[dead] == G.BUILDING).any(1)
            left_home = np.hypot(pos[ia, 0] - start[0], pos[ia, 1] - start[1]) * cell >= p.struct_min_m
            stop_b = bld_any & left_home & (rng.random(dead.sum()) < p.p_struct)
            reason[ia[out_any]] = LEFT_MAP
            reason[ia[~out_any & stop_b]] = STRUCTURE
            turn = rng.uniform(30, 90, dead.sum()) * rng.choice([-1, 1], dead.sum())
            head[ia] = (head[ia] + turn) % 360                     # ping-pong, never straight back
            t[ia] += 5.0

        mv = ~dead
        if not mv.any():
            continue
        ia = act[mv]
        wm = w[mv] / w[mv].sum(1, keepdims=True)
        choice = (rng.random(mv.sum())[:, None] > wm.cumsum(1)).sum(1)
        choice = np.minimum(choice, 2)
        idx = np.arange(mv.sum())
        nr, nc = ri[mv][idx, choice], ci[mv][idx, choice]
        nk = k[mv][idx, choice]
        npos_r, npos_c = cr[mv][idx, choice], cc[mv][idx, choice]   # continuous position

        # 5. time for this step: base speed x terrain x slope (Tobler, relative to flat)
        step_m = np.full(ia.size, cell)                             # always one cell length
        dzs = dem[nr, nc] - dem[np.rint(pos[ia, 0]).astype(int), np.rint(pos[ia, 1]).astype(int)]
        s = dzs / step_m
        tobler = np.exp(-3.5 * np.abs(s + 0.05)) / np.exp(-3.5 * 0.05)
        terr = np.maximum(spd_f[nr, nc], 0.3)                       # wading through water is slow
        v = speed[ia] * terr * np.clip(tobler, 0.2, 1.2)
        dt = step_m / v
        t[ia] += dt

        pos[ia, 0], pos[ia, 1] = npos_r, npos_c
        # Direction walkers: wobble shakes each step but does NOT add up, so they hold their
        # course until a barrier deflects them (EXPERT: go straight until stuck).
        # Random wanderers: wobble adds up (a correlated random walk).
        keep = kind[ia] == 1
        head[ia[keep]] = h[mv][keep]

        # 6. roads: at the FIRST road, decide once: 66% cross roads, 34% follow roads
        on_road = np.isin(nk, [G.ROAD, G.PATH])
        first = on_road & (road_mode[ia] == 0)
        if first.any():
            j = ia[first]
            road_mode[j] = np.where(rng.random(j.size) < p.p_cross_road, 1, 2)
        # road followers on a road turn with it (heading = the step they just took)
        turn = on_road & (road_mode[ia] == 2)
        head[ia[turn]] = np.degrees(ang[mv][idx, choice])[turn] % 360
        # direction walkers (not road followers) turn back toward their original course
        back = (kind[ia] == 0) & (road_mode[ia] != 2)
        if back.any() and p.return_deg > 0:
            j = ia[back]
            diff = (heading0[j] - head[j] + 180) % 360 - 180
            head[j] = (head[j] + np.clip(diff, -p.return_deg, p.return_deg)) % 360
        on_road_prev[ia] = on_road

        # 7. terrain stops
        u = rng.random(ia.size)
        stuck = ((nk == G.BRUSH) & (u < p.p_brush)) | \
                ((nk == G.WOODS) & (u < p.p_woods)) | \
                ((nk == G.WETLAND) & (u < p.p_wet)) | \
                (drain[nr, nc] & ~on_road & (u < p.p_drain))
        u2 = rng.random(ia.size)
        water = (nk == G.WATER) | ((nk == G.STREAM) & (u2 < p.p_stream))
        reason[ia[stuck]] = STUCK
        reason[ia[water]] = IN_WATER
        if spotting and p.p_spot > 0:
            rate = np.clip(p.p_spot * traffic[nr, nc], 0, 0.999)
            seen = on_road & (rng.random(ia.size) < 1 - (1 - rate) ** (dt / 60.0))
            reason[ia[seen & (reason[ia] == ACTIVE)]] = SPOTTED
        if goal_rc is not None:
            at_goal = (kind[ia] == 2) & (np.hypot(nr - goal_rc[0], nc - goal_rc[1]) < goal_cells)
            reason[ia[at_goal & (reason[ia] == ACTIVE)]] = GOAL

        # 8. mobility and simulation time
        tired = (t[ia] >= mobility_s[ia]) & (reason[ia] == ACTIVE)
        reason[ia[tired]] = TIRED
        late = (t[ia] >= t_max) & (reason[ia] == ACTIVE)
        reason[ia[late]] = OUT_OF_TIME

        # 9. record position every minute
        new_min = np.minimum((t[ia] // 60).astype(int), T)
        while True:
            gap = new_min > last_min[ia]
            if not gap.any():
                break
            j = ia[gap]
            last_min[j] += 1
            rec[j, last_min[j]] = pos[j]

    # walkers stay where they stopped for the rest of the time
    for mi in range(1, T + 1):
        later = last_min < mi
        rec[later, mi] = pos[later]

    return Walks(pos=rec, end=np.rint(pos).astype(int), reason=reason, kind=kind,
                 speed=speed, mobility_min=mobility_s / 60, heading0=heading0,
                 minutes=minutes, start=tuple(start), params=asdict(p), bounces=bounces)


# ---------------- statistics vs ISRID ----------------
ISRID = {  # temperate dementia (DATA): Koester, Lost Person Behavior
    "dist_km_p25": 0.3, "dist_km_p50": 1.0, "dist_km_p75": 2.4,
    "structure": 20, "road": 18, "woods": 17, "field": 14, "linear": 9,
    "drainage": 9, "water": 7, "brush": 6,
    "track_offset_m_p50": 15, "dispersion_deg_p50": 23,
    "downhill": 42, "same": 39, "uphill": 19,
}
FIND_TYPES = ["structure", "road", "woods", "field", "linear", "drainage", "water", "brush"]


def find_type(grid, walks, p=None):
    """Map each end point to an ISRID find category."""
    p = p or Params(**walks.params)
    r, c = walks.end[:, 0], walks.end[:, 1]
    k = grid["cls"][r, c]
    out = np.full(len(r), "field", dtype=object)
    out[np.isin(k, [G.WOODS])] = "woods"
    out[np.isin(k, [G.BRUSH])] = "brush"
    # Amherst wetland is mostly WOODED wetland (NLCD 90), which a search team would usually
    # record as woods. Counted as woods unless it is low ground (then drainage). Judgment call.
    out[np.isin(k, [G.WETLAND])] = "woods"
    out[drainage_mask(grid, p.drain_tpi)[r, c]] = "drainage"
    out[np.isin(k, [G.WATER, G.STREAM])] = "water"
    out[np.isin(k, [G.PATH])] = "linear"
    out[np.isin(k, [G.ROAD])] = "road"
    out[walks.reason == STRUCTURE] = "structure"
    return out


def stats(grid, walks):
    cell = float(grid["cell"])
    start = np.array(walks.start)
    d = np.hypot(*(walks.end - start).T) * cell / 1000
    ft = find_type(grid, walks)
    dr, dc = (walks.end - start).T
    bearing = np.degrees(np.arctan2(dc, -dr)) % 360
    moved = d > 0.05
    disp = np.abs((bearing - walks.heading0 + 180) % 360 - 180)[moved]
    dem = grid["dem"]
    dz = dem[walks.end[:, 0], walks.end[:, 1]] - dem[start[0], start[1]]
    out = {
        "dist_km_p25": np.percentile(d, 25), "dist_km_p50": np.percentile(d, 50),
        "dist_km_p75": np.percentile(d, 75),
        **{f: (ft == f).mean() * 100 for f in FIND_TYPES},
        "track_offset_m_p50": np.median(grid["dist_road"][walks.end[:, 0], walks.end[:, 1]]),
        "dispersion_deg_p50": np.median(disp) if disp.size else np.nan,
        "downhill": (dz < -ELEV_SAME_M).mean() * 100, "same": (np.abs(dz) <= ELEV_SAME_M).mean() * 100,
        "uphill": (dz > ELEV_SAME_M).mean() * 100,
    }
    return out


def print_stats(s):
    print(f"\n{'Statistic':<22}{'ISRID':>8}{'Model':>8}")
    for key, target in ISRID.items():
        print(f"{key:<22}{target:>8}{s[key]:>8.1f}")


# ---------------- run ----------------
def run_demo(n=5000, seed=42):
    grid = G.load()
    case = json.load(open(G.D + "demo_case.json"))
    start = G.latlon_to_cell(grid, case["start"]["lat"], case["start"]["lon"])
    t0 = time.time()
    walks = simulate(grid, start, n=n, seed=seed, params=load_params())
    print(f"Simulated {n} walkers in {time.time() - t0:.1f} s")
    for i, name in enumerate(REASONS):
        share = (walks.reason == i).mean() * 100
        if share:
            print(f"  {name:<22} {share:5.1f}%")
    print_stats(stats(grid, walks))

    truth = G.latlon_to_cell(grid, case["hidden_truth"]["lat"], case["hidden_truth"]["lon"])
    save_preview(grid, walks, start, truth)
    np.savez_compressed(G.D + "walks_demo.npz", **{k: v for k, v in asdict(walks).items()
                                                   if isinstance(v, np.ndarray)})
    return grid, walks


def save_preview(grid, walks, start, truth=None, out="sim_preview.png", pad=150):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap, BoundaryNorm
    r0, c0 = start
    rs, cs = slice(max(r0 - pad, 0), r0 + pad), slice(max(c0 - pad, 0), c0 + pad)
    colors = ["#ecebb0", "#f2a541", "#ffffff", "#333333", "#1f5fa8", "#c7d97a",
              "#7fb069", "#6fb7a0", "#c0392b", "#8e6bbf", "#e3dccb", "#5aa9e6"]
    sub = grid["cls"][rs, cs].astype(float)
    sub[sub == G.OUTSIDE] = np.nan
    fig, axes = plt.subplots(1, 2, figsize=(18, 9), dpi=110)
    for ax in axes:
        ax.imshow(sub, cmap=ListedColormap(colors),
                  norm=BoundaryNorm(np.arange(-0.5, len(colors) + 0.5), len(colors)), interpolation="nearest")
        ax.axis("off")
    ro, co = rs.start, cs.start
    for i in range(min(150, len(walks.end))):
        axes[0].plot(walks.pos[i, :, 1] - co, walks.pos[i, :, 0] - ro, lw=0.6, alpha=0.6)
    axes[0].set_title("150 sample walks", fontsize=14)
    H2, _, _ = np.histogram2d(walks.end[:, 0] - ro, walks.end[:, 1] - co,
                              bins=[2 * pad, 2 * pad], range=[[0, 2 * pad], [0, 2 * pad]])
    from scipy.ndimage import gaussian_filter
    heat = np.sqrt(gaussian_filter(H2, 2))     # square root so the busy start point does not hide the rest
    heat[heat < heat.max() * 0.05] = np.nan
    axes[1].imshow(heat, cmap="hot_r", alpha=0.75, interpolation="bilinear")
    axes[1].set_title("Where walkers stop (heat map, square-root scale)", fontsize=14)
    for ax in axes:
        ax.set_xlim(0, sub.shape[1]); ax.set_ylim(sub.shape[0], 0)
        ax.scatter(c0 - co, r0 - ro, s=300, marker="*", c="#d62728", edgecolors="white", zorder=5)
        if truth:
            ax.scatter(truth[1] - co, truth[0] - ro, s=200, marker="X", c="black",
                       edgecolors="white", zorder=5)
    plt.tight_layout()
    plt.savefig(out)
    print(f"Saved {out}")


if __name__ == "__main__":
    run_demo()
