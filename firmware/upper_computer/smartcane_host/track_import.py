"""把 GeoJSON、GPX、KML 统一转换为地图组件使用的 GeoJSON 要素集。"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


class TrackImportError(ValueError):
    """轨迹格式不支持、内容损坏或没有可用坐标。"""

    pass


def load_track(path: str | Path) -> dict[str, Any]:
    """按扩展名加载轨迹；返回标准 FeatureCollection。"""
    source = Path(path)
    suffix = source.suffix.lower()
    try:
        if suffix in {".geojson", ".json"}:
            return _load_geojson(source)
        if suffix == ".gpx":
            return _load_gpx(source)
        if suffix == ".kml":
            return _load_kml(source)
    except (OSError, json.JSONDecodeError, ET.ParseError, ValueError) as exc:
        if isinstance(exc, TrackImportError):
            raise
        raise TrackImportError(f"无法读取 {source.name}：{exc}") from exc
    raise TrackImportError("仅支持 GeoJSON、GPX 和 KML 文件")


def _load_geojson(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or data.get("type") not in {
        "FeatureCollection",
        "Feature",
        "Point",
        "MultiPoint",
        "LineString",
        "MultiLineString",
        "Polygon",
        "MultiPolygon",
    }:
        raise TrackImportError("文件不是有效的 GeoJSON 对象")
    if data["type"] == "FeatureCollection":
        return data
    if data["type"] == "Feature":
        return _feature_collection([data])
    return _feature_collection([{"type": "Feature", "properties": {}, "geometry": data}])


def _load_gpx(path: Path) -> dict[str, Any]:
    # GPX 坐标属性顺序是 lat/lon，转换后 GeoJSON 必须改为 [lon, lat]。
    root = ET.parse(path).getroot()
    features: list[dict[str, Any]] = []

    for track_index, track in enumerate(root.findall(".//{*}trk"), start=1):
        name = track.findtext("{*}name") or f"轨迹 {track_index}"
        for segment in track.findall(".//{*}trkseg"):
            coordinates = [_lat_lon(point) for point in segment.findall("{*}trkpt")]
            if coordinates:
                features.append(_line_feature(coordinates, name))

    for route_index, route in enumerate(root.findall(".//{*}rte"), start=1):
        name = route.findtext("{*}name") or f"路线 {route_index}"
        coordinates = [_lat_lon(point) for point in route.findall("{*}rtept")]
        if coordinates:
            features.append(_line_feature(coordinates, name))

    for point_index, point in enumerate(root.findall(".//{*}wpt"), start=1):
        lon, lat = _lat_lon(point)
        name = point.findtext("{*}name") or f"航点 {point_index}"
        features.append(
            {
                "type": "Feature",
                "properties": {"name": name},
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
            }
        )

    if not features:
        raise TrackImportError("GPX 中没有轨迹、路线或航点")
    return _feature_collection(features)


def _load_kml(path: Path) -> dict[str, Any]:
    # KML coordinates 文本本身就是 lon,lat[,alt]，当前地图只使用前两项。
    root = ET.parse(path).getroot()
    features: list[dict[str, Any]] = []
    for index, node in enumerate(root.findall(".//{*}coordinates"), start=1):
        coordinates = []
        for item in (node.text or "").split():
            values = item.split(",")
            if len(values) >= 2:
                coordinates.append([float(values[0]), float(values[1])])
        if not coordinates:
            continue
        geometry = (
            {"type": "Point", "coordinates": coordinates[0]}
            if len(coordinates) == 1
            else {"type": "LineString", "coordinates": coordinates}
        )
        features.append(
            {
                "type": "Feature",
                "properties": {"name": f"KML 图层 {index}"},
                "geometry": geometry,
            }
        )
    if not features:
        raise TrackImportError("KML 中没有可用坐标")
    return _feature_collection(features)


def _lat_lon(node: ET.Element) -> list[float]:
    return [float(node.attrib["lon"]), float(node.attrib["lat"])]


def _line_feature(coordinates: list[list[float]], name: str) -> dict[str, Any]:
    geometry_type = "LineString" if len(coordinates) > 1 else "Point"
    geometry_coordinates: Any = coordinates if len(coordinates) > 1 else coordinates[0]
    return {
        "type": "Feature",
        "properties": {"name": name},
        "geometry": {"type": geometry_type, "coordinates": geometry_coordinates},
    }


def _feature_collection(features: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": features}
