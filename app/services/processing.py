"""Upload orchestration: validate, parse, measure, and record.

Flow for POST /api/files/:
1. validate extension + non-empty + size limit
2. persist raw bytes to uploads/
3. parse (shapefile zip or KML) -> ParsedFile
4. pick a target projected CRS for the dataset
5. compute a measurement per feature (gracefully skipping unsupported types)
6. mark the record COMPLETED or FAILED
"""

from pathlib import Path

from pyproj import CRS

from .. import config
from ..domain import ParsedFile
from ..store import FileRecord, store
from ..errors import (
    AppError,
    EmptyFileError,
    FileTooLargeError,
    UnsupportedFileTypeError,
)
from . import parsers
from .crs_strategy import choose_target_crs
from .measurements import measure_feature


def _validate(name: str, data: bytes) -> None:
    ext = Path(name).suffix.lower()
    if ext not in config.ALLOWED_EXTENSIONS:
        raise UnsupportedFileTypeError()
    if not data:
        raise EmptyFileError()
    max_bytes = config.MAX_UPLOAD_MB * 1024 * 1024
    if len(data) > max_bytes:
        raise FileTooLargeError(config.MAX_UPLOAD_MB)


def process_upload(
    filename: str,
    data: bytes,
    record,  # FileRecord
) -> None:
    """Run the full parse-and-measure pipeline for a freshly uploaded file."""
    record.status = "PROCESSING"
    try:
        _validate(filename, data)
        store.save_raw(record.id, filename, data)

        ext = Path(filename).suffix.lower()
        if ext == ".zip":
            parsed = parsers.parse_zip(data, filename)
        else:
            parsed = parsers.parse_kml(data, filename)

        _finalize(record, parsed)
        record.status = "COMPLETED"
    except AppError as exc:
        record.status = "FAILED"
        record.error = exc.message
        raise
    except Exception as exc:  # unexpected bug -- still mark the record failed
        record.status = "FAILED"
        record.error = f"Unexpected processing error: {exc}"
        raise AppError(str(exc)) from exc


def _finalize(record, parsed: ParsedFile) -> None:
    """Measure each feature and populate the record."""
    record.features = parsed.features
    record.feature_count = len(parsed.features)
    record.source_crs = parsed.source_crs

    # Dataset-level target CRS: derived from the union of all geometries so a
    # file spanning two UTM zones still gets one sensible answer.
    src = CRS.from_user_input(parsed.source_crs) if parsed.source_crs else None
    projectable = [f for f in parsed.features if f.geometry is not None and not f.geometry.is_empty]
    if not projectable:
        record.target_crs = None
        return

    collected = _dataset_extent_geometries(projectable, src)
    target, why = choose_target_crs(collected, src)
    record.target_crs = _crs_str(target)
    record.crs_choice_reason = why

    for feat in record.features:
        if feat.geometry is None:
            continue
        feat.measurement = measure_feature(feat.geometry, src)


def _dataset_extent_geometries(projectable, src):
    """Collect WGS84 centroids of all projectable features for CRS choice."""
    import numpy as np
    import shapely
    from pyproj import Transformer
    from shapely.geometry import MultiPoint

    wgs84 = CRS.from_epsg(4326)

    def _to_wgs84(coords):
        x, y = transformer.transform(coords[:, 0], coords[:, 1])
        return np.column_stack([x, y])

    transformer = None
    if src is not None and src != wgs84:
        transformer = Transformer.from_crs(src, wgs84, always_xy=True)

    centroids = []
    for f in projectable:
        g = f.geometry
        if transformer is not None:
            g = shapely.transform(g, _to_wgs84)
        centroids.append(g.centroid)
    return MultiPoint(centroids)


def _crs_str(crs: CRS) -> str | None:
    if crs is None:
        return None
    epsg = crs.to_epsg()
    return f"EPSG:{epsg}" if epsg else crs.to_string()
