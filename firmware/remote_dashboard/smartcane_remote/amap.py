from __future__ import annotations

import math
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable

from .state import valid_gps_payload


class MapUnavailable(RuntimeError):
    """Raised when no safe static map can be returned."""


@dataclass(frozen=True)
class MapImage:
    data: bytes
    content_type: str


def _outside_china(lat: float, lon: float) -> bool:
    return lon < 72.004 or lon > 137.8347 or lat < 0.8293 or lat > 55.8271


def _transform_lat(x: float, y: float) -> float:
    value = -100 + 2 * x + 3 * y + 0.2 * y * y + 0.1 * x * y
    value += 0.2 * math.sqrt(abs(x))
    value += (20 * math.sin(6 * x * math.pi) + 20 * math.sin(2 * x * math.pi)) * 2 / 3
    value += (20 * math.sin(y * math.pi) + 40 * math.sin(y / 3 * math.pi)) * 2 / 3
    value += (160 * math.sin(y / 12 * math.pi) + 320 * math.sin(y * math.pi / 30)) * 2 / 3
    return value


def _transform_lon(x: float, y: float) -> float:
    value = 300 + x + 2 * y + 0.1 * x * x + 0.1 * x * y
    value += 0.1 * math.sqrt(abs(x))
    value += (20 * math.sin(6 * x * math.pi) + 20 * math.sin(2 * x * math.pi)) * 2 / 3
    value += (20 * math.sin(x * math.pi) + 40 * math.sin(x / 3 * math.pi)) * 2 / 3
    value += (150 * math.sin(x / 12 * math.pi) + 300 * math.sin(x / 30 * math.pi)) * 2 / 3
    return value


def wgs84_to_gcj02(lat: float, lon: float) -> tuple[float, float]:
    """Convert GPS WGS-84 coordinates for a mainland AMap static map."""
    if _outside_china(lat, lon):
        return lat, lon
    earth_radius = 6378245.0
    eccentricity = 0.00669342162296594323
    radians = lat * math.pi / 180
    delta_lat = _transform_lat(lon - 105, lat - 35)
    delta_lon = _transform_lon(lon - 105, lat - 35)
    magic = 1 - eccentricity * math.sin(radians) ** 2
    sqrt_magic = math.sqrt(magic)
    delta_lat = delta_lat * 180 / (
        (earth_radius * (1 - eccentricity) / (magic * sqrt_magic)) * math.pi
    )
    delta_lon = delta_lon * 180 / (
        earth_radius / sqrt_magic * math.cos(radians) * math.pi
    )
    return lat + delta_lat, lon + delta_lon


class AmapStaticMap:
    """Server-side AMap proxy so the map key is not sent to browsers."""

    def __init__(
        self,
        api_key: str,
        cache_seconds: float = 60.0,
        fetcher: Callable[..., Any] | None = None,
    ) -> None:
        self.api_key = api_key
        self.cache_seconds = cache_seconds
        self._fetcher = fetcher or urllib.request.urlopen
        self._lock = threading.Lock()
        self._cached_key = ""
        self._cached_at = 0.0
        self._cached_image: MapImage | None = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def get(self, gps: dict[str, Any]) -> MapImage:
        if not self.configured:
            raise MapUnavailable("AMap key is not configured")
        if not valid_gps_payload(gps):
            raise MapUnavailable("No valid GPS position")

        converted_lat, converted_lon = wgs84_to_gcj02(
            float(gps["lat"]), float(gps["lon"])
        )
        map_lat = round(converted_lat, 3)
        map_lon = round(converted_lon, 3)
        source = "live" if gps.get("source") == "live" else "last"
        cache_key = f"{source}:{map_lat:.3f},{map_lon:.3f}"
        now = time.monotonic()
        with self._lock:
            if (
                self._cached_key == cache_key
                and self._cached_image is not None
                and now - self._cached_at <= self.cache_seconds
            ):
                return self._cached_image

        marker_color = "0x008000" if source == "live" else "0xFFFF00"
        query = urllib.parse.urlencode(
            {
                "location": f"{map_lon:.3f},{map_lat:.3f}",
                "zoom": "16",
                "size": "900*360",
                "markers": f"mid,{marker_color},:{map_lon:.3f},{map_lat:.3f}",
                "key": self.api_key,
            }
        )
        request = urllib.request.Request(
            f"https://restapi.amap.com/v3/staticmap?{query}",
            headers={"User-Agent": "SmartCane-Remote/1.0"},
        )
        try:
            with self._fetcher(request, timeout=6) as response:
                data = response.read(2_000_001)
                content_type = response.headers.get("Content-Type", "image/png").split(";", 1)[0]
        except Exception as exc:
            raise MapUnavailable("AMap request failed") from exc
        if len(data) > 2_000_000 or not content_type.startswith("image/"):
            raise MapUnavailable("Invalid AMap image response")

        image = MapImage(data=data, content_type=content_type)
        with self._lock:
            self._cached_key = cache_key
            self._cached_at = now
            self._cached_image = image
        return image
