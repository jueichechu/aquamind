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
