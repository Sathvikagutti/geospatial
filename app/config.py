"""Application configuration loaded from environment variables."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Directory where uploaded files and extracted shapefile contents are stored.
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", BASE_DIR / "uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# Per-file upload size limit in megabytes.
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))

ALLOWED_EXTENSIONS = {".zip", ".kml"}

# FastAPI metadata
APP_TITLE = "Geospatial File Measurement API"
APP_DESCRIPTION = (
    "Accepts a Shapefile (.zip) or KML file, extracts its features, and returns "
    "CRS-aware measurements (polygon area, linestring length)."
)
APP_VERSION = "1.0.0"
