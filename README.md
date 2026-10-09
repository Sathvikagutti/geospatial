# Geospatial File Measurement API

A FastAPI service that accepts a geospatial file (Shapefile `.zip` or KML), extracts
its features, and returns CRS-aware measurements — polygon areas and linestring
lengths computed in a proper projected coordinate system, never in degrees.

```
POST /api/files/                    upload + parse + measure
GET  /api/files/                    list uploads
GET  /api/files/{id}/               file info
GET  /api/files/{id}/features       extracted features (geometry + attributes)
GET  /api/files/{id}/measurements/  measurements per feature
```

Interactive OpenAPI docs are generated automatically at `/docs` and `/redoc`.

---

## Setup

Requires Python **3.11+** and [uv](https://docs.astral.sh/uv/) (or plain pip).

```bash
# clone, then from the project root:
uv sync --all-groups          # creates .venv and installs everything, including test deps

# run the API
uv run uvicorn app.main:app --reload
# -> http://127.0.0.1:8000  (docs at http://127.0.0.1:8000/docs)

# run the test suite (41 tests: units + end-to-end)
uv run pytest
```

Without uv:

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]" 2>/dev/null || pip install fastapi "uvicorn[standard]" geopandas shapely pyproj python-multipart pytest httpx
uvicorn app.main:app --reload
```

### Configuration (environment variables)

| Variable        | Default                    | Purpose                                   |
|-----------------|----------------------------|-------------------------------------------|
| `UPLOAD_DIR`    | `./uploads`                | Where uploaded files are persisted        |
| `MAX_UPLOAD_MB` | `50`                       | Per-file upload size limit                |

`uploads/` is git-ignored; no external database is required for the base flow.

---

## API

### `POST /api/files/`

Multipart upload. Accepts a `.zip` shapefile bundle (`.shp` + `.shx` + `.dbf`, optionally
`.prj`) or a `.kml` document. The file is parsed, measured, and registered in one call.

```bash
curl -F "file=@survey.kml" http://localhost:8000/api/files/
```

`201 Created`:

```json
{
  "id": "466c66488680",
  "filename": "sample.kml",
  "status": "COMPLETED",
  "feature_count": 4,
  "crs": "EPSG:4326",
  "target_crs": "EPSG:32644",
  "error": null
}
```

Error responses carry a human-readable `detail`; the status distinguishes the failure:
`415` unsupported extension, `413` too large, `400` empty file / broken archive
(missing `.shp` or sidecars), `422` unparseable geometry content.

### `GET /api/files/{id}/`

```json
{
  "id": "466c66488680",
  "filename": "survey.kml",
  "status": "COMPLETED",
  "feature_count": 4,
  "crs": "EPSG:4326",
  "target_crs": "EPSG:32644",
  "error": null
}
```

`404` when the id is unknown.

### `GET /api/files/{id}/measurements/`

Per-feature measurements. Areas are in m²/km²/ha, lengths in m/km, every response
declares both the source CRS and the projected CRS the numbers were computed in.

```json
{
  "file_id": "466c66488680",
  "filename": "survey.kml",
  "status": "COMPLETED",
  "source_crs": "EPSG:4326",
  "target_crs": "EPSG:32644",
  "crs_choice_reason": "centroid near (80.61, 16.42); UTM zone 44N selected",
  "measurement_count": 2,
  "measurements": [
    {
      "feature_id": "pm_1",
      "geometry_type": "POLYGON",
      "crs": "EPSG:4326",
      "target_crs": "EPSG:32644",
      "crs_choice_reason": "centroid near (80.61, 16.42); UTM zone 44N selected",
      "area": {
        "area_m2": 9448596.04,
        "area_km2": 9.448596,
        "area_ha": 944.8596,
        "perimeter_m": 13120.39
      },
      "length": null,
      "unsupported": false,
      "reason": null
    },
    {
      "feature_id": "pm_2",
      "geometry_type": "LINESTRING",
      "length": { "length_m": 7987.89, "length_km": 7.988 },
      "area": null,
      "unsupported": false,
      "reason": null
    },
    {
      "feature_id": "pm_3",
      "geometry_type": "POINT",
      "area": null,
      "length": null,
      "unsupported": true,
      "reason": "Geometry type POINT has no measurable length/area."
    },
    {
      "feature_id": "pm_4",
      "geometry_type": "UNKNOWN",
      "unsupported": true,
      "reason": "Feature has no geometry."
    }
  ]
}
```

Points, null geometries, and GeometryCollections are reported back with
`unsupported: true` and an explanation rather than causing a failure — one bad
feature never breaks the batch.

### `GET /api/files/{id}/features`

The raw extracted features: GeoJSON geometry (source CRS), attribute properties,
and the measurement dict inline.

---

## Architecture

```
app/
├── main.py                 FastAPI app factory: router registration, error handler
├── config.py               env-driven settings (upload dir, size limit)
├── domain.py               Feature / ParsedFile dataclasses (the shared language)
├── errors.py               AppError hierarchy, one class per failure mode
├── schemas/files.py        Pydantic response models
├── store.py                FileRecord + FileStore (uploads persisted to disk)
├── routers/files.py        thin HTTP layer: validate, delegate, translate errors
└── services/
    ├── parsers.py          .zip shapefile and KML -> ParsedFile
    ├── crs_strategy.py     choose_target_crs(geom, source_crs)
    ├── measurements.py     measure_feature(geom, src) -> area/length dict
    └── processing.py       orchestration: validate -> parse -> CRS -> measure
