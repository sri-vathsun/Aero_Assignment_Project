"""Application Configuration settings."""
from pathlib import Path

# Base Paths
BASE_DIR = Path(__file__).resolve().parent.parent
TEMP_UPLOAD_DIR = BASE_DIR / "temp_uploads"
TEMP_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# API Metadata
API_TITLE = "Geospatial File Measurement API"
API_DESCRIPTION = (
    "Production-ready backend service to process Shapefile (.zip) and KML geospatial files, "
    "project geographic coordinates appropriately, and compute geometric measurements."
)
API_VERSION = "1.0.0"

# Upload and Processing Configurations
ALLOWED_EXTENSIONS = {".zip", ".kml", ".kmz"}
MAX_FILE_SIZE_MB = 100  # 100 MB upload limit
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

# Default fallback coordinate reference system
DEFAULT_GEOGRAPHIC_CRS = "EPSG:4326"
