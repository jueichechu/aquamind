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

The file contains no leak-label column. **Do not assume every reading is leak-free or assign normal labels automatically.** This inspection does not train or evaluate a detector, and does not change the existing synthetic benchmark. The preprocessing step below defines chronological splits and interval alignment; hybrid training is described below; classification evaluation is still outstanding. Real-base sequences with injected leaks must be described as hybrid evaluation, not field-validated leak detection. WEUSEDTO and the WRF educational dataset remain uninvestigated in this increment.


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

Pattern generation and model fitting are implemented below. Validation threshold selection is described below; held-out scoring remains outstanding. Any protocol changes before test execution must be versioned and explained; after test outcomes are inspected, that test period cannot be reused as fresh confirmation for further tuning. Even a successful result would support only a one-house chronological hybrid experiment, not real household leak F1 or household-to-household generalization.


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

The [generated normalization summary](../../ml/data/manifests/ampds2-hybrid-normalizer-v1.json) records 48,960 training values, mean 0.1367525438 GPM, and scale 0.3216670930 GPM. Held-out sequences were validated structurally but were not used to fit parameters or scored by a model. Tests verify parameter independence from held-out flow changes, frozen application, serialization round-trip, constant-input handling, and rejection of corrupted patterns or split manifests. The hybrid training adapter is described below; the existing synthetic trainer retains its label assumptions.

## Hybrid LSTM training

```sh
PYTHONPATH=ml ml/.venv/bin/python -m aquamind_ml.hybrid_train --dataset ml/data/external/ampds2/hybrid-v1.json --output ml/artifacts/ampds2-lstm-v1 --epochs 20
```

The adapter trains the existing PyTorch LSTM autoencoder on all 510 unmodified AMPds2 training days. These days are unlabeled and may contain unknown anomalies. It selects the checkpoint by minimum reconstruction MSE on the 108 unmodified validation references, with earliest epoch breaking ties. Injected validation variants and every test variant are excluded from training and checkpoint selection. The shared CPU optimizer uses fixed seeds, deterministic PyTorch operations, Adam, gradient clipping, and training-only normalization.

The ignored artifact directory contains `weights.pt` and `training.json`, including the configuration, history, chosen epoch, frozen normalization, dataset/source/weight hashes, label disclosure, and execution environment. Existing directories are never overwritten. Tests verify reproducible model tensors, unchanged training results when test data and validation injections are removed, checkpoint selection, artifact reloading, and rejection of missing validation references.

This training run produces reconstruction weights only. Validation threshold selection and injection-detection scoring are described below; held-out evaluation remains outstanding. Reconstruction MSE is not precision, recall, F1, or a leak probability. The trained hybrid model is not yet connected to FastAPI/MCP or the dashboard; the existing synthetic detector remains separately versioned.


The first 20-epoch run is recorded in [the generated training baseline](../../evals/baselines/ampds2-training-v1.json). It selected epoch 17, with unmodified-validation MSE 0.7224179484 in normalized squared-error units. A second complete run produced identical model tensors and loss history. This is reproducible training evidence, not a classification benchmark; no validation injection scores or test scores have been calculated.

## Validation-only scoring baseline

```sh
PYTHONPATH=ml ml/.venv/bin/python -m aquamind_ml.hybrid_validate --dataset ml/data/external/ampds2/hybrid-v1.json --checkpoint ml/artifacts/ampds2-lstm-v1 --output evals/reports/ampds2-validation-v1.json
```

The command verifies checkpoint weights, dataset provenance, and the saved training-only normalization. It scores validation windows using daily mean squared reconstruction error in normalized units. The threshold maximizes validation F1, with a higher threshold breaking ties. Test sequences are structurally loaded but are never transformed or scored. Tests enforce a validation-only access boundary and verify that changing target labels does not change reconstruction scores.

