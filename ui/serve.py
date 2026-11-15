"""Local server for the 2D Amherst case map and walker probability API.

Run: python3 ui/serve.py --port 8002. Normal map use reads data/grid.npz.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import re
import threading
import time
from functools import lru_cache
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

import model_service as model

ROOT = Path(__file__).resolve().parent
DATA = ROOT.parent / 'data'
CACHE = ROOT / '.cache'
BBOX = '42.363,-72.557,42.379,-72.521'
QUERY = f'[out:json][timeout:25];(way["building"]({BBOX});way["highway"]({BBOX});way["waterway"]({BBOX}););out geom;'
TERRAIN = (
    ('Mapzen / AWS', 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png', 'image/png'),
    ('Mapterhorn', 'https://tiles.mapterhorn.com/{z}/{x}/{y}.webp', 'image/webp'),
)
OVERPASS = (
    'https://overpass.private.coffee/api/interpreter',
    'https://overpass-api.de/api/interpreter',
)
GRID = DATA / 'grid.npz'
GRID_LOCK = threading.Lock()


@lru_cache(maxsize=1)
def load_grid():
    import numpy as np
    with np.load(GRID, allow_pickle=False) as archive:
        crs = str(archive['crs'])
        if 'UTM zone 18N' not in crs:
            raise ValueError('The UI grid reader expects the committed Amherst UTM zone 18N grid')
        return archive['dem'], archive['cls'], archive['transform'].astype(float)


def utm18(lon, lat):
    """WGS84 longitude/latitude to the grid's UTM zone 18N coordinates."""
    import numpy as np
    a, e2, k0 = 6378137.0, 0.0066943799901413165, 0.9996
    ep2 = e2 / (1 - e2)
    phi, lam = np.radians(lat), np.radians(lon + 75)
    sin, cos, tan = np.sin(phi), np.cos(phi), np.tan(phi)
    n = a / np.sqrt(1 - e2 * sin * sin)
    t, c, aa = tan * tan, ep2 * cos * cos, cos * lam
    m = a * ((1 - e2 / 4 - 3 * e2**2 / 64 - 5 * e2**3 / 256) * phi
             - (3 * e2 / 8 + 3 * e2**2 / 32 + 45 * e2**3 / 1024) * np.sin(2 * phi)
             + (15 * e2**2 / 256 + 45 * e2**3 / 1024) * np.sin(4 * phi)
             - (35 * e2**3 / 3072) * np.sin(6 * phi))
    x = 500000 + k0 * n * (aa + (1 - t + c) * aa**3 / 6
                            + (5 - 18 * t + t**2 + 72 * c - 58 * ep2) * aa**5 / 120)
    y = k0 * (m + n * tan * (aa**2 / 2 + (5 - t + 9 * c + 4 * c**2) * aa**4 / 24
                             + (61 - 58 * t + t**2 + 600 * c - 330 * ep2) * aa**6 / 720))
    return x, y


