"""Pydantic schemas and data transfer models for the Geospatial API."""
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class FileStatus(str, Enum):
    """Status lifecycle of an uploaded geospatial file."""
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class MeasurementType(str, Enum):
    """Type of measurement performed on a geometry."""
    AREA = "AREA"
    LENGTH = "LENGTH"
    NONE = "NONE"


class GeometryMeasurement(BaseModel):
    """Measurement outcome for a single spatial feature."""
    feature_id: str = Field(..., description="Unique index or ID of the feature")
    geometry_type: str = Field(..., description="Type of geometry (e.g. Polygon, LineString, Point)")
    is_supported: bool = Field(..., description="True if geometry supports measurement calculations")
    measurement_type: MeasurementType = Field(..., description="Type of measurement applied")
    value: Optional[float] = Field(None, description="Primary measurement value (sq meters for area, meters for length)")
    unit: Optional[str] = Field(None, description="Primary measurement unit (e.g., 'sq_meters' or 'meters')")
    formatted: Optional[str] = Field(None, description="Human-friendly formatted measurement string")
    additional_units: Optional[Dict[str, float]] = Field(
        default=None,
        description="Convenience conversions (e.g., hectares, square kilometers, kilometers)"
    )
    projected_crs: Optional[str] = Field(None, description="Projected coordinate system used for calculation")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Feature attributes and metadata")


class FileInfoResponse(BaseModel):
    """File metadata summary returned by GET /api/files/{id}/."""
    id: str = Field(..., description="Unique identifier for the file record")
    filename: str = Field(..., description="Original uploaded filename")
    feature_count: int = Field(..., description="Total count of geospatial features parsed")
    crs: str = Field(..., description="Original coordinate reference system detected in the file")
    status: FileStatus = Field(..., description="Current processing status")
    uploaded_at: str = Field(..., description="Timestamp of file upload")
    error_message: Optional[str] = Field(None, description="Error explanation if status is FAILED")


class MeasurementsSummary(BaseModel):
    """Aggregated measurements and summary statistics."""
    total_features: int
    measured_features: int
    unsupported_features: int
    geometry_distribution: Dict[str, int]
    total_area_sq_meters: Optional[float] = None
    total_area_sq_km: Optional[float] = None
    total_length_meters: Optional[float] = None
    total_length_km: Optional[float] = None


class MeasurementsResponse(BaseModel):
    """Detailed measurements returned by GET /api/files/{id}/measurements/."""
    id: str = Field(..., description="Unique identifier for the file record")
    filename: str = Field(..., description="Original uploaded filename")
    original_crs: str = Field(..., description="Source coordinate reference system")
    projected_crs_strategy: str = Field(..., description="Description of the projection strategy applied")
    summary: MeasurementsSummary = Field(..., description="Overall summary and aggregated totals")
    features: List[GeometryMeasurement] = Field(..., description="Detailed measurements per feature")


class HealthCheckResponse(BaseModel):
    """Service health response."""
    status: str
    service: str
    version: str