The [generated validation baseline](../../evals/baselines/ampds2-validation-v1.json) records threshold 0.3039536774 and F1 0.9231 across 1,512 variants, but **this is a failed discrimination baseline**: all 1,512 variants trigger an alarm. It exactly matches the always-positive reference. Both unmodified-reference and demand-confounder alarm rates are 100%, and balanced accuracy is 0.5. The 12:2 positive/reference composition makes aggregate F1 look high even when the detector provides no useful separation at its chosen threshold.

The report includes sensitivity for every rate/duration, nominal confusion counts, reference/confounder alarm rates, and per-variant score changes from the same base day's unmodified reference. Full per-variant evidence is saved locally under ignored `evals/reports/`. Paired deltas are diagnostic metadata only; the standalone score does not assume access to a household's counterfactual unmodified day. No confidence intervals or held-out results are claimed.

This result does not establish real household leak-detection performance. Keep the held-out test period unopened while diagnosing scoring/calibration on training and validation data. The current threshold is recorded for reproducibility, but no production detector has been frozen from it. Any change to scoring, threshold objective, or pattern protocol must be documented before test evaluation; a useful detector must demonstrate acceptable reference and confounder alarm behavior alongside aggregate injection-detection metrics.

## Sustained residual scoring experiment

Scoring protocol `sustained-residual-v1` is defined before running its validation comparison. Center each UTC slot's residual using its median over unmodified training days; divide by that slot's population standard deviation with a fixed 0.01 floor in normalized-flow units. Within each day, score every 16-interval (four-hour) stretch by its fourth-smallest standardized residual (nearest-rank lower quartile), then take the largest stretch score, clamped at zero. There is no wrap across day boundaries. This aims to retain persistent excess flow while reducing sensitivity to isolated demand bursts. It uses LSTM reconstruction residuals and does not access injection timing or a counterfactual base day during inference.

The threshold objective changes from unconstrained maximum F1: maximize validation F1 subject to alarm rates at most 5% **separately** on unmodified references and demand confounders, with higher thresholds breaking ties. Five percent is a declared development cap, not an established acceptable household alert rate. Include the above-maximum threshold so rejecting every variant remains feasible. Apply the same objective to daily MSE to distinguish the scoring effect from the constraint effect. Keep the earlier unconstrained MSE baseline. Fit all calibration parameters from training only; use validation for threshold development; do not score test data in this experiment. Low-flow injections may remain difficult and must be reported by rate and duration.

Reproduce the validation-only comparison:

```sh
PYTHONPATH=ml ml/.venv/bin/python -m aquamind_ml.hybrid_sustained --dataset ml/data/external/ampds2/hybrid-v1.json --checkpoint ml/artifacts/ampds2-lstm-v1 --output evals/reports/ampds2-sustained-validation-reproduced-v1.json
```

The [generated comparison](../../evals/baselines/ampds2-sustained-validation-v1.json) records:

| Validation measure | Sustained residual | MSE with same alarm constraints |
| --- | ---: | ---: |
| Precision | 0.9921 | 0.6429 |
| Recall | 0.3889 | 0.0069 |
| F1 | 0.5588 | 0.0137 |
| Unmodified-reference alarms | 0/108 | 0/108 |
| Demand-confounder alarms | 4/108 | 5/108 |

The sustained score improves discrimination under the same alarm constraints, but misses 792 of 1,296 injected patterns. It detects none of the 0.01 or 0.03 GPM injections. At 0.1 GPM, sensitivity is 20.4% for four hours, 91.7% for twelve hours, and 100% for a full day. This is a development result with important low-flow limitations, not an achieved leak-detection target. Its lower F1 than the original flag-everything result reflects a changed threshold objective and fewer nominal false alarms, not a directly comparable unconstrained optimization result.

The implementation records all 96 training-derived centers/scales, source hashes, both thresholds, confusion counts, per-pattern sensitivity, and paired validation evidence. The fixed scale floor is applied as a Python float after population standard deviation, avoiding a float32 rounding error below the declared 0.01 minimum. Repeated scoring after that repair produced identical real validation scores and metrics. Tests cover zero-variance calibration, serialized parameters, short demand spikes, no cross-midnight wrapping, separate group alarm limits, an all-negative fallback, and a test partition that raises if accessed. No held-out score or production artifact is produced.