tests/
├── fixture_factory.py      generates shapefile zips + KML bytes in memory
├── test_crs_strategy.py    zone math, hemisphere, polar and projected fallbacks
├── test_measurements.py    values checked against independent geodesic truth
├── test_parsers.py         zip integrity, sidecars, KML namespaces, ExtendedData
└── test_api_e2e.py         every endpoint through the FastAPI TestClient
```

**Key structural choice:** the HTTP layer knows nothing about geometry, and the
geometry services know nothing about HTTP. `processing.process_upload` is the only
place the two meet. That made the whole pipeline testable without FastAPI, and
keeps each file replaceable.

### File-processing flow

```
POST /api/files/
  1. extension/size/emptiness validation (415/413/400)
  2. raw bytes persisted to uploads/<id>.<ext>       (retryable later)
  3. parser dispatch:
       .zip -> zip integrity + sidecar check -> scratch-dir extract -> geopandas
       .kml -> XML parse -> Placemark walk -> GeoJSON -> shapely shapes
  4. ParsedFile(features[], source_crs) stored on the FileRecord
  5. measurement pass -> record marked COMPLETED (or FAILED with reason)
```

A malformed file fails fast with the specific cause in `detail`; a valid file with
a mix of good and degenerate features completes and reports the degenerate ones
individually.

### Measurement calculation flow

```
for each feature:
  geometry null/empty or non-measurable type -> marked unsupported, skipped
  POLYGON/MULTIPOLYGON   -> reproject -> area (m2, km2, ha) + perimeter
  LINESTRING/MULTILINE   -> reproject -> length (m, km)
the reproject step is skipped entirely when the source CRS is already projected
```

### CRS handling

Nothing is ever measured in degrees. The decision tree in `crs_strategy.py`:

1. **Source is already projected with metre units** → measure in place; no
   reprojection means no added error.
2. **Source is geographic (e.g. EPSG:4326) or missing** → compute the dataset's
   WGS84 centroid, map longitude to the containing UTM zone (6° bands;
   `EPSG:326xx` north / `EPSG:327xx` south). At lat 16°N a UTM zone introduces
   ≲0.04% scale distortion across the whole zone — far below typical
   measurement tolerance.
3. **Polar geometry (|lat| ≥ 84°)** → UTM breaks down; fall back to the
   equal-area `EPSG:6933`.

The chosen CRS and the reason travel with every response (`target_crs`,
`crs_choice_reason`), so a client can audit exactly which projection produced a
number. Web-Mercator (EPSG:3857) is deliberately never used for area: it
inflates area by `1/cos(lat)`² (≈11% at Vijayawada's latitude, worse further
from the equator).

The KML loader pins `EPSG:4326` because the KML 2.2 spec mandates WGS84
lon/lat coordinates — a `.prj`-free format still gets a correct, declared CRS.
Shapefiles without `.prj` report `crs: null` rather than silently assuming.

---

## Design Decisions

**FastAPI over Django.** The task is a small, stateless, CPU-bound file
pipeline. Django+DRF buys an ORM and admin that this service doesn't need, while
FastAPI gives async file handling, Pydantic schemas, and generated OpenAPI docs
with zero configuration. (The measure step is synchronous and cheap; very large
files would move it to a task queue — see Future Scope.)

**Multi-geometry-type files are inherently unsupported by Shapefile.** The ESRI
format stores exactly one geometry type per layer. The test fixtures reflect
that reality: polygon-only and line-only zips, while the KML fixtures carry all
types in one document. The parser reads whatever the archive holds and reports
it.

**Scratch-dir extraction for shapefiles.** GDAL requires `.shp/.shx/.dbf/.prj`
as sibling files on disk; the `/vsizip/` in-memory path proved unreliable for
multi-file bundles. Extraction happens into an OS temp dir that is deleted
immediately after read, with a zip-slip guard rejecting absolute paths and `..`
traversal.

**Independent truth for tests.** Measurement tests don't compare the service
against itself: they check against `pyproj.Geod` geodesic area/length (a
completely different math path), with a 0.5% tolerance that absorbs the known
UTM-vs-geodesic discrepancy. A service that naively measured in degrees would
produce ~0.0008 "km²" instead of 9.45 and fail loudly.

**In-memory store.** Records live for the process lifetime; uploads persist to
disk. Every access funnels through `FileStore`, so swapping in Postgres/Redis
later touches one file.

**Errors as types, not strings.** One `AppError` subclass per failure mode with
its own HTTP status; the FastAPI handler maps them to consistent `{"detail":
...}` bodies. Adding a failure mode is a two-line change.

---

## Learning & Future Scope

### What this project exercises

- Reading the KML 2.2 spec and hand-rolling a namespace-correct parser that
  handles `<MultiGeometry>`, `<ExtendedData>`, 3D coordinates, and attribute-
  only placemarks — cases that generic tools quietly mangle.
- The practical meaning of *geodesic vs projected* measurement, UTM band math,
  and why "just use Web Mercator" is the most common GIS API bug.
- Building test fixtures that generate real (not committed binary) shapefiles
  at test time, and testing measurement correctness against an independent
  mathematical reference.

### Future scope

- **Background processing:** move the measure pass into a queue (Celery /
  RQ / arq) with the record's `PENDING/PROCESSING/COMPLETED/FAILED` status
  already wired for it; enables very large files without blocking.
- **Durable storage:** replace the in-memory store with Postgres + SQLAlchemy
  (or Redis); the `FileStore` seam makes this contained.
- **More formats:** GeoJSON, GPX, GeoPackage — each is one `parsers.py` branch.
- **Auth & multi-tenancy:** API keys at the router, ownership on `FileRecord`.
- **Chunked uploads** and resumable transfers for datasets beyond the size
  cap, plus S3-backed artifact storage.
- **Geometry repair** (zero-buffer self-intersection fixing) with an explicit
  `repaired: true` flag in the response so clients know when a measurement
  came from adjusted input.
