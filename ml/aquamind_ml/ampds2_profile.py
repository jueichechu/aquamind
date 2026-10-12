"""Describe only AMPds2 training windows; never infer normal/leak labels."""

import argparse
from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
from statistics import fmean

MANIFEST = Path(__file__).resolve().parents[1] / 'data/manifests/ampds2-windows-v1.json'


def distribution(values: list[float]) -> dict:
    ordered = sorted(values)
    return {'min': ordered[0], 'median_nearest_rank': ordered[math.ceil(len(ordered) * .5) - 1],
            'p95_nearest_rank': ordered[math.ceil(len(ordered) * .95) - 1],
            'max': ordered[-1], 'mean': fmean(ordered)}


def profile_training(dataset: dict) -> dict:
    if (dataset.get('schema') != 'aquamind-ampds2-unlabeled-v1' or
            dataset.get('units') != 'US gallons/minute' or dataset.get('labels') != 'unknown'):
        raise ValueError('Expected unlabeled AMPds2 windows in US GPM')
    rows = dataset['train']
    if not isinstance(rows, list) or not rows:
        raise ValueError('Training partition is empty')
    previous = None
    all_rates, totals, zero_fractions, positive_runs = [], [], [], []
    months: dict[str, list[float]] = {}
    for row in rows:
        start = datetime.fromisoformat(row['start_timestamp'])
        if (start.utcoffset() != timedelta(0) or
                (start.hour, start.minute, start.second, start.microsecond) != (0, 0, 0, 0) or
                (previous is not None and start - previous != timedelta(days=1))):
            raise ValueError('Expected consecutive midnight-UTC training days')
        previous = start
        rates = row['flow_rates_gpm']
        if (not isinstance(rates, list) or len(rates) != 96 or
                any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in rates)):
            raise ValueError('Expected 96 finite non-negative flow rates')
        total = math.fsum(rates) * 15
        totals.append(total)
        months.setdefault(start.strftime('%Y-%m'), []).append(total)
        all_rates.extend(rates)
        zero_fractions.append(sum(v == 0 for v in rates) / 96)
        run = longest = 0
        for value in rates:
            run = run + 1 if value > 0 else 0
            longest = max(longest, run)
        positive_runs.append(longest * 15)
    training_bytes = json.dumps(rows, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return {'schema': 'aquamind-ampds2-training-profile-v1', 'partition': 'train',
            'training_sha256': hashlib.sha256(training_bytes).hexdigest(),
            'days': len(rows), 'first_day': rows[0]['start_timestamp'], 'last_day': rows[-1]['start_timestamp'],
            'daily_gallons': distribution(totals), 'interval_average_gpm': distribution(all_rates),
            'daily_zero_interval_fraction': distribution(zero_fractions),
            'longest_daily_positive_run_minutes': distribution(positive_runs),
            'monthly_daily_gallons': {month: {'days': len(values), **distribution(values)}
                                     for month, values in months.items()},
            'labels': 'unknown', 'interpretation': 'Descriptive only; positive flow is not a leak label',
            'validation_or_test_statistics_used': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    contents = args.input.read_bytes()
    if hashlib.sha256(contents).hexdigest() != json.loads(MANIFEST.read_text())['output_sha256']:
        raise ValueError('Expected pinned AMPds2 window export')
    report = profile_training(json.loads(contents))
    with args.output.open('x') as stream:
        stream.write(json.dumps(report, indent=2, allow_nan=False) + '\n')


if __name__ == '__main__':
    main()
