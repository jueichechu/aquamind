"""Immutable hybrid windows: injection targets are distinct from physical leak labels."""

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
from statistics import fmean, pstdev

from .ampds2_hybrid import PROTOCOL, variants
from .data import FlowNormalizer, _flow, _require


@dataclass(frozen=True)
class HybridWindow:
    flow_rates_gpm: tuple[float, ...]
    start_timestamp: str
    base_day_id: str
    variant_id: str
    variant_kind: str
    injection_present: bool
    is_continuous_injection: bool
    added_gpm: float
    start_interval: int
    end_interval_exclusive: int
    added_gallons: float
    source_sha256: str
    physical_leak_label: str = 'unknown'


@dataclass(frozen=True)
class HybridDataset:
    train: tuple[HybridWindow, ...]
    validation: tuple[HybridWindow, ...]
    test: tuple[HybridWindow, ...]
    sha256: str
    training_sha256: str
    base_export_sha256: str


def load_hybrid_dataset(path: str | Path) -> HybridDataset:
    contents = Path(path).read_bytes()
    raw = json.loads(contents)
    _require(isinstance(raw, dict), 'Dataset must be an object')
    for key, expected in (('schema', 'aquamind-ampds2-hybrid-v1'), ('protocol', PROTOCOL),
                          ('units', 'US gallons/minute'), ('normalization', 'none'),
                          ('label_scope', 'controlled continuous-injection detection; physical leak labels unknown')):
        _require(raw.get(key) == expected, f'Unsupported {key}')
    for key, expected in (('interval_minutes', 15), ('window_size', 96)):
        _require(type(raw.get(key)) is int and raw[key] == expected, f'Unsupported {key}')
    source = raw.get('base_export_sha256')
    _require(isinstance(source, str) and len(source) == 64 and
             all(c in '0123456789abcdef' for c in source), 'Invalid source hash')
    groups = {}
    last_end = None
    boundary_days = []
    for split in ('train', 'validation', 'test'):
        rows = raw.get(split)
        _require(isinstance(rows, list) and bool(rows), 'Empty or invalid split')
        windows = []
        cursor = 0
        previous = None
        while cursor < len(rows):
            base = rows[cursor]
            _require(isinstance(base, dict) and base.get('variant_kind') == 'unmodified',
                     'Each base day must begin with an unmodified reference')
            try:
                start = datetime.fromisoformat(base['start_timestamp'])
            except (KeyError, TypeError, ValueError):
                raise ValueError('Invalid base timestamp') from None
            _require(start.utcoffset() == timedelta(0) and
                     (start.hour, start.minute, start.second, start.microsecond) == (0, 0, 0, 0),
                     'Expected midnight UTC')
            _require(previous is None or start - previous == timedelta(days=1), 'Nonconsecutive base days')
            if previous is None and last_end is not None:
                _require(start - last_end == timedelta(days=2), 'Missing chronological boundary gap')
                boundary_days.append((last_end + timedelta(days=1)).isoformat())
            flows = base.get('flow_rates_gpm')
            _require(isinstance(flows, list) and len(flows) == 96 and all(_flow(v) for v in flows),
                     'Invalid base sequence')
            expected_rows = variants({'start_timestamp': base['start_timestamp'], 'flow_rates_gpm': flows}, split, source)
            for expected in expected_rows:
                _require(cursor < len(rows), 'Incomplete pattern grid')
                row = rows[cursor]
                _require(isinstance(row, dict), 'Invalid hybrid row')
                _require(type(row.get('injection_present')) is bool and
                         type(row.get('is_continuous_injection')) is bool, 'Targets must be booleans')
                _require(all(type(row.get(k)) is int for k in ('start_interval', 'end_interval_exclusive')),
                         'Interval bounds must be integers')
                _require(all(_flow(row.get(k)) for k in ('added_gpm', 'added_gallons')), 'Invalid injection amounts')
                _require(isinstance(row.get('flow_rates_gpm'), list) and
                         all(_flow(v) for v in row['flow_rates_gpm']), 'Invalid flow sequence')
                _require(row == expected, 'Row differs from versioned pattern protocol or base sequence')
                windows.append(HybridWindow(**(row | {'flow_rates_gpm': tuple(float(v) for v in row['flow_rates_gpm'])})))
                cursor += 1
            previous = start
        last_end = previous
        groups[split] = tuple(windows)
    _require(raw.get('purged_days') == boundary_days, 'Invalid purged-day manifest')
    training_bytes = json.dumps(raw['train'], sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    return HybridDataset(**groups, sha256=hashlib.sha256(contents).hexdigest(),
                         training_sha256=hashlib.sha256(training_bytes).hexdigest(), base_export_sha256=source)


@dataclass(frozen=True)
class HybridFlowNormalizer(FlowNormalizer):
    """Fit on unmodified unlabeled training features; no normal/leak assertion."""

    training_sha256: str

    @classmethod
    def fit(cls, dataset: HybridDataset) -> 'HybridFlowNormalizer':
        _require(bool(dataset.train) and all(w.variant_kind == 'unmodified' and not w.injection_present
                 and not w.is_continuous_injection and w.physical_leak_label == 'unknown'
                 for w in dataset.train), 'Expected unmodified unlabeled training windows')
        values = [v for w in dataset.train for v in w.flow_rates_gpm]
        _require(all(_flow(v) for v in values), 'Invalid training flows')
        return cls(fmean(values), pstdev(values) or 1.0, len(values), dataset.sha256, dataset.training_sha256)
