"""
Calibration: tune the ASSUMPTION knobs until the model reproduces ISRID statistics.
DATA values (speed, mobility shape, 66% road crossing) are never tuned.

Run from the repo root:   python -m rescuers.calibrate
Takes about 5 to 15 minutes. Output:
  data/calibrated_params.json   (used automatically by sim.py and infer.py)
  calibration_report.md         (target vs before vs after table, for the pitch)
"""

import json
import time
from dataclasses import asdict, replace
from concurrent.futures import ProcessPoolExecutor
import os
import numpy as np
from scipy import ndimage

from rescuers import grid as G
from rescuers import sim

# ---------------- what we tune, and in what range ----------------
KNOBS = {  # name: (low, high)
    "share_direction": (0.40, 0.95),
    "share_random":    (0.10, 0.45),
    "wobble_direction": (5.0, 25.0),
    "downhill":        (0.0, 0.6),
    "p_struct":        (0.005, 0.40),
    "p_water":         (0.02, 0.95),   # rivers, ponds, lakes: chance to go in (and stop)
    "p_stream":        (0.0003, 0.30), # small streams and ditches (crossable)
    "water_attract":   (1.0, 2.0),
    "p_wet":           (0.0002, 0.03),
    "p_brush":         (0.001, 0.05),
    "p_woods":         (0.00005, 0.006),
    "p_drain":         (0.0001, 0.015),
    "road_stick":      (1.5, 40.0),      # how strongly road followers stay on roads
    "mobility_scale":  (1.0, 20.0),
}
LOG_KNOBS = {"p_wet", "p_brush", "p_woods", "p_drain", "p_struct", "p_stream", "p_water", "mobility_scale",
             "road_stick"}
# share_goal is not tuned: it only matters when a case has a goal, and calibration starts have none.

# ---------------- how we score a setting ----------------
# distances: relative error; shares (percent): error in points / 10; others: relative error
WEIGHTS = {
    "dist_km_p25": 1.0, "dist_km_p50": 3.0, "dist_km_p75": 2.0,
    "structure": 1.0, "woods": 1.0, "field": 1.0, "linear": 0.5,
    # Low weight: many ISRID "road" finds are people SPOTTED by drivers while walking.
    # The model records where walkers stop and does not model public sightings.
    "road": 0.25,
    "drainage": 1.0, "water": 1.5,
    "brush": 0.25,   # brush is only 0.2% of the Amherst map, so 6% cannot be reached
    "track_offset_m_p50": 0.5, "dispersion_deg_p50": 0.25,   # only 11 cases
    "downhill": 0.5, "same": 0.25, "uphill": 0.25,
}
SHARE_KEYS = set(sim.FIND_TYPES) | {"downhill", "same", "uphill"}

N_STARTS = 20
WALKERS_PER_START = 400
MINUTES = 360   # long enough that few walkers are cut off mid-walk

_GRID = None


def _init(grid):
    global _GRID
    _GRID = grid


def pick_starts(grid, k=N_STARTS, seed=0, min_edge_km=3.0):
    """Random homes: walkable cells next to a building, at least 3 km from the map edge."""
    cls = grid["cls"]
    cell = float(grid["cell"])
    inside = cls != G.OUTSIDE
    edge_m = ndimage.distance_transform_edt(inside) * cell
    near_bld = ndimage.binary_dilation(cls == G.BUILDING, iterations=2)
    ok = np.isin(cls, [G.DEV_OPEN, G.OPEN, G.PATH]) & near_bld & (edge_m > min_edge_km * 1000)
    rr, cc = np.where(ok)
    if len(rr) < k:
        raise RuntimeError("Not enough start candidates; lower min_edge_km.")
    rng = np.random.default_rng(seed)
    i = rng.choice(len(rr), size=k, replace=False)
    return list(zip(rr[i].tolist(), cc[i].tolist()))


