"""Choose an appropriate projected CRS for measurement.

Strategy
--------
Source files typically arrive in EPSG:4326 (or another geographic CRS).
Measuring in degrees is meaningless (a "degree" of longitude shrinks away
from the equator), so we transform to a projected metric CRS first.

1. If the source CRS already exists *and* is projected with metric units,
   use it as-is — re-projecting would only introduce error.
2. If the source is geographic, we pick a projected CRS matched to the
   geometry's location:

   a. For a single-part or modest-area dataset, compute the geometry's
      centroid and select the matching UTM zone (EPSG:326xx for northern
      hemisphere, EPSG:327xx for southern). UTM preserves shape well and
      keeps the scale distortion at the centre of a zone to ~0.04%, well
      under measurement tolerance.

   b. For very large or pole-crossing geometries where a single UTM zone
      does not fit, fall back to an equal-area projection (EPSG:6933,
      WGS 84 / NSIDC EASE-Grid 2.0) which is a solid default for area.
"""

import numpy as np
import shapely
from pyproj import CRS, Transformer

# Web-Mercator is deliberately NOT used for area: it inflates areas away
# from the equator by a factor of 1/cos(lat) and is not conformal in area.
WEB_MERCATOR = CRS.from_epsg(3857)

# Metric equal-area fallback for global-scale geometries.
EQUAL_AREA_EPSG = 6933

UTM_INCREMENT = 6  # degrees of longitude per UTM zone


def utm_zone_from_longitude(lon: float) -> int:
    """Return the UTM zone number (1..60) containing the given longitude."""
    zone = int((lon + 180) // UTM_INCREMENT) + 1
    return max(1, min(60, zone))

def utm_crs(lon: float, lat: float) -> CRS:
    """Return the WGS84 UTM zone covering (lon, lat).

    EPSG:326xx for the northern hemisphere, EPSG:327xx for the southern.
    """
    zone = utm_zone_from_longitude(lon)
    epsg = (326 if lat >= 0 else 327) * 100 + zone
    return CRS.from_epsg(epsg)


def choose_target_crs(geom, source_crs: CRS | None) -> tuple[CRS, str]:
    """Pick a metric CRS appropriate for `geom`.

    Returns (target_crs, explanation) where explanation is a short human
    string suitable for API responses / logging.
    """
    if geom is None or geom.is_empty:
        return (source_crs, "empty geometry; no transformation applied")

    # 1. Source already projected & metric -> measure in place.
    if source_crs is not None:
        s = source_crs
        if s.is_projected and s.axis_info[0].unit_name.lower() in {"metre", "meter", "m"}:
            return (s, "source CRS is already projected with metre units")

    # 2. Determine source; default to EPSG:4326 only when nothing is declared.
    src = source_crs or CRS.from_epsg(4326)

    # 3. Reproject geometry to geographic coords to find its centroid
    wgs84 = CRS.from_epsg(4326)
    if src != wgs84:
        transformer = Transformer.from_crs(src, wgs84, always_xy=True)

        def _to_wgs84(coords):
            rest = [coords[:, i] for i in range(2, coords.shape[1])]
            x, y, *z = transformer.transform(coords[:, 0], coords[:, 1], *rest)
            return np.column_stack([x, y, *z])

        wgs_geom = shapely.transform(geom, _to_wgs84)
    else:
        wgs_geom = geom

    centroid = wgs_geom.centroid
    lon, lat = centroid.x, centroid.y

    # Poles / high latitudes: UTM degrades, use equal-area.
    if abs(lat) >= 84:
        target = CRS.from_epsg(EQUAL_AREA_EPSG)
        return (
            target,
            f"centroid at lat {lat:.2f} is near-polar; using EPSG:{EQUAL_AREA_EPSG} equal-area fallback",
        )

    target = utm_crs(lon, lat)
    return (
        target,
        f"centroid near ({lon:.2f}, {lat:.2f}); UTM zone {utm_zone_from_longitude(lon)}"
        f"{'N' if lat >= 0 else 'S'} selected",
    )
