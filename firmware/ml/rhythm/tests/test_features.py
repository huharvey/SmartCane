import unittest

import numpy as np

from rhythm_ml.features import feature_vector, quantize_features


class FeatureTests(unittest.TestCase):
    def test_constant_ibi_quantization(self):
        features = feature_vector([800.0] * 12, signal_quality=1.0)
        self.assertTrue(np.allclose(features, [0, 0, 0, 0, 1, 0]))
        self.assertEqual(quantize_features(features).tolist(), [0, 0, 0, 0, 127, 0])

    def test_cpp_half_away_quantization_for_positive_input(self):
        values = [0.1575, 0.1575, 0.5 / 127.0, 0.42, 0.5 / 127.0, 1.0]
        self.assertEqual(quantize_features(values).tolist(), [64, 64, 1, 64, 1, 127])


if __name__ == "__main__":
    unittest.main()
