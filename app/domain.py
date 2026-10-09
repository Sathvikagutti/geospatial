"""Core domain models shared across the service layers."""

from dataclasses import dataclass, field

from shapely.geometry import shape

# Supported OGC geometry types (upper-case).
SUPPORTED_GEOMETRY_TYPES = {"POINT", "LINESTRING", "POLYGON", "MULTIPOINT", "MULTILINESTRING", "MULTIPOLYGON"}

# Types that get a derived measurement; everything else is reported without one.
MEASURABLE_TYPES = {"LINESTRING", "MULTILINESTRING", "POLYGON", "MULTIPOLYGON"}


@dataclass
class Feature:
    """A single geospatial feature extracted from an uploaded file."""

    id: str
    geometry_type: str  # upper-case OGC type, e.g. "POLYGON"
    geometry: shape  # shapely geometry (possibly None for null geometry)
    crs: str | None
    properties: dict = field(default_factory=dict)
    measurement: dict | None = None  # filled in by the measurement pipeline

    @property
    def is_measurable(self) -> bool:
        return (
            self.geometry is not None
            and not self.geometry.is_empty
            and self.geometry_type in MEASURABLE_TYPES
        )

    @property
    def measurement_kind(self) -> str | None:
        """Return 'area' for (multi)polygons and 'length' for (multi)linestrings."""
        if not self.is_measurable:
            return None
        if "POLYGON" in self.geometry_type:
            return "area"
        if "LINESTRING" in self.geometry_type:
            return "length"
        return None


@dataclass
class ParsedFile:
    """Result of parsing an uploaded geospatial file."""

    filename: str
    source_crs: str | None
    features: list[Feature]