## Background-flow ablation protocol

Before further validation scoring, define a fixed ablation to separate reconstruction effects from residual standardization. Keep the four-hour/fourth-smallest persistence operator and the same separate 5% reference/confounder alarm caps. Compare: (1) the existing slot-standardized sustained residual score; (2) residuals centered by training-slot median, converted back into GPM without dividing by slot standard deviation; and (3) the same persistence operator applied directly to measured GPM. The third candidate is explicitly a model-free physical baseline. It must not be credited as PyTorch/LSTM performance.

Use identical validation variants, threshold objective, and diagnostics for all three. Do not alter pattern strengths/durations, inspect test scores, or tune additional window lengths/quantiles during this ablation. The comparison can reveal whether slot variance masks small offsets or whether reconstruction harms/preserves the useful background-flow signal. It cannot establish real leak truth or prove the LSTM adds value merely because a rule performs well. Counterfactual base-day score changes remain offline diagnostics only.

Run the ablation:

```sh
PYTHONPATH=ml ml/.venv/bin/python -m aquamind_ml.hybrid_floor --dataset ml/data/external/ampds2/hybrid-v1.json --checkpoint ml/artifacts/ampds2-lstm-v1 --output evals/reports/ampds2-background-validation-reproduced-v1.json
```

The [generated ablation report](../../evals/baselines/ampds2-background-validation-v1.json) finds:

| Validation measure | Slot-standardized LSTM residual | Centered LSTM residual, GPM | Measured-flow rule, GPM |
| --- | ---: | ---: | ---: |
| Recall | 0.3889 | 0.0340 | 0.0123 |
| F1 | 0.5588 | 0.0654 | 0.0243 |
| Unmodified-reference alarms | 0/108 | 0/108 | 0/108 |
| Demand-confounder alarms | 4/108 | 5/108 | 5/108 |

The earlier slot-standardized score reproduces its previous result. Removing slot scaling worsens sensitivity under the same false-alarm constraints. The measured-flow rule also performs poorly, so this comparison does not support replacing the model with this particular flow rule. It does not establish that the LSTM beats every possible model-free method. Both GPM scores require relatively high thresholds (0.3236 and 0.4321 GPM respectively) to meet the demand-confounder alarm constraint, suppressing subtle injections. The fixed four-hour lower-quartile operator still admits enough demand-confounder scores to limit sensitivity.

These alternatives do not improve the current candidate and should not be promoted to the served detector. The next development step is to investigate persistence robustness to the two-hour demand confounder, with any new rule specified before its validation run. Preserve the current patterns and withheld test period. Full paired score evidence stays in the ignored local report; no held-out metric, new checkpoint, or production deployment is produced by this experiment. Tests cover physical units, burst rejection, within-day boundaries, invalid inputs, held-out access prevention, and independence of the measured-flow baseline from normalization/model parameters.

## Strict persistence protocol

Define `strict-persistence-v1` before its validation run: replace the fourth-smallest residual in each 16-interval stretch with its minimum, then take the maximum stretch score and clamp at zero. Retain the trained LSTM, training-only per-slot residual centers/scales, fixed four-hour duration, original injection grid, and separate 5% validation reference/confounder alarm caps. This requires excess evidence at every interval of a qualifying stretch, reducing the chance that two-hour demand plus unrelated background fills the lower quartile. A single low interval can suppress a real event, so this is a tradeoff to measure, not a guaranteed improvement.

Compare strict standardized-LSTM residuals with the earlier lower-quartile residual candidate, and also apply strict persistence directly to measured GPM as an explicitly model-free control. Do not tune more durations, quantiles, or pattern strengths in this experiment. Report reference alarms and sensitivity by rate/duration, maintain separate attribution for the control, and keep test outcomes unopened. Detector promotion requires acceptable reference-alarm behavior and pattern sensitivity, not aggregate synthetic-injection F1 alone.

Reproduce the strict comparison:

