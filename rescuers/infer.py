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
from scipy.ndimage import gaussian_filter

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
    return (h * 60 + m) - (h0 * 60 + m0)


def clue_likelihood(grid, walks, clue, start_hhmm, cp=None):
    """Multiplier for every walker's weight, shape (n,)."""
    cp = cp or ClueParams()
    cell = float(grid["cell"])
    if "lat" in clue:      # "not_reported" has no place
        r, c = G.latlon_to_cell(grid, clue["lat"], clue["lon"])
    T = walks.minutes
    pos = walks.pos

    if clue["type"] == "sighting":
        t = to_minute(clue["time"], start_hhmm)
        lo, hi = int(max(0, t - cp.sighting_window_min)), int(min(T, t + cp.sighting_window_min))
        seg = pos[:, lo:hi + 1]
        d = np.hypot(seg[..., 0] - r, seg[..., 1] - c).min(1) * cell
        return cp.reliability * np.exp(-d ** 2 / (2 * cp.sighting_err_m ** 2)) + (1 - cp.reliability) * 0.05

    if clue["type"] == "camera_negative":
        lo, hi = [int(np.clip(to_minute(x, start_hhmm), 0, T)) for x in clue["window"]]
        seg = pos[:, lo:hi + 1]
        d = np.hypot(seg[..., 0] - r, seg[..., 1] - c).min(1) * cell
        return np.where(d <= cp.camera_range_m, cp.camera_miss, 1.0)

    if clue["type"] == "area_searched":
        t = clue.get("time")
        m = T if t is None else int(np.clip(to_minute(t, start_hhmm), 0, T))
        d = np.hypot(pos[:, m, 0] - r, pos[:, m, 1] - c) * cell
        return np.where(d <= clue.get("radius_m", 150), 1 - cp.pod, 1.0)

    if clue["type"] == "not_reported":
        t = clue.get("time")
        m = T if t is None else int(np.clip(to_minute(t, start_hhmm), 0, T))
        traffic = sim.traffic_layer(grid)
        H, W = traffic.shape
        rr = np.clip(np.rint(pos[:, 1:m + 1, 0]).astype(int), 0, H - 1)
        cc = np.clip(np.rint(pos[:, 1:m + 1, 1]).astype(int), 0, W - 1)
        p_spot = walks.params.get("p_spot", sim.Params().p_spot)
        rate = np.clip(p_spot * traffic[rr, cc], 0, 0.999)
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
    new = sim.Walks(pos=pos, end=end, reason=walks.reason[idx], kind=walks.kind[idx],
                    speed=walks.speed[idx], mobility_min=walks.mobility_min[idx],
                    heading0=walks.heading0[idx], minutes=walks.minutes, start=walks.start,
                    params=walks.params)
    return new, np.ones(n)


def heatmap(grid, walks, w, minute=None, smooth_cells=2.0):
    """Probability per cell (sums to 1) of where the person is at `minute` (default: end)."""
    H, W = grid["cls"].shape
    m = walks.minutes if minute is None else minute
    rr = np.clip(np.rint(walks.pos[:, m, 0]).astype(int), 0, H - 1)
    cc = np.clip(np.rint(walks.pos[:, m, 1]).astype(int), 0, W - 1)
    heat = np.zeros((H, W))
    np.add.at(heat, (rr, cc), w)
    heat = gaussian_filter(heat, smooth_cells)
    heat[grid["cls"] == G.OUTSIDE] = 0
    blocked = np.isin(grid["cls"], [G.BUILDING, G.BARRIER])
    heat[blocked] = 0
    return heat / heat.sum()


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

    def record(label):
        heat = heatmap(grid, walks, w, minute=now)
        area, mass = truth_rank(grid, heat, truth)
        stages.append((label, heat))
        print(f"{label:<34} search area to reach truth: {area:6.2f} km2   "
              f"({mass * 100:4.1f}% of probability)   walkers that count: {ess(w):7.0f}")

    print(f"{n} walkers. Map shows where Walter is likely at 21:00.\n")
    record("No clues")
    for clue in case["clues"]:
        clue = dict(clue)
        if clue["type"] == "area_searched" and "time" not in clue:
            clue["time"] = clue.get("entered_at", "21:00")
        w = w * clue_likelihood(grid, walks, clue, start_hhmm)
        if ess(w) < n / 2:
            walks, w = resample(walks, w, rng)
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
