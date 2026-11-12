# Bill import layout validation

Bill import produces candidates for review. A successful request does not prove
that every candidate matches the document. Review dates, units, consumption and
optional charges before calculating. The API response and consent requirements
remain unchanged.

## Covered behavior

- One statement can have multiple services, protection plans, payment coupons,
  meter dates and history charts without being multiple water bills. Prefer the
  current water service period and its explicitly printed consumption.
- HCF explicitly defined as 100 cubic feet maps to CCF. Scaled gallons such as
  Kgal must not be relabeled as unscaled gallons. Unsupported units remain blank
  for manual correction, with a warning to check quantity and unit together.
  The provider schema accepts `kgal` internally so the model can preserve that
  printed scale. The server withholds its quantity and unit even if the model
  omits the warning. The public API unit choices do not change.
- Chart heights and meter register differences are not exact billed consumption.
  A provider-only consumption assessment suppresses these candidates; it is not
  evidence that the model's interpretation is correct.
- Protection plans, bundled totals and partial charge components cannot fill a
  service charge. If USD has a missing source, discard currency and both prices
  while retaining an otherwise valid report. Do not invent source evidence.
  Other malformed values, sources, extra fields and invalid pages still fail
  validation. If neither a water period nor consumption can be identified,
  optional prices are also withheld for manual entry. Public response validation
  remains strict.
- No automatic paid retries, additional tools or provider storage are enabled.
  Session checks, explicit consent, request limits and human review still apply.
- Bill extraction with `gpt-5.4-mini` and its dated snapshots requests low reasoning
  instead of the model's default of none. Other configured models retain their
  defaults. The existing timeout and output-token cap remain unchanged; reasoning
  counts toward that cap and API usage, and incomplete responses still fail closed.
  See the official [model documentation](https://developers.openai.com/api/docs/models/gpt-5.4-mini)
  and [reasoning budget guidance](https://developers.openai.com/api/docs/guides/reasoning).

## Reproduce the checks

Run commands from the repository root. Listing and scoring make no provider calls:

```sh
ml/.venv/bin/python evals/bill_import_layouts.py
PYTHONPATH=ml ml/.venv/bin/python -m unittest discover -s ml/tests -p 'test_bill_import*.py' -v
```

The manifest at `evals/fixtures/bill-import-layout-v1.json` declares expectations
independently of provider output. Five fixtures are original fictional layouts;
two are official public illustrative samples. The public samples are referenced,
not redistributed or downloaded automatically. Inspect any input before sharing.
The fixture generator requires the optional authoring packages Pillow and
ReportLab; these are not application runtime dependencies.

```sh
ml/.venv/bin/python evals/bill_import_layouts.py --prepare /tmp/aquamind-layout-inputs
```

A live trial uses the existing server-side `OPENAI_API_KEY` and `OPENAI_MODEL`
from the environment or ignored root `.env.local`. It sends the entire selected
file to OpenAI and incurs API usage. Each invocation runs exactly one case:

```sh
PYTHONPATH=ml ml/.venv/bin/python evals/bill_import_layouts.py \
  --run-live layout-1 --documents /tmp/aquamind-layout-inputs \
  --results /tmp/aquamind-layout-run-1 --share-with-ai
ml/.venv/bin/python evals/bill_import_layouts.py --score /tmp/aquamind-layout-run-1
```

Supply each public sample separately using its manifest filename if testing it.
The default command lists all case IDs and filenames. A started marker prevents
replaying a case in the same results directory, including after an uncertain
failure. Do not delete markers to retry. A separately planned comparison uses a
new directory and preserves earlier outcomes. Results contain candidate fields,
warnings and source classifications, not raw document text or provider exception
messages. Keep results private; do not commit household bill data. New runs also
record input and extraction-source SHA-256 hashes for reproducibility. Paid trials
are not part of automated CI.

## Development observations, 2026-11-11

Using `gpt-5.4-mini`, the first seven-case run passed four cases. It exposed a
scaled-unit error, an invented chart quantity, and a validation failure on two
separate statements. Intermediate revisions also exposed inconsistent optional
currency source labels. Those failures were retained while developing the guards.

The final seven-case run passed the unchanged expectations below:

| Case | Input | Expected outcome |
| --- | --- | --- |
| layout-1 | Fictional two-page combined-services PDF | Current water period, consumption and separate service subtotals |
| layout-2 | Fictional quarterly HCF JPEG | Correct exclusive end and HCF-to-CCF label |
| layout-3 | Fictional Kgal PDF | Blank unsupported unit and explicit review warning |
| layout-4 | Fictional two-statement PDF | All fields withheld with `multiple_bills` |
| layout-5 | Fictional electricity PNG | All fields withheld with `not_water_bill` |
| layout-6 | Bellevue public sample PNG | Current water period and consumption; no invoice-wide charge substitution |
| layout-7 | EPCOR Arizona public sample WebP | No invented dates or consumption from illustrative labels/history bars |

This is a development regression set inspected during implementation, not a
holdout or a representative accuracy estimate. One final call per layout does
not measure repeatability. The extraction source SHA-256 for that run was
`8809f522362932b2efc3247d2bddcc132a41758d42cc61f18977862a6417bdf4`.
Provider output can vary, and strict validation can still reject a response.
Indeed, a subsequent hosted check of the same fictional Kgal PDF returned
5 US gallons with no uncertainty warning. This was retained as a failure and
motivated the provider-only `kgal` option and warning-independent server guard.
The preceding seven-case result describes its stated source revision; it did not
establish repeatability or eliminate unit-reading mistakes. The model must still
identify the printed unit correctly, and reviewers must check it against the bill.
With low reasoning enabled, two further trials of the reported bill recovered its
current period and consumption, and the scaled-unit and separate-statement checks
passed. The Arizona example correctly withheld dates and consumption but misread
an optional charge digit. That failure was retained; optional prices are now also
withheld when both the water period and consumption are absent. Regression tests
cover that abstention without another paid retry. These observations do not prove
that low reasoning eliminates extraction mistakes.
Blurred images, unusual units, unsupported currencies, missing periods and
unfamiliar utility layouts may require manual entry. These checks do not establish
support for every U.S. bill, reliable OCR of every scan, or automatic Kgal conversion.

The public format references are [Bellevue's bill guide](https://bellevuewa.gov/city-government/departments/utilities/pay-your-utility-bill/understanding-your-utility-bill),
[EPCOR Arizona's bill guide](https://www.epcor.com/us/en/az/account/billing/understand-your-bill.html),
[NYC water rates](https://www.nyc.gov/html/dep/html/water_rates/index.shtml), and
[Austin's rate study](https://www.austintexas.gov/sites/default/files/files/Water/CostServStudy/finalreportvol1.pdf).
The NYC and Austin references inform unit patterns; their original bills were not
submitted as additional live evaluation cases.
