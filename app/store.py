"""In-memory record store and upload-artifact persistence.

The raw upload is kept on disk (uploads/<id>.<ext>) so it can be reprocessed
or downloaded later; parsed features live on the record for the process
lifetime. Swapping this for Redis/Postgres is a single-file change since every
access goes through FileRecord/FileStore.
"""

import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import config


@dataclass
class FileRecord:
    """Everything the API knows about one uploaded file."""

    id: str
    filename: str
    status: str  # PENDING -> PROCESSING -> COMPLETED | FAILED
    error: str | None = None
    feature_count: int = 0
    source_crs: str | None = None
    target_crs: str | None = None
    crs_choice_reason: str | None = None
    features: list = field(default_factory=list)  # list[domain.Feature]

    def to_summary(self) -> dict:
        d = asdict(self)
        d.pop("features", None)
        return d


class FileStore:
    """Simple process-local registry of FileRecord objects."""

    def __init__(self, upload_dir: Path | None = None):
        self._configured_dir = upload_dir
        self._records: dict[str, FileRecord] = {}

    @property
    def upload_dir(self) -> Path:
        """Resolve the upload directory lazily so test overrides take effect."""
        d = self._configured_dir or config.UPLOAD_DIR
        d.mkdir(parents=True, exist_ok=True)
        return d

    def create(self, filename: str, record_id: str | None = None) -> FileRecord:
        rec = FileRecord(
            id=record_id or uuid.uuid4().hex[:12],
            filename=filename,
            status="PENDING",
        )
        self._records[rec.id] = rec
        return rec

    def get(self, record_id: str) -> FileRecord | None:
        return self._records.get(record_id)

    def all(self) -> list[FileRecord]:
        return list(self._records.values())

    def save_raw(self, record_id: str, filename: str, data: bytes) -> Path:
        """Write the uploaded bytes under the upload dir."""
        ext = Path(filename).suffix.lower() or ".bin"
        path = self.upload_dir / f"{record_id}{ext}"
        path.write_bytes(data)
        return path


# Singleton store used by the API layer.
store = FileStore()
