"""Integration tests for FastAPI endpoints: upload, file info, and measurements."""
import io
import zipfile
from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.services.storage import file_storage

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_storage():
    """Ensure a clean storage state before every test."""
    file_storage.clear()
    yield
    file_storage.clear()


SAMPLE_KML = b"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark id="pm_poly">
      <name>Survey Field Alpha</name>
      <ExtendedData>
        <Data name="crop"><value>Wheat</value></Data>
      </ExtendedData>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              77.50,13.00,0 77.51,13.00,0 77.51,13.01,0 77.50,13.01,0 77.50,13.00,0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
    <Placemark id="pm_line">
      <name>Canal Line</name>
      <LineString>
        <coordinates>
          77.50,13.00,0 77.51,13.00,0
        </coordinates>
      </LineString>
    </Placemark>
    <Placemark id="pm_point">
      <name>Observation Station</name>
      <Point>
        <coordinates>77.505,13.005,0</coordinates>
      </Point>
    </Placemark>
  </Document>
</kml>
"""


def test_upload_kml_and_retrieve_measurements():
    """Test full workflow: upload KML -> get file info -> get measurements."""
    # 1. Upload KML file
    files = {"file": ("test_survey.kml", io.BytesIO(SAMPLE_KML), "application/vnd.google-earth.kml+xml")}
    response = client.post("/api/files/", files=files)

    assert response.status_code == 201
    file_data = response.json()
    assert "id" in file_data
    assert file_data["filename"] == "test_survey.kml"
    assert file_data["feature_count"] == 3
    assert file_data["crs"] == "EPSG:4326"
    assert file_data["status"] == "COMPLETED"

    file_id = file_data["id"]

    # 2. Get file info
    info_resp = client.get(f"/api/files/{file_id}/")
    assert info_resp.status_code == 200
    info_data = info_resp.json()
    assert info_data["id"] == file_id
    assert info_data["feature_count"] == 3

    # 3. Get measurements
    meas_resp = client.get(f"/api/files/{file_id}/measurements/")
    assert meas_resp.status_code == 200
    meas_data = meas_resp.json()

    assert meas_data["id"] == file_id
    assert meas_data["filename"] == "test_survey.kml"
    assert "UTM" in meas_data["projected_crs_strategy"]

    # Verify Summary
    summary = meas_data["summary"]
    assert summary["total_features"] == 3
    assert summary["measured_features"] == 2
    assert summary["unsupported_features"] == 1
    assert summary["geometry_distribution"]["Polygon"] == 1
    assert summary["geometry_distribution"]["LineString"] == 1
    assert summary["geometry_distribution"]["Point"] == 1
    assert summary["total_area_sq_meters"] is not None
    assert summary["total_length_meters"] is not None

    # Verify individual feature measurements
    features = meas_data["features"]
    assert len(features) == 3

    # Polygon measurement
    poly_feat = next(f for f in features if f["feature_id"] == "pm_poly")
    assert poly_feat["geometry_type"] == "Polygon"
    assert poly_feat["measurement_type"] == "AREA"
    assert poly_feat["unit"] == "sq_meters"
    assert poly_feat["value"] > 500_000
    assert poly_feat["properties"]["crop"] == "Wheat"

    # LineString measurement
    line_feat = next(f for f in features if f["feature_id"] == "pm_line")
    assert line_feat["geometry_type"] == "LineString"
    assert line_feat["measurement_type"] == "LENGTH"
    assert line_feat["unit"] == "meters"
    assert line_feat["value"] > 500

    # Point measurement (gracefully handled, no calculation)
    pt_feat = next(f for f in features if f["feature_id"] == "pm_point")
    assert pt_feat["geometry_type"] == "Point"
    assert pt_feat["measurement_type"] == "NONE"
    assert pt_feat["value"] is None
    assert pt_feat["is_supported"] is False


def test_file_not_found_errors():
    """Verify 404 responses for non-existent file IDs."""
    resp1 = client.get("/api/files/nonexistent_id/")
    assert resp1.status_code == 404
    assert "was not found" in resp1.json()["detail"]

    resp2 = client.get("/api/files/nonexistent_id/measurements/")
    assert resp2.status_code == 404
    assert "was not found" in resp2.json()["detail"]


def test_upload_invalid_file_extension():
    """Verify 400 error when uploading unsupported file types like .txt or .csv."""
    files = {"file": ("data.txt", io.BytesIO(b"Hello World"), "text/plain")}
    response = client.post("/api/files/", files=files)
    assert response.status_code == 400
    assert "Unsupported file extension" in response.json()["detail"]


def test_upload_corrupt_zip_archive():
    """Verify 422 error when uploading a zip with no geospatial data."""
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        zf.writestr("test.txt", "not a spatial file")
    zip_buffer.seek(0)

    files = {"file": ("corrupt.zip", zip_buffer, "application/zip")}
    response = client.post("/api/files/", files=files)
    assert response.status_code == 422
    assert "Geospatial parsing error" in response.json()["detail"]
