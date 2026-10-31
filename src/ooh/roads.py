"""OpenStreetMap data: roads, buildings, points of interest and metro lines.

Data comes from OSMnx (Overpass API) and is cached per placement as a GeoPackage under
``data/cache/``. The cache is committed to the repository, so the app runs offline and on
Streamlit Community Cloud without hitting Overpass. If there is no cache and Overpass is
unreachable, a synthetic straight carriageway is generated and labelled SAMPLE.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point

from . import geometry as geo
from .config import CACHE_DIR, Placement

log = logging.getLogger(__name__)

FETCH_RADIUS_M = 1500
POI_RADIUS_M = 1000
ROADSIDE_OFFSET_M = 15  # ASSUMPTION: face sits 15 m to the right of the carriageway centre line
SNAP_MAX_M = 400
MAIN_CLASSES = {"motorway", "trunk", "primary"}

OVERPASS_MIRRORS = [
    "https://overpass-api.de/api",
    "https://overpass.kumi.systems/api",
    "https://overpass.private.coffee/api",
]

LAYERS = ("edges", "buildings", "pois", "rail", "stations")


@dataclass
class OsmArea:
    """OSM layers around one placement, in UTM metres."""

    edges: gpd.GeoDataFrame
    buildings: gpd.GeoDataFrame
    pois: gpd.GeoDataFrame
    rail: gpd.GeoDataFrame
    stations: gpd.GeoDataFrame
    source: str          # "OpenStreetMap (cached YYYY-MM-DD)" or "SAMPLE synthetic road"
    is_sample: bool


@dataclass
class SnappedPlacement:
    """Where the face ends up after snapping to the road, and how it got there."""

    id: str
    lat: float
    lon: float
    x: float
    y: float
    facing_bearing_deg: float
    travel_bearing_deg: float
    road_name: str
    highway: str
    snap_distance_m: float
    method: str
    note: str

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- cache


def _cache_path(placement: Placement) -> Path:
    return CACHE_DIR / f"osm_{placement.id}.gpkg"


def _meta_path(placement: Placement) -> Path:
    return CACHE_DIR / f"osm_{placement.id}.json"


def _cache_valid(placement: Placement) -> bool:
    path, meta_path = _cache_path(placement), _meta_path(placement)
    if not path.exists() or not meta_path.exists():
        return False
    meta = json.loads(meta_path.read_text())
    moved = geo.haversine_m(meta["lon"], meta["lat"], placement.lon, placement.lat)
    return moved < 50 and meta.get("radius_m", 0) >= FETCH_RADIUS_M


def _stringify(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Make list-valued OSM tags writable to GeoPackage."""
    gdf = gdf.copy()
    for col in gdf.columns:
        if col == "geometry":
            continue
        if gdf[col].map(lambda v: isinstance(v, (list, dict, set))).any():
            gdf[col] = gdf[col].map(lambda v: json.dumps(list(v)) if isinstance(v, (list, set)) else v)
        if gdf[col].dtype == object:
            gdf[col] = gdf[col].map(lambda v: None if v is None or (isinstance(v, float) and np.isnan(v)) else str(v))
    return gdf


# --------------------------------------------------------------------------- download


def _configure_osmnx(endpoint: str) -> None:
    import osmnx as ox

    ox.settings.overpass_url = endpoint
    ox.settings.overpass_rate_limit = False
    ox.settings.requests_timeout = 180
    ox.settings.use_cache = True
    ox.settings.cache_folder = str(CACHE_DIR / "osmnx_http")
    ox.settings.log_console = False
    ox.settings.useful_tags_way = list(
        {*ox.settings.useful_tags_way, "lanes", "maxspeed", "ref", "name:en", "oneway"}
    )


def _features(center: tuple[float, float], tags: dict, dist: int) -> gpd.GeoDataFrame:
    import osmnx as ox

    try:
        gdf = ox.features_from_point(center, tags=tags, dist=dist)
    except Exception as exc:  # osmnx raises InsufficientResponseError when nothing matches
        if exc.__class__.__name__ == "InsufficientResponseError":
            return gpd.GeoDataFrame(geometry=[], crs=geo.WGS84)
        raise
    return gdf.reset_index()


def download_area(placement: Placement, retries_per_mirror: int = 2) -> None:
    """Download roads, buildings, POIs and metro around a placement into the GeoPackage cache."""
    import osmnx as ox

    center = (placement.lat, placement.lon)
    last_error: Exception | None = None
    for endpoint in OVERPASS_MIRRORS:
        _configure_osmnx(endpoint)
        for attempt in range(retries_per_mirror):
            try:
                log.info("Overpass %s: %s (attempt %d)", endpoint, placement.id, attempt + 1)
                graph = ox.graph_from_point(center, dist=FETCH_RADIUS_M, network_type="drive",
                                            simplify=True, retain_all=True)
                edges = ox.graph_to_gdfs(graph, nodes=False, fill_edge_geometry=True).reset_index()
                buildings = _features(center, {"building": True}, FETCH_RADIUS_M)
                pois = _features(center, {"amenity": True, "shop": True, "tourism": True,
                                          "office": True, "leisure": True}, POI_RADIUS_M)
                rail = _features(center, {"railway": ["subway", "light_rail"]}, FETCH_RADIUS_M)
                stations = _features(center, {"railway": ["station", "halt"]}, 2500)
                _write_cache(placement, edges, buildings, pois, rail, stations, endpoint)
                return
            except Exception as exc:  # network errors, Overpass at capacity, timeouts
                last_error = exc
                log.warning("Overpass failed (%s): %s", endpoint, exc)
                time.sleep(5 * (2**attempt))
    raise RuntimeError(f"All Overpass mirrors failed for {placement.id}: {last_error}")


