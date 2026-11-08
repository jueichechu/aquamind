"""Artifact delivery checks require no provider calls, PyTorch, or model weights."""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
from zipfile import ZipFile, ZipInfo

from aquamind_ml.model_release import (FILES, SOURCES, MAX_ARCHIVE_BYTES,
                                      archive_files, install_release, validate_files)


class ModelReleaseTests(unittest.TestCase):
    def fixture(self, *, extra=None):
        weights = b'fictional-test-weights-not-deserialized'
        source = Path(__file__).resolve().parents[1] / 'aquamind_ml'
        manifest = {'schema_version': 1, 'score': 'positive_standardized_residual_v1',
                    'comparison': '>=', 'weights_sha256': sha256(weights).hexdigest(),
                    'source_sha256': {name: sha256((source / name).read_bytes()).hexdigest() for name in SOURCES}}
        files = {'weights.pt': weights, 'detector.json': json.dumps(manifest).encode()}
        stream = BytesIO()
        with ZipFile(stream, 'w') as archive:
            for name, value in files.items():
                archive.writestr(name, value)
            if extra:
                archive.writestr(*extra)
        raw = stream.getvalue()
        release = {'schema_version': 1, 'url': 'https://api.github.com/repos/jueichechu/aquamind/releases/assets/723284055',
                   'archive_sha256': sha256(raw).hexdigest(),
                   'manifest_sha256': sha256(files['detector.json']).hexdigest(),
                   'weights_sha256': sha256(weights).hexdigest()}
        release['model_version'] = 'detector-' + release['manifest_sha256'][:16]
        return raw, release, files

    def test_install_is_verified_atomic_and_does_not_redownload_or_overwrite(self):
        raw, release, files = self.fixture()
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.geturl.return_value = 'https://release-assets.githubusercontent.com/example'
        response.read.return_value = raw
        opener = Mock(return_value=response)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'detector'
            install_release(output, release=release, opener=opener)
            self.assertEqual({p.name: p.read_bytes() for p in output.iterdir()}, files)
            opener.assert_called_once()
            request = opener.call_args.args[0]
            self.assertEqual(request.get_header('Accept'), 'application/octet-stream')
            self.assertFalse(request.has_header('Authorization'))
            self.assertEqual(opener.call_args.kwargs, {'timeout': 30})
            response.read.assert_called_once_with(MAX_ARCHIVE_BYTES + 1)
            install_release(output, release=release, opener=opener)
            opener.assert_called_once()
            (output / 'weights.pt').write_bytes(b'corrupt')
            with self.assertRaises(ValueError):
                install_release(output, release=release, opener=opener)
            self.assertEqual((output / 'weights.pt').read_bytes(), b'corrupt')

    def test_rejects_corruption_source_drift_and_wrong_version(self):
        raw, release, files = self.fixture()
        for key in ('archive_sha256', 'manifest_sha256', 'weights_sha256', 'model_version'):
            changed = deepcopy(release)
            changed[key] = 'invalid'
            with self.subTest(key=key), self.assertRaises(ValueError):
                archive_files(raw, changed)
        manifest = json.loads(files['detector.json'])
        manifest['source_sha256']['model.py'] = 'changed'
        files['detector.json'] = json.dumps(manifest).encode()
        release['manifest_sha256'] = sha256(files['detector.json']).hexdigest()
        release['model_version'] = 'detector-' + release['manifest_sha256'][:16]
        with self.assertRaisesRegex(ValueError, 'source mismatch'):
            validate_files(files, release)

    def test_rejects_extra_paths_duplicates_symlinks_and_oversized_files(self):
        for extra in (('../escaped', b'private'), ('detector.json', b'duplicate'), ('other', b'extra')):
            with self.subTest(extra=extra):
                raw, release, _ = self.fixture(extra=extra)
                with self.assertRaises(ValueError):
                    archive_files(raw, release)
        _, release, files = self.fixture()
        for symlink in (False, True):
            stream = BytesIO()
            with ZipFile(stream, 'w') as archive:
                for name in FILES:
                    entry = ZipInfo(name)
                    if name == 'weights.pt':
                        entry.external_attr = (0o120777 if symlink else 0o100644) << 16
                    archive.writestr(entry, files[name] if symlink else b'x' * (128 * 1024 + 1))
            raw = stream.getvalue()
            release['archive_sha256'] = sha256(raw).hexdigest()
            with self.assertRaises(ValueError):
                archive_files(raw, release)

    def test_download_failure_leaves_no_artifact_and_never_retries(self):
        _, release, _ = self.fixture()
        opener = Mock(side_effect=TimeoutError('private transport details'))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'detector'
            with self.assertRaises(TimeoutError):
                install_release(output, release=release, opener=opener)
            opener.assert_called_once()
            self.assertFalse(output.exists())

    def test_only_the_exact_public_asset_endpoint_is_accepted(self):
        _, release, _ = self.fixture()
        for url in ('https://untrusted.invalid/model', release['url'] + '?token=private',
                    release['url'] + '0', release['url'].replace('https:', 'http:')):
            opener = Mock()
            with tempfile.TemporaryDirectory() as directory, self.subTest(url=url):
                with self.assertRaises(ValueError):
                    install_release(Path(directory) / 'detector', release=release | {'url': url}, opener=opener)
                opener.assert_not_called()


if __name__ == '__main__':
    unittest.main()
