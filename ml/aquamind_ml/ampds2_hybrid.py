"""Versioned controlled patterns on unlabeled AMPds2 base days, not leak labels."""

import argparse
from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path

PROTOCOL = 'ampds2-hybrid-v1'
RATES = (0.01, 0.03, 0.1, 0.3)
HOURS = (4, 12, 24)
MANIFEST = Path(__file__).resolve().parents[1] / 'data/manifests/ampds2-windows-v1.json'


def variants(row: dict, split: str, source_sha256: str) -> list[dict]:
    base_id = 'ampds2-house-1/' + row['start_timestamp']
    specs = [('unmodified', 0.0, 0)]
    if split != 'train':
        specs += [('continuous_injection', rate, hours * 4) for rate in RATES for hours in HOURS]
        specs += [('demand_confounder', 1.0, 8)]
    result = []
    for kind, rate, length in specs:
        key = json.dumps([PROTOCOL, row['start_timestamp'], rate, length], separators=(',', ':'))
        start = int.from_bytes(hashlib.sha256(key.encode()).digest(), 'big') % (97 - length) if length else 0
        flows = list(row['flow_rates_gpm'])
        for index in range(start, start + length):
            flows[index] += rate
        result.append({'base_day_id': base_id, 'source_sha256': source_sha256,
                       'start_timestamp': row['start_timestamp'], 'variant_kind': kind,
                       'variant_id': base_id + '/' + kind + f'/{rate}/{length}',
                       'injection_present': length > 0, 'is_continuous_injection': kind == 'continuous_injection',
                       'physical_leak_label': 'unknown', 'added_gpm': rate,
                       'start_interval': start, 'end_interval_exclusive': start + length,
                       'added_gallons': rate * length * 15, 'flow_rates_gpm': flows})
    return result


def generate(dataset: dict, source_sha256: str) -> dict:
    if (dataset.get('schema') != 'aquamind-ampds2-unlabeled-v1' or
            dataset.get('labels') != 'unknown' or dataset.get('units') != 'US gallons/minute'):
        raise ValueError('Expected unlabeled AMPds2 GPM windows')
    groups = {}
    last_end = None
    for split in ('train', 'validation', 'test'):
        rows = dataset[split]
        if not isinstance(rows, list) or not rows:
            raise ValueError('Empty split')
        previous = None
        groups[split] = []
        for row in rows:
            stamp = datetime.fromisoformat(row['start_timestamp'])
            if (stamp.utcoffset() != timedelta(0) or
                    (stamp.hour, stamp.minute, stamp.second, stamp.microsecond) != (0, 0, 0, 0) or
                    (previous is not None and stamp - previous != timedelta(days=1)) or
                    (previous is None and last_end is not None and stamp - last_end < timedelta(days=2))):
                raise ValueError('Invalid chronological split or missing boundary gap')
            flows = row['flow_rates_gpm']
            if (not isinstance(flows, list) or len(flows) != 96 or
                    any(type(v) not in (float, int) or not math.isfinite(v) or v < 0 for v in flows)):
                raise ValueError('Invalid base flow sequence')
            groups[split].extend(variants(row, split, source_sha256))
            previous = stamp
        last_end = previous
    return {'schema': 'aquamind-ampds2-hybrid-v1', 'protocol': PROTOCOL,
            'base_export_sha256': source_sha256, 'interval_minutes': 15, 'window_size': 96,
            'units': 'US gallons/minute', 'normalization': 'none',
            'label_scope': 'controlled continuous-injection detection; physical leak labels unknown',
            'purged_days': dataset.get('purged_days', []), **groups}


def export(path: Path, output: Path) -> dict:
    contents = path.read_bytes()
    digest = hashlib.sha256(contents).hexdigest()
    if digest != json.loads(MANIFEST.read_text())['output_sha256']:
        raise ValueError('Expected pinned AMPds2 window export')
    dataset = generate(json.loads(contents), digest)
    encoded = (json.dumps(dataset, separators=(',', ':'), allow_nan=False) + '\n').encode()
    with output.open('xb') as stream:
        stream.write(encoded)
    return {'protocol': PROTOCOL, 'base_export_sha256': digest,
            'output_sha256': hashlib.sha256(encoded).hexdigest(),
            'splits': {split: {'base_days': len({r['base_day_id'] for r in dataset[split]}),
                               'variants': len(dataset[split]),
                               'kinds': {kind: sum(r['variant_kind'] == kind for r in dataset[split])
                                         for kind in ('unmodified', 'continuous_injection', 'demand_confounder')}}
                       for split in ('train', 'validation', 'test')}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(export(args.input, args.output), indent=2))


if __name__ == '__main__':
    main()
