"""End-to-End API tests using real and sample geospatial files."""
from pathlib import Path
from fastapi.testclient import TestClient
import pytest

from app.main import app

client = TestClient(app)


def test_e2e_sample_parcels_kml():
    """Test full API lifecycle with multi-geometry sample KML."""
    kml_path = Path("sample_data/sample_parcels.kml")
    assert kml_path.exists()

    with open(kml_path, "rb") as f:
        response = client.post(
            "/api/files/",
            files={"file": ("sample_parcels.kml", f, "application/vnd.google-earth.kml+xml")}
        )

    assert response.status_code == 201
    file_info = response.json()
    file_id = file_info["id"]
    assert file_info["filename"] == "sample_parcels.kml"
    assert file_info["feature_count"] == 6
    assert file_info["crs"] == "EPSG:4326"
    assert file_info["status"] == "COMPLETED"

    # Fetch measurements
    meas_response = client.get(f"/api/files/{file_id}/measurements/")
    assert meas_response.status_code == 200
    meas_data = meas_response.json()

    summary = meas_data["summary"]
    assert summary["total_features"] == 6
    assert summary["measured_features"] == 4  # 2 polygons + 2 linestrings
    assert summary["unsupported_features"] == 2  # 2 points
    assert summary["geometry_distribution"]["Polygon"] == 2
    assert summary["geometry_distribution"]["LineString"] == 2
    assert summary["geometry_distribution"]["Point"] == 2

    # Verify metric units are used
    assert summary["total_area_sq_meters"] > 1_000_000  # Over 1 km²
    assert summary["total_length_meters"] > 3_000  # Over 3 km
    assert "EPSG:32643" in [f["projected_crs"] for f in meas_data["features"] if f["projected_crs"]]


def test_e2e_india_boundary_shapefile_zip():
    """Test full API lifecycle with real gadm41_IND_0 shapefile zip."""
    zip_path = Path("sample_data/india_boundary_shp.zip")
    if not zip_path.exists():
        pytest.skip("sample_data/india_boundary_shp.zip not found")

    with open(zip_path, "rb") as f:
        response = client.post(
            "/api/files/",
            files={"file": ("india_boundary_shp.zip", f, "application/zip")}
        )

    assert response.status_code == 201
    file_info = response.json()
    file_id = file_info["id"]
    assert file_info["status"] == "COMPLETED"
    assert file_info["feature_count"] >= 1

    # Fetch measurements
    meas_response = client.get(f"/api/files/{file_id}/measurements/")
    assert meas_response.status_code == 200
    meas_data = meas_response.json()

    # Verify India total boundary area is calculated in projected metric units
    summary = meas_data["summary"]
    assert summary["total_area_sq_meters"] > 1e11  # India is ~3.287 million km² = ~3.2e12 m²
    assert summary["total_area_sq_km"] > 2_000_000


def test_e2e_india_gadm_2_kmz():
    """Test full API lifecycle with the provided india_gadm_2.kmz file."""
    kmz_path = Path("india_gadm_2.kmz")
    if not kmz_path.exists():
        pytest.skip("india_gadm_2.kmz not found")

    with open(kmz_path, "rb") as f:
        response = client.post(
            "/api/files/",
            files={"file": ("india_gadm_2.kmz", f, "application/vnd.google-earth.kmz")}
        )

    assert response.status_code == 201
    file_info = response.json()
    assert file_info["status"] == "COMPLETED"
    assert file_info["feature_count"] > 0

    # Retrieve info endpoint
    info_resp = client.get(f"/api/files/{file_info['id']}/")
    assert info_resp.status_code == 200
    assert info_resp.json()["id"] == file_info["id"]
