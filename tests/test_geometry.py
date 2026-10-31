import pytest

from ooh import geometry as geo


@pytest.mark.parametrize("dx,dy,expected", [(0, 1, 0), (1, 0, 90), (0, -1, 180), (-1, 0, 270), (1, 1, 45)])
def test_bearing_xy_compass(dx, dy, expected):
    assert geo.bearing_xy(0, 0, dx, dy) == pytest.approx(expected)


def test_bearing_lonlat_known_pairs():
    # Due north and due east from a point in Dubai.
    assert geo.bearing_lonlat(55.27, 25.20, 55.27, 25.30) == pytest.approx(0, abs=1e-6)
    assert geo.bearing_lonlat(55.27, 25.20, 55.37, 25.20) == pytest.approx(90, abs=0.1)
    # Dubai Marina -> DIFC runs north-east along Sheikh Zayed Road.
    assert 40 < geo.bearing_lonlat(55.1455, 25.0805, 55.2770, 25.2115) < 50


def test_angle_diff_wraps():
    assert geo.angle_diff(350, 10) == pytest.approx(20)
    assert geo.angle_diff(10, 350) == pytest.approx(20)
    assert geo.angle_diff(0, 180) == pytest.approx(180)


def test_utm_round_trip_and_distance():
    x, y = geo.to_utm(55.2770, 25.2115)
    lon, lat = geo.to_wgs(x, y)
    assert (lon, lat) == pytest.approx((55.2770, 25.2115), abs=1e-7)
    x2, y2 = geo.offset_point(x, y, 90, 1000)
    lon2, lat2 = geo.to_wgs(x2, y2)
    assert geo.haversine_m(lon, lat, lon2, lat2) == pytest.approx(1000, rel=0.002)


def test_cone_contains_axis_not_back():
    from shapely.geometry import Point

    cone = geo.cone_polygon(0, 0, 0, 400, 35)
    assert cone.contains(Point(0, 200))
    assert not cone.contains(Point(0, -200))
    assert not cone.contains(Point(300, 100))  # 71 degrees off axis
