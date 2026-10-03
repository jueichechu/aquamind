from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
from statistics import fmean, pstdev
import tempfile
import unittest

from aquamind_ml.data import FlowNormalizer, load_dataset


def fixture():
    raw = {"schemaVersion": 1, "source": "synthetic", "intervalMinutes": 15,
           "windowSize": 96, "seedSplit": {"train": [0], "validation": [1], "test": [2]}}
    for seed, split in enumerate(("train", "validation", "test")):
        raw[split] = [{"seed": seed, "scenarioId": "normal", "hasAnomaly": False,
                       "hasLeak": False, "flowRatesGpm": [0.0, 2.0] * 48,
                       "startTimestamp": "2026-06-15T00:00:00.000Z",
                       "endTimestamp": "2026-06-15T23:45:00.000Z"}]
    return raw


class DataTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "dataset.json"

    def load(self, raw):
        self.path.write_text(json.dumps(raw))
        return load_dataset(self.path)

    def test_load_checksum_and_immutable_features(self):
        data = self.load(fixture())
        self.assertEqual(data.sha256, hashlib.sha256(self.path.read_bytes()).hexdigest())
        self.assertIsInstance(data.train[0].flow_rates_gpm, tuple)
        self.assertEqual(data.train[0].seed, 0)

    def test_rejects_bad_schema_manifest_and_rows(self):
        changes = [
            lambda r: r.update(schemaVersion=True),
            lambda r: r.update(source="real"),
            lambda r: r["seedSplit"].update(test=[0]),
            lambda r: r["seedSplit"].update(train=[0, 0]),
            lambda r: r.update(train=[]),
            lambda r: r["train"][0].update(seed=True),
            lambda r: r["train"][0].update(seed=5),
            lambda r: r["train"].append(deepcopy(r["train"][0])),
            lambda r: r["train"][0].update(flowRatesGpm=[1] * 95),
            lambda r: r["train"][0].update(hasAnomaly=1),
            lambda r: r["train"][0].update(scenarioId="overnight-leak", hasAnomaly=True, hasLeak=True),
            lambda r: r["test"][0].update(scenarioId="irrigation-after-rain", hasAnomaly=True, hasLeak=True),
            lambda r: r["train"][0].update(startTimestamp="invalid"),
            lambda r: r["train"][0].update(endTimestamp="2026-06-15T23:30:00Z"),
        ]
        for change in changes:
            with self.subTest(change=changes.index(change)):
                raw = fixture()
                change(raw)
                with self.assertRaises(ValueError):
                    self.load(raw)
        for value in (True, "2", -1, float("nan"), float("inf")):
            with self.subTest(flow=value):
                raw = fixture()
                raw["train"][0]["flowRatesGpm"][0] = value
                with self.assertRaises(ValueError):
                    self.load(raw)

    def test_training_only_fit_and_no_clipping_of_unseen_values(self):
        data = self.load(fixture())
        normalizer = FlowNormalizer.fit(data)
        self.assertEqual((normalizer.mean_gpm, normalizer.scale_gpm), (1, 1))
        changed = replace(data, validation=(replace(data.validation[0], flow_rates_gpm=(1000.0,) * 96),),
                          test=())
        self.assertEqual(FlowNormalizer.fit(changed), normalizer)
        self.assertEqual(normalizer.transform(changed.validation)[0][0], 999)
        values = normalizer.transform(data.train)[0]
        self.assertAlmostEqual(fmean(values), 0)
        self.assertAlmostEqual(pstdev(values), 1)
        self.assertEqual(data.train[0].flow_rates_gpm, (0.0, 2.0) * 48)
        self.assertEqual(FlowNormalizer(**json.loads(json.dumps(asdict(normalizer)))), normalizer)

    def test_constant_training_data_and_invalid_fits(self):
        data = self.load(fixture())
        constant = replace(data, train=(replace(data.train[0], flow_rates_gpm=(0.0,) * 96),))
        self.assertEqual(FlowNormalizer.fit(constant).scale_gpm, 1)
        for changed in (replace(data, train=()),
                        replace(data, train=(replace(data.train[0], has_leak=True),))):
            with self.assertRaises(ValueError):
                FlowNormalizer.fit(changed)


if __name__ == "__main__":
    unittest.main()
