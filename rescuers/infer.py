"""
Inverse step: clues -> walker weights -> search heat map.

Run from the repo root:   python -m rescuers.infer
Output: how the hidden truth ranks before and after each clue, and infer_preview.png

Clue rules (Model Rules Spec, section 6). All values are ASSUMPTIONS; weights never go to 0
because witnesses and cameras make mistakes.
  sighting          closest approach d to the place within time +/- window:
                    w *= reliability * exp(-d^2 / (2 * err^2)) + (1 - reliability) * 0.05
  camera_negative   passed within camera range during the window: w *= miss_rate
  area_searched     inside the area at search time: w *= (1 - POD)
  not_reported      still missing at `time`, so nobody saw him on a road. For every minute on a
                    road or path: w *= (1 - p_spot * traffic). p_spot is the calibrated value.
"""

import json
from dataclasses import dataclass
import numpy as np

from rescuers import grid as G
from rescuers import sim


@dataclass
class ClueParams:
    sighting_err_m: float = 100.0      # how far off a witness's location can be
    sighting_window_min: float = 10.0  # +/- minutes around the reported time
    reliability: float = 0.8           # chance the witness saw the right person
    camera_range_m: float = 30.0
    camera_miss: float = 0.1           # camera fails to catch someone who passed
    pod: float = 0.7                   # probability of detection for a hasty search


def to_minute(hhmm, start_hhmm):
    h, m = map(int, hhmm.split(":"))
    h0, m0 = map(int, start_hhmm.split(":"))
    return ((h * 60 + m) - (h0 * 60 + m0)) % (24 * 60)   # works across midnight


def clue_likelihood(grid, walks, clue, start_hhmm, cp=None):
    """Multiplier for every walker's weight, shape (n,)."""
    cp = cp or ClueParams()
    cell = float(grid["cell"])
    if "lat" in clue:      # "not_reported" has no place
        r, c = G.latlon_to_cell(grid, clue["lat"], clue["lon"])
    T = walks.minutes
    pos = walks.pos
    n = pos.shape[0]
    born = walks.born if walks.born is not None else np.zeros(n, dtype=int)

    def masked_min_dist(lo, hi):
        """Closest approach in minutes lo..hi, ignoring minutes before a walker was born."""
        seg = pos[:, lo:hi + 1]
        d = np.hypot(seg[..., 0] - r, seg[..., 1] - c) * cell
        d[np.arange(lo, hi + 1)[None, :] < born[:, None]] = np.inf
        return d.min(1)

    if clue["type"] == "sighting":
        t = to_minute(clue["time"], start_hhmm)
        if not 0 <= t <= T:
            raise ValueError("Sighting is outside the simulation window")
        lo, hi = int(max(0, t - cp.sighting_window_min)), int(min(T, t + cp.sighting_window_min))
        d = masked_min_dist(lo, hi)
        rel = clue.get("reliability", cp.reliability)     # per clue, from the LLM (high/medium/low)
        return rel * np.exp(-d ** 2 / (2 * cp.sighting_err_m ** 2)) + (1 - rel) * 0.05

    if clue["type"] == "camera_negative":
        lo, hi = [to_minute(x, start_hhmm) for x in clue["window"]]
        if not 0 <= lo <= hi <= T:
            raise ValueError("Camera window is outside the simulation window")
        d = masked_min_dist(lo, hi)
        return np.where(d <= clue.get("range_m", cp.camera_range_m),
                        clue.get("miss_rate", cp.camera_miss), 1.0)

    if clue["type"] == "area_searched":
        t = clue.get("time")
        m = T if t is None else to_minute(t, start_hhmm)
        if not 0 <= m <= T:
            raise ValueError("Search completion is outside the simulation window")
        d = np.hypot(pos[:, m, 0] - r, pos[:, m, 1] - c) * cell
        return np.where((d <= clue.get("radius_m", 150)) & (born <= m),
                        1 - clue.get("pod", cp.pod), 1.0)

    if clue["type"] == "not_reported":
        t = clue.get("time")
        m = T if t is None else int(np.clip(to_minute(t, start_hhmm), 0, T))
        traffic = sim.traffic_layer(grid)
        H, W = traffic.shape
        rr = np.clip(np.rint(pos[:, 1:m + 1, 0]).astype(int), 0, H - 1)
        cc = np.clip(np.rint(pos[:, 1:m + 1, 1]).astype(int), 0, W - 1)
        p_spot = walks.params.get("p_spot", sim.Params().p_spot)
        rate = np.clip(p_spot * traffic[rr, cc], 0, 0.999)
        rate[np.arange(1, m + 1)[None, :] <= born[:, None]] = 0     # not there yet
        return np.exp(np.log1p(-rate).sum(1))

    raise ValueError(f"Unknown clue type: {clue['type']}")


