"""Geospatial file parsers for ESRI Shapefiles (.zip) and KML/KMZ files."""
from dataclasses import dataclass, field
import os
from pathlib import Path
import shutil
import tempfile
from typing import Any, Dict, List, Optional, Tuple
import zipfile

from lxml import etree
import pyproj
from pyproj import CRS
import shapefile
import shapely
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPolygon,
    Point,
    Polygon,
    shape,
)
from shapely.geometry.base import BaseGeometry

from app.config import DEFAULT_GEOGRAPHIC_CRS


@dataclass
class ParsedFeature:
    """Standardized internal representation of a spatial feature."""
    id: str
    geometry_type: str
    geometry: Optional[BaseGeometry]
    crs: str
    properties: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedDataset:
    """Standardized representation of a parsed geospatial file."""
    filename: str
    crs: str
    feature_count: int
    features: List[ParsedFeature]


class ShapefileParser:
    """Parser for zipped ESRI Shapefiles."""

    @staticmethod
    def _is_safe_path(base_dir: Path, target_path: Path) -> bool:
        """Prevent Zip-Slip vulnerabilities by ensuring resolved path is within base_dir."""
        try:
            target_path.resolve().relative_to(base_dir.resolve())
            return True
        except ValueError:
            return False

    @classmethod
    def parse_zip(cls, zip_path: Path, filename: str) -> ParsedDataset:
        """
        Extract and parse a Shapefile from a .zip archive.
        
        Args:
            zip_path: Path to the .zip archive on disk
            filename: Original uploaded filename
        """
        temp_extract_dir = Path(tempfile.mkdtemp(prefix="shp_extract_"))
        try:
            # 1. Safely extract zip archive
            with zipfile.ZipFile(zip_path, "r") as archive:
                for member in archive.infolist():
                    target = temp_extract_dir / member.filename
                    if not cls._is_safe_path(temp_extract_dir, target):
                        raise ValueError(f"Insecure zip archive entry detected: {member.filename}")
                archive.extractall(temp_extract_dir)

            # 2. Find .shp file
            shp_files = list(temp_extract_dir.rglob("*.shp"))
            if not shp_files:
                raise ValueError("No .shp file found inside the uploaded zip archive.")
            
            # Use the first valid .shp file found
            shp_file = shp_files[0]
            base_stem = shp_file.stem
            parent_dir = shp_file.parent

            # 3. Detect CRS from .prj file if present
            detected_crs = DEFAULT_GEOGRAPHIC_CRS
            prj_file = parent_dir / f"{base_stem}.prj"
            if prj_file.exists():
                try:
                    prj_content = prj_file.read_text(encoding="utf-8", errors="ignore").strip()
                    if prj_content:
                        crs_obj = CRS.from_user_input(prj_content)
                        # Extract EPSG authority code if available, else standard string
                        epsg = crs_obj.to_epsg()
                        detected_crs = f"EPSG:{epsg}" if epsg else crs_obj.name or "CUSTOM_PROJECTED"
                except Exception:
                    detected_crs = DEFAULT_GEOGRAPHIC_CRS

            # 4. Read Shapefile records
            features: List[ParsedFeature] = []
            with shapefile.Reader(str(shp_file)) as sf:
                for idx, shape_rec in enumerate(sf.iterShapeRecords()):
                    feature_id = str(idx + 1)
                    raw_shape = shape_rec.shape

                    # Convert to Shapely geometry
                    geom: Optional[BaseGeometry] = None
                    geom_type = "None"
                    if raw_shape and raw_shape.points:
                        try:
                            geom = shape(raw_shape.__geo_interface__)
                            if not geom.is_valid:
                                geom = shapely.make_valid(geom)
                            geom_type = geom.geom_type
                        except Exception:
                            geom = None
                            geom_type = "Invalid"

                    # Extract DBF attributes
                    properties: Dict[str, Any] = {}
                    if hasattr(shape_rec, "record"):
                        try:
                            properties = shape_rec.record.as_dict()
                        except Exception:
                            properties = {}

                    features.append(
                        ParsedFeature(
                            id=feature_id,
                            geometry_type=geom_type,
                            geometry=geom,
                            crs=detected_crs,
                            properties=properties,
                        )
                    )

            return ParsedDataset(
                filename=filename,
                crs=detected_crs,
                feature_count=len(features),
                features=features,
            )

        finally:
            # Clean up extracted temp files
            shutil.rmtree(temp_extract_dir, ignore_errors=True)


