"""Install one checksum-pinned synthetic detector during a trusted build, never at startup."""

import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import tempfile
from urllib.request import Request, urlopen
from zipfile import ZipFile

RELEASE_PATH = Path(__file__).resolve().parents[1] / 'model-release-v1.json'
MAX_ARCHIVE_BYTES = 256 * 1024
MAX_FILE_BYTES = 128 * 1024
FILES = frozenset({'detector.json', 'weights.pt'})
SOURCES = frozenset({'model.py', 'calibration.py', 'detector.py'})


def validate_files(files, release):
    """Verify artifact identity and the frozen runtime before any tensor deserialization."""
    if set(files) != FILES or any(len(value) > MAX_FILE_BYTES for value in files.values()):
        raise ValueError('Unsupported detector files')
    if (sha256(files['detector.json']).hexdigest() != release['manifest_sha256'] or
            sha256(files['weights.pt']).hexdigest() != release['weights_sha256']):
        raise ValueError('Detector checksum mismatch')
    manifest = json.loads(files['detector.json'])
    if (manifest['schema_version'] != 1 or manifest['score'] != 'positive_standardized_residual_v1' or
            manifest['comparison'] != '>=' or manifest['weights_sha256'] != release['weights_sha256'] or
            release['model_version'] != 'detector-' + release['manifest_sha256'][:16] or
            set(manifest['source_sha256']) != SOURCES):
        raise ValueError('Unsupported frozen detector')
    for name in SOURCES:
        if sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() != manifest['source_sha256'][name]:
            raise ValueError('Frozen runtime source mismatch')


def archive_files(raw, release):
    if len(raw) > MAX_ARCHIVE_BYTES or sha256(raw).hexdigest() != release['archive_sha256']:
        raise ValueError('Release checksum mismatch')
    with ZipFile(BytesIO(raw)) as archive:
        entries = archive.infolist()
        # No extractall: reject duplicate names, paths, directories and symlinks,
        # and write only these fixed filenames after all validation succeeds.
        if (len(entries) != 2 or {entry.filename for entry in entries} != FILES or
                any(entry.file_size > MAX_FILE_BYTES or entry.is_dir() or
                    (entry.external_attr >> 16) & 0o170000 not in (0, 0o100000) for entry in entries)):
            raise ValueError('Unsupported release archive')
        files = {entry.filename: archive.read(entry) for entry in entries}
    validate_files(files, release)
    return files


def install_release(output: Path, *, release=None, opener=urlopen):
    release = json.loads(RELEASE_PATH.read_text()) if release is None else release
    if (release['schema_version'] != 1 or
            release['url'] != 'https://api.github.com/repos/jueichechu/aquamind/releases/assets/723284055'):
        raise ValueError('Unsupported detector release')
    if output.exists():
        validate_files({name: (output / name).read_bytes() for name in FILES}, release)
        return  # Verified build cache only; never overwrite a frozen artifact.
    request = Request(release['url'], headers={
        'User-Agent': 'AquaMind-model-build/1', 'Accept': 'application/octet-stream'})
    # One download attempt, bounded in bytes and socket timeout. No credentials.
    with opener(request, timeout=30) as response:
        if not response.geturl().startswith('https://'):
            raise ValueError('Insecure artifact response')
        raw = response.read(MAX_ARCHIVE_BYTES + 1)
    files = archive_files(raw, release)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.detector-build-', dir=output.parent) as temporary:
        staged = Path(temporary) / 'detector'
        staged.mkdir()
        for name, contents in files.items():
            (staged / name).write_bytes(contents)
        staged.rename(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        install_release(args.output)
    except Exception:
        parser.exit(1, 'Frozen detector build installation failed; no artifact was accepted.\n')
    print('Verified frozen synthetic detector installed.')


if __name__ == '__main__':
    main()
