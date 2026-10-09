import json
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from aquamind_ml.api import create_app
from aquamind_ml.data import load_dataset
from aquamind_ml.detector import FrozenDetector, freeze_detector
from aquamind_ml.train import TrainingConfig, train_to_directory
from test_data import fixture


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        root = Path(cls.directory.name)
        raw = fixture()
        raw["validation"].append(dict(raw["validation"][0], scenarioId="overnight-leak",
                                      hasAnomaly=True, hasLeak=True, flowRatesGpm=[3.0] * 96))
        path = root / "data.json"
        path.write_text(json.dumps(raw))
        train_to_directory(path, root / "training", TrainingConfig(epochs=1, hidden_size=4, latent_size=2))
        cls.detector_path = root / "detector"
        freeze_detector(path, root / "training", cls.detector_path)
        cls.window = load_dataset(path).test[0]
        cls.body = {"start_timestamp": cls.window.start_timestamp,
                    "flow_rates_gpm": list(cls.window.flow_rates_gpm)}

    def test_real_prediction_matches_direct_inference(self):
        expected = FrozenDetector(self.detector_path).predict((self.window,))[0]
        with TestClient(create_app(self.detector_path)) as client:
            self.assertEqual(client.get("/health").status_code, 200)
            self.assertEqual(client.get("/ready").status_code, 200)
            response = client.post("/v1/anomaly/predict", json=self.body)
            self.assertEqual(response.status_code, 200)
            for key, value in expected.items():
                self.assertEqual(response.json()[key], value)
            self.assertEqual(response.json()["request_id"], response.headers["X-Request-ID"])
            self.assertEqual(response.json()["training_data"], "synthetic")

    def test_rejects_malformed_windows(self):
        cases = [{"flow_rates_gpm": [0] * 95}, {"flow_rates_gpm": [0] * 97},
                 {"flow_rates_gpm": [True] * 96}, {"flow_rates_gpm": ["1"] * 96},
                 {"flow_rates_gpm": [-1] * 96}, {"flow_rates_gpm": [1001] * 96},
                 {"start_timestamp": "2026-06-15T01:00:00Z"},
                 {"start_timestamp": "2026-06-15T00:00:00"}, {"is_leak": True}]
        with TestClient(create_app(self.detector_path)) as client:
            for case in cases:
                with self.subTest(case=case):
                    response = client.post("/v1/anomaly/predict", json=self.body | case)
                    self.assertEqual(response.status_code, 422)

    def test_missing_model_returns_503_but_health_remains_live(self):
        with TestClient(create_app(Path(self.directory.name) / "missing")) as client:
            self.assertEqual(client.get("/health").status_code, 200)
            self.assertEqual(client.get("/ready").status_code, 503)
            self.assertEqual(client.post("/v1/anomaly/predict", json=self.body).status_code, 503)
