"""Unit tests for Shapefile and KML parsers."""
import io
from pathlib import Path
import zipfile
import pytest

from app.services.parsers import GeospatialParser, KMLParser, ShapefileParser


def test_kml_parser_with_sample_xml():
    """Verify KML parser parses Polygon, LineString, Point, and attributes."""
    sample_kml = b"""<?xml version="1.0" encoding="UTF-8"?>
    <kml xmlns="http://www.opengis.net/kml/2.2">
      <Document>
        <Placemark id="f1">
          <name>Survey Field Alpha</name>
          <description>Agricultural sector</description>
          <ExtendedData>
            <Data name="crop"><value>Wheat</value></Data>
            <Data name="owner"><value>Farmer Bob</value></Data>
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
        <Placemark id="f2">
          <name>Boundary Fence</name>
          <LineString>
            <coordinates>
              77.50,13.00,0 77.51,13.00,0
            </coordinates>
          </LineString>
        </Placemark>
        <Placemark id="f3">
          <name>Well Head</name>
          <Point>
            <coordinates>77.505,13.005,0</coordinates>
          </Point>
        </Placemark>
      </Document>
    </kml>
    """

    dataset = KMLParser.parse_kml_content(sample_kml, "test.kml")

    assert dataset.filename == "test.kml"
    assert dataset.feature_count == 3
    assert dataset.crs == "EPSG:4326"

    # Feature 1: Polygon
    f1 = dataset.features[0]
    assert f1.id == "f1"
    assert f1.geometry_type == "Polygon"
    assert f1.geometry is not None
    assert f1.properties["name"] == "Survey Field Alpha"
    assert f1.properties["crop"] == "Wheat"
    assert f1.properties["owner"] == "Farmer Bob"

    # Feature 2: LineString
    f2 = dataset.features[1]
    assert f2.id == "f2"
    assert f2.geometry_type == "LineString"
    assert f2.geometry is not None
    assert f2.properties["name"] == "Boundary Fence"

    # Feature 3: Point
    f3 = dataset.features[2]
    assert f3.id == "f3"
    assert f3.geometry_type == "Point"
    assert f3.geometry is not None
    assert f3.properties["name"] == "Well Head"


def test_real_kmz_parsing():
    """Verify parsing the provided real-world india_gadm_2.kmz file."""
    kmz_path = Path("india_gadm_2.kmz")
    if not kmz_path.exists():
        pytest.skip("india_gadm_2.kmz not present in workspace")

    dataset = GeospatialParser.parse(kmz_path, "india_gadm_2.kmz")
    assert dataset.feature_count > 0
    assert dataset.crs == "EPSG:4326"
    first = dataset.features[0]
    assert first.geometry is not None
    assert first.geometry_type in ("Polygon", "MultiPolygon")
    assert "COUNTRY" in first.properties or "NAME_1" in first.properties


def test_real_shapefile_zip_parsing(tmp_path):
    """Package gadm41_IND_0 shapefile into a zip and verify ShapefileParser."""
    shp_dir = Path("gadm41_IND_shp")
    shp_base = shp_dir / "gadm41_IND_0"
    if not (shp_dir.exists() and (shp_dir / "gadm41_IND_0.shp").exists()):
        pytest.skip("gadm41_IND_shp not present in workspace")

    # Create temporary zip containing shapefile components
    zip_target = tmp_path / "india_boundary.zip"
    with zipfile.ZipFile(zip_target, "w") as zf:
        for ext in [".shp", ".shx", ".dbf", ".prj", ".cpg"]:
            src = shp_dir / f"gadm41_IND_0{ext}"
            if src.exists():
                zf.write(src, arcname=f"gadm41_IND_0{ext}")

    dataset = GeospatialParser.parse(zip_target, "india_boundary.zip")
    assert dataset.feature_count > 0
    assert "EPSG:4326" in dataset.crs or "WGS 84" in dataset.crs
    assert len(dataset.features) == dataset.feature_count
    assert dataset.features[0].geometry_type in ("Polygon", "MultiPolygon")


def test_invalid_archive_handling(tmp_path):
    """Verify that an archive with neither .shp nor .kml raises a clean ValueError."""
    dummy_zip = tmp_path / "empty.zip"
    with zipfile.ZipFile(dummy_zip, "w") as zf:
        zf.writestr("notes.txt", "just plain text")

    with pytest.raises(ValueError, match="Invalid archive contents"):
        GeospatialParser.parse(dummy_zip, "empty.zip")


def test_unsupported_file_extension(tmp_path):
    """Verify that unsupported extensions raise ValueError."""
    dummy_file = tmp_path / "data.csv"
    dummy_file.write_text("x,y\n1,2")

    with pytest.raises(ValueError, match="Unsupported file format"):
        GeospatialParser.parse(dummy_file, "data.csv")