def ess(w):
    """Effective sample size: how many walkers still really count."""
    w = w / w.sum()
    return 1.0 / np.sum(w ** 2)


def resample(walks, w, rng, jitter_cells=1.0):
    """
    When too few walkers carry the weight, copy the good ones and shift each copy slightly,
    so the map stays smooth. Returns new walks and equal weights.
    """
    n = len(w)
    p = w / w.sum()
    idx = rng.choice(n, size=n, p=p)
    shift = rng.normal(0, jitter_cells, (n, 1, 2)).astype(np.float32)
    pos = walks.pos[idx] + shift
    end = np.rint(pos[:, -1]).astype(int)
    pick = lambda a: None if a is None else a[idx]
    new = sim.Walks(pos=pos, end=end, reason=walks.reason[idx], kind=walks.kind[idx],
                    speed=walks.speed[idx], mobility_min=walks.mobility_min[idx],
                    heading0=walks.heading0[idx], minutes=walks.minutes, start=walks.start,
                    params=walks.params, bounces=pick(walks.bounces), born=pick(walks.born))
    return new, np.ones(n)


def relaunch_from_sighting(grid, walks, w, clue, start_hhmm, params=None, n_new=None, seed=0,
                           cp=None):
    """
    A sighting says: he was HERE at THIS time. Reweighting walkers from home is not enough when
    few of them passed there (far sightings). So we also launch new walkers from the sighting
    point, with the same calibrated rules, heading the way he was going (last seen -> sighting),
    and only the walking time he has left. (Particle-filter "rejuvenation".)

    Result = reliability x (walkers that fit the sighting: old ones that passed there + new ones,
                            pooled by how many effective walkers each group has)
           + (1 - reliability) x (old walkers with their weights before this clue: witness wrong)
    """
    cp = cp or ClueParams()
    p = params or sim.Params(**walks.params)
    cell = float(grid["cell"])
    T = walks.minutes
    t = to_minute(clue["time"], start_hhmm)
    if t <= 0 or t >= T - 1:
        return walks, w * clue_likelihood(grid, walks, clue, start_hhmm, cp)
    rel = clue.get("reliability", cp.reliability)
    n_new = n_new or max(len(w) // 2, 1000)
    r, c = G.latlon_to_cell(grid, clue["lat"], clue["lon"])
    r0, c0 = walks.start
    head = float(np.degrees(np.arctan2(c - c0, -(r - r0))) % 360) if (r, c) != (r0, c0) else None

    nw = sim.simulate(grid, (r, c), n=n_new, params=p, minutes=T - t, heading=head,
                      heading_sd=30.0, seed=seed, spotting=False, walked_min=float(t))
    rng = np.random.default_rng(seed)
    # the witness place is uncertain: shift each new path by the sighting error
    shift = rng.normal(0, cp.sighting_err_m / cell, (n_new, 1, 2)).astype(np.float32)
    pos_new = np.empty((n_new, T + 1, 2), dtype=np.float32)
    pos_new[:, t:] = nw.pos + shift
    pos_new[:, :t] = pos_new[:, t:t + 1]          # unknown before the sighting
    H, W = grid["cls"].shape
    end_new = np.clip(np.rint(pos_new[:, -1]).astype(int), 0, [H - 1, W - 1])

    # old walkers that fit the sighting (the "witness right" part of the usual clue)
    tt = int(t)
    lo, hi = int(max(0, tt - cp.sighting_window_min)), int(min(T, tt + cp.sighting_window_min))
    seg = walks.pos[:, lo:hi + 1]
    d = np.hypot(seg[..., 0] - r, seg[..., 1] - c).min(1) * cell
    fit = w * np.exp(-d ** 2 / (2 * cp.sighting_err_m ** 2))
    prior = w / w.sum()
    ess_fit = ess(fit) if fit.sum() > 0 else 0.0
    share_new = n_new / (n_new + ess_fit)
    w_old = (1 - rel) * prior + (rel * (1 - share_new) * fit / fit.sum() if fit.sum() > 0 else 0)
    w_new = np.full(n_new, rel * share_new / n_new)

    cat = lambda a, b: None if a is None or b is None else np.concatenate([a, b])
    born_old = walks.born if walks.born is not None else np.zeros(len(w), dtype=np.int32)
    out = sim.Walks(pos=np.concatenate([walks.pos, pos_new]), end=np.concatenate([walks.end, end_new]),
                    reason=np.concatenate([walks.reason, nw.reason]), kind=np.concatenate([walks.kind, nw.kind]),
                    speed=np.concatenate([walks.speed, nw.speed]),
                    mobility_min=np.concatenate([walks.mobility_min, nw.mobility_min + t]),
                    heading0=np.concatenate([walks.heading0, nw.heading0]), minutes=T,
                    start=walks.start, params=walks.params, bounces=cat(walks.bounces, nw.bounces),
                    born=np.concatenate([born_old, np.full(n_new, tt, dtype=np.int32)]))
    return out, np.concatenate([w_old, w_new])


def apply_clue(grid, walks, w, clue, start_hhmm, params=None, seed=0, rng=None):
    """
    One call per clue for the app. Sightings restart walkers from the sighting place;
    other clues reweight. Resamples when too few walkers carry the weight.
    Returns (walks, w).
    """
    if clue["type"] == "sighting" and clue.get("time"):
        walks, w = relaunch_from_sighting(grid, walks, w, clue, start_hhmm, params, seed=seed)
    else:
        w = w * clue_likelihood(grid, walks, clue, start_hhmm)
    if ess(w) < len(w) / 2:
        walks, w = resample(walks, w, rng or np.random.default_rng(seed))
    return walks, w / w.mean()


def ring_prior(grid, center):
    """ISRID distance rings around `center` (row, col): probability per cell, sums to 1."""
    H, W = grid["cls"].shape
    rr, cc = np.ogrid[0:H, 0:W]
    d = np.maximum(np.hypot(rr - center[0], cc - center[1]) * float(grid["cell"]) / 1000, 0.02)
    f = np.exp(-(np.log(d) - sim.DIST_MU) ** 2 / (2 * sim.DIST_SIGMA ** 2)) / (d * sim.DIST_SIGMA)
    prior = f / d
    prior[np.isin(grid["cls"], [G.OUTSIDE, G.BUILDING, G.BARRIER])] = 0
    return prior / prior.sum()


def heatmap(grid, walks, w, minute=None, smooth_cells=2.0, floor=0.05, center=None):
    """
    Probability per cell (sums to 1) of where the person is at `minute` (default: end).
    floor: share given to ISRID distance rings around `center` (default: last seen place;
    after a sighting, pass the sighting place). Walkers never cover every cell, so no place
    is ever zero, and where walkers did not go the map falls back to rings, like a searcher.
    """
    H, W = grid["cls"].shape
    m = walks.minutes if minute is None else minute
    rr = np.clip(np.rint(walks.pos[:, m, 0]).astype(int), 0, H - 1)
    cc = np.clip(np.rint(walks.pos[:, m, 1]).astype(int), 0, W - 1)
    heat = np.zeros((H, W), dtype=np.float32)
    np.add.at(heat, (rr, cc), w)
    if smooth_cells > 0:          # Gaussian blur in plain NumPy (no SciPy needed in the UI)
        radius = max(1, int(np.ceil(3 * smooth_cells)))
        axis = np.arange(-radius, radius + 1)
        kernel = np.exp(-0.5 * (axis / smooth_cells) ** 2)
        kernel /= kernel.sum()
        padded = np.pad(heat, ((radius, radius), (0, 0)), mode="reflect")
        heat = sum(kernel[i] * padded[i:i + H] for i in range(len(kernel)))
        padded = np.pad(heat, ((0, 0), (radius, radius)), mode="reflect")
        heat = sum(kernel[i] * padded[:, i:i + W] for i in range(len(kernel)))
    heat[grid["cls"] == G.OUTSIDE] = 0
    heat[np.isin(grid["cls"], [G.BUILDING, G.BARRIER])] = 0   # kept: the benchmark was run this way
    total = heat.sum()
    if total <= 0:
        raise ValueError("No walker probability remains within the Amherst grid")
    heat = heat / total
    if floor > 0:
        heat = (1 - floor) * heat + floor * ring_prior(grid, center or walks.start)
    return heat


def truth_rank(grid, heat, truth_rc, radius_cells=3):
    """
    Search the hottest cells first. How much area until we reach the true spot?
    Returns (area km2, share of probability searched before reaching it).
    """
    r, c = truth_rc
    target = heat[max(r - radius_cells, 0):r + radius_cells + 1,
                  max(c - radius_cells, 0):c + radius_cells + 1].max()
    hotter = heat >= target
    cell = float(grid["cell"])
    return hotter.sum() * cell * cell / 1e6, heat[hotter].sum()


def run_demo(n=20000, seed=7, minutes=240):
    rng = np.random.default_rng(seed)
    grid = G.load()
    case = json.load(open(G.D + "demo_case.json"))
    start_hhmm = case["start"]["last_seen_time"]
    start = G.latlon_to_cell(grid, case["start"]["lat"], case["start"]["lon"])
    truth = G.latlon_to_cell(grid, case["hidden_truth"]["lat"], case["hidden_truth"]["lon"])
    now = int(np.clip(to_minute("21:00", start_hhmm), 0, minutes))

    params = sim.load_params()
    walks = sim.simulate(grid, start, n=n, minutes=minutes, seed=seed, params=params, spotting=False)
    w = np.ones(n)
    stages = []
    center = [start]

    def record(label):
        heat = heatmap(grid, walks, w, minute=now, center=center[0])
        area, mass = truth_rank(grid, heat, truth)
        stages.append((label, heat))
        print(f"{label:<34} search area to reach truth: {area:7.3f} km2   "
              f"({mass * 100:4.1f}% of probability)   walkers that count: {ess(w):7.0f}")

    print(f"{n} walkers. Map shows where Walter is likely at 21:00.\n")
    record("No clues")
    for clue in case["clues"]:
        clue = dict(clue)
        if clue["type"] == "area_searched" and "time" not in clue:
            clue["time"] = clue.get("entered_at", "21:00")
        walks, w = apply_clue(grid, walks, w, clue, start_hhmm, params, seed=seed, rng=rng)
        if clue["type"] == "sighting":
            center[0] = G.latlon_to_cell(grid, clue["lat"], clue["lon"])
        record(f"After clue {clue['id']} ({clue['type']})")
    w = w * clue_likelihood(grid, walks, {"type": "not_reported", "time": "21:00"}, start_hhmm)
    record("Still missing (not reported)")

    save_preview(grid, stages, start, truth, case)
    return grid, walks, w


def save_preview(grid, stages, start, truth, case, out="infer_preview.png", pad=130):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap, BoundaryNorm
    r0, c0 = start
    rs, cs = slice(max(r0 - pad, 0), r0 + pad), slice(max(c0 - pad, 0), c0 + pad)
    ro, co = rs.start, cs.start
    colors = ["#ecebb0", "#f2a541", "#ffffff", "#333333", "#1f5fa8", "#c7d97a",
              "#7fb069", "#6fb7a0", "#c0392b", "#8e6bbf", "#e3dccb", "#5aa9e6"]
    sub = grid["cls"][rs, cs].astype(float)
    sub[sub == G.OUTSIDE] = np.nan
    fig, axes = plt.subplots(1, len(stages), figsize=(6 * len(stages), 6.5), dpi=110)
    for ax, (label, heat) in zip(np.atleast_1d(axes), stages):
        ax.imshow(sub, cmap=ListedColormap(colors), norm=BoundaryNorm(np.arange(-0.5, len(colors) + 0.5), len(colors)),
                  interpolation="nearest", alpha=0.6)
        h = heat[rs, cs].copy()
        # show the hottest cells holding 80% of the probability
        flat = np.sort(h.ravel())[::-1]
        cut = flat[np.searchsorted(np.cumsum(flat), 0.8 * flat.sum())]
        h[h < cut] = np.nan
        ax.imshow(np.sqrt(h), cmap="hot_r", alpha=0.85, interpolation="bilinear")
        ax.scatter(c0 - co, r0 - ro, s=250, marker="*", c="#d62728", edgecolors="white", zorder=5)
        for clue in case["clues"]:
            r, c = G.latlon_to_cell(grid, clue["lat"], clue["lon"])
            ax.scatter(c - co, r - ro, s=90, marker="o", facecolors="none",
                       edgecolors="#1f4e9c", linewidths=2, zorder=5)
        ax.scatter(truth[1] - co, truth[0] - ro, s=180, marker="X", c="black",
                   edgecolors="white", zorder=6)
        ax.set_xlim(0, sub.shape[1]); ax.set_ylim(sub.shape[0], 0)
        ax.set_title(label, fontsize=13)
        ax.axis("off")
    fig.suptitle("Hot zone = cells holding 80% of the probability.  Star = last seen.  "
                 "Circles = clue places.  X = hidden truth.", fontsize=12)
    plt.tight_layout()
    plt.savefig(out)
    print(f"\nSaved {out}")


if __name__ == "__main__":
    run_demo()
