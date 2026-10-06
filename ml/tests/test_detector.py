from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from aquamind_ml.confirm import confirm
from aquamind_ml.data import load_dataset
from aquamind_ml.detector import FrozenDetector, freeze_detector
from aquamind_ml.train import TrainingConfig, train_to_directory
from test_data import fixture


class DetectorTests(unittest.TestCase):
    def test_frozen_inference_and_confirmation_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw = fixture()
            for split in ("validation", "test"):
                raw[split].append(dict(raw[split][0], scenarioId="overnight-leak", hasAnomaly=True,
                                      hasLeak=True, flowRatesGpm=[3.0] * 96))
            path = root / "data.json"
            path.write_text(json.dumps(raw))
            train_to_directory(path, root / "training", TrainingConfig(epochs=1, hidden_size=4, latent_size=2))
            freeze_detector(path, root / "training", root / "detector")
            detector = FrozenDetector(root / "detector")
            windows = load_dataset(path).test
            original = detector.predict(windows)
            # Inference cannot depend on labels or scenario provenance.
            changed = tuple(replace(w, has_leak=not w.has_leak, scenario_id="ignored") for w in windows)
            self.assertEqual(original, detector.predict(changed))
            self.assertEqual(original, FrozenDetector(root / "detector").predict(windows))
            with self.assertRaisesRegex(ValueError, "overlap"):
                confirm(path, root / "detector")
            for split in ("train", "validation", "test"):
                raw["seedSplit"][split] = [s + 100 for s in raw["seedSplit"][split]]
                for row in raw[split]:
                    row["seed"] += 100
            path.write_text(json.dumps(raw))
            with patch("aquamind_ml.detector.FlowNormalizer.fit", side_effect=AssertionError("must not fit")), \
                 patch("aquamind_ml.detector.ResidualCalibration.fit", side_effect=AssertionError("must not fit")):
                report = confirm(path, root / "detector")
            self.assertFalse(report["refitted"])
            self.assertEqual(report["test"]["count"], 2)
            with self.assertRaises(FileExistsError):
                freeze_detector(path, root / "training", root / "detector")
            (root / "detector" / "weights.pt").write_bytes(b"corrupt")
            with self.assertRaisesRegex(ValueError, "checksum"):
                FrozenDetector(root / "detector")
