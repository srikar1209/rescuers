"""
Diagnostic: WHY are walker distances short?

Run from the repo root:   python -m rescuers.diagnose
Uses the calibrated parameters and the same 20 start points as calibrate.py.
Output: tables in the terminal + diagnose_report.md + diagnose_paths.png

What it measures for every walker:
  straight   distance from start to end (what ISRID measures)
  path       length of the walked path
  winding    path / straight (1 = perfectly straight)
  bounces    times all 3 cells ahead were blocked and the walker turned 30-90 degrees
  walk time  minutes the walker was moving
"""

import numpy as np
from scipy import ndimage

from rescuers import grid as G
from rescuers import sim
from rescuers import calibrate as C

N_PER_START = 400


def run(grid, params, starts, n=N_PER_START):
    cell = float(grid["cell"])
    cls = grid["cls"]
    bld = (cls == G.BUILDING).astype(float)
    # share of building cells within 300 m: town vs rural start
    density = ndimage.uniform_filter(bld, size=61)
    rows = []
    for i, s in enumerate(starts):
        w = sim.simulate(grid, s, n=n, params=params, minutes=C.MINUTES, seed=1 + i)
        pos = w.pos.astype(float)
        step = np.hypot(*np.diff(pos, axis=1).transpose(2, 0, 1)) * cell        # (n, T) m per minute
        path = step.sum(1) / 1000
        moving = step > 1.0
        walk_min = moving.sum(1)
        straight = np.hypot(*(w.end - np.array(s)).T) * cell / 1000
        # on a road for more than half of the moving minutes = road follower
        rr = np.clip(np.rint(pos[:, 1:, 0]).astype(int), 0, cls.shape[0] - 1)
        cc = np.clip(np.rint(pos[:, 1:, 1]).astype(int), 0, cls.shape[1] - 1)
        on_road = np.isin(cls[rr, cc], [G.ROAD, G.PATH]) & moving
        road_share = on_road.sum(1) / np.maximum(walk_min, 1)
        group = np.where(w.kind == 1, "random",
                         np.where(road_share > 0.5, "direction, road follower", "direction, off road"))
        dem = np.where(np.isnan(grid["dem"]), np.nanmean(grid["dem"]), grid["dem"])
        dz = dem[w.end[:, 0], w.end[:, 1]] - dem[s]
        rows.append(dict(straight=straight, path=path, walk_min=walk_min, bounces=w.bounces,
                         group=group, reason=w.reason, mobility=w.mobility_min, dz=dz,
                         speed=w.speed, town=np.full(n, density[s] > 0.05), start=np.full(n, i)))
    return {k: np.concatenate([r[k] for r in rows]) for k in rows[0]}, rows


