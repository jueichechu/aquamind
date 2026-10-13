# AMPds2 water inspection

AMPds2 contains minute-resolution measurements from one Canadian house over 2012–2014. Its authors pre-cleaned the series, including filling missing readings. This is useful real consumption data, but cannot establish generalization to other households. [Author site](https://makonin.com/ampds/), [data descriptor](https://doi.org/10.1038/sdata.2016.37).

The [Harvard Dataverse release](https://doi.org/10.7910/DVN/FIE0S4), version 3.1, specifies **CC BY 4.0** with attribution to Makonin, Ellert, Bajic, and Popowich (2016), *Electricity, water, and natural gas consumption of a residential house in Canada from 2012 to 2014*, Scientific Data 3, 160037. The pinned manifest records the citation, file ID, source URL, byte length and checksums. This increment uses only the unrestricted whole-house water file, not bills or other household documents.

`Water_WHW.csv` has `unix_ts`, `counter`, `avg_rate`, and `inst_rate`. Timestamps are Unix seconds; the cumulative counter is liters and both rates are liters/minute. Use average rate, not instantaneous rate, for future interval-volume calculations. [Measurement definitions, Table 4](https://makonin.com/Publications/papers/makonin2016electricity.pdf).

## Reproduce

From the repository root, download into the ignored external-data directory. `--no-clobber` preserves existing downloads; the inspector refuses an existing output report.

```sh
mkdir -p ml/data/external/ampds2
curl --fail --location --max-time 120 --no-clobber 'https://dataverse.harvard.edu/api/access/datafile/2699405?format=original' --output ml/data/external/ampds2/Water_WHW.csv
PYTHONPATH=ml ml/.venv/bin/python -m aquamind_ml.ampds2 --input ml/data/external/ampds2/Water_WHW.csv --output ml/data/external/ampds2/inspection.json
```

Compare the output with [the checked-in inspection](../../ml/data/manifests/ampds2-water-inspection.json). The original CSV must match both the repository MD5 and our pinned SHA-256 before a report is emitted. The inspector checks column layout, finite non-negative measurements, monotonic counters and exact minute spacing. Counter/rate discrepancies above 0.002 liters are counted, not repaired. It performs no resampling, normalization, anomaly injection, or labeling. No raw dataset is committed.

The file contains no leak-label column. **Do not assume every reading is leak-free or assign normal labels automatically.** This inspection does not train or evaluate a detector, and does not change the existing synthetic benchmark. The preprocessing step below defines chronological splits and interval alignment; real-data-derived ML experiments are still outstanding. Real-base sequences with injected leaks must be described as hybrid evaluation, not field-validated leak detection. WEUSEDTO and the WRF educational dataset remain uninvestigated in this increment.


## Unlabeled 15-minute windows

Run the checksum-verified preprocessor after downloading the original file:

```sh
PYTHONPATH=ml ml/.venv/bin/python -m aquamind_ml.ampds2_windows --input ml/data/external/ampds2/Water_WHW.csv --output ml/data/external/ampds2/windows-v1.json
```

The export uses a separate `aquamind-ampds2-unlabeled-v1` schema. It cannot be passed to the synthetic labeled dataset loader. Every window remains **unlabeled**, including the nominal training split; selecting a split does not assert normal or leak-free behavior. There is no normalization, injection, threshold selection, or model training in this command.

Because `avg_rate` is based on the counter difference from the preceding reading, a reading at time `t` is assigned to the preceding minute `(t-60,t]`. The first row is discarded because this input has no preceding counter. Fifteen minute volumes are summed and divided by 15 and 3.785411784 liters per US gallon to produce interval-average GPM. Windows use start timestamps at midnight UTC, with 96 intervals covering the day. UTC days are not local household days; local nighttime analysis must account for timezone and daylight saving separately.

Only complete 1,440-minute UTC days are retained; partial edge days are dropped without filling. Invalid, duplicate, or missing minute timestamps fail validation. The 729 complete days are split chronologically at floor(70% × days) and floor(85% × days), with the first day after each cut withheld as a gap. This yields 510 training, 108 validation, and 109 test windows, with two purged days. An additional 1,440 source rows are excluded at the edges, including the first row.

The [generated manifest](../../ml/data/manifests/ampds2-windows-v1.json) records dates, counts, and source/output hashes. Repeating the transformation produced byte-identical output. Output files are never overwritten and full derived sequences stay ignored.

The one-day gaps prevent adjacent windows across partitions; they do not establish household independence or eliminate seasonal dependence. All partitions come from one house. Future fitting must use training data only, with validation for development and the final period reserved for evaluation. Before adapting the LSTM, investigate temporal distribution shifts and establish a defensible normal-data selection/injection policy without inspecting test outcomes to tune it.

## Training-only profile and first hybrid experiment

Generate the descriptive profile without analyzing validation/test measurements:

```sh
PYTHONPATH=ml ml/.venv/bin/python -m aquamind_ml.ampds2_profile --input ml/data/external/ampds2/windows-v1.json --output ml/data/external/ampds2/training-profile.json
```

The CLI verifies the pinned export checksum. The statistics function accesses only `train`; tests supply inaccessible held-out partitions to enforce that boundary. The [generated training profile](../../ml/data/manifests/ampds2-training-profile-v1.json) includes its own training-content hash, daily volumes, interval rates, zero-flow fractions, longest within-day positive runs, and monthly volume summaries. Quantiles use nearest rank. Positive runs mean consecutive intervals with average GPM greater than zero, not continuous second-by-second flow or proof of a leak.

Across 510 training days, median daily consumption is approximately 199.98 US gallons; the 95th percentile is 308.29, and the maximum is 778.65. The median longest positive run is 165 minutes, with a maximum of 465 minutes. These observations motivate testing varied injection timing and magnitude instead of making every anomaly a large overnight offset. They do not justify filtering high-volume days or assigning real leak labels. UTC monthly groups may contain partial months.

The first hybrid experiment is specified before validation/test scoring:

- Keep all unmodified training days, including zero-use and high-use days. Treat autoencoder fitting as unsupervised learning on an unlabeled baseline that may contain unknown anomalies. Fit normalization on this training partition only. Do not call it verified normal data.
- Retain the existing chronological partitions and gaps. Every generated variant stays with its base day; no base day or variant may move between splits. Preserve the current synthetic detector and its reports separately.
- For validation and eventual held-out evaluation, include every unmodified base day and all combinations of additive constant flow at 0.01, 0.03, 0.1, and 0.3 GPM for 4, 12, and 24 hours. Choose a valid start interval deterministically from a SHA-256 of protocol version, base-day timestamp, rate, and duration. Patterns remain within the day, with no clipping or wrapping.
- Also include a separate demand-confounder variant: add 1 GPM for two hours, with deterministic timing. Its scenario label is synthetic elevated demand, not a real leak annotation. Its alarm rate tests whether the detector simply flags extra volume.
- Record base-day ID, source hash, injected interval bounds, added GPM, added gallons, variant kind, and injection presence. Do not attach a physical-leak ground-truth label to original readings. Continuous-flow injections represent controlled patterns, not exhaustive fixture/leak realism.
- Select the threshold using validation only. For this first protocol, maximize F1 for continuous-injection detection against the unmodified and demand-confounder references, breaking ties toward the higher threshold. Freeze the checkpoint, normalization, scoring method, threshold, and protocol before opening test outcomes.
- Report injection-detection precision/recall/F1 and counts alongside sensitivity by rate/duration, unmodified-reference alarm rate, demand-confounder alarm rate, and paired score changes. These references are nominal negatives for a constructed task, not verified leak-free ground truth. Aggregate uncertainty by base day, not by treating related variants as independent households.

Pattern generation is implemented below. Model fitting, validation selection, and held-out scoring remain subsequent increments; no hybrid performance results exist yet. Any protocol changes before test execution must be versioned and explained; after test outcomes are inspected, that test period cannot be reused as fresh confirmation for further tuning. Even a successful result would support only a one-house chronological hybrid experiment, not real household leak F1 or household-to-household generalization.


## Deterministic hybrid export

```sh
PYTHONPATH=ml ml/.venv/bin/python -m aquamind_ml.ampds2_hybrid --input ml/data/external/ampds2/windows-v1.json --output ml/data/external/ampds2/hybrid-v1.json
```

The command verifies the pinned base export, refuses to overwrite output, and prints counts and checksums. Full sequences remain in the ignored external-data directory. The [checked-in generation manifest](../../ml/data/manifests/ampds2-hybrid-v1.json) records 510 unmodified training rows, 1,512 validation variants from 108 base days, and 1,526 test variants from 109 base days. Two runs produced byte-identical exports. Generation does not fit a model or inspect held-out model outcomes.

Each validation/test base day produces one original, 12 continuous-injection variants, and one demand confounder. Start selection hashes the compact JSON array `["ampds2-hybrid-v1", start_timestamp, added_gpm, duration_intervals]` with SHA-256, interprets its bytes as an unsigned big-endian integer, and takes modulo `97 - duration_intervals`. Duration is measured in 15-minute intervals. The resulting start/end interval bounds are zero-based, with an exclusive end; full-day injections start at zero. The original has zero added volume and empty bounds `[0,0)`.

`injection_present` is true for both continuous injections and the demand confounder. `is_continuous_injection` is the constructed classification target; the confounder is false for that target. `physical_leak_label` remains `unknown` for every row. Added gallons are `added_gpm × duration_intervals × 15`; original values are neither clipped nor replaced. The source export hash and base-day ID allow grouping all related variants for analysis.

The 12 positive variants per base day deliberately cover the protocol grid; they are **not a realistic leak prevalence estimate**. Report class composition and reference/confounder alarm rates beside any future aggregate F1. Randomly splitting variant rows would leak base patterns across partitions and is prohibited by this export's design. Tests cover volume conservation, interval bounds, the complete pattern grid, immutable base sequences, deterministic generation, split independence, and rejection of overlapping partitions or missing boundary gaps.


## Hybrid loading and normalization

`aquamind_ml.hybrid_data.load_hybrid_dataset` returns immutable `HybridDataset` and `HybridWindow` records. The loader checks schema, units, protocol, source hashes, UTC daily ordering, boundary gaps and purged-day metadata. It reconstructs each protocol variant from its unmodified reference to verify the complete grid, exact added flow/volume, interval bounds, variant identities, and target labels. Training permits only unmodified references. Physical leak labels stay `unknown`; there is no `has_leak` field.

```python
from dataclasses import asdict
from aquamind_ml.hybrid_data import load_hybrid_dataset, HybridFlowNormalizer

dataset = load_hybrid_dataset("ml/data/external/ampds2/hybrid-v1.json")
normalizer = HybridFlowNormalizer.fit(dataset)
training_features = normalizer.transform(dataset.train)
validation_features = normalizer.transform(dataset.validation)
# Save asdict(normalizer) with the future training artifact.
```

The normalizer reuses the existing global z-score transformation and fits mean/population standard deviation on unmodified training features only. This does not assert that those real baseline days are leak-free. Constant training input uses unit scale; no clipping is applied. Transformations return features only, leaving the immutable source records unchanged. Parameters include full-dataset and training-only hashes.

The [generated normalization summary](../../ml/data/manifests/ampds2-hybrid-normalizer-v1.json) records 48,960 training values, mean 0.1367525438 GPM, and scale 0.3216670930 GPM. Held-out sequences were validated structurally but were not used to fit parameters or scored by a model. Tests verify parameter independence from held-out flow changes, frozen application, serialization round-trip, constant-input handling, and rejection of corrupted patterns or split manifests. A hybrid training adapter remains to be implemented; the existing synthetic trainer's assumptions are unchanged.
