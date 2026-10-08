"""Unit tests for the Geospatial Engine and CRS projection logic."""
from shapely.geometry import Polygon, LineString, Point, GeometryCollection
from app.services.geo_engine import GeospatialEngine
from app.models.schemas import MeasurementType


def test_utm_zone_determination():
    """Verify UTM zone EPSG calculation across hemispheres."""
    # New Delhi, India (East, North) -> Zone 43N
    assert GeospatialEngine.get_utm_epsg(77.2, 28.6) == "EPSG:32643"
    # New York, USA (West, North) -> Zone 18N
    assert GeospatialEngine.get_utm_epsg(-74.0, 40.7) == "EPSG:32618"
    # Sydney, Australia (East, South) -> Zone 56S
    assert GeospatialEngine.get_utm_epsg(151.2, -33.8) == "EPSG:32756"


def test_polygon_area_in_projected_crs():
    """
    Verify that polygon area is calculated in square meters, NOT square degrees.
    A roughly 0.01 deg x 0.01 deg square near equator is ~1.1 km x 1.1 km = ~1,200,000 m².
    In degrees it would be 0.0001, which is invalid.
    """
    # Create ~1km x 1km polygon near Bangalore/India (lon 77.5, lat 13.0)
    # 0.009 deg latitude ≈ 1,000 meters
    poly = Polygon([
        (77.500, 13.000),
        (77.509, 13.000),
        (77.509, 13.009),
        (77.500, 13.009),
        (77.500, 13.000),
    ])

    measurement = GeospatialEngine.measure_feature(
        feature_id="poly_01",
        geometry=poly,
        source_crs="EPSG:4326",
        properties={"name": "Test Farm Field"}
    )

    assert measurement.is_supported is True
    assert measurement.measurement_type == MeasurementType.AREA
    assert measurement.unit == "sq_meters"
    assert measurement.projected_crs == "EPSG:32643"
    # Area should be roughly ~970,000 to ~1,100,000 sq meters
    assert 900_000 <= measurement.value <= 1_200_000
    assert measurement.additional_units is not None
    assert "square_kilometers" in measurement.additional_units
    assert "hectares" in measurement.additional_units


def test_linestring_length_in_projected_crs():
    """Verify that LineString length is calculated in meters, NOT degrees."""
    # ~1 km line segment
    line = LineString([(77.50, 13.00), (77.50, 13.009)])

    measurement = GeospatialEngine.measure_feature(
        feature_id="line_01",
        geometry=line,
        source_crs="EPSG:4326",
        properties={"highway": "primary"}
    )

    assert measurement.is_supported is True
    assert measurement.measurement_type == MeasurementType.LENGTH
    assert measurement.unit == "meters"
    # ~0.009 deg latitude is ~990 - 1000 meters
    assert 950 <= measurement.value <= 1050
    assert measurement.additional_units["kilometers"] > 0.9


def test_point_handling_graceful():
    """Verify Point geometry produces no measurement and does not raise errors."""
    point = Point(77.5946, 12.9716)

    measurement = GeospatialEngine.measure_feature(
        feature_id="pt_01",
        geometry=point,
        source_crs="EPSG:4326",
        properties={"landmark": "Bangalore"}
    )

    assert measurement.is_supported is False
    assert measurement.measurement_type == MeasurementType.NONE
    assert measurement.value is None
    assert "Point geometry" in measurement.formatted


def test_unsupported_geometry_graceful():
    """Verify unsupported geometry types do not crash the engine."""
    empty_coll = GeometryCollection([])

    measurement = GeospatialEngine.measure_feature(
        feature_id="coll_01",
        geometry=empty_coll,
        source_crs="EPSG:4326",
    )

    # Empty geometry handled gracefully
    assert measurement.is_supported is False
    assert measurement.value is None


def test_measurements_summary_aggregation():
    """Verify summary correctly tallies counts, totals, and distributions."""
    poly = Polygon([(77.50, 13.00), (77.51, 13.00), (77.51, 13.01), (77.50, 13.01), (77.50, 13.00)])
    line = LineString([(77.50, 13.00), (77.51, 13.00)])
    pt = Point(77.50, 13.00)

    m1 = GeospatialEngine.measure_feature("1", poly, "EPSG:4326")
    m2 = GeospatialEngine.measure_feature("2", line, "EPSG:4326")
    m3 = GeospatialEngine.measure_feature("3", pt, "EPSG:4326")

    summary = GeospatialEngine.aggregate_measurements([m1, m2, m3])

    assert summary.total_features == 3
    assert summary.measured_features == 2
    assert summary.unsupported_features == 1
    assert summary.geometry_distribution == {"Polygon": 1, "LineString": 1, "Point": 1}
    assert summary.total_area_sq_meters is not None
    assert summary.total_length_meters is not None
