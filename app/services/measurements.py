"""Measurement calculation for supported geometry types.

For every feature we:
1. Skip measurement when the geometry type is unsupported (Point,
   GeometryCollection, null/empty geometries) — the feature is still returned
   with its attributes so the response stays complete.
2. Transform the geometry from its source CRS into the target projected CRS
   chosen by `crs_strategy`.
3. Compute area (m^2, with hectares/km^2 convenience fields for polygons) or
   geodesic-quality projected length (m, with km convenience field).
"""

import numpy as np
import shapely
from pyproj import CRS, Transformer

from .crs_strategy import choose_target_crs

# One shared transformer per (src, dst) pair; pyproj caches internally but
# creating them up-front keeps the loop hot path allocation-free.
_transformer_cache: dict[tuple[int, int], Transformer] = {}


def _transformer(src: CRS, dst: CRS) -> Transformer:
    key = (src.to_epsg() or hash(src.to_wkt()), dst.to_epsg() or hash(dst.to_wkt()))
    if key not in _transformer_cache:
        _transformer_cache[key] = Transformer.from_crs(src, dst, always_xy=True)
    return _transformer_cache[key]


def _reproject(geom, src: CRS, dst: CRS):
    if src == dst:
        return geom
    transformer = _transformer(src, dst)

    def _transform_coords(coords):
        """coords: (N, >=2) array -> pyproj-transformed (N, d) array."""
        rest = [coords[:, i] for i in range(2, coords.shape[1])]
        x, y, *z = transformer.transform(coords[:, 0], coords[:, 1], *rest)
        return np.column_stack([x, y, *z])

    return shapely.transform(geom, _transform_coords)


def measure_feature(geom, source_crs: CRS | None) -> dict:
    """Return a measurement dict for a single (non-point) geometry.

    Raises nothing; shapes with unsupported types are assumed filtered by the caller.
    """
    if geom is None or geom.is_empty:
        return {"target_crs": None, "crs_choice_reason": "empty or null geometry; nothing to measure"}

    target, why = choose_target_crs(geom, source_crs)
    src = source_crs or CRS.from_epsg(4326)
    projected = _reproject(geom, src, target)

    geom_type = geom.geom_type
    result: dict = {"target_crs": _crs_str(target), "crs_choice_reason": why}

    if geom_type == "Polygon":
        area_m2 = projected.area
        result.update(
            {
                "area_m2": round(area_m2, 2),
                "area_km2": round(area_m2 / 1_000_000, 6),
                "area_ha": round(area_m2 / 10_000, 4),
                "perimeter_m": round(projected.length, 2),
            }
        )
    elif geom_type == "MultiPolygon":
        areas = [p.area for p in projected.geoms]
        result.update(
            {
                "area_m2": round(sum(areas), 2),
                "area_km2": round(sum(areas) / 1_000_000, 6),
                "area_ha": round(sum(areas) / 10_000, 4),
                "perimeter_m": round(projected.length, 2),
                "parts": len(areas),
            }
        )
    elif geom_type == "LineString":
        result.update(
            {
                "length_m": round(projected.length, 2),
                "length_km": round(projected.length / 1_000, 3),
            }
        )
    elif geom_type == "MultiLineString":
        lens = [ln.length for ln in projected.geoms]
        result.update(
            {
                "length_m": round(sum(lens), 2),
                "length_km": round(sum(lens) / 1_000, 3),
                "parts": len(lens),
            }
        )
    # Point / GeometryCollection / unknown -> no measurement keys at all.
    return result


def _crs_str(crs: CRS) -> str:
    epsg = crs.to_epsg()
    return f"EPSG:{epsg}" if epsg else crs.to_string()
