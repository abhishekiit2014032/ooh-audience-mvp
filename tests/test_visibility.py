from ooh.visibility import build_segments, score_segments


def _scored(placement, snapped, area, params):
    roads, _ = build_segments(placement, snapped, area, params)
    return score_segments(roads, placement, snapped, params)


def test_segment_behind_face_has_zero_visibility(placement, snapped, area, params):
    df = _scored(placement, snapped, area, params)
    behind = df[df["edge_id"] == "behind-north"]
    assert len(behind) > 0
    assert (behind["V"] == 0).all()
    assert not behind["included"].any()


def test_opposite_direction_segment_excluded(placement, snapped, area, params):
    df = _scored(placement, snapped, area, params)
    away = df[(df["edge_id"] == "front-south") & df["in_cone"]]
    assert len(away) > 0, "the southbound carriageway lies inside the cone"
    assert not away["heading_ok"].any()
    assert not away["included"].any()
    assert (away["V"] == 0).all()


def test_oncoming_segments_visible_and_bounded(placement, snapped, area, params):
    df = _scored(placement, snapped, area, params)
    front = df[(df["edge_id"] == "front-north") & df["included"]]
    assert len(front) > 5
    assert (front["V"] > 0).all() and (front["V"] <= 1).all()
    # closer segments score higher on distance
    assert front.sort_values("dist_m")["D"].is_monotonic_decreasing


def test_obstruction_factor_applies(placement, snapped, area, params):
    import geopandas as gpd
    from shapely.geometry import box

    from ooh import geometry as geo

    x, y = snapped.x, snapped.y
    area.buildings = gpd.GeoDataFrame(geometry=[box(x - 8, y - 200, x - 2, y - 150)], crs=geo.UTM)
    df = _scored(placement, snapped, area, params)
    blocked = df[df["included"] & df["blocked"]]
    assert len(blocked) > 0
    assert (blocked["O"] == params.base("obstruction_factor")).all()