@lru_cache(maxsize=64)
def grid_tile(z: int, x: int, y: int):
    """Return Terrarium elevation and class PNGs sampled from the committed 10 m grid."""
    import numpy as np
    from PIL import Image
    dem, cls, transform = load_grid()
    size = 256
    pixel = (np.arange(size, dtype=np.float64) + 0.5) / size
    tx, ty = np.meshgrid(x + pixel, y + pixel)
    lon = tx / (2 ** z) * 360 - 180
    lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * ty / (2 ** z)))))
    east, north = utm18(lon, lat)
    col = (east - transform[2]) / transform[0] - 0.5
    row = (north - transform[5]) / transform[4] - 0.5
    valid = (row >= 0) & (col >= 0) & (row < cls.shape[0] - 1) & (col < cls.shape[1] - 1)
    rr = np.clip(np.rint(row).astype(int), 0, cls.shape[0] - 1)
    cc = np.clip(np.rint(col).astype(int), 0, cls.shape[1] - 1)
    classes = np.where(valid, cls[rr, cc], 255).astype(np.uint8)
    if not np.any(classes != 255):
        return None
    # Bilinear interpolation of 10 m elevation samples. Invalid neighbors use the
    # nearest valid center; cells outside the study polygon use the tile median.
    r0 = np.clip(np.floor(row).astype(int), 0, cls.shape[0] - 2)
    c0 = np.clip(np.floor(col).astype(int), 0, cls.shape[1] - 2)
    dr, dc = np.clip(row - r0, 0, 1), np.clip(col - c0, 0, 1)
    a, b, c, d = dem[r0, c0], dem[r0, c0 + 1], dem[r0 + 1, c0], dem[r0 + 1, c0 + 1]
    nearest = dem[rr, cc]
    a, b, c, d = (np.where(np.isfinite(v), v, nearest) for v in (a, b, c, d))
    heights = a * (1 - dr) * (1 - dc) + b * (1 - dr) * dc + c * dr * (1 - dc) + d * dr * dc
    tile_median = float(np.nanmedian(heights[classes != 255]))
    heights = np.nan_to_num(heights, nan=tile_median)
    encoded = np.clip(heights + 32768, 0, 65535.996)
    whole = np.floor(encoded).astype(np.uint32)
    rgb = np.empty((size, size, 3), dtype=np.uint8)
    rgb[:, :, 0] = whole // 256
    rgb[:, :, 1] = whole % 256
    rgb[:, :, 2] = np.floor((encoded - whole) * 256).astype(np.uint8)
    def png(array):
        output = io.BytesIO()
        Image.fromarray(array).save(output, format='PNG')
        return output.getvalue()
    return png(rgb), png(classes)


def read_grid_tile(z: int, x: int, y: int):
    # Avoid concurrent first-load decompression of the 26 MB grid archive.
    with GRID_LOCK:
        return grid_tile(z, x, y)


def request_bytes(url: str, data: bytes | None = None) -> bytes:
    headers = {'User-Agent': 'Rescuers-Amherst-Terrain/0.1 (hackathon demo)', 'Accept': '*/*'}
    if data is not None:
        headers['Content-Type'] = 'application/x-www-form-urlencoded; charset=utf-8'
    with urlopen(Request(url, data=data, headers=headers), timeout=8) as response:
        return response.read()


def _mapped_distance(element, lat: float, lon: float) -> float:
    """Approximate distance in meters to an OSM point, line, or mapped polygon."""
    xscale = 111320 * math.cos(math.radians(lat))
    yscale = 111320
    coords = element.get('geometry') or [element]
    points = [((p['lon'] - lon) * xscale, (p['lat'] - lat) * yscale)
              for p in coords if 'lon' in p and 'lat' in p]
    if not points:
        return float('inf')
    if len(points) > 3 and points[0] == points[-1]:
        inside = False
        for (ax, ay), (bx, by) in zip(points, points[1:]):
            if (ay > 0) != (by > 0) and 0 < ax + (bx - ax) * (-ay) / (by - ay):
                inside = not inside
        if inside:
            return 0.0
    closest = min(math.hypot(x, y) for x, y in points)
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        dx, dy = bx - ax, by - ay
        factor = max(0.0, min(1.0, -(ax * dx + ay * dy) / (dx * dx + dy * dy))) if dx or dy else 0.0
        closest = min(closest, math.hypot(ax + factor * dx, ay + factor * dy))
    return closest