def measure(params_dict, starts, n=WALKERS_PER_START, seed=1):
    """Run walkers from every start, pool them, and compute the ISRID statistics."""
    grid = _GRID
    p = sim.Params(**params_dict)
    cell = float(grid["cell"])
    dem = np.where(np.isnan(grid["dem"]), np.nanmean(grid["dem"]), grid["dem"])
    dist, ftypes, offset, disp, dz, reasons = [], [], [], [], [], []
    for i, s in enumerate(starts):
        w = sim.simulate(grid, s, n=n, params=p, minutes=MINUTES, seed=seed + i)
        d = np.hypot(*(w.end - np.array(s)).T) * cell / 1000
        dist.append(d)
        ftypes.append(sim.find_type(grid, w, p))
        offset.append(grid["dist_road"][w.end[:, 0], w.end[:, 1]])
        dr, dc = (w.end - np.array(s)).T
        bearing = np.degrees(np.arctan2(dc, -dr)) % 360
        moved = d > 0.05
        disp.append(np.abs((bearing - w.heading0 + 180) % 360 - 180)[moved])
        dz.append(dem[w.end[:, 0], w.end[:, 1]] - dem[s])
        reasons.append(w.reason)
    dist, ftypes = np.concatenate(dist), np.concatenate(ftypes)
    offset, disp, dz = np.concatenate(offset), np.concatenate(disp), np.concatenate(dz)
    reasons = np.concatenate(reasons)
    out = {
        "dist_km_p25": np.percentile(dist, 25), "dist_km_p50": np.percentile(dist, 50),
        "dist_km_p75": np.percentile(dist, 75),
        **{f: (ftypes == f).mean() * 100 for f in sim.FIND_TYPES},
        "track_offset_m_p50": float(np.median(offset)),
        "dispersion_deg_p50": float(np.median(disp)) if disp.size else 0.0,
        "downhill": (dz < -2).mean() * 100, "same": (np.abs(dz) <= 2).mean() * 100,
        "uphill": (dz > 2).mean() * 100,
        **{f"stop: {name}": (reasons == i).mean() * 100 for i, name in enumerate(sim.REASONS) if i},
    }
    return {k: float(v) for k, v in out.items()}


def score(stats):
    total = 0.0
    for k, w in WEIGHTS.items():
        target, model = sim.ISRID[k], stats[k]
        if k in SHARE_KEYS:
            err = abs(model - target) / 10.0
        else:
            err = abs(model - target) / max(target, 1e-6)
        total += w * err
    return total


def sample_setting(rng, ranges, base):
    d = asdict(base)
    for k, (lo, hi) in ranges.items():
        if k in LOG_KNOBS:
            d[k] = float(np.exp(rng.uniform(np.log(lo), np.log(hi))))
        else:
            d[k] = float(rng.uniform(lo, hi))
    return d


def narrow(best, ranges, shrink=0.35):
    """New ranges around the best settings (approximate Bayesian computation, round 2)."""
    new = {}
    for k, (lo, hi) in ranges.items():
        vals = np.array([b[k] for b in best])
        span = (hi - lo) * shrink
        new[k] = (max(lo, vals.min() - span / 4), min(hi, vals.max() + span / 4))
    return new


def _job(args):
    d, starts = args
    st = measure(d, starts)
    return d, st, score(st)


def search(grid, starts, rounds=(200, 120, 80), keep=15, seed=0, workers=None):
    rng = np.random.default_rng(seed)
    base = sim.Params()
    ranges = dict(KNOBS)
    results = []
    workers = workers or max(1, (os.cpu_count() or 2) - 1)
    with ProcessPoolExecutor(max_workers=workers, initializer=_init, initargs=(grid,)) as ex:
        for rnd, count in enumerate(rounds, 1):
            t0 = time.time()
            jobs = [(sample_setting(rng, ranges, base), starts) for _ in range(count)]
            if rnd == 1:   # warm start: previous best and defaults always compete
                jobs += [(asdict(sim.load_params(verbose=False)), starts), (asdict(base), starts)]
            out = list(ex.map(_job, jobs))
            results += out
            results.sort(key=lambda x: x[2])
            best = [r[0] for r in results[:keep]]
            print(f"Round {rnd}: {count} settings in {time.time() - t0:.0f} s. "
                  f"Best score {results[0][2]:.2f}")
            ranges = narrow(best, ranges)
    return results


