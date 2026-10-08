"""Geospatial measurement and coordinate transformation engine."""
import math
from typing import Any, Dict, List, Optional, Tuple
import pyproj
from pyproj import CRS, Transformer
import shapely
from shapely.geometry.base import BaseGeometry
import numpy as np

from app.models.schemas import (
    GeometryMeasurement,
    MeasurementsSummary,
    MeasurementType,
)


class GeospatialEngine:
    """Core engine for CRS transformations and geometric measurements."""

    @staticmethod
    def get_utm_epsg(lon: float, lat: float) -> str:
        """
        Determine the EPSG code of the optimal UTM zone for given longitude and latitude.
        
        Args:
            lon: Longitude in decimal degrees [-180, 180]
            lat: Latitude in decimal degrees [-90, 90]
            
        Returns:
            EPSG string, e.g. 'EPSG:32643' for India/Zone 43N
        """
        # Clamp lon to [-180, 180]
        clamped_lon = max(-180.0, min(180.0, lon))
        zone_number = int(math.floor((clamped_lon + 180) / 6.0)) + 1
        if zone_number > 60:
            zone_number = 60

        # Northern hemisphere: 326xx, Southern hemisphere: 327xx
        epsg_code = 32600 + zone_number if lat >= 0 else 32700 + zone_number
        return f"EPSG:{epsg_code}"

    @classmethod
    def is_geographic_crs(cls, crs_str: str) -> bool:
        """
        Check if a given CRS string represents a geographic (degree-based) coordinate system.
        """
        try:
            crs_obj = CRS.from_user_input(crs_str)
            return crs_obj.is_geographic
        except Exception:
            # Assume geographic (degrees) as a safe fallback if unknown or standard 4326
            return True

    @classmethod
    def project_geometry(
        cls,
        geom: BaseGeometry,
        source_crs: str,
        target_crs: str
    ) -> BaseGeometry:
        """
        Transform a Shapely geometry from source_crs to target_crs.
        
        Uses modern vectorized shapely.transform with always_xy=True.
        """
        if source_crs == target_crs:
            return geom

        import numpy as np
        transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
        return shapely.transform(geom, lambda c: np.column_stack(transformer.transform(c[:, 0], c[:, 1])))

    @classmethod
    def measure_feature(
        cls,
        feature_id: str,
        geometry: BaseGeometry,
        source_crs: str = "EPSG:4326",
        properties: Optional[Dict[str, Any]] = None,
    ) -> GeometryMeasurement:
        """
        Calculate appropriate measurements for a single geometry feature.
        
        - Polygon / MultiPolygon -> Area (m², km², hectares)
        - LineString / MultiLineString -> Length (m, km)
        - Point / MultiPoint -> Gracefully handled, no measurement required
        - Others -> Gracefully handled as unsupported
        """
        props = properties or {}
        geom_type = geometry.geom_type if geometry else "Unknown"

        if geometry is None or geometry.is_empty:
            return GeometryMeasurement(
                feature_id=feature_id,
                geometry_type="Empty",
                is_supported=False,
                measurement_type=MeasurementType.NONE,
                value=None,
                unit=None,
                formatted="Empty geometry",
                additional_units=None,
                projected_crs=None,
                properties=props,
            )

        # 1. Point / MultiPoint -> Zero-dimensional, no projection or measurement needed
        if geom_type in ("Point", "MultiPoint"):
            return GeometryMeasurement(
                feature_id=feature_id,
                geometry_type=geom_type,
                is_supported=False,
                measurement_type=MeasurementType.NONE,
                value=None,
                unit=None,
                formatted="Point geometry: zero-dimensional entity, no measurement required",
                additional_units=None,
                projected_crs=None,
                properties=props,
            )

        # 2. Check if geometry type is supported for measurement
        is_supported_polygon = geom_type in ("Polygon", "MultiPolygon")
        is_supported_linestring = geom_type in ("LineString", "MultiLineString")

        if not (is_supported_polygon or is_supported_linestring):
            return GeometryMeasurement(
                feature_id=feature_id,
                geometry_type=geom_type,
                is_supported=False,
                measurement_type=MeasurementType.NONE,
                value=None,
                unit=None,
                formatted=f"Geometry type '{geom_type}' is not supported for measurement calculations",
                additional_units=None,
                projected_crs=None,
                properties=props,
            )

        # 3. Determine target projected CRS if source is geographic (degrees)
        is_geo = cls.is_geographic_crs(source_crs)
        if is_geo:
            centroid = geometry.centroid
            target_projected_crs = cls.get_utm_epsg(centroid.x, centroid.y)
            try:
                projected_geom = cls.project_geometry(geometry, source_crs, target_projected_crs)
            except Exception:
                projected_geom = geometry
                target_projected_crs = source_crs
        else:
            target_projected_crs = source_crs
            projected_geom = geometry

        # 4. Polygon / MultiPolygon -> Calculate Area
        if is_supported_polygon:
            area_sq_m = round(float(projected_geom.area), 2)
            area_sq_km = round(area_sq_m / 1_000_000.0, 6)
            hectares = round(area_sq_m / 10_000.0, 4)

            return GeometryMeasurement(
                feature_id=feature_id,
                geometry_type=geom_type,
                is_supported=True,
                measurement_type=MeasurementType.AREA,
                value=area_sq_m,
                unit="sq_meters",
                formatted=f"{area_sq_m:,.2f} m² ({area_sq_km} km² / {hectares} ha)",
                additional_units={
                    "square_kilometers": area_sq_km,
                    "hectares": hectares,
                },
                projected_crs=target_projected_crs,
                properties=props,
            )

        # 5. LineString / MultiLineString -> Calculate Length
        length_m = round(float(projected_geom.length), 2)
        length_km = round(length_m / 1000.0, 4)

        return GeometryMeasurement(
            feature_id=feature_id,
            geometry_type=geom_type,
            is_supported=True,
            measurement_type=MeasurementType.LENGTH,
            value=length_m,
            unit="meters",
            formatted=f"{length_m:,.2f} m ({length_km} km)",
            additional_units={
                "kilometers": length_km,
            },
            projected_crs=target_projected_crs,
            properties=props,
        )

    @staticmethod
    def aggregate_measurements(measurements: List[GeometryMeasurement]) -> MeasurementsSummary:
        """Aggregate individual feature measurements into a comprehensive summary."""
        total_features = len(measurements)
        measured_features = sum(1 for m in measurements if m.is_supported and m.value is not None)
        unsupported_features = total_features - measured_features

        geometry_distribution: Dict[str, int] = {}
        total_area = 0.0
        has_area = False
        total_length = 0.0
        has_length = False

        for m in measurements:
            geometry_distribution[m.geometry_type] = geometry_distribution.get(m.geometry_type, 0) + 1
            if m.measurement_type == MeasurementType.AREA and m.value is not None:
                total_area += m.value
                has_area = True
            elif m.measurement_type == MeasurementType.LENGTH and m.value is not None:
                total_length += m.value
                has_length = True

        total_area_m2 = round(total_area, 2) if has_area else None
        total_area_km2 = round(total_area / 1_000_000.0, 6) if has_area else None
        total_len_m = round(total_length, 2) if has_length else None
        total_len_km = round(total_length / 1000.0, 4) if has_length else None

        return MeasurementsSummary(
            total_features=total_features,
            measured_features=measured_features,
            unsupported_features=unsupported_features,
            geometry_distribution=geometry_distribution,
            total_area_sq_meters=total_area_m2,
            total_area_sq_km=total_area_km2,
            total_length_meters=total_len_m,
            total_length_km=total_len_km,
        )
