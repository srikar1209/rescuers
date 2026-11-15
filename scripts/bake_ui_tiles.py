"""Bake the committed Amherst grid into the UI's zoom-14 terrain tiles.

Run from the repository root: python scripts/bake_ui_tiles.py
The zip is a deterministic display derivative of data/grid.npz, not model input.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'ui'))

import serve
from rescuers import grid as G


def tile_xy(lat, lon, zoom=14):
    lat_rad = math.radians(float(lat))
    scale = 2**zoom
    return ((float(lon) + 180) / 360 * scale,
            (1 - math.asinh(math.tan(lat_rad)) / math.pi) / 2 * scale)


def main():
    grid = serve.model.model_grid()
    height, width = grid['cls'].shape
    corners = [tile_xy(*G.cell_to_latlon(grid, row, col))
               for row in (0, height - 1) for col in (0, width - 1)]
    x0, x1 = math.floor(min(x for x, _ in corners)) - 1, math.ceil(max(x for x, _ in corners)) + 1
    y0, y1 = math.floor(min(y for _, y in corners)) - 1, math.ceil(max(y for _, y in corners)) + 1
    output = ROOT / 'ui' / 'tiles_z14.zip'
    count = 0

    def write_tile(archive, name, payload):
        info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
        info.compress_type = ZIP_STORED
        archive.writestr(info, payload)

    with ZipFile(output, 'w', compression=ZIP_STORED) as archive:
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                tiles = serve.grid_tile(14, x, y)
                if tiles is None:
                    continue
                write_tile(archive, f'terrain/14/{x}/{y}.png', tiles[0])
                write_tile(archive, f'classes/14/{x}/{y}.png', tiles[1])
                count += 1
    print(f'Wrote {count} Amherst tile pairs to {output}')


if __name__ == '__main__':
    main()