def stability(grid, params, n=20000, minutes=MINUTES):
    """Do two runs with different seeds give the same hot zone? (Walter's start, no clues.)"""
    from rescuers import infer
    case = json.load(open(G.D + "demo_case.json"))
    start = G.latlon_to_cell(grid, case["start"]["lat"], case["start"]["lon"])
    zones = []
    for seed in (101, 202):
        w = sim.simulate(grid, start, n=n, params=params, minutes=minutes, seed=seed)
        heat = infer.heatmap(grid, w, np.ones(n))
        flat = np.sort(heat.ravel())[::-1]
        cut = flat[np.searchsorted(np.cumsum(flat), 0.8)]
        zones.append(heat >= cut)
    a, b = zones
    return (a & b).sum() / (a | b).sum()


def main():
    t_start = time.time()
    grid = G.load()
    _init(grid)
    starts = pick_starts(grid)
    print(f"Calibrating on {len(starts)} start points x {WALKERS_PER_START} walkers.\n")

    before = measure(asdict(sim.Params()), starts)
    print(f"Default parameters: score {score(before):.2f}")

    results = search(grid, starts)
    best_d, best_stats, best_score = results[0]
    # confirm the winner with more walkers and new seeds
    confirm = measure(best_d, starts, n=1500, seed=999)
    print(f"Best setting confirmed with 1,500 walkers per start: score {score(confirm):.2f}")

    params = sim.Params(**best_d)
    json.dump(asdict(params), open(sim.PARAMS_FILE, "w"), indent=2)
    print(f"Saved {sim.PARAMS_FILE}")

    stab = stability(grid, params)
    print(f"Stability (20,000 walkers, two seeds): hot zones overlap {stab * 100:.0f}%")

    write_report(before, confirm, asdict(sim.Params()), best_d, stab, time.time() - t_start)


def write_report(before, after, p0, p1, stab, secs, out="calibration_report.md"):
    lines = ["# Calibration report", "",
             f"{N_STARTS} random start points in Amherst, {WALKERS_PER_START} walkers each per setting; "
             f"400 settings searched in 3 rounds; winner confirmed with 1,500 walkers per start. "
             f"Run time {secs / 60:.0f} min.", "",
             "## ISRID target vs model", "",
             "| Statistic | ISRID | Before | After |", "| --- | --- | --- | --- |"]
    for k in sim.ISRID:
        lines.append(f"| {k} | {sim.ISRID[k]} | {before[k]:.1f} | {after[k]:.1f} |")
    lines += ["", f"Score (lower is better): before {score(before):.2f}, after {score(after):.2f}", "",
              f"Stability: two runs of 20,000 walkers with different seeds share "
              f"{stab * 100:.0f}% of their hot zone (80% probability area).", "",
              "## Tuned values (ASSUMPTIONS)", "", "| Knob | Default | Calibrated |", "| --- | --- | --- |"]
    for k, (lo, hi) in KNOBS.items():
        if k in LOG_KNOBS:
            pos = (np.log(p1[k]) - np.log(lo)) / (np.log(hi) - np.log(lo))
        else:
            pos = (p1[k] - lo) / (hi - lo)
        flag = " (at LOW limit)" if pos < 0.05 else " (at HIGH limit)" if pos > 0.95 else ""
        lines.append(f"| {k} | {p0[k]:.4g} | {p1[k]:.4g}{flag} |")
    lines += ["", "## Why walkers stopped (after calibration)", "", "| Reason | Share |", "| --- | --- |"]
    for k, v in after.items():
        if k.startswith("stop: ") and v > 0:
            lines.append(f"| {k[6:]} | {v:.1f}% |")
    lines += ["", "## Remaining error by statistic (largest first)", "",
              "| Statistic | Share of remaining error |", "| --- | --- |"]
    parts = {k: w * (abs(after[k] - sim.ISRID[k]) / 10.0 if k in SHARE_KEYS
                     else abs(after[k] - sim.ISRID[k]) / max(sim.ISRID[k], 1e-6))
             for k, w in WEIGHTS.items()}
    tot = sum(parts.values())
    for k, v in sorted(parts.items(), key=lambda x: -x[1])[:6]:
        lines.append(f"| {k} | {v / tot * 100:.0f}% |")
    lines += ["", "DATA values (speed, mobility shape, 66% road crossing) were not tuned. "
              "`mobility_scale` reconciles ISRID's mobility sample (n = 42) with its distance "
              "sample (n = 175)."]
    open(out, "w").write("\n".join(lines))
    print(f"Saved {out}")
    print("\n" + "\n".join(lines[6:]))


if __name__ == "__main__":
    main()
