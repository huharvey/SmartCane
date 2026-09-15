"""Qt 地图组件：按需缓存 OSM 瓦片，离线时仍绘制 GPS 与矢量轨迹。"""

from __future__ import annotations

import math
from collections import OrderedDict
from pathlib import Path
from typing import Any, Iterable

from PyQt5.QtCore import QPoint, QRect, QStandardPaths, Qt, QUrl
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkDiskCache, QNetworkReply, QNetworkRequest
from PyQt5.QtWidgets import QWidget

TILE_SIZE = 256
MIN_ZOOM = 2
MAX_ZOOM = 19


def _world_xy(latitude: float, longitude: float, zoom: int) -> tuple[float, float]:
    """把 WGS-84 经纬度投影为指定层级的 Web Mercator 世界像素。"""
    latitude = max(-85.05112878, min(85.05112878, latitude))
    scale = TILE_SIZE * (1 << zoom)
    x = (longitude + 180.0) / 360.0 * scale
    sin_lat = math.sin(math.radians(latitude))
    y = (0.5 - math.log((1 + sin_lat) / (1 - sin_lat)) / (4 * math.pi)) * scale
    return x, y


def _lat_lon(x: float, y: float, zoom: int) -> tuple[float, float]:
    """Web Mercator 世界像素反算为 WGS-84 纬度、经度。"""
    scale = TILE_SIZE * (1 << zoom)
    longitude = x / scale * 360.0 - 180.0
    n = math.pi - 2.0 * math.pi * y / scale
    latitude = math.degrees(math.atan(math.sinh(n)))
    return latitude, longitude