def describe_mapped_place(elements, lat: float, lon: float) -> dict:
    """Identify the nearest named OSM feature without claiming it is the exact site."""
    choices = []
    for element in elements:
        tags = element.get('tags') or {}
        name = tags.get('name')
        if not isinstance(name, str) or not name.strip():
            continue
        distance = _mapped_distance(element, lat, lon)
        if distance > 120:
            continue
        kind = next((key for key in ('amenity', 'shop', 'tourism', 'leisure',
                                    'building', 'historic', 'natural', 'waterway', 'highway')
                     if key in tags), 'mapped feature')
        # At equal distance, prefer an identifiable place over a long road.
        choices.append((distance, kind == 'highway', name.strip(), kind))
    if not choices:
        return {'name': None, 'kind': None, 'distance_m': None,
                'description': 'No named OpenStreetMap feature found within 120 m.'}
    distance, _, name, kind = min(choices)
    relation = 'At mapped ' if distance < 1 and kind != 'highway' else 'Near '
    detail = (f'{relation}{name}' + (f' (about {round(distance)} m away)' if distance >= 1 else ''))
    return {'name': name, 'kind': kind, 'distance_m': round(distance), 'description': detail}


@lru_cache(maxsize=128)
def nearby_mapped_place(lat: float, lon: float) -> dict:
    query = (f'[out:json][timeout:12];(node["name"](around:120,{lat:.6f},{lon:.6f});'
             f'way["name"](around:120,{lat:.6f},{lon:.6f}););out geom;')
    for endpoint in OVERPASS:
        try:
            data = json.loads(request_bytes(endpoint, urlencode({'data': query}).encode()))
            return describe_mapped_place(data.get('elements', []), lat, lon)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, TypeError):
            continue
    return {'name': None, 'kind': None, 'distance_m': None,
            'description': 'Mapped place lookup is unavailable; use the model cell coordinates.'}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def send_data(self, payload: bytes, content_type: str, source: str | None = None, status: int = 200):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'public, max-age=86400' if status == 200 and content_type.startswith('image/') else 'no-store')
        if source:
            self.send_header('X-Data-Source', source)
        self.end_headers()
        self.wfile.write(payload)

    def send_json(self, value, status=200):
        self.send_data(json.dumps(value).encode(), 'application/json; charset=utf-8', status=status)

    def read_json(self):
        length = int(self.headers.get('Content-Length', '0'))
        if not 0 < length <= 65536:
            raise ValueError('Request body must be 1–65536 bytes')
        return json.loads(self.rfile.read(length))

    def do_POST(self):
        try:
            body = self.read_json()
            if self.path == '/api/runs':
                self.send_json(model.start_run(body), 202)
            elif self.path == '/api/extract':
                if not isinstance(body, dict) or not isinstance(body.get('text'), str) or not body['text'].strip():
                    raise ValueError('Enter clue text first')
                self.send_json({'draft': model.extract_clue(body['text'])})
            else:
                self.send_json({'error': 'Unknown endpoint'}, 404)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
            self.send_json({'error': str(error)}, 400)
        except RuntimeError as error:
            self.send_json({'error': str(error)}, 503)
        except Exception as error:
            self.send_json({'error': str(error)}, 500)

    def do_PUT(self):
        try:
            match = re.fullmatch(r'/api/runs/([a-f0-9]{12})/evidence', self.path)
            if not match:
                self.send_json({'error': 'Unknown endpoint'}, 404)
                return
            body = self.read_json()
            self.send_json(model.set_evidence(model.get_run(match[1]), body))
        except KeyError as error:
            self.send_json({'error': str(error)}, 404)
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            self.send_json({'error': str(error)}, 400)
        except Exception as error:
            self.send_json({'error': str(error)}, 500)

    def do_GET(self):
        url = urlsplit(self.path)
        query = parse_qs(url.query)
        if self.path in ('/', '/index.html'):
            self.send_data((ROOT / 'index.html').read_bytes(), 'text/html; charset=utf-8')
            return
        if self.path == '/api/health':
            self.send_json({'ok': True, 'service': 'rescuers-amherst', 'grid': GRID.exists()})
            return
        if self.path == '/api/demo':
            self.send_json(model.demo_case())
            return
        if self.path == '/api/demo/reveal':
            self.send_json(model.demo_reveal())
            return
        if url.path == '/api/place':
            try:
                lat = float(query['lat'][0]); lon = float(query['lon'][0])
                model.point({'lat': lat, 'lon': lon}, 'Selected model cell')
                self.send_json(nearby_mapped_place(round(lat, 6), round(lon, 6)))
            except (KeyError, IndexError, ValueError, TypeError) as error:
                self.send_json({'error': str(error)}, 400)
            return
        match = re.fullmatch(r'/api/runs/([a-f0-9]{12})', url.path)
        if match:
            try:
                self.send_json(model.public_run(model.get_run(match[1])))
            except KeyError:
                self.send_json({'error': 'Unknown run'}, 404)
            return
        match = re.fullmatch(r'/api/runs/([a-f0-9]{12})/summary', url.path)
        if match:
            try:
                minute = int(query.get('minute', ['240'])[0])
                self.send_json(model.summary(model.get_run(match[1]), minute))
            except KeyError:
                self.send_json({'error': 'Unknown run'}, 404)
            except (ValueError, TypeError) as error:
                self.send_json({'error': str(error)}, 400)
            return
        match = re.fullmatch(r'/api/runs/([a-f0-9]{12})/walkers', url.path)
        if match:
            try:
                run = model.get_run(match[1])
                minute = int(query.get('minute', ['240'])[0])
                requested_version = int(query.get('version', [str(run['version'])])[0])
                if requested_version != run['version']:
                    raise ValueError('Evidence version changed; refresh the positions')
                self.send_json(model.walker_positions(run, minute))
            except KeyError:
                self.send_json({'error': 'Unknown run'}, 404)
            except (ValueError, TypeError) as error:
                self.send_json({'error': str(error)}, 400)
            return
        match = re.fullmatch(r'/api/runs/([a-f0-9]{12})/heat/(\d{1,2})/(\d{1,6})/(\d{1,6})', url.path)
        if match:
            try:
                minute = int(query.get('minute', ['240'])[0])
                run = model.get_run(match[1])
                with model.LOCK:
                    requested_version = int(query.get('version', [str(run['version'])])[0])
                    if requested_version != run['version']:
                        raise ValueError('Evidence version changed; refresh the tile')
                    self.heat_tile(run, *map(int, match.groups()[1:]), minute)
            except KeyError:
                self.send_json({'error': 'Unknown run'}, 404)
            except (ValueError, TypeError) as error:
                self.send_json({'error': str(error)}, 400)
            return
        match = re.fullmatch(r'/api/terrain/(\d{1,2})/(\d{1,6})/(\d{1,6})', self.path)
        if match:
            self.terrain(*map(int, match.groups()))
            return
        match = re.fullmatch(r'/api/grid-class/(\d{1,2})/(\d{1,6})/(\d{1,6})', self.path)
        if match:
            self.grid_class(*map(int, match.groups()))
            return
        if self.path == '/api/features':
            self.features()
            return
        super().do_GET()

    def heat_tile(self, run, z, x, y, minute):
        import numpy as np
        from PIL import Image, ImageFilter
        if z != 14 or not (0 <= x < 2**z and 0 <= y < 2**z):
            raise ValueError('Unsupported probability tile')
        heat = model.run_heat(run, minute)
        _, cls, transform = load_grid()
        pixel = (np.arange(256, dtype=np.float64) + 0.5) / 256
        tx, ty = np.meshgrid(x + pixel, y + pixel)
        lon = tx / 2**z * 360 - 180
        lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * ty / 2**z))))
        east, north = utm18(lon, lat)
        col = np.rint((east - transform[2]) / transform[0] - 0.5).astype(int)
        row = np.rint((north - transform[5]) / transform[4] - 0.5).astype(int)
        valid = (row >= 0) & (col >= 0) & (row < cls.shape[0]) & (col < cls.shape[1])
        rr, cc = np.clip(row, 0, cls.shape[0] - 1), np.clip(col, 0, cls.shape[1] - 1)
        # Build one continuous display field for the entire grid so tile edges
        # remain seamless. The blur changes only the visualization, not weights.
        display = run.setdefault('heat_display', {})
        key = (run['version'], int(minute))
        if key not in display:
            positive = heat[heat > 0]
            ranked = np.sort(positive)[::-1]
            core_count = min(len(ranked), int(np.searchsorted(np.cumsum(ranked), 0.8) + 1))
            core = ranked[:core_count]
            reference = max(float(np.quantile(core, .95)), 1e-15)
            strength = np.sqrt(np.clip(heat / reference, 0, 1))
            field = Image.fromarray(np.uint8(np.round(strength * 255)), 'L')
            display[key] = np.asarray(field.filter(ImageFilter.GaussianBlur(radius=8))).copy()
            if len(display) > 8:
                display.pop(next(iter(display)))
        intensity = np.where(valid & (cls[rr, cc] != 255), display[key][rr, cc] / 255, 0)
        rgba = np.zeros((256, 256, 4), dtype=np.uint8)
        warm = np.clip(intensity * 2, 0, 1)
        hot = np.clip((intensity - .5) * 2, 0, 1)
        rgba[:, :, 0] = np.uint8(255 - 10 * warm - 27 * hot)
        rgba[:, :, 1] = np.uint8(234 - 83 * warm - 112 * hot)
        rgba[:, :, 2] = np.uint8(75 - 22 * warm - 21 * hot)
        rgba[:, :, 3] = np.uint8(np.clip((intensity - .02) * 320, 0, 210))
        out = io.BytesIO()
        Image.fromarray(rgba, 'RGBA').save(out, format='PNG')
        self.send_data(out.getvalue(), 'image/png', 'Amherst walker posterior')

    def terrain(self, z: int, x: int, y: int):
        if z != 14 or not (0 <= x < 2**z and 0 <= y < 2**z):
            self.send_error(400, 'Unsupported terrain tile')
            return
        if GRID.exists():
            try:
                result = read_grid_tile(z, x, y)
                if result is None:
                    self.send_error(404, 'Outside the Amherst grid')
                else:
                    self.send_data(result[0], 'image/png', 'USGS 3DEP via Amherst model grid')
                return
            except (ImportError, OSError, ValueError, RuntimeError) as error:
                self.send_data(json.dumps({'error': f'Cannot read grid.npz: {error}'}).encode(), 'application/json', status=500)
                return
        local = DATA / 'amherst_elevation_10m.tif'
        if local.exists():
            try:
                import numpy as np
                import rasterio
                from PIL import Image
                from rasterio.enums import Resampling
                from rasterio.transform import from_bounds
                from rasterio.warp import reproject

                extent = 20037508.342789244
                span = 2 * extent / (2 ** z)
                left, top = -extent + x * span, extent - y * span
                heights = np.full((256, 256), np.nan, dtype=np.float32)
                with rasterio.open(local) as source:
                    reproject(
                        source=rasterio.band(source, 1), destination=heights,
                        src_transform=source.transform, src_crs=source.crs,
                        src_nodata=source.nodata,
                        dst_transform=from_bounds(left, top - span, left + span, top, 256, 256),
                        dst_crs='EPSG:3857', dst_nodata=np.nan,
                        resampling=Resampling.bilinear,
                    )
                if np.isfinite(heights).any():
                    encoded = np.clip(np.nan_to_num(heights, nan=0) + 32768, 0, 65535.996)
                    whole = np.floor(encoded).astype(np.uint32)
                    rgba = np.empty((256, 256, 4), dtype=np.uint8)
                    rgba[:, :, 0] = whole // 256
                    rgba[:, :, 1] = whole % 256
                    rgba[:, :, 2] = np.floor((encoded - whole) * 256).astype(np.uint8)
                    rgba[:, :, 3] = 255
                    output = io.BytesIO()
                    Image.fromarray(rgba, 'RGBA').save(output, format='PNG')
                    self.send_data(output.getvalue(), 'image/png', 'Local USGS 3DEP elevation')
                    return
            except (ImportError, OSError, ValueError, RuntimeError) as error:
                print(f'Local DEM could not be read: {error}', flush=True)
        errors = []
        for name, template, content_type in TERRAIN:
            suffix = '.webp' if content_type == 'image/webp' else '.png'
            target = CACHE / 'terrain' / str(z) / str(x) / f'{y}{suffix}'
            try:
                if target.exists():
                    payload = target.read_bytes()
                else:
                    payload = request_bytes(template.format(z=z, x=x, y=y))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(payload)
                self.send_data(payload, content_type, name)
                return
            except (HTTPError, URLError, TimeoutError, OSError) as error:
                errors.append(f'{name}: {error}')
        print(f'Terrain tile {z}/{x}/{y} upstream failure: {errors}', flush=True)
        self.send_data(json.dumps({'error': 'Elevation unavailable', 'details': errors}).encode(), 'application/json', status=502)

    def grid_class(self, z: int, x: int, y: int):
        if not GRID.exists():
            self.send_error(404, 'Amherst grid is missing')
            return
        if z != 14 or not (0 <= x < 2**z and 0 <= y < 2**z):
            self.send_error(400, 'Unsupported class tile')
            return
        try:
            result = read_grid_tile(z, x, y)
            if result is None:
                self.send_error(404, 'Outside the Amherst grid')
            else:
                self.send_data(result[1], 'image/png', 'Amherst model grid classes')
        except (ImportError, OSError, ValueError, RuntimeError) as error:
            self.send_data(json.dumps({'error': f'Cannot read grid.npz: {error}'}).encode(), 'application/json', status=500)

    def features(self):
        local = DATA / 'amherst_full_features.geojson'
        if local.exists():
            try:
                data = json.loads(local.read_text())
                elements = []
                for feature in data.get('features', []):
                    properties = feature.get('properties') or {}
                    tags = {key: value for key, value in properties.items()
                            if key in ('building', 'building:levels', 'height', 'highway', 'waterway')
                            and value not in (None, 'nan', '')}
                    if not any(key in tags for key in ('building', 'highway', 'waterway')):
                        continue
                    geometry = feature.get('geometry') or {}
                    kind, coords = geometry.get('type'), geometry.get('coordinates') or []
                    if kind == 'Polygon':
                        paths = coords[:1]
                    elif kind == 'MultiPolygon':
                        paths = [polygon[0] for polygon in coords if polygon]
                    elif kind == 'LineString':
                        paths = [coords]
                    elif kind == 'MultiLineString':
                        paths = coords
                    else:
                        continue
                    for path in paths:
                        if len(path) >= 2 and any(-72.557 <= point[0] <= -72.521 and 42.363 <= point[1] <= 42.379 for point in path):
                            elements.append({'tags': tags, 'geometry': [
                                {'lon': point[0], 'lat': point[1]} for point in path]})
                self.send_data(json.dumps({'elements': elements}).encode(), 'application/json', 'Local Amherst OSM GeoJSON')
                return
            except (OSError, ValueError, TypeError, KeyError, IndexError) as error:
                print(f'Local OSM file could not be read: {error}', flush=True)
        target = CACHE / 'amherst_osm_features.json'
        if target.exists() and time.time() - target.stat().st_mtime < 7 * 86400:
            self.send_data(target.read_bytes(), 'application/json', 'OpenStreetMap / Overpass')
            return
        errors = []
        for url in OVERPASS:
            try:
                payload = request_bytes(url, urlencode({'data': QUERY}).encode())
                data = json.loads(payload)
                if not isinstance(data.get('elements'), list):
                    raise ValueError('Missing Overpass elements')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
                self.send_data(payload, 'application/json', 'OpenStreetMap / Overpass')
                return
            except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
                errors.append(f'{url}: {error}')
        print(f'OSM upstream failure: {errors}', flush=True)
        self.send_data(json.dumps({'error': 'OSM features unavailable', 'details': errors}).encode(), 'application/json', status=502)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8001)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'Open http://127.0.0.1:{args.port}/ (serving {ROOT})', flush=True)
    server.serve_forever()
