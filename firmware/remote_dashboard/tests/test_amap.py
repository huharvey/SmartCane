import unittest

from smartcane_remote.amap import AmapStaticMap, MapUnavailable, wgs84_to_gcj02


class FakeResponse:
    def __init__(self):
        self.headers = {"Content-Type": "image/png"}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, _limit):
        return b"fake-png"


class AmapTests(unittest.TestCase):
    def test_server_side_proxy_fetches_and_caches_static_map(self):
        requests = []

        def fetcher(request, timeout):
            requests.append((request.full_url, timeout))
            return FakeResponse()

        service = AmapStaticMap("server-only-key", fetcher=fetcher)
        gps = {
            "valid": True,
            "source": "live",
            "lat": 30.306869,
            "lon": 120.077684,
        }
        first = service.get(gps)
        second = service.get(gps)

        self.assertEqual(first.data, b"fake-png")
        self.assertEqual(second, first)
        self.assertEqual(len(requests), 1)
        self.assertIn("server-only-key", requests[0][0])

    def test_missing_key_or_position_is_rejected(self):
        with self.assertRaises(MapUnavailable):
            AmapStaticMap("").get({"valid": True, "lat": 30, "lon": 120})
        with self.assertRaises(MapUnavailable):
            AmapStaticMap("key").get({"valid": False})

    def test_mainland_coordinate_conversion_is_not_identity(self):
        lat, lon = wgs84_to_gcj02(30.306869, 120.077684)
        self.assertNotAlmostEqual(lat, 30.306869, places=5)
        self.assertNotAlmostEqual(lon, 120.077684, places=5)


if __name__ == "__main__":
    unittest.main()
