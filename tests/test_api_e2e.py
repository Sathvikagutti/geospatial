"""End-to-end API tests exercising every endpoint through the FastAPI TestClient."""

import io

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.fixture_factory import (
    make_invalid_zip,
    make_kml,
    make_shapefile_zip,
)


@pytest.fixture()
def client():
    return TestClient(app)


def _upload(client, data: bytes, filename: str):
    return client.post(
        "/api/files/",
        files={"file": (filename, io.BytesIO(data), "application/octet-stream")},
    )


class TestUpload:
    def test_upload_shapefile_zip(self, client):
        r = _upload(client, make_shapefile_zip(), "block.zip")
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["status"] == "COMPLETED"
        assert body["feature_count"] == 2
        assert body["crs"] == "EPSG:4326"
        assert body["target_crs"] == "EPSG:32644"

    def test_upload_kml(self, client):
        r = _upload(client, make_kml(), "survey.kml")
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["status"] == "COMPLETED"
        assert body["feature_count"] == 4
        assert body["crs"] == "EPSG:4326"

    def test_rejects_unsupported_extension(self, client):
        r = _upload(client, b"about", "notes.pdf")
        assert r.status_code == 415

    def test_rejects_empty_body(self, client):
        r = _upload(client, b"", "empty.kml")
        assert r.status_code == 400

    def test_rejects_invalid_zip(self, client):
        r = _upload(client, make_invalid_zip(), "bad.zip")
        assert r.status_code == 400
        assert "no .shp" in r.json()["detail"]

    def test_rejects_broken_kml(self, client):
        r = _upload(client, b"<kml><Document><Placemark>", "broken.kml")
        assert r.status_code == 422
        assert "not valid XML" in r.json()["detail"]


class TestFileInfo:
    def test_returns_stored_summary(self, client):
        created = _upload(client, make_shapefile_zip(), "block.zip").json()
        r = client.get(f"/api/files/{created['id']}/")
        assert r.status_code == 200
        assert r.json() == created

    def test_unknown_id_is_404(self, client):
        r = client.get("/api/files/does-not-exist/")
        assert r.status_code == 404

    def test_listing_includes_uploads(self, client):
        _upload(client, make_kml(), "survey.kml")
        r = client.get("/api/files/")
        assert r.status_code == 200
        assert len(r.json()) >= 1


class TestMeasurements:
    def test_measurements_for_shapefile(self, client):
        created = _upload(client, make_shapefile_zip(), "block.zip").json()
        r = client.get(f"/api/files/{created['id']}/measurements/")
        assert r.status_code == 200
        body = r.json()
        assert body["source_crs"] == "EPSG:4326"
        assert body["target_crs"] == "EPSG:32644"
        assert body["measurement_count"] == 2  # polygon + linestring
        by_type = {m["geometry_type"]: m for m in body["measurements"]}

        poly = by_type["POLYGON"]
        assert poly["area"]["area_km2"] > 0
        assert poly["length"] is None
        assert not poly["unsupported"]

    def test_measurements_for_kml(self, client):
        created = _upload(client, make_kml(), "survey.kml").json()
        r = client.get(f"/api/files/{created['id']}/features")
        assert r.status_code == 200
        feats = r.json()
        assert len(feats) == 4

        poly = next(f for f in feats if f["geometry_type"] == "POLYGON")
        assert poly["measurement"]["area_km2"] > 0
        # Geometry echoed in source CRS coordinates (degrees).
        assert 70 < poly["geometry"]["coordinates"][0][0][0] < 90
