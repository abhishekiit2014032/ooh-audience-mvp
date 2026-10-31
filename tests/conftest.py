"""Shared fixtures: a tiny synthetic road network around one face, no network access."""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ooh import geometry as geo  # noqa: E402
from ooh.config import Params, Placement, load_assumptions  # noqa: E402
from ooh.roads import OsmArea, SnappedPlacement  # noqa: E402

LON, LAT = 55.2770, 25.2115


@pytest.fixture
def params() -> Params:
    return Params(load_assumptions())


@pytest.fixture
def placement() -> Placement:
    # Faces south (180): it serves traffic driving north towards it.
    return Placement(id="T1", name="Test face", lat=LAT, lon=LON, corridor="Test Road", facing_bearing_deg=180,
                     type="static", width_m=12, height_m=8, cost_per_month_aed=100000)


@pytest.fixture
def snapped(placement) -> SnappedPlacement:
    x, y = geo.to_utm(LON, LAT)
    return SnappedPlacement(id="T1", lat=LAT, lon=LON, x=x, y=y, facing_bearing_deg=180,
                            travel_bearing_deg=0, road_name="Test Road", highway="motorway",
                            snap_distance_m=0, method="test", note="")


def _edge(edge_id, x1, y1, x2, y2, lanes=6):
    return {"edge_id": edge_id, "u": 0, "v": 1, "highway": "motorway", "name": "Test Road", "name_en": "",
            "ref": "", "lanes_osm": lanes, "maxspeed_osm": 100, "oneway": True,
            "geometry": LineString([(x1, y1), (x2, y2)])}


@pytest.fixture
def area(snapped) -> OsmArea:
    """Three one-way carriageways, all 10 m west of the face.

    * northbound south of the face (in front, towards the face) -> visible
    * southbound south of the face (in front, driving away)      -> excluded by heading
    * northbound north of the face (behind the face)             -> outside the cone
    """
    x, y = snapped.x, snapped.y
    rows = [
        _edge("front-north", x - 10, y - 600, x - 10, y - 5),
        _edge("front-south", x - 30, y - 5, x - 30, y - 600),
        _edge("behind-north", x - 10, y + 5, x - 10, y + 600),
    ]
    edges = gpd.GeoDataFrame(rows, geometry="geometry", crs=geo.UTM)
    empty = gpd.GeoDataFrame({"name": pd.Series(dtype=str)}, geometry=gpd.GeoSeries([], crs=geo.UTM))
    return OsmArea(edges=edges, buildings=empty, pois=empty.copy(), rail=empty.copy(), stations=empty.copy(),
                   source="test", is_sample=False)
