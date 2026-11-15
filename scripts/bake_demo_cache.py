"""Bake the fictional demo's 5,000 paths and displayed minutes 0–150.

Run from the repository root: python scripts/bake_demo_cache.py
The artifacts are exact derivatives of the committed grid, rules, and demo inputs.
They contain no fictional outcome. Custom cases and accepted clues still compute live.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'ui'))

import model_service as model
import serve
from rescuers import grid as G, infer, sim


def write_zip(archive, name, payload):
    info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    archive.writestr(info, payload)


def main():
    demo = model.demo_case()
    start = demo['start']
    grid = model.model_grid()
    start_rc = G.latlon_to_cell(grid, start['lat'], start['lon'])
    params = sim.load_params(str(ROOT / 'data/calibrated_params.json'), verbose=False)
    walks = sim.simulate(grid, start_rc, n=5000, minutes=model.HORIZON,
                         heading=None, goal=None, seed=42, params=params, spotting=False)
    baseline = infer.clue_likelihood(grid, walks,
        {'type': 'not_reported', 'time': '21:00'}, start['last_seen_time'])
    baseline = np.maximum(baseline, np.finfo(np.float64).tiny)
    baseline /= baseline.sum()
    signature = model.demo_signature()

    walks_file = model.DEMO_WALKS.with_suffix('.npz.tmp')
    with walks_file.open('wb') as output:
        np.savez_compressed(output, pos=walks.pos, end=walks.end, reason=walks.reason,
                            kind=walks.kind, speed=walks.speed,
                            mobility_min=walks.mobility_min, heading0=walks.heading0,
                            bounces=walks.bounces, born=walks.born,
                            start=np.asarray(walks.start), baseline=baseline,
                            params_json=json.dumps(walks.params, sort_keys=True),
                            signature=signature)
    walks_file.replace(model.DEMO_WALKS)

    run = {'status': 'ready', 'version': 0, 'walks': walks,
           'weights': baseline, 'heat_cache': {}}
    timeline_file = model.DEMO_TIMELINE.with_suffix('.zip.tmp')
    with ZipFile(timeline_file, 'w') as archive:
        write_zip(archive, 'meta.json', json.dumps({
            'signature': signature, 'last_minute': model.DEMO_LAST_MINUTE,
            'walkers': 5000, 'seed': 42}, sort_keys=True).encode())
        for minute in range(model.DEMO_LAST_MINUTE + 1):
            heat = model.run_heat(run, minute)
            summary = model.summary(run, minute)
            display = serve.make_heat_display(heat)
            output = io.BytesIO()
            np.save(output, display, allow_pickle=False)
            write_zip(archive, f'display/{minute:03d}.npy', output.getvalue())
            write_zip(archive, f'summary/{minute:03d}.json',
                      json.dumps(summary, separators=(',', ':')).encode())
            if minute % 30 == 0:
                print(f'Baked demo minute {minute}/{model.DEMO_LAST_MINUTE}', flush=True)
    timeline_file.replace(model.DEMO_TIMELINE)
    print(f'Wrote {model.DEMO_WALKS} and {model.DEMO_TIMELINE}')


if __name__ == '__main__':
    main()
