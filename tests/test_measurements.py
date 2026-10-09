"""Unit tests for measurement calculations.

Expected values are computed independently (geodesic reference values for the
Vijayawada test geometry), so these tests genuinely pin CRS-aware math rather
than comparing the implementation against itself.
"""

import math

import pytest
from pyproj import CRS, Geod
from shapely.geometry import LineString, MultiPolygon, Point, Polygon

from app.services.measurements import measure_feature
from tests.fixture_factory import LINESTRING_DEGREES, POLYGON_DEGREES

GEOD = Geod(ellps="WGS84")

TOLERANCE = 0.005  # 0.5% -- UTM distortion vs geodesic truth at zone centre


def _geodesic_polygon_area_km2(poly: Polygon) -> float:
    """Reference area via the geodesic math of pyproj (independent of UTM)."""
    lon, lat = poly.exterior.coords.xy
    area, _ = GEOD.polygon_area_perimeter(lon, lat)
    return abs(area) / 1_000_000


def _geodesic_length_km(line: LineString) -> float:
    lon, lat = line.coords.xy
    return GEOD.line_length(lon, lat) / 1_000


class TestPolygonArea:
    def test_polygon_area_close_to_geodesic(self):
        result = measure_feature(POLYGON_DEGREES, CRS.from_epsg(4326))
        expected_km2 = _geodesic_polygon_area_km2(POLYGON_DEGREES)
        assert result["area_km2"] == pytest.approx(expected_km2, rel=TOLERANCE)

    def test_polygon_units_are_consistent(self):
        result = measure_feature(POLYGON_DEGREES, CRS.from_epsg(4326))
        assert result["area_km2"] == pytest.approx(result["area_m2"] / 1e6, rel=1e-4)
        assert result["area_ha"] == pytest.approx(result["area_m2"] / 1e4, rel=1e-4)
        assert result["perimeter_m"] > 0

    def test_polygon_is_not_measured_in_degrees(self):
        """The classic bug: area in deg^2 would be ~0.0008 instead of ~8 km^2."""
        result = measure_feature(POLYGON_DEGREES, CRS.from_epsg(4326))
        assert result["area_km2"] > 1.0

    def test_polygon_target_crs_is_projected(self):
        result = measure_feature(POLYGON_DEGREES, CRS.from_epsg(4326))
        crs = CRS.from_user_input(result["target_crs"])
        assert crs.is_projected


class TestLineStringLength:
    def test_linestring_length_close_to_geodesic(self):
        result = measure_feature(LINESTRING_DEGREES, CRS.from_epsg(4326))
        expected_km = _geodesic_length_km(LINESTRING_DEGREES)
        assert result["length_km"] == pytest.approx(expected_km, rel=TOLERANCE)

    def test_linestring_units_are_consistent(self):
        result = measure_feature(LINESTRING_DEGREES, CRS.from_epsg(4326))
        assert result["length_km"] == pytest.approx(result["length_m"] / 1000, rel=1e-4)


class TestUnsupportedTypes:
    def test_point_returns_no_measurement_keys(self):
        result = measure_feature(Point(80.6, 16.4), CRS.from_epsg(4326))
        assert "area_m2" not in result
        assert "length_m" not in result
        assert result["target_crs"].startswith("EPSG:326")

    def test_empty_polygon(self):
        result = measure_feature(Polygon(), CRS.from_epsg(4326))
        assert "area_m2" not in result

    def test_multipolygon_reports_parts(self):
        mp = MultiPolygon(
            [POLYGON_DEGREES, POLYGON_DEGREES.buffer(0.001)]
        )
        result = measure_feature(mp, CRS.from_epsg(4326))
        assert result["parts"] == 2
        assert result["area_m2"] > 0


class TestAlreadyProjectedSource:
    def test_utm_source_kept_and_measured_in_place(self):
        # Build a square in UTM 44N with exactly known metric dimensions.
        utm = CRS.from_epsg(32644)
        poly_utm = Polygon([(500000, 1800000), (600000, 1800000), (600000, 1900000), (500000, 1900000), (500000, 1800000)])
        result = measure_feature(poly_utm, utm)
        # A 100 km x 100 km square in a metre CRS.
        assert result["area_km2"] == pytest.approx(100 * 100, rel=TOLERANCE)
