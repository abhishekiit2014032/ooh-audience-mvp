"""Activation exports: the exposure zone as GeoJSON, and a centre + radius list.

These files are what a planner hands to a location-data partner (Blis, Azira) or uploads to
a platform's radius targeting. Nothing is executed in the MVP: activation is a CONCEPT until
a data partner is signed and the privacy review is done.
"""

from __future__ import annotations

import csv
import io
import json
import math

from . import geometry as geo

# Smallest radius most self-serve platforms accept for a pin (ASSUMPTION; check each platform).
PLATFORM_MIN_RADIUS_KM = 1.0


def zone_feature(pid: str, name: str, lon: float, lat: float, facing: float, radius_m: float,
                 half_angle: float) -> dict:
    ring = geo.cone_polygon_lonlat(lon, lat, facing, radius_m, half_angle)
    return {
        "type": "Feature",
        "properties": {
            "placement_id": pid, "name": name, "facing_bearing_deg": facing,
            "radius_m": radius_m, "half_angle_deg": half_angle,
            "label": "ESTIMATE", "purpose": "OOH exposure zone for partner geofencing (CONCEPT)",
        },
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }


def zones_geojson(features: list[dict]) -> str:
    return json.dumps({"type": "FeatureCollection", "features": features}, indent=2)


def radius_row(pid: str, name: str, lon: float, lat: float, facing: float, radius_m: float,
               half_angle: float) -> dict:
    """The smallest circle that covers the cone, and the platform-ready radius."""
    x, y = geo.to_utm(lon, lat)
    cone = geo.cone_polygon(x, y, facing, radius_m, half_angle)
    c = cone.centroid
    cover_m = max(math.hypot(px - c.x, py - c.y) for px, py in cone.exterior.coords)
    clon, clat = geo.to_wgs(c.x, c.y)
    platform_km = max(PLATFORM_MIN_RADIUS_KM, round(cover_m / 1000, 2))
    return {
        "placement_id": pid, "name": name, "centre_lat": round(clat, 6), "centre_lon": round(clon, 6),
        "zone_cover_radius_km": round(cover_m / 1000, 3), "platform_radius_km": platform_km,
        "note": ("platform minimum applies; audience will include people outside the zone"
                 if platform_km > cover_m / 1000 else "radius covers the exposure zone"),
    }


def radius_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()
