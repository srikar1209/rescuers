"""
Benchmark: does our model help searchers more than simple methods?

Run from the repo root:   pip install scikit-image   (once)
                          python -m rescuers.benchmark          (300 cases, about 20 min)
                          python -m rescuers.benchmark 1000     (final run, about 1 h)
 Output: benchmark_report.md and benchmark.png

FAIRNESS: the true spots are NOT made by our walkers (that would be grading ourselves).
Each case:
  1. start   a random home in Amherst, from a different set than the calibration starts
  2. truth   placed with ISRID statistics only: a distance drawn from ISRID's distance curve
             (25/50/75% = 0.3/1.0/2.4 km), a find type drawn from ISRID's shares (structure 20%,
             road 18%, ...), then a random map cell of that type at that distance
  3. route   for the sighting test: the cheapest walking route from start to truth (not our
             walker rules); a witness sees him part way along it, reported with 50 m error

Score per method = area searched before reaching the truth, searching the most likely cells
first (km2, lower is better). This is how long a search team needs.

Test A, no clues:
  rings      circle search around the last seen point (the "basic instinct")
  stats map  ISRID distance x ISRID find type per cell. This is the SAME recipe that placed the
             truths, so it is a ceiling for test A, not a rival. Our model should come close.
  our model  20 start-specific walkers, calibrated
Test B, one sighting:
  rings around the sighting   what a sensible searcher does with a sighting
  our model + sighting        walkers reweighted by the clue
  (the stats map cannot use a sighting: it has no time and no paths)
"""

import json
import time
import os
import numpy as np
from concurrent.futures import ProcessPoolExecutor
from scipy import ndimage

from rescuers import grid as G
from rescuers import sim, infer
from rescuers import calibrate as C

N_CASES = 300
WALKERS = 20000        # same as the app
# Tie rule: if BOTH methods reach the person within this area (a few minutes of searching),
# the case is a tie, not a win or a loss. Applied the same way to every comparison.
TIE_KM2 = 0.05
MINUTES = 720
START_HHMM = "12:00"
SIGHTING_ERR_M = 50.0
# Walkers never cover every cell. Where no walker went, a searcher would fall back to
# distance rings. So the model map = 95% walkers + 5% ISRID distance rings around the latest
# known place (last seen, or the sighting). Same as infer.heatmap in the app.
FLOOR = 0.05
# ISRID temperate dementia distance (DATA): lognormal through 25/50/75% = 0.3 / 1.0 / 2.4 km
D_MU = np.log(1.0)
D_SIGMA = np.log(2.4 / 0.3) / (2 * 0.6745)
TYPE_ORDER = ["water", "road", "linear", "structure", "drainage", "brush", "woods", "field"]
_G = None


def labels(grid, p):
    """One ISRID find type per cell (same meaning as sim.find_type). -1 = cannot be found there."""
    cls = grid["cls"]
    lab = np.full(cls.shape, -1, dtype=np.int8)
    blocked = np.isin(cls, [G.BUILDING, G.BARRIER, G.OUTSIDE])
    near_bld = ndimage.binary_dilation(cls == G.BUILDING, iterations=1) & ~blocked
    drain = sim.drainage_mask(grid, p.drain_tpi)
    masks = {
        "water": np.isin(cls, [G.WATER, G.STREAM]),
        "road": cls == G.ROAD,
        "linear": cls == G.PATH,
        "structure": near_bld,
        "drainage": drain & ~blocked,
        "brush": cls == G.BRUSH,
        "woods": np.isin(cls, [G.WOODS, G.WETLAND]),
        "field": ~blocked,
    }
    for i, t in enumerate(TYPE_ORDER):                   # earlier types win
        lab[masks[t] & (lab == -1)] = i
    lab[blocked] = -1
    return lab


def _init(grid, lab):
    global _G, _LAB
    _G, _LAB = grid, lab


