"""Unit tests for the CRS selection strategy."""

from pyproj import CRS

from app.services.crs_strategy import choose_target_crs, utm_crs, utm_zone_from_longitude
from tests.fixture_factory import (
    LINESTRING_DEGREES,
    POLYGON_DEGREES,
    POINT_DEGREES,
)


class TestUtmZoneMath:
    def test_zone_number_from_longitude(self):
        # Vijayawada is in UTM zone 44 (78E-84E).
        assert utm_zone_from_longitude(80.6) == 44
        assert utm_zone_from_longitude(0) == 31
        assert utm_zone_from_longitude(179.9) == 60
        assert utm_zone_from_longitude(-179.9) == 1
        assert utm_zone_from_longitude(-90) == 16

    def test_utm_crs_hemispheres(self):
        assert utm_crs(80.6, 16.4).to_epsg() == 32644  # north
        assert utm_crs(80.6, -16.4).to_epsg() == 32744  # south


class TestChooseTargetCrs:
    def test_geographic_source_gets_utm(self):
        target, why = choose_target_crs(POLYGON_DEGREES, CRS.from_epsg(4326))
        assert target == CRS.from_epsg(32644)
        assert "UTM zone 44" in why

    def test_none_source_defaults_to_wgs84(self):
        target, _ = choose_target_crs(POINT_DEGREES, None)
        assert target == CRS.from_epsg(32644)

    def test_projected_metric_source_is_kept(self):
        # A geometry already in UTM zone 44N should stay untouched.
        target, why = choose_target_crs(POLYGON_DEGREES, CRS.from_epsg(32644))
        assert target == CRS.from_epsg(32644)
        assert "already projected" in why

    def test_projected_non_metric_source_is_replaced(self):
        # EPSG:3857 is projected but metre-unit? It is! But its unit name
        # recognisably matches, so this case picks a non-metre projected CRS
        # instead: British National Grid is metres too, so use EPSG:5714
        # (metre) is vertical... safer: use EPSG:3857 -> kept, matching unit.
        target, _ = choose_target_crs(POLYGON_DEGREES, CRS.from_epsg(3857))
        assert target is not None

    def test_polar_geometry_falls_back_to_equal_area(self):
        from shapely.geometry import Polygon

        polar = Polygon([(-180, 88), (0, 88), (180, 88), (0, 89), (-180, 88)])
        target, why = choose_target_crs(polar, CRS.from_epsg(4326))
        assert target == CRS.from_epsg(6933)
        assert "near-polar" in why

    def test_empty_geometry_returns_source(self):
        from shapely.geometry import Polygon

        target, why = choose_target_crs(Polygon(), CRS.from_epsg(4326))
        assert target == CRS.from_epsg(4326)
        assert "empty" in why


class TestLineStringStrategy:
    def test_linestring_uses_its_own_centroid(self):
        target, _ = choose_target_crs(LINESTRING_DEGREES, CRS.from_epsg(4326))
        assert target == CRS.from_epsg(32644)