def _write_cache(placement: Placement, edges, buildings, pois, rail, stations, endpoint: str) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(placement)
    if path.exists():
        path.unlink()

    keep_edges = ["u", "v", "key", "osmid", "name", "name:en", "ref", "highway", "lanes",
                  "maxspeed", "oneway", "length", "geometry"]
    edges = edges[[c for c in keep_edges if c in edges.columns]]
    buildings = buildings[buildings.geometry.geom_type.isin(["Polygon", "MultiPolygon"])][["geometry"]]
    poi_cols = ["name", "amenity", "shop", "tourism", "office", "leisure", "geometry"]
    pois = pois[[c for c in poi_cols if c in pois.columns]].copy()
    pois["geometry"] = pois.geometry.representative_point()
    rail_cols = ["name", "railway", "geometry"]
    rail = rail[rail.geometry.geom_type.isin(["LineString", "MultiLineString"])] if len(rail) else rail
    rail = rail[[c for c in rail_cols if c in rail.columns]]
    st_cols = ["name", "name:en", "railway", "station", "geometry"]
    stations = stations[[c for c in st_cols if c in stations.columns]].copy() if len(stations) else stations
    if len(stations):
        stations["geometry"] = stations.geometry.representative_point()

    for name, gdf in zip(LAYERS, (edges, buildings, pois, rail, stations)):
        gdf = gpd.GeoDataFrame(gdf, geometry="geometry", crs=geo.WGS84)
        if len(gdf) == 0:
            gdf = gpd.GeoDataFrame({"name": pd.Series(dtype=str)},
                                   geometry=gpd.GeoSeries([], crs=geo.WGS84))
        _stringify(gdf).to_file(path, layer=name, driver="GPKG")

    _meta_path(placement).write_text(json.dumps({
        "placement": placement.id, "lat": placement.lat, "lon": placement.lon,
        "radius_m": FETCH_RADIUS_M, "endpoint": endpoint,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "counts": {"edges": len(edges), "buildings": len(buildings), "pois": len(pois),
                   "rail": len(rail), "stations": len(stations)},
    }, indent=2))


# --------------------------------------------------------------------------- load


