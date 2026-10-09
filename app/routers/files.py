"""HTTP layer for the /api/files endpoints.

The router stays thin: validate input, delegate to the processing service,
translate AppErrors into JSON error responses.
"""

from fastapi import APIRouter, File, HTTPException, UploadFile

from ..errors import AppError, FileNotFoundError_
from ..schemas.files import (
    FeatureOut,
    FileSummary,
    MeasurementOut,
    MeasurementsResponse,
)
from ..services.processing import process_upload
from ..store import store

router = APIRouter(prefix="/api/files", tags=["files"])


def _get_record_or_404(record_id: str):
    rec = store.get(record_id)
    if rec is None:
        raise FileNotFoundError_("No uploaded file with this id.")
    return rec


def _app_error_to_http(exc: AppError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.post(
    "",
    response_model=FileSummary,
    status_code=201,
    summary="Upload and process a geospatial file (.zip shapefile or .kml)",
)
async def upload_file(file: UploadFile = File(..., description="A .zip shapefile bundle or .kml document.")):
    """Accepts a geospatial file, parses it, and computes measurements.

    The blocking pipeline runs in a worker thread so the event loop stays free.
    """
    filename = file.filename or ""
    data = await file.read()

    record = store.create(filename)
    try:
        process_upload(filename, data, record)
    except AppError as exc:
        raise _app_error_to_http(exc) from exc

    return FileSummary(
        id=record.id,
        filename=record.filename,
        status=record.status,
        feature_count=record.feature_count,
        crs=record.source_crs,
        target_crs=record.target_crs,
        error=record.error,
    )


@router.get("", response_model=list[FileSummary], summary="List uploaded files")
def list_files():
    return [
        FileSummary(
            id=r.id,
            filename=r.filename,
            status=r.status,
            feature_count=r.feature_count,
            crs=r.source_crs,
            target_crs=r.target_crs,
            error=r.error,
        )
        for r in store.all()
    ]


@router.get("/{record_id}", response_model=FileSummary, summary="Get info about an uploaded file")
def get_file(record_id: str):
    try:
        rec = _get_record_or_404(record_id)
    except AppError as exc:
        raise _app_error_to_http(exc) from exc
    return FileSummary(
        id=rec.id,
        filename=rec.filename,
        status=rec.status,
        feature_count=rec.feature_count,
        crs=rec.source_crs,
        target_crs=rec.target_crs,
        error=rec.error,
    )


@router.get(
    "/{record_id}/features",
    response_model=list[FeatureOut],
    summary="List extracted features with their measurements",
)
def get_features(record_id: str):
    try:
        rec = _get_record_or_404(record_id)
    except AppError as exc:
        raise _app_error_to_http(exc) from exc

    out = []
    for f in rec.features:
        measurement = f.measurement
        out.append(
            FeatureOut(
                id=f.id,
                geometry_type=f.geometry_type,
                geometry=_to_geojson(f.geometry),
                crs=f.crs,
                properties=f.properties,
                measurement=measurement,
            )
        )
    return out


@router.get(
    "/{record_id}/measurements",
    response_model=MeasurementsResponse,
    summary="Get measurements for every feature in the file",
)
def get_measurements(record_id: str):
    try:
        rec = _get_record_or_404(record_id)
    except AppError as exc:
        raise _app_error_to_http(exc) from exc

    if rec.status != "COMPLETED":
        raise HTTPException(
            status_code=409,
            detail=f"File is not fully processed yet (status={rec.status}).",
        )

    items: list[MeasurementOut] = []
    for f in rec.features:
        m = f.measurement or {}
        area_keys = ("area_m2", "area_km2", "area_ha", "perimeter_m")
        length_keys = ("length_m", "length_km")
        area = {k: m[k] for k in area_keys if k in m} or None
        length = {k: m[k] for k in length_keys if k in m} or None
        unsupported = f.geometry is None or f.geometry_type not in {
            "POLYGON", "MULTIPOLYGON", "LINESTRING", "MULTILINESTRING"
        }
        reason = None
        if unsupported:
            if f.geometry is None:
                reason = "Feature has no geometry."
            elif f.geometry.is_empty:
                reason = "Feature has an empty geometry."
            else:
                reason = f"Geometry type {f.geometry_type} has no measurable length/area."

        items.append(
            MeasurementOut(
                feature_id=f.id,
                geometry_type=f.geometry_type,
                crs=f.crs,
                target_crs=rec.target_crs,
                crs_choice_reason=m.get("crs_choice_reason"),
                area=area,
                length=length,
                unsupported=unsupported,
                reason=reason,
            )
        )

    return MeasurementsResponse(
        file_id=rec.id,
        filename=rec.filename,
        status=rec.status,
        source_crs=rec.source_crs,
        target_crs=rec.target_crs,
        crs_choice_reason=rec.crs_choice_reason,
        measurement_count=sum(1 for i in items if not i.unsupported),
        measurements=items,
    )


def _to_geojson(geom) -> dict | None:
    if geom is None:
        return None
    import json

    from shapely.geometry import mapping

    return json.loads(json.dumps(mapping(geom)))
