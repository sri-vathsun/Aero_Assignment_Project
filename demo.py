"""Live Demonstration Script for Geospatial File Measurement API."""
import json
from pathlib import Path
import httpx

API_BASE_URL = "http://127.0.0.1:8000"

def main():
    print("=" * 70)
    print("   GEOSPATIAL FILE MEASUREMENT API - LIVE INTERACTIVE DEMO   ")
    print("=" * 70)

    client = httpx.Client(base_url=API_BASE_URL, timeout=60.0)

    # 1. Health Check
    print("\n[Step 1] Checking Service Health (GET /api/health)...")
    res = client.get("/api/health")
    print(f"Status: {res.status_code}")
    print(json.dumps(res.json(), indent=2))

    # 2. Upload KML File
    kml_file = Path("sample_data/sample_parcels.kml")
    print(f"\n[Step 2] Uploading KML File: {kml_file.name} (POST /api/files/)...")
    with open(kml_file, "rb") as f:
        upload_kml = client.post(
            "/api/files/",
            files={"file": (kml_file.name, f, "application/vnd.google-earth.kml+xml")}
        )
    print(f"Status: {upload_kml.status_code} Created")
    kml_info = upload_kml.json()
    print(json.dumps(kml_info, indent=2))
    kml_id = kml_info["id"]

    # 3. Retrieve File Information
    print(f"\n[Step 3] Fetching File Information (GET /api/files/{kml_id}/)...")
    file_info = client.get(f"/api/files/{kml_id}/").json()
    print(json.dumps(file_info, indent=2))

    # 4. Retrieve Measurements for KML
    print(f"\n[Step 4] Fetching Measurements (GET /api/files/{kml_id}/measurements/)...")
    meas = client.get(f"/api/files/{kml_id}/measurements/").json()
    print(f"Projection Strategy Used: {meas['projected_crs_strategy']}")
    print("\nSummary Statistics:")
    print(json.dumps(meas["summary"], indent=2))
    
    print("\nFeature-by-Feature Measurement Breakdown:")
    for f in meas["features"]:
        print(f"  • Feature ID: {f['feature_id']:<20} | Type: {f['geometry_type']:<12} | Projected: {f['projected_crs']}")
        print(f"    Measurement : {f['formatted']}")
        if f['properties']:
            print(f"    Properties  : {f['properties']}")
        print()

    # 5. Upload ESRI Shapefile Zip
    shp_zip = Path("sample_data/india_boundary_shp.zip")
    print(f"\n[Step 5] Uploading Shapefile (.zip): {shp_zip.name} (POST /api/files/)...")
    with open(shp_zip, "rb") as f:
        upload_shp = client.post(
            "/api/files/",
            files={"file": (shp_zip.name, f, "application/zip")}
        )
    print(f"Status: {upload_shp.status_code} Created")
    shp_info = upload_shp.json()
    print(json.dumps(shp_info, indent=2))
    shp_id = shp_info["id"]

    # 6. Retrieve Measurements for Shapefile
    print(f"\n[Step 6] Fetching Measurements (GET /api/files/{shp_id}/measurements/)...")
    shp_meas = client.get(f"/api/files/{shp_id}/measurements/").json()
    print("\nShapefile Summary:")
    print(json.dumps(shp_meas["summary"], indent=2))
    print(f"\nTotal Area Calculated: {shp_meas['summary']['total_area_sq_km']:,.2f} sq km")

    # 7. List All Uploaded Files
    print(f"\n[Step 7] Listing All Processed Files (GET /api/files/)...")
    files_list = client.get("/api/files/").json()
    print(f"Total files in store: {len(files_list)}")
    for item in files_list:
        print(f"  - ID: {item['id']} | Filename: {item['filename']} | Features: {item['feature_count']} | Status: {item['status']}")

    print("\n" + "=" * 70)
    print("   DEMO COMPLETED SUCCESSFULLY!   ")
    print("=" * 70)

if __name__ == "__main__":
    main()
