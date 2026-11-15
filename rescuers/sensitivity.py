"""
Sensitivity check: change ONE rule number at a time and see what moves.

Run from the repo root:   python -m rescuers.sensitivity
Takes about 5 to 10 minutes. Output: sensitivity_report.md and sensitivity.png

For every tuned knob: -50% and +50% of its calibrated value (kept inside its calibration range).
For DATA values (walking speed, 66% road crossing): -20% and +20%, a plausible data error.
Everything else stays at the calibrated values. Same 20 start points and the same random seeds
as calibration, so differences come from the change, not from luck.
"""

import time
import os
from dataclasses import asdict
from concurrent.futures import ProcessPoolExecutor
import numpy as np

from rescuers import grid as G
from rescuers import sim
from rescuers import calibrate as C

TUNED_STEP = 0.5
DATA_STEP = 0.2
DATA_KNOBS = {"speed_mean": (0.3, 1.1), "p_cross_road": (0.3, 0.95)}


def _job(args):
    name, side, d, starts = args
    st = C.measure(d, starts)
    return name, side, st, C.score(st)


def changed(base, k, factor, lo, hi):
    d = dict(base)
    v = base[k] * factor
    if base[k] == 0:                       # e.g. return_deg near 0: step by 10% of the range
        v = (hi - lo) * 0.1 * (1 if factor > 1 else 0)
    d[k] = float(np.clip(v, lo, hi))
    return d


def main():
    t0 = time.time()
    grid = G.load()
    C._init(grid)
    starts = C.pick_starts(grid)
    base = asdict(sim.load_params())
    knobs = {k: (lo, hi, TUNED_STEP, "tuned") for k, (lo, hi) in C.KNOBS.items()}
    knobs.update({k: (lo, hi, DATA_STEP, "DATA") for k, (lo, hi) in DATA_KNOBS.items()})
    jobs = [("calibrated", "", base, starts)]
    for k, (lo, hi, step, _) in knobs.items():
        jobs.append((k, "low", changed(base, k, 1 - step, lo, hi), starts))
        jobs.append((k, "high", changed(base, k, 1 + step, lo, hi), starts))
    print(f"{len(jobs)} runs ({len(knobs)} knobs x 2 + calibrated), {len(starts)} starts x "
          f"{C.WALKERS_PER_START} walkers each\n")
    workers = max(1, (os.cpu_count() or 2) - 1)
    with ProcessPoolExecutor(max_workers=workers, initializer=C._init, initargs=(grid,)) as ex:
        out = list(ex.map(_job, jobs))
    base_st, base_score = out[0][2], out[0][3]
    res = {}
    for name, side, st, sc in out[1:]:
        res.setdefault(name, {})[side] = (st, sc)

    def moved(st):
        """Statistics that moved the most vs calibrated (in the score's own units)."""
        diffs = []
        for k in sim.ISRID:
            if k in C.SHARE_KEYS:
                d, unit = st[k] - base_st[k], "pts"
                size = abs(d) / 10
            else:
                d, unit = st[k] - base_st[k], ""
                size = abs(d) / max(sim.ISRID[k], 1e-6)
            diffs.append((size, f"{k} {d:+.1f}{unit}"))
        top = [(z, s) for z, s in sorted(diffs, reverse=True)[:2] if z > 0.005]
        return [s for _, s in top] or ["nothing"]

    rows = []
    for k, (lo, hi, step, kind) in knobs.items():
        (st_l, sc_l), (st_h, sc_h) = res[k]["low"], res[k]["high"]
        impact = max(abs(sc_l - base_score), abs(sc_h - base_score))
        rows.append((impact, k, kind, step, sc_l, sc_h, moved(st_l), moved(st_h)))
    rows.sort(reverse=True)

    lines = ["# Sensitivity check", "",
             f"Calibrated score: {base_score:.2f} (lower = closer to ISRID). Each row changes ONE "
             f"number; everything else stays calibrated. Tuned knobs: -{TUNED_STEP:.0%} / "
             f"+{TUNED_STEP:.0%}. DATA values: -{DATA_STEP:.0%} / +{DATA_STEP:.0%}.", "",
             "| Rule number | Kind | Score if lower | Score if higher | What moves most (lower) | "
             "What moves most (higher) |", "|---|---|---|---|---|---|"]
    for impact, k, kind, step, sl, sh, ml, mh in rows:
        lines.append(f"| {k} | {kind} | {sl:.2f} ({sl - base_score:+.2f}) | {sh:.2f} "
                     f"({sh - base_score:+.2f}) | {', '.join(ml)} | {', '.join(mh)} |")
    strong = [r[1] for r in rows if r[0] >= 1.0]
    weak = [r[1] for r in rows if r[0] < 0.3]
    lines += ["", f"Rules that matter most (score changes by 1 or more): {', '.join(strong) or 'none'}.",
              f"Rules with little effect (under 0.3): {', '.join(weak) or 'none'}.",
              "", f"Run time {(time.time() - t0) / 60:.0f} min."]
    open("sensitivity_report.md", "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    save_plot(rows, base_score)


def save_plot(rows, base_score, out="sensitivity.png"):
    """Tornado chart: how far the score moves when each number goes down or up."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ink, ink2, grid_c, axis_c, surf = "#0b0b0b", "#52514e", "#e1e0d9", "#c3c2b7", "#fcfcfb"
    blue, orange = "#2a78d6", "#eb6834"          # slot 1 = lower, slot 2 = higher
    rows = rows[::-1]
    y = np.arange(len(rows))
    fig, ax = plt.subplots(figsize=(9, 0.38 * len(rows) + 1.4), dpi=150, facecolor=surf)
    ax.set_facecolor(surf)
    lo = [r[4] - base_score for r in rows]
    hi = [r[5] - base_score for r in rows]
    ax.barh(y + 0.2, lo, height=0.36, color=blue, label="number lower", edgecolor=surf, linewidth=1)
    ax.barh(y - 0.2, hi, height=0.36, color=orange, label="number higher", edgecolor=surf, linewidth=1)
    ax.set_yticks(y)
    ax.set_yticklabels([f"{r[1]}{' (DATA)' if r[2] == 'DATA' else ''}" for r in rows], color=ink2, fontsize=9)
    ax.axvline(0, color=axis_c, lw=1)
    ax.set_xlabel(f"Change in score vs calibrated ({base_score:.2f}); right = worse fit to ISRID", color=ink2)
    ax.set_title("Which rule numbers matter", loc="left", color=ink, fontsize=12)
    ax.grid(True, axis="x", color=grid_c, lw=0.6)
    for s in ["top", "right", "left"]:
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(axis_c)
    ax.tick_params(colors=ink2)
    ax.legend(frameon=False, loc="lower right", labelcolor=ink2, fontsize=9)
    plt.tight_layout()
    plt.savefig(out, facecolor=surf)
    print(f"Saved {out}")


if __name__ == "__main__":
    main()
