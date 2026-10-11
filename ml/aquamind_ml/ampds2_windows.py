"""Prepare unlabeled AMPds2 daily windows with chronological, purged splits."""

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Iterable

from .ampds2 import verified_report

LITERS_PER_US_GALLON = 3.785411784


def daily_windows(rows: Iterable[tuple[int, float]]) -> tuple[list[dict], int]:
    """avg_rate at t describes (t-60,t]; emit start-labeled UTC intervals.

    Discard the first rate because its preceding counter is outside this input.
    Keep only complete UTC days; never fill missing samples or cross day bounds.
    """
    windows = []
    previous = None
    day = None
    samples: list[float] = []
    dropped = 0

    def finish():
        nonlocal dropped
        if len(samples) == 1440:
            windows.append({"start_timestamp": datetime.fromtimestamp(day, timezone.utc).isoformat(),
                            "flow_rates_gpm": [math.fsum(samples[i:i + 15]) / 15 / LITERS_PER_US_GALLON
                                               for i in range(0, 1440, 15)]})
        else:
            dropped += len(samples)

    for timestamp, rate in rows:
        if (type(timestamp) is not int or timestamp % 60 or
                type(rate) not in (int, float) or not math.isfinite(rate) or rate < 0):
            raise ValueError("Invalid minute reading")
        if previous is None:
            previous = timestamp
            dropped += 1
            continue
        if timestamp - previous != 60:
            raise ValueError("Expected consecutive minute readings")
        previous = timestamp
        start = timestamp - 60
        current_day = start // 86400 * 86400
        if current_day != day:
            if day is not None:
                finish()
            day, samples = current_day, []
        samples.append(float(rate))
    if day is not None:
        finish()
    if not windows:
        raise ValueError("No complete UTC days")
    return windows, dropped


def chronological_split(windows: list[dict]) -> dict:
    """Fixed 70%/15% cut points; purge one full day at each new split."""
    first_cut, second_cut = len(windows) * 70 // 100, len(windows) * 85 // 100
    groups = {"train": windows[:first_cut], "validation": windows[first_cut + 1:second_cut],
              "test": windows[second_cut + 1:]}
    if any(not group for group in groups.values()):
        raise ValueError("Insufficient days for three nonempty purged splits")
    return groups | {"purged_days": [windows[first_cut]["start_timestamp"],
                                      windows[second_cut]["start_timestamp"]]}


def prepare(path: Path) -> dict:
    provenance = verified_report(path)
    with path.open(newline="", encoding="utf-8") as stream:
        rows = csv.DictReader(stream)
        windows, dropped = daily_windows((int(row["unix_ts"]), float(row["avg_rate"])) for row in rows)
    return {"schema": "aquamind-ampds2-unlabeled-v1", "source": provenance,
            "household_id": "ampds2-house-1", "interval_minutes": 15, "window_size": 96,
            "units": "US gallons/minute", "liters_per_us_gallon": LITERS_PER_US_GALLON,
            "alignment": "avg_rate at t represents preceding minute; windows start at midnight UTC",
            "normalization": "none", "labels": "unknown", "anomalies_injected": False,
            "split_policy": "chronological 70/15/15 cut points; one day purged at each boundary",
            "discarded_edge_minute_rows": dropped, **chronological_split(windows)}


def export(path: Path, output: Path) -> dict:
    dataset = prepare(path)
    contents = (json.dumps(dataset, separators=(",", ":"), allow_nan=False) + "\n").encode()
    with output.open("xb") as stream:
        stream.write(contents)
    return {"schema": dataset["schema"], "source_sha256": dataset["source"]["sha256"],
            "output_sha256": hashlib.sha256(contents).hexdigest(),
            "discarded_edge_minute_rows": dataset["discarded_edge_minute_rows"],
            "purged_days": dataset["purged_days"],
            "splits": {name: {"windows": len(dataset[name]),
                              "first_day": dataset[name][0]["start_timestamp"],
                              "last_day": dataset[name][-1]["start_timestamp"]}
                       for name in ("train", "validation", "test")}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.input, args.output), indent=2))


if __name__ == "__main__":
    main()
