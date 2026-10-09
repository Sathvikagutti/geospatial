"""Parsers turning uploaded bytes (.zip shapefile bundle or .kml) into ParsedFile.

Both loaders normalise their output to:
- a list[Feature] with ids, geometry types, shapely geometries, properties,
- the source CRS as an "EPSG:xxxx" string (or None when the file does not
  declare one and defaults were applied).
"""

import io
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

import geopandas as gpd
import pandas as pd
from pyproj import CRS
from shapely.geometry import shape

from ..domain import Feature, ParsedFile
from ..errors import (
    InvalidArchiveError,
    KmlParseError,
    NoGeometryError,
    ShapefileParseError,
)

KML_NS = "http://www.opengis.net/kml/2.2"

# Pretty-print compound geometry type names (MultiPolygon, etc.) consistently.
_GEOM_TYPE_MAP = {
    "Point": "POINT",
    "LineString": "LINESTRING",
    "Polygon": "POLYGON",
    "MultiPoint": "MULTIPOINT",
    "MultiLineString": "MULTILINESTRING",
    "MultiPolygon": "MULTIPOLYGON",
    "GeometryCollection": "GEOMETRYCOLLECTION",
    "LinearRing": "LINEARRING",
}

# ---------------------------------------------------------------------------
# KML
# ---------------------------------------------------------------------------


def _kml_root(data: bytes) -> ET.Element:
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise KmlParseError(f"KML is not valid XML: {exc}") from exc


def _kml_crs(root: ET.Element) -> str:
    """KML (OGC KML 2.x) always carries WGS84 lon/lat coordinates (EPSG:4326)."""
    return "EPSG:4326"


def parse_kml(data: bytes, filename: str) -> ParsedFile:
    root = _kml_root(data)
    placemarks = root.findall(f".//{{{KML_NS}}}Placemark")

    features: list[Feature] = []
    geom_tags = [
        "Point",
        "LineString",
        "Polygon",
        "MultiGeometry",
        "Model",
        "Track",
        "MultiTrack",
    ]

    for i, pm in enumerate(placemarks):
        pm_id = pm.get("id") or f"placemark_{i}"
        props: dict = {}
        ext = pm.find(f"{{{KML_NS}}}ExtendedData")
        if ext is not None:
            for schema_data in ext.findall(f"{{{KML_NS}}}SchemaData"):
                for sd in schema_data.findall(f"{{{KML_NS}}}SimpleData"):
                    props[sd.get("name", "")] = sd.text
            for data in ext.findall(f"{{{KML_NS}}}Data"):
                name = data.get("name", "")
                value_el = data.find(f"{{{KML_NS}}}value")
                props[name] = value_el.text if value_el is not None else None

        geometry = None
        geom_types = set()
        for tag in geom_tags:
            if pm.find(f".//{{{KML_NS}}}{tag}") is not None:
                geom_types.add(tag)
        if geom_types:
            gml_str = _geometry_xml_to_geojson(pm, geom_types)
            if gml_str:
                geometry = shape(gml_str)

        features.append(
            Feature(
                id=pm_id,
                geometry_type=_shared_type_of(geometry, geom_types),
                geometry=geometry,
                crs=_kml_crs(root),
                properties=props,
            )
        )
    return ParsedFile(filename=filename, source_crs="EPSG:4326", features=features)


def _shared_type_of(geom, geom_tags: set) -> str:
    """Return a geometry type label, preferring MultiGeometry handling."""
    if "MultiGeometry" in geom_tags:
        if geom is not None and hasattr(geom, "geom_type"):
            gt = geom.geom_type
            if gt.startswith("Multi"):
                return _GEOM_TYPE_MAP.get(gt, gt.upper())
            # e.g. MultiGeometry with exactly one polygon: still report MULTI
            return "MULTI" + gt.upper()
        return "MULTIGEOMETRY"
    if geom is None:
        return "UNKNOWN"
    return _GEOM_TYPE_MAP.get(geom.geom_type, geom.geom_type.upper())


def _geometry_xml_to_geojson(pm: ET.Element, geom_tags: set) -> dict | None:
    """Build a GeoJSON geometry dict from KML geometry elements."""
    if "MultiGeometry" in geom_tags:
        parts_geojson = []
        for tag in ("Point", "LineString", "Polygon"):
            for el in pm.findall(f".//{{{KML_NS}}}{tag}"):
                gj = _single_kml_geometry(el, tag)
                if gj:
                    parts_geojson.append(gj)
        if parts_geojson:
            types = {gj["type"] for gj in parts_geojson}
            if len(types) == 1 and len(parts_geojson) > 1:
                only = types.pop()
                return {"type": f"Multi{only}", "coordinates": [gj["coordinates"] for gj in parts_geojson]}
            if len(types) == 1 and len(parts_geojson) == 1:
                return parts_geojson[0]
            return {"type": "GeometryCollection", "geometries": parts_geojson}
        return None

    for tag in ("Point", "LineString", "Polygon"):
        el = pm.find(f".//{{{KML_NS}}}{tag}")
        if el is not None:
            return _single_kml_geometry(el, tag)
    return None


