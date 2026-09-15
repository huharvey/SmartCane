"""轨迹文件、图传地址和 MJPEG 跨分块重组单元测试。"""

import json
import tempfile
import unittest
from pathlib import Path

from smartcane_host.camera_worker import extract_jpeg_frames, normalize_base_url, stream_url
from smartcane_host.track_import import load_track


class TrackImportTests(unittest.TestCase):
    """覆盖上位机交接中最容易出错的坐标顺序和网络分帧。"""

    def test_geojson_geometry_is_wrapped(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "line.geojson"
            path.write_text(
                json.dumps({"type": "LineString", "coordinates": [[104, 30], [105, 31]]}),
                encoding="utf-8",
            )
            data = load_track(path)
        self.assertEqual(data["type"], "FeatureCollection")
        self.assertEqual(data["features"][0]["geometry"]["type"], "LineString")

    def test_gpx_track(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "route.gpx"
            path.write_text(
                '<gpx version="1.1"><trk><name>demo</name><trkseg>'
                '<trkpt lat="30.1" lon="104.1"/><trkpt lat="30.2" lon="104.2"/>'
                '</trkseg></trk></gpx>',
                encoding="utf-8",
            )
            data = load_track(path)
        self.assertEqual(data["features"][0]["properties"]["name"], "demo")
        self.assertEqual(data["features"][0]["geometry"]["coordinates"][0], [104.1, 30.1])

    def test_camera_urls(self):
        self.assertEqual(normalize_base_url("192.168.4.1/"), "http://192.168.4.1")
        self.assertEqual(stream_url("http://192.168.4.1"), "http://192.168.4.1:81/stream")

    def test_mjpeg_chunk_reassembly(self):
        buffer = bytearray(b"boundary\xff\xd8first\xff\xd9noise\xff\xd8partial")
        self.assertEqual(extract_jpeg_frames(buffer), [b"\xff\xd8first\xff\xd9"])
        buffer.extend(b"-end\xff\xd9")
        self.assertEqual(extract_jpeg_frames(buffer), [b"\xff\xd8partial-end\xff\xd9"])


if __name__ == "__main__":
    unittest.main()