def _first_number(value, default: float | None = None) -> float | None:
    """Parse OSM numeric tags like '5', '["4", "5"]', '80 mph' or 'none'."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return default
    text = str(value)
    if text.startswith("["):
        try:
            nums = [_first_number(v) for v in json.loads(text)]
            nums = [n for n in nums if n is not None]
            return max(nums) if nums else default
        except json.JSONDecodeError:
            pass
    digits = "".join(ch if (ch.isdigit() or ch == ".") else " " for ch in text).split()
    if not digits:
        return default
    num = float(digits[0])
    return num * 1.609 if "mph" in text else num


def _first_text(value) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    text = str(value)
    if text.startswith("["):
        try:
            items = json.loads(text)
            return str(items[0]) if items else ""
        except json.JSONDecodeError:
            return text
    return text


def _normalise_edges(edges: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    edges = edges.copy()
    edges["highway"] = edges["highway"].map(_first_text)
    edges["name"] = edges.get("name", pd.Series("", index=edges.index)).map(_first_text)
    edges["name_en"] = edges.get("name:en", pd.Series("", index=edges.index)).map(_first_text)
    edges["ref"] = edges.get("ref", pd.Series("", index=edges.index)).map(_first_text)
    edges["lanes_osm"] = edges.get("lanes", pd.Series(None, index=edges.index)).map(_first_number)
    edges["maxspeed_osm"] = edges.get("maxspeed", pd.Series(None, index=edges.index)).map(_first_number)
    oneway = edges.get("oneway", pd.Series("False", index=edges.index)).astype(str).str.lower()
    edges["oneway"] = oneway.isin(["true", "1", "yes"])
    edges["edge_id"] = [f"{u}-{v}-{k}" for u, v, k in zip(edges["u"], edges["v"], edges["key"])]
    return edges[["edge_id", "u", "v", "highway", "name", "name_en", "ref", "lanes_osm",
                  "maxspeed_osm", "oneway", "geometry"]]


def load_area(placement: Placement, allow_download: bool = True) -> OsmArea:
    """Return OSM layers around a placement, in UTM. Downloads on a cache miss."""
    if not _cache_valid(placement) and allow_download:
        try:
            download_area(placement)
        except Exception as exc:
            log.warning("Using synthetic road for %s: %s", placement.id, exc)
    if not _cache_valid(placement):
        return synthetic_area(placement)

    path = _cache_path(placement)
    layers = {name: gpd.read_file(path, layer=name).to_crs(geo.UTM) for name in LAYERS}
    meta = json.loads(_meta_path(placement).read_text())
    return OsmArea(
        edges=_normalise_edges(layers["edges"]),
        buildings=layers["buildings"],
        pois=layers["pois"],
        rail=layers["rail"],
        stations=layers["stations"],
        source=f"OpenStreetMap via Overpass (cached {meta['fetched_at'][:10]})",
        is_sample=False,
    )


def synthetic_area(placement: Placement) -> OsmArea:
    """A straight dual carriageway through the configured point. Last-resort fallback, SAMPLE."""
    x, y = geo.to_utm(placement.lon, placement.lat)
    travel = (placement.facing_bearing_deg + 180) % 360
    rows = []
    for direction, side in ((travel, 1), ((travel + 180) % 360, -1)):
        # each carriageway sits 12 m either side of the configured point
        cx, cy = geo.offset_point(x, y, travel + 90, -12 * side)
        start = geo.offset_point(cx, cy, direction, -FETCH_RADIUS_M)
        end = geo.offset_point(cx, cy, direction, FETCH_RADIUS_M)
        rows.append({
            "edge_id": f"synthetic-{placement.id}-{side}", "u": 0, "v": 1, "highway": "motorway",
            "name": placement.corridor, "name_en": placement.corridor, "ref": "",
            "lanes_osm": None, "maxspeed_osm": None, "oneway": True,
            "geometry": LineString([start, end]),
        })
    edges = gpd.GeoDataFrame(rows, geometry="geometry", crs=geo.UTM)
    empty = gpd.GeoDataFrame({"name": pd.Series(dtype=str)}, geometry=gpd.GeoSeries([], crs=geo.UTM))
    return OsmArea(edges=edges, buildings=empty, pois=empty.copy(), rail=empty.copy(),
                   stations=empty.copy(), source="SAMPLE synthetic road (OSM unavailable)",
                   is_sample=True)


# --------------------------------------------------------------------------- snapping


def _matches(row, tokens: list[str]) -> bool:
    text = " ".join([row["name"], row["name_en"], row["ref"]]).lower()
    return any(t.lower() in text for t in tokens)


def _bearing_at(line: LineString, distance: float) -> float:
    a = line.interpolate(max(0.0, distance - 5))
    b = line.interpolate(min(line.length, distance + 5))
    return geo.bearing_xy(a.x, a.y, b.x, b.y)


def snap_placement(placement: Placement, area: OsmArea) -> SnappedPlacement:
    """Snap the face to the nearest matching carriageway that carries traffic towards it.

    The carriageway must match the corridor name or ref and its travel bearing must be
    within 60 degrees of (configured facing + 180). The face is then placed 15 m to the
    right of that carriageway and faces straight back at oncoming traffic.
    """
    px, py = geo.to_utm(placement.lon, placement.lat)
    point = Point(px, py)
    wanted_travel = (placement.facing_bearing_deg + 180) % 360

    edges = area.edges
    main = edges[edges["highway"].isin(MAIN_CLASSES)]
    named = main[main.apply(_matches, axis=1, tokens=placement.road_match)] if len(main) else main
    pool, note = (named, "matched corridor name/ref") if len(named) else (main, "no name match; nearest main road")

    best = None
    for _, row in pool.iterrows():
        line: LineString = row.geometry
        d = line.distance(point)
        if d > SNAP_MAX_M:
            continue
        along = line.project(point)
        travel = _bearing_at(line, along)
        if geo.angle_diff(travel, wanted_travel) > 60:
            continue
        if best is None or d < best[0]:
            best = (d, row, along, travel)

    if best is None:
        return SnappedPlacement(
            id=placement.id, lat=placement.lat, lon=placement.lon, x=px, y=py,
            facing_bearing_deg=placement.facing_bearing_deg, travel_bearing_deg=wanted_travel,
            road_name=placement.corridor, highway="unknown", snap_distance_m=0.0,
            method="config", note="no carriageway within 400 m in the facing direction; kept config values",
        )

    d, row, along, travel = best
    on_road = row.geometry.interpolate(along)
    hx, hy = geo.offset_point(on_road.x, on_road.y, travel + 90, ROADSIDE_OFFSET_M)
    lon, lat = geo.to_wgs(hx, hy)
    road_name = row["name_en"] or row["name"] or row["ref"] or row["highway"]
    return SnappedPlacement(
        id=placement.id, lat=round(lat, 6), lon=round(lon, 6), x=hx, y=hy,
        facing_bearing_deg=round((travel + 180) % 360, 1), travel_bearing_deg=round(travel, 1),
        road_name=road_name, highway=row["highway"], snap_distance_m=round(d, 1),
        method="osm", note=f"{note}; face offset {ROADSIDE_OFFSET_M} m right of carriageway",
    )
