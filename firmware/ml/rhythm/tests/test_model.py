import unittest

import numpy as np
import pandas as pd

from rhythm_ml.model import (
    QuantizedModel,
    consensus_subject_metrics,
    stratified_subject_split,
)


class ModelTests(unittest.TestCase):
    def test_subject_split_has_no_leakage(self):
        rows = []
        for label, prefix in ((0, "N"), (1, "A")):
            for subject in range(10):
                for window in range(3):
                    rows.append({"subject_id": f"{prefix}{subject}", "label": label, "window": window})
        split = stratified_subject_split(pd.DataFrame(rows), seed=7)
        all_subjects = [subject for names in split.values() for subject in names]
        self.assertEqual(len(all_subjects), len(set(all_subjects)))
        self.assertEqual(set(all_subjects), {f"N{i}" for i in range(10)} | {f"A{i}" for i in range(10)})

    def test_quantized_probability_direction(self):
        model = QuantizedModel(
            weights=np.asarray([2, 0, 0, 0, 0, 0], dtype=np.int8),
            bias=-127,
            score_scale=127.0,
            af_threshold=0.5,
        )
        probability = model.probabilities_from_q(np.asarray([[0] * 6, [127, 0, 0, 0, 0, 0]]))
        self.assertLess(probability[0], 0.5)
        self.assertGreater(probability[1], 0.5)

    def test_consensus_requires_three_consecutive_windows(self):
        frame = pd.DataFrame(
            {
                "subject_id": ["A"] * 4 + ["N"] * 4,
                "label": [1] * 4 + [0] * 4,
                "window_end_s": [15, 20, 25, 30] * 2,
            }
        )
        probabilities = np.asarray([0.8, 0.9, 0.7, 0.1, 0.8, 0.1, 0.8, 0.1])
        result = consensus_subject_metrics(frame, probabilities, threshold=0.6)
        self.assertEqual(result["tp"], 1)
        self.assertEqual(result["tn"], 1)


if __name__ == "__main__":
    unittest.main()