```sh
PYTHONPATH=ml ml/.venv/bin/python -m aquamind_ml.hybrid_persistence --dataset ml/data/external/ampds2/hybrid-v1.json --checkpoint ml/artifacts/ampds2-lstm-v1 --output evals/reports/ampds2-persistence-validation-reproduced-v1.json
```

The [generated strict-persistence report](../../evals/baselines/ampds2-persistence-validation-v1.json) records:

| Validation measure | Earlier lower-quartile residual | Strict LSTM residual | Strict measured-flow control |
| --- | ---: | ---: | ---: |
| Precision | 0.9921 | 0.9935 | 0.9896 |
| Recall | 0.3889 | 0.8218 | 0.5154 |
| F1 | 0.5588 | 0.8995 | 0.6778 |
| Unmodified-reference alarms | 0/108 | 2/108 | 2/108 |
| Demand-confounder alarms | 4/108 | 5/108 | 5/108 |

The strict residual threshold is 0.0851231068 in training-standardized residual units. Requiring all 16 intervals lowers the selected threshold while still satisfying both development alarm caps. The earlier candidate reproduces its previous results exactly. Strict residual scoring detects 1,065 of 1,296 injected variants and outperforms this measured-flow control under the same criterion. That comparison supports a contribution from the LSTM residual/calibration path in this constructed validation task, but cannot establish superiority over all possible rules or models.

Weak short patterns remain: four-hour sensitivity is 13.0% at 0.01 GPM and 25.9% at 0.03 GPM. Corresponding twelve-hour sensitivity is 77.8% and 97.2%; full-day sensitivity is 100% for all tested rates. The generated report retains the complete rate/duration breakdown. Aggregate F1 remains dependent on the designed pattern prevalence and correlated variants.

This candidate is ready to freeze for a held-out experiment, not to claim real-world household leak performance. The next increment should version the checkpoint, training-only normalization/calibration, strict score, threshold, and source hashes before any test scoring. Score the withheld period once without refitting or threshold adjustment, and report the actual outcome even if performance falls. If further development follows inspected test results, obtain a fresh confirmation period/dataset. Tests for this increment cover exact four-hour persistence, interrupted events, short demand, no cross-day wrapping, invalid tensors, validation alarm caps, and inaccessible held-out data.

## Frozen strict-persistence artifact

```sh
PYTHONPATH=ml ml/.venv/bin/python -m aquamind_ml.hybrid_detector --dataset ml/data/external/ampds2/hybrid-v1.json --checkpoint ml/artifacts/ampds2-lstm-v1 --validation evals/baselines/ampds2-persistence-validation-v1.json --output ml/artifacts/ampds2-detector-v1
```

The freeze command consumes the committed validation summary without selecting another threshold or scoring test windows. It verifies weights, dataset/normalization provenance, selected epoch, validation-source hashes, the training-only residual fit, and the declared alarm constraints. It copies the weights and writes a deterministic `detector.json` completion manifest. Existing directories are never overwritten.

The manifest locks the model dimensions, weights, global normalization, 96 residual centers/scales, strict four-hour scoring contract, threshold, comparison, development base days, last development date, validation-report hash, and runtime source hashes. Only training and validation base-day identities enter the development list. The [generated freeze record](../../evals/baselines/ampds2-detector-freeze-v1.json) pins the full manifest SHA-256 and model version before held-out scoring.

`FrozenHybridDetector` loads weights and saved parameters without fitting or using dataset labels. It rejects changed weights, unsupported scoring contracts, invalid thresholds, and runtime-source mismatches. Updating those source files requires an explicitly new artifact/version. Predictions contain `score`, `is_continuous_pattern`, and `model_version`; the flag reflects the controlled-pattern target, not a verified plumbing diagnosis or probability. For reproducible CPU comparisons, callers use one PyTorch thread. This artifact is local and is not yet promoted into the HTTP/MCP service.

All 1,512 frozen validation scores and flags exactly match the saved validation experiment, with fitting disabled during reload/inference. Tests also verify label/provenance independence, refusal to overwrite, and corrupted/stale artifact rejection. No held-out prediction has been calculated in this increment. Next, evaluate the pinned detector on the withheld period without refitting or threshold changes, report reference/confounder alarm rates and pattern sensitivity alongside aggregate metrics, retaining the hybrid-data qualification.