class MapWidget(QWidget):
    """支持拖动/缩放的地图；无网络时保留网格、定位点和轨迹。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(360, 320)
        self.setMouseTracking(True)
        self.setToolTip("在线底图 © OpenStreetMap contributors；网络不可用时仍显示 GPS 与导入轨迹")
        self.center_latitude = 30.0
        self.center_longitude = 104.0
        self.zoom = 4
        self.follow_gps = True
        self.gps: tuple[float, float, str] | None = None
        self.gps_trail: list[tuple[float, float]] = []
        self.imported_lines: list[list[tuple[float, float]]] = []
        self.imported_points: list[tuple[float, float]] = []
        self.imported_name = ""
        self._drag_origin: QPoint | None = None
        self._drag_center_world: tuple[float, float] | None = None
        self._memory_tiles: OrderedDict[str, QPixmap] = OrderedDict()
        self._pending_tiles: set[str] = set()

        self.network = QNetworkAccessManager(self)
        cache = QNetworkDiskCache(self)
        cache_root = Path(QStandardPaths.writableLocation(QStandardPaths.CacheLocation)) / "osm_tiles"
        cache_root.mkdir(parents=True, exist_ok=True)
        cache.setCacheDirectory(str(cache_root))
        # 尊重瓦片服务缓存头，最多使用 256 MiB；不实现区域预下载。
        cache.setMaximumCacheSize(256 * 1024 * 1024)
        self.network.setCache(cache)
        self.network.finished.connect(self._tile_finished)

    def update_gps(self, latitude: float, longitude: float, popup: str) -> None:
        """更新实时定位点并追加去重后的轨迹，最多保留 5000 点。"""
        if not (math.isfinite(latitude) and math.isfinite(longitude)):
            return
        self.gps = (latitude, longitude, popup)
        last = self.gps_trail[-1] if self.gps_trail else None
        if last is None or abs(last[0] - latitude) > 1e-7 or abs(last[1] - longitude) > 1e-7:
            self.gps_trail.append((latitude, longitude))
            if len(self.gps_trail) > 5000:
                self.gps_trail.pop(0)
        if self.follow_gps:
            self.center_latitude = latitude
            self.center_longitude = longitude
            self.zoom = max(self.zoom, 16)
        self.update()

    def set_track(self, geojson: dict[str, Any], name: str) -> None:
        """提取 GeoJSON 中的点/线/面边界并缩放到导入范围。"""
        self.imported_lines = []
        self.imported_points = []
        self.imported_name = name
        self._collect_geojson(geojson)
        locations = self.imported_points + [point for line in self.imported_lines for point in line]
        if locations:
            self._fit_locations(locations)
        self.update()

    def clear_track(self) -> None:
        self.imported_lines.clear()
        self.imported_points.clear()
        self.imported_name = ""
        self.update()

    def clear_live_trail(self) -> None:
        self.gps_trail.clear()
        self.update()

    def set_follow(self, enabled: bool) -> None:
        self.follow_gps = enabled
        if enabled and self.gps:
            self.center_latitude, self.center_longitude = self.gps[:2]
            self.zoom = max(self.zoom, 16)
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor("#07101c"))
        self._draw_tiles(painter)
        self._draw_grid(painter)
        self._draw_polyline(painter, self.gps_trail, QColor("#45e0cd"), 4)
        for line in self.imported_lines:
            self._draw_polyline(painter, line, QColor("#ffb454"), 4)
        painter.setPen(QPen(QColor("#ffb454"), 2))
        painter.setBrush(QColor("#ffb454"))
        for latitude, longitude in self.imported_points:
            point = self._screen_point(latitude, longitude)
            painter.drawEllipse(point, 5, 5)
        self._draw_gps(painter)
        self._draw_overlay(painter)

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt API
        steps = 1 if event.angleDelta().y() > 0 else -1
        new_zoom = max(MIN_ZOOM, min(MAX_ZOOM, self.zoom + steps))
        if new_zoom != self.zoom:
            self.zoom = new_zoom
            self.update()
        event.accept()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        if event.button() == Qt.LeftButton:
            self._drag_origin = event.pos()
            self._drag_center_world = _world_xy(self.center_latitude, self.center_longitude, self.zoom)
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt API
        if self._drag_origin is None or self._drag_center_world is None:
            return
        delta = event.pos() - self._drag_origin
        x = self._drag_center_world[0] - delta.x()
        y = self._drag_center_world[1] - delta.y()
        self.center_latitude, self.center_longitude = _lat_lon(x, y, self.zoom)
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API
        self._drag_origin = None
        self._drag_center_world = None
        self.unsetCursor()

    def _draw_tiles(self, painter: QPainter) -> None:
        # 只请求当前窗口真正可见的瓦片；经度方向允许环绕，纬度方向不越界。
        center_x, center_y = _world_xy(self.center_latitude, self.center_longitude, self.zoom)
        left = center_x - self.width() / 2
        top = center_y - self.height() / 2
        first_x = math.floor(left / TILE_SIZE)
        last_x = math.floor((left + self.width()) / TILE_SIZE)
        first_y = math.floor(top / TILE_SIZE)
        last_y = math.floor((top + self.height()) / TILE_SIZE)
        tile_count = 1 << self.zoom

        for tile_y in range(first_y, last_y + 1):
            if tile_y < 0 or tile_y >= tile_count:
                continue
            for tile_x in range(first_x, last_x + 1):
                wrapped_x = tile_x % tile_count
                key = f"{self.zoom}/{wrapped_x}/{tile_y}"
                rect = QRect(
                    round(tile_x * TILE_SIZE - left),
                    round(tile_y * TILE_SIZE - top),
                    TILE_SIZE,
                    TILE_SIZE,
                )
                pixmap = self._memory_tiles.get(key)
                if pixmap is not None:
                    self._memory_tiles.move_to_end(key)
                    painter.drawPixmap(rect, pixmap)
                else:
                    painter.fillRect(rect, QColor("#0b1727"))
                    self._request_tile(key)

    def _draw_grid(self, painter: QPainter) -> None:
        painter.setPen(QPen(QColor(47, 67, 94, 70), 1))
        for x in range(0, self.width(), 64):
            painter.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 64):
            painter.drawLine(0, y, self.width(), y)

    def _draw_polyline(
        self, painter: QPainter, points: Iterable[tuple[float, float]], color: QColor, width: int
    ) -> None:
        points = list(points)
        if len(points) < 2:
            return
        path = QPainterPath()
        start = self._screen_point(*points[0])
        path.moveTo(start)
        for coordinate in points[1:]:
            path.lineTo(self._screen_point(*coordinate))
        painter.setPen(QPen(QColor(4, 10, 18, 180), width + 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(path)
        painter.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawPath(path)

    def _draw_gps(self, painter: QPainter) -> None:
        if not self.gps:
            return
        point = self._screen_point(self.gps[0], self.gps[1])
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(69, 224, 205, 55))
        painter.drawEllipse(point, 15, 15)
        painter.setBrush(QColor("#45e0cd"))
        painter.drawEllipse(point, 7, 7)
        painter.setPen(QPen(Qt.white, 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(point, 8, 8)

    def _draw_overlay(self, painter: QPainter) -> None:
        painter.setFont(QFont("Microsoft YaHei UI", 9))
        painter.setPen(QColor("#a8b7ce"))
        painter.setBrush(QColor(7, 16, 28, 215))
        painter.drawRoundedRect(10, 10, 164, 48, 8, 8)
        painter.drawText(20, 31, f"中心 {self.center_latitude:.5f}, {self.center_longitude:.5f}")
        painter.drawText(20, 49, f"缩放 {self.zoom} · 拖动/滚轮操作")
        attribution = "© OpenStreetMap contributors"
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(attribution) + 16
        painter.setBrush(QColor(7, 16, 28, 210))
        painter.setPen(QColor("#9fb2ce"))
        painter.drawRect(self.width() - width, self.height() - 24, width, 24)
        painter.drawText(self.width() - width + 8, self.height() - 7, attribution)
        if self.gps:
            painter.setBrush(QColor(7, 16, 28, 225))
            painter.setPen(QColor("#45e0cd"))
            text = self.gps[2]
            text_width = min(self.width() - 28, metrics.horizontalAdvance(text) + 20)
            painter.drawRoundedRect(10, self.height() - 58, text_width, 32, 7, 7)
            painter.drawText(20, self.height() - 37, metrics.elidedText(text, Qt.ElideRight, text_width - 20))

    def _screen_point(self, latitude: float, longitude: float) -> QPoint:
        center_x, center_y = _world_xy(self.center_latitude, self.center_longitude, self.zoom)
        point_x, point_y = _world_xy(latitude, longitude, self.zoom)
        return QPoint(round(self.width() / 2 + point_x - center_x), round(self.height() / 2 + point_y - center_y))

    def _request_tile(self, key: str) -> None:
        # PreferCache 优先使用磁盘缓存，避免重复访问公共瓦片服务器。
        if key in self._pending_tiles:
            return
        self._pending_tiles.add(key)
        request = QNetworkRequest(QUrl(f"https://tile.openstreetmap.org/{key}.png"))
        request.setRawHeader(b"User-Agent", b"SmartCaneUpperComputer/1.0")
        request.setAttribute(QNetworkRequest.CacheLoadControlAttribute, QNetworkRequest.PreferCache)
        reply = self.network.get(request)
        reply.setProperty("tile_key", key)

    def _tile_finished(self, reply: QNetworkReply) -> None:
        key = str(reply.property("tile_key") or "")
        self._pending_tiles.discard(key)
        if reply.error() == QNetworkReply.NoError:
            pixmap = QPixmap()
            if pixmap.loadFromData(bytes(reply.readAll()), "PNG"):
                self._memory_tiles[key] = pixmap
                self._memory_tiles.move_to_end(key)
                while len(self._memory_tiles) > 384:
                    self._memory_tiles.popitem(last=False)
                self.update()
        reply.deleteLater()

    def _fit_locations(self, locations: list[tuple[float, float]]) -> None:
        min_lat = min(item[0] for item in locations)
        max_lat = max(item[0] for item in locations)
        min_lon = min(item[1] for item in locations)
        max_lon = max(item[1] for item in locations)
        self.center_latitude = (min_lat + max_lat) / 2
        self.center_longitude = (min_lon + max_lon) / 2
        available_width = max(100, self.width() * 0.78)
        available_height = max(100, self.height() * 0.78)
        for zoom in range(MAX_ZOOM, MIN_ZOOM - 1, -1):
            x1, y1 = _world_xy(min_lat, min_lon, zoom)
            x2, y2 = _world_xy(max_lat, max_lon, zoom)
            if abs(x2 - x1) <= available_width and abs(y2 - y1) <= available_height:
                self.zoom = zoom
                break

    def _collect_geojson(self, node: Any) -> None:
        # 递归支持 FeatureCollection、GeometryCollection 及常见多几何类型。
        if not isinstance(node, dict):
            return
        node_type = node.get("type")
        if node_type == "FeatureCollection":
            for feature in node.get("features", []):
                self._collect_geojson(feature)
        elif node_type == "Feature":
            self._collect_geojson(node.get("geometry"))
        elif node_type == "GeometryCollection":
            for geometry in node.get("geometries", []):
                self._collect_geojson(geometry)
        elif node_type == "Point":
            point = self._coordinate(node.get("coordinates"))
            if point:
                self.imported_points.append(point)
        elif node_type == "MultiPoint":
            for raw in node.get("coordinates", []):
                point = self._coordinate(raw)
                if point:
                    self.imported_points.append(point)
        elif node_type == "LineString":
            line = self._line(node.get("coordinates", []))
            if line:
                self.imported_lines.append(line)
        elif node_type in {"MultiLineString", "Polygon"}:
            for raw_line in node.get("coordinates", []):
                line = self._line(raw_line)
                if line:
                    self.imported_lines.append(line)
        elif node_type == "MultiPolygon":
            for polygon in node.get("coordinates", []):
                for raw_line in polygon:
                    line = self._line(raw_line)
                    if line:
                        self.imported_lines.append(line)

    @staticmethod
    def _coordinate(raw: Any) -> tuple[float, float] | None:
        try:
            longitude, latitude = float(raw[0]), float(raw[1])
        except (TypeError, ValueError, IndexError):
            return None
        if not (math.isfinite(latitude) and math.isfinite(longitude)):
            return None
        return latitude, longitude

    def _line(self, raw_line: Any) -> list[tuple[float, float]]:
        return [point for raw in raw_line if (point := self._coordinate(raw)) is not None]