def place_truth(grid, lab, start, rng, cell):
    H, W = lab.shape
    rr, cc = np.mgrid[0:H, 0:W]
    dist = np.hypot(rr - start[0], cc - start[1]) * cell / 1000
    shares = np.array([sim.ISRID[t] for t in TYPE_ORDER], float)
    shares /= shares.sum()
    # Draw the distance ONCE (so test distances follow ISRID exactly). Then pick the find type
    # among the types that exist at that distance, with ISRID's shares.
    for _ in range(20):
        d = float(np.clip(np.exp(rng.normal(D_MU, D_SIGMA)), 0.05, 6.0))
        ring = (np.abs(dist - d) <= max(0.1 * d, 0.03)) & (lab >= 0)
        if not ring.any():
            continue                                     # ring falls off the map: redraw
        present = np.bincount(lab[ring], minlength=len(TYPE_ORDER)) > 0
        sh = shares * present
        t = rng.choice(len(TYPE_ORDER), p=sh / sh.sum())
        idx = np.flatnonzero(ring & (lab == t))
        k = rng.choice(idx)
        return (int(k // W), int(k % W)), d, TYPE_ORDER[t], dist
    return None, None, None, dist


def cheapest_route(grid, start, goal, margin=40):
    """Cheapest walking route on the grid (cost = 1 / terrain speed). Not our walker rules."""
    from skimage.graph import MCP_Geometric
    r0, r1 = sorted([start[0], goal[0]]); c0, c1 = sorted([start[1], goal[1]])
    H, W = grid["cls"].shape
    r0, c0 = max(r0 - margin, 0), max(c0 - margin, 0)
    r1, c1 = min(r1 + margin, H - 1), min(c1 + margin, W - 1)
    spd = grid["speed"][r0:r1 + 1, c0:c1 + 1].astype(float)
    cost = np.where(spd > 0, 1.0 / np.maximum(spd, 0.05), np.inf)
    g = (goal[0] - r0, goal[1] - c0)
    cost[g] = 1.0                                   # the truth itself may be in water
    s = (start[0] - r0, start[1] - c0)
    cost[s] = 1.0
    mcp = MCP_Geometric(cost)
    mcp.find_costs([s], [g])
    try:
        path = mcp.traceback(g)
    except Exception:
        return None
    path = np.array(path) + [r0, c0]
    return path if len(path) > 1 else None


def area_before(mask_hotter, cell):
    return mask_hotter.sum() * cell * cell / 1e6


def run_case(args):
    i, start, seed = args
    t_case = time.time()
    grid, lab = _G, _LAB
    cell = float(grid["cell"])
    rng = np.random.default_rng(seed)
    p = sim.load_params(verbose=False)
    truth, d, ftype, dist = place_truth(grid, lab, start, rng, cell)
    if truth is None:
        return None
    ok = lab >= 0
    out = dict(case=i, dist_km=d, type=ftype)

    # A1. rings around the last seen point
    out["rings"] = area_before(ok & (dist <= dist[truth]), cell)

    # A2. ISRID stats map: distance density per area x find-type share / ring share of that type
    dd = np.maximum(dist, 0.02)
    f = np.exp(-(np.log(dd) - D_MU) ** 2 / (2 * D_SIGMA ** 2)) / (dd * D_SIGMA * np.sqrt(2 * np.pi))
    per_area = f / (2 * np.pi * dd)
    band = np.minimum((dist / 0.05).astype(int), 400)
    stats = np.zeros(dist.shape)
    for t_i, t in enumerate(TYPE_ORDER):
        m = lab == t_i
        cnt_t = np.bincount(band[m], minlength=401).astype(float)
        cnt_all = np.bincount(band[ok], minlength=401).astype(float)
        frac = np.where(cnt_all > 0, cnt_t / np.maximum(cnt_all, 1), 0)
        share = sim.ISRID[t] / 100
        stats[m] = per_area[m] * share / np.maximum(frac[band[m]], 1e-9)
    stats[~ok] = 0
    out["stats_map"], _ = infer.truth_rank(grid, stats / stats.sum(), truth)

    # A3. our model, no clues (end positions = where he ends up)
    walks = sim.simulate(grid, start, n=WALKERS, params=p, minutes=MINUTES, seed=seed, spotting=False)
    w = np.ones(WALKERS)
    heat = infer.heatmap(grid, walks, w, floor=FLOOR, center=start)
    out["model"], _ = infer.truth_rank(grid, heat, truth)

    # B. one sighting along an independent route
    route = cheapest_route(grid, start, truth)
    if route is not None:
        step = np.hypot(*np.diff(route, axis=0).T) * cell
        v = 0.62 * np.maximum(grid["speed"][route[1:, 0], route[1:, 1]], 0.3)
        t_min = np.concatenate([[0], np.cumsum(step / v)]) / 60
        k = int(rng.uniform(0.3, 0.7) * (len(route) - 1))
        if 1 <= t_min[k] < MINUTES - 1:
            seen = route[k] + rng.normal(0, SIGHTING_ERR_M / cell, 2)
            seen = np.clip(np.rint(seen).astype(int), 0, np.array(lab.shape) - 1)
            lat, lon = G.cell_to_latlon(grid, int(seen[0]), int(seen[1]))
            hh = 12 * 60 + int(round(t_min[k]))
            clue = {"type": "sighting", "lat": lat, "lon": lon, "time": f"{hh // 60:02d}:{hh % 60:02d}"}
            sr, sc = G.latlon_to_cell(grid, lat, lon)
            H, W = lab.shape
            rr, cc = np.mgrid[0:H, 0:W]
            dist_s = np.hypot(rr - sr, cc - sc)
            out["rings_sighting"] = area_before(ok & (dist_s <= dist_s[truth]), cell)
            # old method (reweight only), kept to show what the restart adds
            w_old = w * infer.clue_likelihood(grid, walks, clue, START_HHMM)
            heat = infer.heatmap(grid, walks, w_old, floor=FLOOR, center=(sr, sc))
            out["model_sighting_reweight"], _ = infer.truth_rank(grid, heat, truth)
            # current method: restart walkers from the sighting (what the app does)
            walks2, w2 = infer.relaunch_from_sighting(grid, walks, w, clue, START_HHMM, p, seed=seed)
            heat = infer.heatmap(grid, walks2, w2, floor=FLOOR, center=(sr, sc))
            out["model_sighting"], _ = infer.truth_rank(grid, heat, truth)
    out["secs"] = time.time() - t_case
    out["start"] = list(start)
    return out


def win_tie_loss(model, base):
    model, base = np.asarray(model), np.asarray(base)
    tie = (model <= TIE_KM2) & (base <= TIE_KM2)
    win = (model < base) & ~tie
    loss = (model >= base) & ~tie
    decided = max(win.sum() + loss.sum(), 1)
    return win.sum(), tie.sum(), loss.sum(), win.sum() / decided * 100


def compare_line(rows, mkey, bkey, bname):
    m = [r[mkey] for r in rows]; b = [r[bkey] for r in rows]
    w, t, l, rate = win_tie_loss(m, b)
    ratio = np.median(np.array(b) / np.maximum(np.array(m), 1e-4))
    return (f"Our model vs {bname}: {w} wins, {t} ties, {l} losses "
            f"(wins {rate:.0f}% of the cases that are not ties). "
            f"Median per case: {ratio:.1f}x less area. "
            f"Total area over all cases: {bname} {sum(b):.0f} km2, our model {sum(m):.0f} km2.")


def by_distance(rows, mkey, bkey, bname):
    out = ["| Distance | Cases | " + bname + " median km2 | Our model median km2 | Wins | Ties | Losses |",
           "|---|---|---|---|---|---|---|"]
    for lo, hi, nm in [(0, 0.5, "< 0.5 km"), (0.5, 1.5, "0.5-1.5 km"), (1.5, 3, "1.5-3 km"), (3, 99, "> 3 km")]:
        sub = [r for r in rows if lo <= r["dist_km"] < hi]
        if sub:
            b = [r[bkey] for r in sub]; m = [r[mkey] for r in sub]
            w, t, l, _ = win_tie_loss(m, b)
            out.append(f"| {nm} | {len(sub)} | {np.median(b):.2f} | {np.median(m):.2f} | {w} | {t} | {l} |")
    return out


def summarize(rows, keys, budgets=(0.25, 0.5, 1.0, 2.0)):
    lines = ["| Method | Median km2 | " + " | ".join(f"Found within {b:g} km2" for b in budgets) + " |",
             "|---|---|" + "---|" * len(budgets)]
    for k, name in keys:
        a = np.array([r[k] for r in rows if k in r])
        cells = [f"{(a <= b).mean() * 100:.0f}%" for b in budgets]
        lines.append(f"| {name} | {np.median(a):.2f} | " + " | ".join(cells) + " |")
    return lines


def main():
    import sys
    global N_CASES
    if len(sys.argv) > 1:
        N_CASES = int(sys.argv[1])
    t0 = time.time()
    grid = G.load()
    p = sim.load_params()
    lab = labels(grid, p)
    sim.traffic_layer(grid)
    sim.drainage_mask(grid, p.drain_tpi)            # cache before sending to workers
    starts = C.pick_starts(grid, k=N_CASES, seed=12345)
    cal = set(C.pick_starts(grid))
    starts = [s for s in starts if s not in cal]
    print(f"{len(starts)} cases (held out from calibration), {WALKERS} walkers each\n")
    workers = max(1, (os.cpu_count() or 2) - 1)
    rows = []
    with ProcessPoolExecutor(max_workers=workers, initializer=_init, initargs=(grid, lab)) as ex:
        for k, r in enumerate(ex.map(run_case, [(i, s, 1000 + i) for i, s in enumerate(starts)]), 1):
            if r:
                rows.append(r)
            if k % 25 == 0:
                print(f"  {k}/{len(starts)} cases, {time.time() - t0:.0f} s")
    json.dump(rows, open("benchmark_results.json", "w"), indent=1)

    A = [("rings", "Rings around last seen (basic instinct)"),
         ("stats_map", "ISRID stats map (ceiling: same recipe as the truths)"),
         ("model", "Our model, no clues")]
    rb = [r for r in rows if "model_sighting" in r]
    B = [("rings_sighting", "Rings around the sighting"),
         ("model_sighting_reweight", "Our model + sighting, reweight only (old)"),
         ("model_sighting", "Our model + sighting, restart from sighting")]
    lines = ["# Benchmark", "",
             f"{len(rows)} cases in Amherst, start points held out from calibration. "
             f"True spots placed with ISRID statistics only (not by our walkers). "
             f"Score = area searched before reaching the truth, most likely cells first.", "",
             "## Test A: no clues", ""] + summarize(rows, A)
    lines += ["", compare_line(rows, "model", "rings", "rings"),
              f"(Tie = both reach the person within {TIE_KM2} km2.)"]
    lines += ["", "### By distance of the truth", ""] + by_distance(rows, "model", "rings", "Rings")
    lines += ["", "### By find type", "", "| Type | Cases | Rings median km2 | Our model median km2 |",
              "|---|---|---|---|"]
    for t in TYPE_ORDER:
        sub = [r for r in rows if r["type"] == t]
        if sub:
            lines.append(f"| {t} | {len(sub)} | {np.median([r['rings'] for r in sub]):.2f} | "
                         f"{np.median([r['model'] for r in sub]):.2f} |")
    if rb:
        lines += ["", "## Test B: one sighting", "", f"{len(rb)} cases with a sighting.", ""] + summarize(rb, B)
        lines += ["", compare_line(rb, "model_sighting", "rings_sighting", "rings around the sighting")]
        lines += ["", "### By distance of the truth", ""] + by_distance(rb, "model_sighting", "rings_sighting",
                                                                      "Rings around sighting")
    slow = sorted(rows, key=lambda r: -r.get("secs", 0))[:3]
    lines += ["", f"Run time {(time.time() - t0) / 60:.0f} min. Slowest cases: " +
              ", ".join(f"#{r['case']} {r['secs']:.0f} s (start {r['start']})" for r in slow)]
    open("benchmark_report.md", "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print("\nSaved benchmark_report.md, benchmark_results.json")
    save_plot(rows, rb)


def save_plot(rows, rb, out="benchmark.png"):
    """Share of cases found vs area searched. Steeper and higher = better."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ink, ink2, grid_c, axis_c, surf = "#0b0b0b", "#52514e", "#e1e0d9", "#c3c2b7", "#fcfcfb"
    blue, orange, aqua = "#2a78d6", "#eb6834", "#1baf7a"     # slots 1-3: model, rings, stats map
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2), dpi=150, facecolor=surf)
    x = np.logspace(-3, 1.3, 300)
    panels = [(axes[0], rows, [("rings", "Rings (basic instinct)", orange, "-"),
                               ("stats_map", "ISRID stats map (ceiling)", aqua, "--"),
                               ("model", "Our model", blue, "-")], "A. No clues"),
              (axes[1], rb, [("rings_sighting", "Rings around sighting", orange, "-"),
                             ("model_sighting", "Our model + sighting", blue, "-")], "B. One sighting")]
    for ax, data, series, title in panels:
        ax.set_facecolor(surf)
        for key, name, col, ls in series:
            a = np.array([r[key] for r in data if key in r])
            if a.size == 0:
                continue
            y = [(a <= v).mean() * 100 for v in x]
            ax.plot(x, y, color=col, lw=2, ls=ls, label=name, solid_capstyle="round")
            i = np.searchsorted(x, np.median(a))
            ax.annotate(name, (x[min(i, len(x) - 1)], 50), xytext=(6, -14 if key.startswith("rings") else 6),
                        textcoords="offset points", color=ink2, fontsize=9)
        ax.set_xscale("log")
        ax.set_xlim(1e-3, 20); ax.set_ylim(0, 100)
        ax.set_xlabel("Area searched before reaching the person (km², log scale)", color=ink2)
        ax.set_ylabel("Cases found (%)", color=ink2)
        ax.set_title(title, loc="left", color=ink, fontsize=12)
        ax.grid(True, color=grid_c, lw=0.6)
        for s in ["top", "right"]:
            ax.spines[s].set_visible(False)
        for s in ["left", "bottom"]:
            ax.spines[s].set_color(axis_c)
        ax.tick_params(colors=ink2)
        ax.legend(frameon=False, loc="upper left", labelcolor=ink2, fontsize=9)
    plt.tight_layout()
    plt.savefig(out, facecolor=surf)
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