## Held-out evaluation protocol

Evaluate only the detector matching the committed pre-test manifest hash and dataset hash. Require every test base day to be disjoint from development and at least two UTC days after the last development day, retaining the withheld boundary day. Make no calls to normalization/calibration fitting or threshold selection. Apply the frozen score and threshold to all test variants, with the same pattern/reference breakdown as validation. Record all predictions locally and a compact generated summary in Git.

For uncertainty, use 1,000 circular moving-block bootstrap replicates over chronologically ordered base days, block length seven days, seed 42, with nearest-rank 2.5th/97.5th percentiles. Keep all variants of a sampled day together. This reflects some within-period temporal dependence and cannot quantify generalization to other households, model-selection uncertainty, or all seasonal effects. A zero bootstrap alarm interval does not establish zero population risk. These choices are fixed before inspecting held-out results.

## Held-out result

```sh
PYTHONPATH=ml ml/.venv/bin/python -m aquamind_ml.hybrid_confirm --dataset ml/data/external/ampds2/hybrid-v1.json --detector ml/artifacts/ampds2-detector-v1 --output evals/reports/ampds2-heldout-reproduced-v1.json
```

The [generated held-out summary](../../evals/baselines/ampds2-heldout-v1.json) evaluates the pinned `hybrid-detector-c805bc1fffe10b80` at its unchanged 0.0851231068 threshold. The detector weights and manifest remained byte-identical to the pre-test record. There was no refitting, threshold selection, or model change during evaluation.

The withheld period is December 13, 2013 through March 31, 2014: 109 base days and 1,526 variants. There are 1,308 positive continuous-injection variants, 109 unmodified references, and 109 demand confounders.

| Held-out measure | Result |
| --- | ---: |
| Precision | 0.9828 |
| Recall | 0.8280 |
| F1 | 0.8988 |
| Balanced accuracy | 0.8704 |
| TP / FP / FN / TN | 1,083 / 19 / 225 / 199 |
| Unmodified-reference alarms | 7/109 (6.42%) |
| Demand-confounder alarms | 12/109 (11.01%) |

The seven-day moving-block bootstrap gives an F1 interval of approximately 0.8894–0.9086. This conditional interval reflects variation within one household/period and does not establish population or unseen-household performance. At 0.01 GPM, sensitivity is 9.2% for four hours, 80.7% for twelve hours, and 100% for a full day. All pattern results and reference-alarm intervals are retained in the generated summary; per-variant predictions remain in the ignored full report.

**The validation alarm caps did not generalize:** both reference rates exceed 5% on the held-out period. Aggregate injection-detection F1 is encouraging, but alert reliability and short low-flow sensitivity remain inadequate for unrestricted household deployment. Preserve this result without adjusting the frozen threshold to test outcomes. Future ML tuning requires a fresh confirmation dataset/period; this test period is now inspected.

### Interpretation and serving limitations

The PyTorch LSTM autoencoder with residual calibration achieved F1 0.8988 on the chronological AMPds2 holdout with controlled synthetic continuous-flow injections. This is a hybrid-data experiment: physical leak labels are unknown, and the result does not demonstrate field leak validation.

The existing local FastAPI p95 benchmark (15.36 ms) used the separately versioned **synthetic-trained detector**. It does not establish the latency of this hybrid artifact or a production service. Do not combine the hybrid F1 and prior latency into wording implying they were measured on the same served model. Hybrid service promotion and its own latency measurement remain later integration work.

This completes the planned frozen-model/held-out experiment, with limitations explicitly recorded. The next major phase is live agent integration with the existing typed MCP tools and approval boundary. It can proceed while the hybrid detector remains experimental and clearly disclosed. Bill workflows, image/voice, end-to-end agent and tool benchmarks, durable storage, and production deployment still remain. OpenAI credentials are needed when the first live agent requests are ready to verify; database and hosting setup are not required for the local agent adapter.
