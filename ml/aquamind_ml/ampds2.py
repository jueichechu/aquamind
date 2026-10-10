"""Inspect the pinned AMPds2 whole-house water CSV without creating ML labels."""

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

MANIFEST = Path(__file__).resolve().parents[1] / "data/manifests/ampds2-water.json"


def inspect_water(path: Path) -> dict:
    count = 0
    first = previous = None
    last_counter = None
    mismatches = 0
    nonzero = 0
    maximum = 0.0
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != ["unix_ts", "counter", "avg_rate", "inst_rate"]:
            raise ValueError("Unexpected AMPds2 water columns")
        for row in reader:
            try:
                if None in row or any(value is None for value in row.values()):
                    raise ValueError()
                timestamp = int(row["unix_ts"])
                values = [float(row[key]) for key in ("counter", "avg_rate", "inst_rate")]
                if not all(math.isfinite(value) and value >= 0 for value in values):
                    raise ValueError()
                if timestamp % 60 or (previous is not None and timestamp - previous != 60):
                    raise ValueError()
                counter, average, _ = values
                if last_counter is not None:
                    if counter < last_counter:
                        raise ValueError()
                    if abs(counter - last_counter - average) > 0.002:
                        mismatches += 1
            except (ValueError, TypeError):
                raise ValueError(f"Invalid water reading at CSV line {reader.line_num}") from None
            if first is None:
                first = timestamp
            previous, last_counter = timestamp, counter
            nonzero += average > 0
            maximum = max(maximum, average)
            count += 1
    if not count:
        raise ValueError("Empty water file")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"source": "AMPds2", "source_type": "real_residential_precleaned",
            "sha256": digest, "rows": count, "interval_seconds": 60,
            "first_timestamp_utc": datetime.fromtimestamp(first, timezone.utc).isoformat(),
            "last_timestamp_utc": datetime.fromtimestamp(previous, timezone.utc).isoformat(),
            "nonzero_average_rate_rows": nonzero, "max_average_rate_liters_per_minute": maximum,
            "counter_rate_discrepancies_over_0_002_liters": mismatches,
            "leak_labels": "not_provided", "transformations": [], "anomalies_injected": False}


def verified_report(path: Path) -> dict:
    manifest = json.loads(MANIFEST.read_text())
    with path.open("rb") as stream:
        md5 = hashlib.file_digest(stream, "md5").hexdigest()
    if path.stat().st_size != manifest["bytes"] or md5 != manifest["md5"]:
        raise ValueError("File does not match pinned AMPds2 original CSV")
    report = inspect_water(path)
    if report["sha256"] != manifest["sha256"] or report["rows"] != manifest["expected_rows"]:
        raise ValueError("Pinned AMPds2 content mismatch")
    return report | {"dataset_doi": manifest["dataset_doi"], "file_id": manifest["file_id"],
                     "license": manifest["license"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = verified_report(args.input)
    with args.output.open("x") as stream:
        stream.write(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
