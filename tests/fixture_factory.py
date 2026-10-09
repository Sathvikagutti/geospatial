"""Build in-memory test fixtures: shapefile .zip bundles and KML documents.

Generated with shapely + geopandas so tests are self-contained (no binary
fixtures committed).
"""

import io
import zipfile

import geopandas as gpd
from shapely.geometry import LineString, MultiPolygon, Point, Polygon

# ---- geometry constants (EPSG:4326 coordinates, around Vijayawada, India) --

POLYGON_DEGREES = Polygon(
    [(80.60, 16.40), (80.62, 16.40), (80.62, 16.44), (80.60, 16.44), (80.60, 16.40)]
)
# ~0.02 deg x 0.04 deg -> about 8.7 km^2 at this latitude.

LINESTRING_DEGREES = LineString([(80.60, 16.40), (80.62, 16.44), (80.64, 16.42)])

POINT_DEGREES = Point(80.61, 16.42)


def make_polygon_only_gdf() -> gpd.GeoDataFrame:
    """Shapefile-compatible pure-polygon dataset (single geometry type per file)."""
    return gpd.GeoDataFrame(
        {
            "name": ["city-block-a", "city-block-b"],
            "category": ["urban", "residential"],
            "geometry": [
                POLYGON_DEGREES,
                Polygon([(80.70, 16.50), (80.72, 16.50), (80.72, 16.54), (80.70, 16.54), (80.70, 16.50)]),
            ],
        },
        crs="EPSG:4326",
    )


def make_line_only_gdf() -> gpd.GeoDataFrame:
    """Shapefile-compatible pure-linestring dataset (same CRS)."""
    return gpd.GeoDataFrame(
        {
            "name": ["ring-road"],
            "category": ["transport"],
            "geometry": [LINESTRING_DEGREES],
        },
        crs="EPSG:4326",
    )


def make_test_gdf() -> gpd.GeoDataFrame:
    """A small mixed-geometry dataset around Vijayawada (EPSG:4326).

    Used only for KML fixtures / non-shapefile writing; a single-file
    shapefile cannot mix geometry types, so the .zip fixtures use the
    type-specific builders above.
    """
    return gpd.GeoDataFrame(
        {
            "name": ["city-block", "ring-road", "mast"],
            "category": ["urban", "transport", "utility"],
            "geometry": [POLYGON_DEGREES, LINESTRING_DEGREES, POINT_DEGREES],
        },
        crs="EPSG:4326",
    )


def make_shapefile_zip(gdf: gpd.GeoDataFrame | None = None, include_sidecars=True) -> bytes:
    """Serialize gdf to a shapefile bundle in a temp dir and zip it in memory."""
    import tempfile
    from pathlib import Path

    gdf = gdf if gdf is not None else make_polygon_only_gdf()
    with tempfile.TemporaryDirectory() as td:
        shp_path = Path(td) / "layer.shp"
        gdf.to_file(shp_path, driver="ESRI Shapefile")
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as zf:
            for member in sorted(shp_path.parent.glob("layer.*")):
                member_name = f"layer{member.suffix}"
                if include_sidecars or member_name.endswith(".shp"):
                    zf.writestr(member_name, member.read_bytes())
    return out.getvalue()


def make_shapefile_zip_inside_folder() -> bytes:
    """Same bundle but with members nested in a subfolder inside the archive."""
    inner = make_shapefile_zip()
    src = zipfile.ZipFile(io.BytesIO(inner))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        for name in src.namelist():
            zf.writestr(f"data/{name}", src.read(name))
    return out.getvalue()


def make_invalid_zip() -> bytes:
    """A .zip with no .shp anywhere."""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as zf:
        zf.writestr("readme.txt", "not a shapefile")
    return out.getvalue()


def make_missing_sidecar_zip() -> bytes:
    """A valid zip whose single .shp has no .shx/.dbf."""
    import tempfile
    from pathlib import Path

    gdf = gpd.GeoDataFrame(
        {"name": ["a"], "geometry": [POLYGON_DEGREES]}, crs="EPSG:4326"
    )
    with tempfile.TemporaryDirectory() as td:
        shp_path = Path(td) / "layer.shp"
        gdf.to_file(shp_path, driver="ESRI Shapefile")
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as zf:
            shp_bytes = (shp_path).read_bytes()
            zf.writestr("layer.shp", shp_bytes)
    return out.getvalue()


# ---- KML ------------------------------------------------------------------


def make_kml() -> bytes:
    """Hand-written KML with a polygon, a linestring, a point, ExtendedData,
    and a wrong-schema xml that still parses by namespace."""
    return b"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark id="pm_1">
      <name>city-block</name>
      <ExtendedData>
        <Data name="category"><value>urban</value></Data>
      </ExtendedData>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              80.60,16.40,0 80.62,16.40,0 80.62,16.44,0 80.60,16.44,0 80.60,16.40,0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
    <Placemark id="pm_2">
      <name>ring-road</name>
      <LineString>
        <coordinates>80.60,16.40,0 80.62,16.44,0 80.64,16.42,0</coordinates>
      </LineString>
    </Placemark>
    <Placemark id="pm_3">
      <name>mast</name>
      <Point><coordinates>80.61,16.42,0</coordinates></Point>
    </Placemark>
    <Placemark id="pm_4">
      <name>no-geometry</name>
      <description>attribute only record</description>
    </Placemark>
  </Document>
</kml>"""


def make_invalid_kml() -> bytes:
    return b"<kml><Document><Placemark><name>broken"


def make_kml_multipolygon() -> bytes:
    return b"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark id="multi_1">
      <name>two parcels</name>
      <MultiGeometry>
        <Polygon><outerBoundaryIs><LinearRing>
          <coordinates>80.60,16.40,0 80.62,16.40,0 80.62,16.44,0 80.60,16.44,0 80.60,16.40,0</coordinates>
        </LinearRing></outerBoundaryIs></Polygon>
        <Polygon><outerBoundaryIs><LinearRing>
          <coordinates>80.70,16.50,0 80.72,16.50,0 80.72,16.54,0 80.70,16.54,0 80.70,16.50,0</coordinates>
        </LinearRing></outerBoundaryIs></Polygon>
      </MultiGeometry>
    </Placemark>
  </Document>
</kml>"""