def table(title, header, lines):
    out = [f"\n## {title}\n", "| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(str(x) for x in ln) + " |" for ln in lines]
    txt = "\n".join(out)
    print(txt)
    return txt


def summarize(d, mask):
    m = mask & (d["walk_min"] > 0)
    if m.sum() == 0:
        return ["-"] * 6
    wind = d["path"][m] / np.maximum(d["straight"][m], 0.01)
    return [f"{mask.mean() * 100:.0f}%",
            f"{np.median(d['straight'][mask]):.2f}",
            f"{np.median(d['path'][m]):.2f}",
            f"{np.median(wind):.1f}",
            f"{np.median(d['bounces'][mask]):.0f}",
            f"{np.median(d['walk_min'][mask]):.0f}"]


def main():
    grid = G.load()
    params = sim.load_params()
    starts = C.pick_starts(grid)
    print(f"{len(starts)} starts x {N_PER_START} walkers\n")
    d, _ = run(grid, params, starts)
    H = ["Group", "Share", "Straight km (median)", "Path km", "Winding", "Bounces", "Walk min"]
    parts = []

    groups = ["direction, off road", "direction, road follower", "random"]
    parts.append(table("1. By walker type", H,
                       [[g] + summarize(d, d["group"] == g) for g in groups] +
                       [["ALL"] + summarize(d, np.ones_like(d["town"]))]))

    parts.append(table("2. Town vs rural start (town = >5% buildings within 300 m)", H,
                       [["town"] + summarize(d, d["town"]), ["rural"] + summarize(d, ~d["town"])]))

    parts.append(table("3. By stop reason", H,
                       [[sim.REASONS[i]] + summarize(d, d["reason"] == i)
                        for i in range(1, len(sim.REASONS)) if (d["reason"] == i).any()]))

    edges = [0, 10, 60, 180, 360, 1e9]
    names = ["< 10 min", "10-60 min", "1-3 h", "3-6 h", "> 6 h (cut at 6 h)"]
    parts.append(table("4. By walking time", H,
                       [[nm] + summarize(d, (d["mobility"] >= a) & (d["mobility"] < b))
                        for nm, a, b in zip(names, edges[:-1], edges[1:])]))

    # time budget: where did the walking time go?
    moved = d["walk_min"] > 0
    ideal_km = d["walk_min"][moved] * 60 * d["speed"][moved] / 1000      # path if flat and paved
    lost = 1 - d["path"][moved] / np.maximum(ideal_km, 1e-6)
    bounce_min = d["bounces"][moved] * 5 / 60
    parts.append(table("5. Time budget (walkers that moved)", ["Measure", "Median"], [
        ["Walk time, min", f"{np.median(d['walk_min'][moved]):.0f}"],
        ["Path if flat and paved, km", f"{np.median(ideal_km):.2f}"],
        ["Actual path, km", f"{np.median(d['path'][moved]):.2f}"],
        ["Path lost to slow terrain, slope and bounces", f"{np.median(lost) * 100:.0f}%"],
        ["Minutes spent bouncing (5 s each)", f"{np.median(bounce_min):.1f}"],
    ]))

    dz = np.abs(d["dz"])
    parts.append(table("6. Elevation change start -> end (ISRID 'same' = 39%)",
                       ["Threshold", "Share 'same'"],
                       [[f"within {t} m", f"{(dz <= t).mean() * 100:.0f}%"] for t in [2, 5, 10, 20]]))

    open("diagnose_report.md", "w").write("# Distance diagnostic\n" + "\n".join(parts) + "\n")
    print("\nSaved diagnose_report.md")
    save_paths(grid, params, starts)


def save_paths(grid, params, starts, out="diagnose_paths.png", pad=120, show=60):
    """Sample paths from 2 town starts and 2 rural starts, colored by walker type."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap, BoundaryNorm
    cls = grid["cls"]
    density = ndimage.uniform_filter((cls == G.BUILDING).astype(float), size=61)
    order = np.argsort([density[s] for s in starts])
    pick = [starts[i] for i in list(order[-2:]) + list(order[:2])]
    labels = ["town", "town", "rural", "rural"]
    colors = ["#ecebb0", "#f2a541", "#ffffff", "#333333", "#1f5fa8", "#c7d97a",
              "#7fb069", "#6fb7a0", "#c0392b", "#8e6bbf", "#e3dccb", "#5aa9e6"]
    fig, axes = plt.subplots(1, 4, figsize=(24, 6.5), dpi=100)
    for ax, s, lab in zip(axes, pick, labels):
        w = sim.simulate(grid, s, n=show, params=params, minutes=C.MINUTES, seed=5)
        r0, c0 = s
        rs, cs = slice(max(r0 - pad, 0), r0 + pad), slice(max(c0 - pad, 0), c0 + pad)
        sub = cls[rs, cs].astype(float)
        sub[sub == G.OUTSIDE] = np.nan
        ax.imshow(sub, cmap=ListedColormap(colors), interpolation="nearest",
                  norm=BoundaryNorm(np.arange(-0.5, len(colors) + 0.5), len(colors)), alpha=0.7)
        for i in range(show):
            col = "#1f77b4" if w.kind[i] == 0 else "#d62728"
            ax.plot(w.pos[i, :, 1] - cs.start, w.pos[i, :, 0] - rs.start, lw=0.8, alpha=0.7, c=col)
        ax.scatter(c0 - cs.start, r0 - rs.start, s=200, marker="*", c="k", zorder=5)
        ax.set_xlim(0, sub.shape[1]); ax.set_ylim(sub.shape[0], 0)
        ax.set_title(f"{lab} start  (blue = direction, red = random)")
        ax.axis("off")
    plt.tight_layout()
    plt.savefig(out)
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
