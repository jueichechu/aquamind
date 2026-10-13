from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest


from aquamind_ml.hybrid_data import load_hybrid_dataset
from aquamind_ml.hybrid_train import train_to_directory
from aquamind_ml.hybrid_validate import load_checkpoint, score_windows, validate, validate_dataset
from aquamind_ml.train import TrainingConfig
from test_hybrid_data import fixture


class HybridValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.path = Path(cls.directory.name) / 'dataset.json'
        cls.path.write_text(json.dumps(fixture()))
        cls.checkpoint = Path(cls.directory.name) / 'run'
        train_to_directory(cls.path, cls.checkpoint, TrainingConfig(epochs=1, hidden_size=4, latent_size=2))

    def test_repeatable_report_and_paired_evidence(self):
        report = validate(self.path, self.checkpoint)
        self.assertEqual(report, validate(self.path, self.checkpoint))
        self.assertFalse(report['test_evaluated'])
        self.assertEqual(report['validation']['count'], 14)
        self.assertEqual(len(report['by_injection_pattern']), 12)
        self.assertEqual(report['by_variant_kind']['unmodified']['count'], 1)
        self.assertEqual(report['always_positive_reference']['tp'], 12)
        self.assertEqual(report['always_positive_reference']['fp'], 2)
        reference = report['validation_rows'][0]
        self.assertEqual(reference['score_change_from_unmodified'], 0)
        for row in report['validation_rows']:
            self.assertEqual(row['score_change_from_unmodified'], row['score'] - reference['score'])

    def test_scoring_cannot_access_test_and_labels_are_not_features(self):
        data, model, normalizer, _, _ = load_checkpoint(self.path, self.checkpoint)
        expected = validate_dataset(data, model, normalizer)
        class WithoutTest:
            validation = data.validation
            @property
            def test(self):
                raise AssertionError('Test partition accessed')
        self.assertEqual(expected, validate_dataset(WithoutTest(), model, normalizer))
        changed_labels = tuple(replace(w, is_continuous_injection=not w.is_continuous_injection) for w in data.validation)
        self.assertEqual(score_windows(model, normalizer, data.validation), score_windows(model, normalizer, changed_labels))

    def test_checkpoint_integrity_and_missing_validation(self):
        data, model, normalizer, _, _ = load_checkpoint(self.path, self.checkpoint)
        with self.assertRaises(ValueError):
            validate_dataset(replace(data, validation=()), model, normalizer)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.joinpath('training.json').write_bytes(self.checkpoint.joinpath('training.json').read_bytes())
            root.joinpath('weights.pt').write_bytes(b'corrupt')
            with self.assertRaises(ValueError):
                load_checkpoint(self.path, root)
            root.joinpath('weights.pt').write_bytes(self.checkpoint.joinpath('weights.pt').read_bytes())
            training = json.loads(root.joinpath('training.json').read_text())
            training['normalizer']['mean_gpm'] += 1
            root.joinpath('training.json').write_text(json.dumps(training))
            with self.assertRaises(ValueError):
                load_checkpoint(self.path, root)