class KMLParser:
    """Parser for KML and KMZ geospatial files."""

    @staticmethod
    def _parse_coordinates(coord_text: str) -> List[Tuple[float, float]]:
        """Parse coordinate string (lon,lat,alt tuples separated by whitespace)."""
        coords = []
        if not coord_text:
            return coords
        for token in coord_text.strip().split():
            parts = token.split(",")
            if len(parts) >= 2:
                try:
                    lon, lat = float(parts[0]), float(parts[1])
                    coords.append((lon, lat))
                except ValueError:
                    continue
        return coords

    @classmethod
    def _parse_geometry_element(cls, elem: etree._Element) -> Optional[BaseGeometry]:
        """Convert a KML geometry XML element to a Shapely geometry."""
        tag = etree.QName(elem).localname

        if tag == "Point":
            coords_elem = elem.find("{*}coordinates")
            if coords_elem is not None and coords_elem.text:
                pts = cls._parse_coordinates(coords_elem.text)
                if pts:
                    return Point(pts[0])

        elif tag == "LineString":
            coords_elem = elem.find("{*}coordinates")
            if coords_elem is not None and coords_elem.text:
                pts = cls._parse_coordinates(coords_elem.text)
                if len(pts) >= 2:
                    return LineString(pts)

        elif tag == "Polygon":
            outer_ring_elem = elem.find(".//{*}outerBoundaryIs/{*}LinearRing/{*}coordinates")
            if outer_ring_elem is not None and outer_ring_elem.text:
                shell_pts = cls._parse_coordinates(outer_ring_elem.text)
                if len(shell_pts) >= 3:
                    # Parse optional inner rings (holes)
                    holes = []
                    for inner_elem in elem.findall(".//{*}innerBoundaryIs/{*}LinearRing/{*}coordinates"):
                        if inner_elem.text:
                            inner_pts = cls._parse_coordinates(inner_elem.text)
                            if len(inner_pts) >= 3:
                                holes.append(inner_pts)
                    poly = Polygon(shell=shell_pts, holes=holes)
                    return poly if poly.is_valid else shapely.make_valid(poly)

        elif tag == "MultiGeometry":
            sub_geoms = []
            for child in elem:
                sub_geom = cls._parse_geometry_element(child)
                if sub_geom is not None and not sub_geom.is_empty:
                    sub_geoms.append(sub_geom)
            
            if not sub_geoms:
                return None
            
            # Combine homogeneously if possible
            if all(g.geom_type in ("Polygon", "MultiPolygon") for g in sub_geoms):
                polys = []
                for g in sub_geoms:
                    if g.geom_type == "Polygon":
                        polys.append(g)
                    elif g.geom_type == "MultiPolygon":
                        polys.extend(g.geoms)
                return MultiPolygon(polys)
            elif all(g.geom_type in ("LineString", "MultiLineString") for g in sub_geoms):
                lines = []
                for g in sub_geoms:
                    if g.geom_type == "LineString":
                        lines.append(g)
                    elif g.geom_type == "MultiLineString":
                        lines.extend(g.geoms)
                return MultiLineString(lines)
            else:
                return GeometryCollection(sub_geoms)

        return None

    @classmethod
    def _parse_placemark(cls, placemark_elem: etree._Element, index: int) -> ParsedFeature:
        """Extract ID, properties, and geometry from a KML Placemark element."""
        # 1. Attributes / Properties
        properties: Dict[str, Any] = {}

        name_elem = placemark_elem.find("{*}name")
        if name_elem is not None and name_elem.text:
            properties["name"] = name_elem.text.strip()

        desc_elem = placemark_elem.find("{*}description")
        if desc_elem is not None and desc_elem.text:
            properties["description"] = desc_elem.text.strip()

        # Parse ExtendedData
        for data_elem in placemark_elem.findall(".//{*}ExtendedData/{*}Data"):
            attr_name = data_elem.attrib.get("name")
            val_elem = data_elem.find("{*}value")
            if attr_name and val_elem is not None and val_elem.text:
                properties[attr_name] = val_elem.text.strip()

        for sdata_elem in placemark_elem.findall(".//{*}ExtendedData/{*}SchemaData/{*}SimpleData"):
            attr_name = sdata_elem.attrib.get("name")
            if attr_name and sdata_elem.text:
                properties[attr_name] = sdata_elem.text.strip()

        # 2. Geometry search
        geom: Optional[BaseGeometry] = None
        for tag in ["Polygon", "LineString", "Point", "MultiGeometry"]:
            geom_elem = placemark_elem.find(f".//{{*}}{tag}")
            if geom_elem is not None:
                geom = cls._parse_geometry_element(geom_elem)
                break

        feature_id = placemark_elem.attrib.get("id") or str(index)
        geom_type = geom.geom_type if geom else "None"

        return ParsedFeature(
            id=str(feature_id),
            geometry_type=geom_type,
            geometry=geom,
            crs=DEFAULT_GEOGRAPHIC_CRS,  # KML OGC standard is always WGS 84 (EPSG:4326)
            properties=properties,
        )

    @classmethod
    def parse_kml_content(cls, kml_bytes: bytes, filename: str) -> ParsedDataset:
        """Parse raw KML bytes into a standardized ParsedDataset."""
        # Parse XML tree safely
        parser = etree.XMLParser(recover=True, no_network=True)
        root = etree.fromstring(kml_bytes, parser=parser)

        features: List[ParsedFeature] = []
        placemarks = root.findall(".//{*}Placemark")

        for idx, pm in enumerate(placemarks):
            feature = cls._parse_placemark(pm, idx + 1)
            features.append(feature)

        return ParsedDataset(
            filename=filename,
            crs=DEFAULT_GEOGRAPHIC_CRS,
            feature_count=len(features),
            features=features,
        )

    @classmethod
    def parse_file(cls, file_path: Path, filename: str) -> ParsedDataset:
        """Parse KML or KMZ file from disk."""
        # If it's a KMZ (zipped KML) or zip containing .kml
        if zipfile.is_zipfile(file_path):
            with zipfile.ZipFile(file_path, "r") as archive:
                kml_names = [n for n in archive.namelist() if n.lower().endswith(".kml")]
                if not kml_names:
                    raise ValueError("No .kml file found inside the zipped archive.")
                with archive.open(kml_names[0]) as kml_file:
                    return cls.parse_kml_content(kml_file.read(), filename)
        else:
            kml_bytes = file_path.read_bytes()
            return cls.parse_kml_content(kml_bytes, filename)