def _single_kml_geometry(el: ET.Element, tag: str) -> dict | None:
    if el is None:
        return None
    coords_el = el.find(f".//{{{KML_NS}}}coordinates")
    if coords_el is None or not (coords_el.text or "").strip():
        return None

    tuples = []
    for chunk in coords_el.text.strip().split():
        parts = chunk.split(",")
        if len(parts) < 2:
            continue
        lon, lat = float(parts[0]), float(parts[1])
        alt = float(parts[2]) if len(parts) > 2 else None
        coord = [lon, lat] + ([alt] if alt is not None else [])
        tuples.append(coord)

    if tag == "Point":
        # KML points carry exactly one coordinate pair.
        if not tuples:
            return None
        return {"type": "Point", "coordinates": tuples[0]}
    if tag == "LineString":
        return {"type": "LineString", "coordinates": tuples}
    if tag == "Polygon":
        # A KML polygon stores each ring as a separate <coordinates>. We expose
        # only the outer boundary; holes are rare and would need linear rings.
        return {"type": "Polygon", "coordinates": [tuples]}

    return None


# ---------------------------------------------------------------------------
# Shapefile (.zip)
# ---------------------------------------------------------------------------


def _safe_member_name(name: str) -> str | None:
    """Guard against zip-slip: reject absolute paths and directory traversal."""
    candidate = Path(name)
    if candidate.is_absolute():
        return None
    if ".." in candidate.parts:
        return None
    return name.replace("\\", "/")


def parse_zip(data: bytes, filename: str) -> ParsedFile:
    """Parse a .zip that must contain a complete shapefile (.shp + .shx + .dbf).

    The bundle is extracted to a scratch directory because GDAL needs the
    .shp/.shx/.dbf/.prj sidecars as sibling files on disk.
    """
    names = _zip_names(data)
    _require_shapefile_members(names, filename)
    shp_member = next(n for n in names if n.lower().endswith(".shp"))

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            with tempfile.TemporaryDirectory() as scratch:
                for name in names:
                    safe = _safe_member_name(name)
                    if safe is not None:
                        zf.extract(safe, scratch)
                        target = Path(scratch, safe)
                        if target.parent != Path(scratch):
                            # flatten nested archives so .shp/.shx stay siblings
                            target.rename(Path(scratch, Path(safe).name))
                gdf = gpd.read_file(Path(scratch, Path(shp_member).name))
    except ShapefileParseError:
        raise
    except Exception as exc:
        raise ShapefileParseError(f"Failed to read shapefile: {exc}") from exc

    return _features_from_gdf(gdf, filename)


def _zip_names(data: bytes) -> list[str]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return zf.namelist()
    except zipfile.BadZipFile as exc:
        raise InvalidArchiveError(f"The uploaded .zip is not a valid archive: {exc}") from exc


def _require_shapefile_members(names: list[str], label: str) -> None:
    shp_files = [n for n in names if n.lower().endswith(".shp")]
    if not shp_files:
        raise InvalidArchiveError("no .shp file found in the archive.")
    for shp_path in shp_files:
        stem = Path(shp_path).stem.lower()
        has_shx = any(
            n.lower().endswith(".shx") and Path(n).stem.lower() == stem
            for n in names
        )
        has_dbf = any(
            n.lower().endswith(".dbf") and Path(n).stem.lower() == stem
            for n in names
        )
        if not has_shx:
            raise InvalidArchiveError(f"'{Path(shp_path).name}' is present but its .shx sidecar is missing.")
        if not has_dbf:
            raise InvalidArchiveError(f"'{Path(shp_path).name}' is present but its .dbf sidecar is missing.")


# ---------------------------------------------------------------------------
# shared
# ---------------------------------------------------------------------------


def _features_from_gdf(gdf: gpd.GeoDataFrame, filename: str) -> ParsedFile:
    crs = _crs_to_string(gdf.crs)

    features: list[Feature] = []
    for idx, row in gdf.iterrows():
        geom = row.geometry
        props = {k: row[k] for k in gdf.columns if k != gdf.geometry.name}
        features.append(
            Feature(
                id=str(idx),
                geometry_type=_type_of(geom),
                geometry=geom,
                crs=crs,
                properties=_clean_props(props),
            )
        )

    if not features:
        raise NoGeometryError("The file contains no features.")
    if all(f.geometry is None for f in features):
        raise NoGeometryError("The file has attribute records but no geometry.")

    return ParsedFile(filename=filename, source_crs=crs, features=features)


def _type_of(geom) -> str:
    if geom is None:
        return "UNKNOWN"
    return _GEOM_TYPE_MAP.get(geom.geom_type, geom.geom_type.upper())


def _crs_to_string(crs) -> str | None:
    if crs is None:
        return None
    if isinstance(crs, CRS):
        epsg = crs.to_epsg()
        if epsg:
            return f"EPSG:{epsg}"
        return crs.to_string()
    return str(crs)


def _clean_props(props: dict) -> dict:
    """Leave scalar/None values alone; stringify everything else."""
    out: dict = {}
    for k, v in props.items():
        if v is None or isinstance(v, (str, int, float, bool)):
            out[k] = None if (isinstance(v, float) and pd.isna(v)) else v
        else:
            out[k] = str(v)
    return out
