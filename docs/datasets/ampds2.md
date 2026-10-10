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

The file contains no leak-label column. **Do not assume every reading is leak-free or assign normal labels automatically.** This inspection does not train or evaluate a detector, and does not change the existing synthetic benchmark. The next data increment should define chronological splits and interval alignment before any real-data-derived ML experiment. Real-base sequences with injected leaks must be described as hybrid evaluation, not field-validated leak detection. WEUSEDTO and the WRF educational dataset remain uninvestigated in this increment.
