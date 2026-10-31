"""Geometry helpers: bearings, exposure cones, segment splitting, line of sight.

All distance maths runs in UTM zone 40N (EPSG:32640), which covers Dubai, so
coordinates are in metres. Bearings are compass bearings: 0 = north, 90 = east.
"""

from __future__ import annotations

import math

import numpy as np
import shapely
from pyproj import Transformer
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import substring

WGS84 = "EPSG:4326"
UTM = "EPSG:32640"

_to_utm = Transformer.from_crs(WGS84, UTM, always_xy=True)
_to_wgs = Transformer.from_crs(UTM, WGS84, always_xy=True)


def to_utm(lon: float, lat: float) -> tuple[float, float]:
    return _to_utm.transform(lon, lat)


def to_wgs(x: float, y: float) -> tuple[float, float]:
    """Return (lon, lat)."""
    return _to_wgs.transform(x, y)


def bearing_xy(x1: float, y1: float, x2: float, y2: float) -> float:
    """Compass bearing in degrees from point 1 to point 2 (projected metres)."""
    return math.degrees(math.atan2(x2 - x1, y2 - y1)) % 360


def bearing_xy_np(x1, y1, x2, y2) -> np.ndarray:
    """Vectorised :func:`bearing_xy`."""
    return np.degrees(np.arctan2(np.asarray(x2) - x1, np.asarray(y2) - y1)) % 360


def bearing_lonlat(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Initial great-circle bearing in degrees between two WGS84 points."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(x, y)) % 360


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6_371_008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def angle_diff(a, b):
    """Smallest absolute difference between two bearings, in degrees (0..180)."""
    d = np.abs((np.asarray(a) - np.asarray(b) + 180) % 360 - 180)
    return float(d) if np.ndim(d) == 0 else d


def offset_point(x: float, y: float, bearing_deg: float, distance_m: float) -> tuple[float, float]:
    """Move a projected point ``distance_m`` along ``bearing_deg``."""
    r = math.radians(bearing_deg)
    return x + distance_m * math.sin(r), y + distance_m * math.cos(r)


def cone_polygon(x: float, y: float, facing_deg: float, radius_m: float,
                 half_angle_deg: float, steps: int = 24) -> Polygon:
    """Circular sector (exposure cone) in projected coordinates."""
    pts = [(x, y)]
    for i in range(steps + 1):
        b = facing_deg - half_angle_deg + 2 * half_angle_deg * i / steps
        pts.append(offset_point(x, y, b, radius_m))
    pts.append((x, y))
    return Polygon(pts)


def cone_polygon_lonlat(lon: float, lat: float, facing_deg: float, radius_m: float,
                        half_angle_deg: float) -> list[list[float]]:
    """Cone as a list of [lon, lat] pairs, for maps and GeoJSON."""
    x, y = to_utm(lon, lat)
    poly = cone_polygon(x, y, facing_deg, radius_m, half_angle_deg)
    return [list(to_wgs(px, py)) for px, py in poly.exterior.coords]


def split_line(line: LineString, seg_len: float) -> list[LineString]:
    """Split a line into pieces of roughly ``seg_len`` metres, keeping its direction."""
    length = line.length
    if length <= seg_len * 1.5:
        return [line]
    n = max(1, round(length / seg_len))
    step = length / n
    return [substring(line, i * step, (i + 1) * step) for i in range(n)]


def line_of_sight_blocked(mid_x: np.ndarray, mid_y: np.ndarray, hx: float, hy: float,
                          buildings: list[Polygon]) -> np.ndarray:
    """True where the 2D sight line from a segment midpoint to the hoarding crosses a building.

    Buildings that contain the hoarding point or the segment midpoint are ignored, so a
    footprint mapped over the road or the face itself does not block everything.
    """
    n = len(mid_x)
    blocked = np.zeros(n, dtype=bool)
    if n == 0 or not buildings:
        return blocked
    lines = shapely.linestrings(
        np.stack([np.column_stack([mid_x, mid_y]), np.tile([hx, hy], (n, 1))], axis=1)
    )
    tree = shapely.STRtree(buildings)
    line_idx, bld_idx = tree.query(lines, predicate="crosses")
    if len(line_idx) == 0:
        return blocked
    hoarding = Point(hx, hy)
    geoms = np.asarray(buildings, dtype=object)
    contains_h = shapely.contains(geoms[bld_idx], hoarding)
    mids = shapely.points(mid_x[line_idx], mid_y[line_idx])
    contains_m = shapely.contains(geoms[bld_idx], mids)
    keep = ~(contains_h | contains_m)
    blocked[np.unique(line_idx[keep])] = True
    return blocked
