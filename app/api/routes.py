"""API routes module implementing geospatial file upload and measurement endpoints."""
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
import tempfile
from typing import List
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from app.config import (
    ALLOWED_EXTENSIONS,
    API_TITLE,
    API_VERSION,
    MAX_FILE_SIZE_BYTES,
    MAX_FILE_SIZE_MB,
    TEMP_UPLOAD_DIR,
)
from app.models.schemas import (
    FileInfoResponse,
    FileStatus,
    HealthCheckResponse,
    MeasurementsResponse,
)
from app.services.geo_engine import GeospatialEngine
from app.services.parsers import GeospatialParser
from app.services.storage import file_storage

router = APIRouter()


@router.get(
    "/health",
    response_model=HealthCheckResponse,
    tags=["System"],
    summary="Health Check",
    description="Returns the operational status and version of the API service."
)
async def health_check():
    """Service health status."""
    return HealthCheckResponse(
        status="healthy",
        service=API_TITLE,
        version=API_VERSION,
    )


@router.post(
    "/files/",
    response_model=FileInfoResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Files"],
    summary="Upload & Process Geospatial File",
    description=(
        "Upload a geospatial file (.zip containing Shapefile or .kml / .kmz). "
        "The file is parsed, validated, and geometric measurements are computed automatically."
    )
)
async def upload_file(file: UploadFile = File(...)):
    """Upload and process a geospatial file."""
    # 1. Validate filename and extension
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is missing or empty."
        )

    filename = file.filename
    file_ext = Path(filename).suffix.lower()

    if file_ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file extension '{file_ext}'. Allowed formats are: {allowed}"
        )

    # 2. Generate unique file identifier
    file_id = uuid.uuid4().hex[:10]
    upload_timestamp = datetime.now(timezone.utc).isoformat()

    # 3. Stream file content to temporary storage with size check
    temp_file_path = TEMP_UPLOAD_DIR / f"{file_id}_{filename}"
    total_bytes = 0

    try:
        with open(temp_file_path, "wb") as buffer:
            while chunk := await file.read(1024 * 1024):  # 1MB chunks
                total_bytes += len(chunk)
                if total_bytes > MAX_FILE_SIZE_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File exceeds maximum allowed size of {MAX_FILE_SIZE_MB} MB."
                    )
                buffer.write(chunk)

        # 4. Parse the geospatial file
        try:
            parsed_dataset = GeospatialParser.parse(temp_file_path, filename)
        except ValueError as parse_err:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Geospatial parsing error: {str(parse_err)}"
            )
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Unexpected error while processing geospatial data: {str(exc)}"
            )

        # 5. Calculate measurements for every extracted feature
        feature_measurements = []
        for feature in parsed_dataset.features:
            measurement = GeospatialEngine.measure_feature(
                feature_id=feature.id,
                geometry=feature.geometry,
                source_crs=parsed_dataset.crs,
                properties=feature.properties,
            )
            feature_measurements.append(measurement)

        # 6. Aggregate measurement summary
        summary = GeospatialEngine.aggregate_measurements(feature_measurements)

        # 7. Construct response objects
        file_info = FileInfoResponse(
            id=file_id,
            filename=filename,
            feature_count=parsed_dataset.feature_count,
            crs=parsed_dataset.crs,
            status=FileStatus.COMPLETED,
            uploaded_at=upload_timestamp,
            error_message=None,
        )

        measurements_response = MeasurementsResponse(
            id=file_id,
            filename=filename,
            original_crs=parsed_dataset.crs,
            projected_crs_strategy=(
                "Dynamic UTM Zone selection via feature centroid with metric reprojection (WGS 84 / UTM)"
            ),
            summary=summary,
            features=feature_measurements,
        )

        # 8. Persist to storage repository
        file_storage.save(file_info=file_info, measurements=measurements_response)

        return file_info

    finally:
        # 9. Clean up temporary uploaded file from disk
        if temp_file_path.exists():
            try:
                temp_file_path.unlink()
            except Exception:
                pass


@router.get(
    "/files/",
    response_model=List[FileInfoResponse],
    tags=["Files"],
    summary="List Uploaded Files",
    description="Returns a list of all uploaded and processed geospatial files."
)
async def list_files():
    """List all uploaded files."""
    return file_storage.list_files()


@router.get(
    "/files/{file_id}/",
    response_model=FileInfoResponse,
    tags=["Files"],
    summary="Get File Information",
    description="Returns metadata for an uploaded geospatial file by ID."
)
async def get_file_info(file_id: str):
    """Retrieve file metadata by ID."""
    record = file_storage.get_file(file_id)
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File with ID '{file_id}' was not found."
        )
    return record


@router.get(
    "/files/{file_id}/measurements/",
    response_model=MeasurementsResponse,
    tags=["Measurements"],
    summary="Get File Measurements",
    description=(
        "Returns calculated measurements (area, length) for all supported features "
        "in the file, transformed into an appropriate metric projected coordinate system."
    )
)
async def get_file_measurements(file_id: str):
    """Retrieve calculated measurements for an uploaded file by ID."""
    measurements = file_storage.get_measurements(file_id)
    if not measurements:
        # Check if file exists at all
        file_rec = file_storage.get_file(file_id)
        if not file_rec:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"File with ID '{file_id}' was not found."
            )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Measurements for file ID '{file_id}' are not available (Status: {file_rec.status})."
        )
    return measurements
