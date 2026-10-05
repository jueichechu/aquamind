import json
from pathlib import Path
import tempfile
import unittest

from aquamind_ml.evaluate import evaluate, metrics, select_threshold
from aquamind_ml.train import TrainingConfig, train_to_directory
from test_data import fixture


class EvaluationTests(unittest.TestCase):
    def test_confusion_counts_and_zero_denominators(self):
        result = metrics([True, True, False, False], [True, False, True, False])
        self.assertEqual([result[k] for k in ("tp", "fp", "fn", "tn")], [1, 1, 1, 1])
        self.assertEqual(result["f1"], 0.5)
        self.assertEqual(metrics([False], [False])["precision"], 0)

    def test_threshold_boundaries_ties_and_invalid_values(self):
        self.assertEqual(select_threshold([0.1, 0.2, 0.8, 0.9], [False, False, True, True]), 0.8)
        self.assertEqual(select_threshold([1, 1], [False, True]), 1)
        # Both thresholds have F1 2/3; the higher threshold wins.
        self.assertEqual(select_threshold([1, 2, 3, 4], [True, False, False, True]), 4)
        for scores, labels in (([], []), ([float("nan"), 1], [False, True]),
                               ([1], [True]), ([1, 2], [0, 1])):
            with self.assertRaises(ValueError):
                select_threshold(scores, labels)

    def test_pipeline_checksums_and_reproducible_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = fixture()
            for split in ("validation", "test"):
                leak = dict(raw[split][0], scenarioId="overnight-leak", hasAnomaly=True,
                            hasLeak=True, flowRatesGpm=[3.0] * 96)
                raw[split].append(leak)
            path = root / "data.json"
            path.write_text(json.dumps(raw))
            checkpoint = root / "model"
            train_to_directory(path, checkpoint, TrainingConfig(epochs=1, hidden_size=4, latent_size=2))
            report = evaluate(path, checkpoint)
            self.assertEqual(report, evaluate(path, checkpoint))
            self.assertEqual(report["test"]["count"], 2)
            self.assertEqual(report["test"], metrics(
                [r["has_leak"] for r in report["test_rows"]],
                [r["predicted_leak"] for r in report["test_rows"]]))
            path.write_text(path.read_text() + "\n")
            with self.assertRaisesRegex(ValueError, "Dataset checksum"):
                evaluate(path, checkpoint)
            path.write_text(json.dumps(raw))
            (checkpoint / "weights.pt").write_bytes(b"corrupt")
            with self.assertRaisesRegex(ValueError, "weight checksum"):
                evaluate(path, checkpoint)
