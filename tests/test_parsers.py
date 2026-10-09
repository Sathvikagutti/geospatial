"""Unit tests for the shapefile and KML parsers."""

import pytest
from shapely.geometry import MultiPolygon, Point

from app.errors import (
    InvalidArchiveError,
    KmlParseError,
    NoGeometryError,
    ShapefileParseError,
)
from app.services import parsers as P
from tests.fixture_factory import (
    make_invalid_kml,
    make_invalid_zip,
    make_kml,
    make_kml_multipolygon,
    make_line_only_gdf,
    make_missing_sidecar_zip,
    make_shapefile_zip,
    make_shapefile_zip_inside_folder,
)


class TestShapefileZip:
    def test_parse_polygon_bundle(self):
        parsed = P.parse_zip(make_shapefile_zip(), "test.zip")
        assert parsed.source_crs == "EPSG:4326"
        assert len(parsed.features) == 2
        types = {f.geometry_type for f in parsed.features}
        assert types == {"POLYGON"}
        assert parsed.features[0].properties["name"] == "city-block-a"

    def test_zip_with_nested_folder(self):
        parsed = P.parse_zip(make_shapefile_zip_inside_folder(), "nested.zip")
        assert len(parsed.features) == 2

    def test_missing_shp_raises_invalid_archive(self):
        with pytest.raises(InvalidArchiveError):
            P.parse_zip(make_invalid_zip(), "junk.zip")

    def test_missing_sidecar_raises(self):
        with pytest.raises(InvalidArchiveError) as exc:
            P.parse_zip(make_missing_sidecar_zip(), "incomplete.zip")
        assert ".shx" in exc.value.message

    def test_not_a_zip_raises(self):
        with pytest.raises(InvalidArchiveError):
            P.parse_zip(b"this is not a zip at all", "fake.zip")

    def test_parse_linestring_bundle(self):
        parsed = P.parse_zip(make_shapefile_zip(make_line_only_gdf()), "lines.zip")
        assert len(parsed.features) == 1
        assert parsed.features[0].geometry_type == "LINESTRING"


class TestKml:
    def test_parse_full_kml(self):
        parsed = P.parse_kml(make_kml(), "sample.kml")
        assert parsed.source_crs == "EPSG:4326"
        ids = [f.id for f in parsed.features]
        assert ids == ["pm_1", "pm_2", "pm_3", "pm_4"]
        types = [f.geometry_type for f in parsed.features]
        assert types == ["POLYGON", "LINESTRING", "POINT", "UNKNOWN"]
        assert parsed.features[3].geometry is None

    def test_extended_data_becomes_properties(self):
        parsed = P.parse_kml(make_kml(), "sample.kml")
        assert parsed.features[0].properties == {"category": "urban"}

    def test_multigeometry_becomes_multipolygon(self):
        parsed = P.parse_kml(make_kml_multipolygon(), "multi.kml")
        f = parsed.features[0]
        assert isinstance(f.geometry, MultiPolygon)
        assert f.geometry_type == "MULTIPOLYGON"

    def test_invalid_xml_raises(self):
        with pytest.raises(KmlParseError):
            P.parse_kml(make_invalid_kml(), "broken.kml")

    def test_kml_coordinates_have_z_stripped_into_ignore(self):
        parsed = P.parse_kml(make_kml(), "sample.kml")
        pt = next(f for f in parsed.features if f.geometry_type == "POINT")
        assert isinstance(pt.geometry, Point)
        assert pt.geometry.x == pytest.approx(80.61)
        assert pt.geometry.y == pytest.approx(16.42)