class GeospatialParser:
    """Master facade to auto-detect and parse any supported geospatial file."""

    @classmethod
    def parse(cls, file_path: Path, original_filename: str) -> ParsedDataset:
        """
        Identify file format and invoke the corresponding parser.
        
        Supports:
        - .zip containing Shapefiles (.shp, .dbf, .prj)
        - .kml files
        - .kmz (or .zip containing .kml)
        """
        suffix = Path(original_filename).suffix.lower()

        if suffix == ".kml":
            return KMLParser.parse_file(file_path, original_filename)

        elif suffix == ".kmz":
            return KMLParser.parse_file(file_path, original_filename)

        elif suffix == ".zip":
            # Check whether the zip contains a Shapefile or a KML
            if not zipfile.is_zipfile(file_path):
                raise ValueError("Uploaded file is not a valid zip archive.")

            with zipfile.ZipFile(file_path, "r") as archive:
                names = archive.namelist()
                has_shp = any(n.lower().endswith(".shp") for n in names)
                has_kml = any(n.lower().endswith(".kml") for n in names)

            if has_shp:
                return ShapefileParser.parse_zip(file_path, original_filename)
            elif has_kml:
                return KMLParser.parse_file(file_path, original_filename)
            else:
                raise ValueError(
                    "Invalid archive contents. The .zip file must contain either an ESRI Shapefile (.shp) or a KML file."
                )

        else:
            raise ValueError(
                f"Unsupported file format '{suffix}'. Only .zip (Shapefile) and .kml / .kmz files are supported."
            )
