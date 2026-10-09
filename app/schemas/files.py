"""Pydantic response models for the files API."""

from typing import Any, Literal

from pydantic import BaseModel, Field

FileStatus = Literal["PENDING", "PROCESSING", "COMPLETED", "FAILED"]


class FeatureOut(BaseModel):
    """A single extracted geospatial feature."""

    id: str = Field(..., description="Stable feature identifier (FID, KML id, or index).")
    geometry_type: str = Field(..., examples=["Polygon", "LineString", "Point"])
    geometry: dict | None = Field(None, description="GeoJSON geometry in the source CRS; null when the feature has no geometry.")
    crs: str | None = Field(None, description="Source CRS of the feature, e.g. EPSG:4326.")
    properties: dict[str, Any] = Field(default_factory=dict)
    measurement: dict[str, Any] | None = Field(
        None,
        description="Computed measurement (area/length) if the geometry type supports one.",
    )


class FileSummary(BaseModel):
    """Summary returned by POST /api/files/ and GET /api/files/{id}/."""

    id: str = Field(..., examples=["abc123"])
    filename: str = Field(..., examples=["survey.kml"])
    status: FileStatus = "COMPLETED"
    feature_count: int = 0
    crs: str | None = Field(None, description="Source CRS as declared by the file.")
    target_crs: str | None = Field(
        None, description="Projected CRS chosen for measurement calculation."
    )
    error: str | None = None


class MeasurementOut(BaseModel):
    """Measurements for a single feature (feature envelope + measurement)."""

    feature_id: str
    geometry_type: str
    crs: str | None
    target_crs: str | None
    crs_choice_reason: str | None = None
    area: dict[str, Any] | None = None
    length: dict[str, Any] | None = None
    unsupported: bool = Field(
        False, description="True when the geometry type has no measurable dimension."
    )
    reason: str | None = Field(
        None, description="Why measurement is not available for this feature."
    )


class MeasurementsResponse(BaseModel):
    """GET /api/files/{id}/measurements/ payload."""

    file_id: str
    filename: str
    status: FileStatus
    source_crs: str | None
    target_crs: str | None
    crs_choice_reason: str | None
    measurement_count: int
    measurements: list[MeasurementOut]
