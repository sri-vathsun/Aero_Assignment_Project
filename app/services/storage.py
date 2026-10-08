"""In-memory thread-safe storage repository for file metadata and measurement records."""
from datetime import datetime, timezone
import threading
from typing import Dict, List, Optional
from app.models.schemas import (
    FileInfoResponse,
    FileStatus,
    MeasurementsResponse,
)


class FileStorageRepository:
    """Thread-safe storage manager for uploaded geospatial files and their measurements."""

    def __init__(self):
        self._lock = threading.Lock()
        self._file_records: Dict[str, FileInfoResponse] = {}
        self._measurements_records: Dict[str, MeasurementsResponse] = {}

    def save(
        self,
        file_info: FileInfoResponse,
        measurements: Optional[MeasurementsResponse] = None
    ) -> None:
        """Save or update file record and its associated measurements."""
        with self._lock:
            self._file_records[file_info.id] = file_info
            if measurements is not None:
                self._measurements_records[file_info.id] = measurements

    def get_file(self, file_id: str) -> Optional[FileInfoResponse]:
        """Retrieve file information by ID."""
        with self._lock:
            return self._file_records.get(file_id)

    def get_measurements(self, file_id: str) -> Optional[MeasurementsResponse]:
        """Retrieve computed measurements by file ID."""
        with self._lock:
            return self._measurements_records.get(file_id)

    def list_files(self) -> List[FileInfoResponse]:
        """Retrieve all file records ordered by upload time descending."""
        with self._lock:
            return list(reversed(list(self._file_records.values())))

    def clear(self) -> None:
        """Clear all records (mainly for test isolation)."""
        with self._lock:
            self._file_records.clear()
            self._measurements_records.clear()


# Global singleton storage instance
file_storage = FileStorageRepository()
