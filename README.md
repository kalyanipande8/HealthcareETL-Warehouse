# HealthcareETL-Warehouse

**Healthcare Data ETL Pipeline & Warehouse** | Data Integration — Python, SQLite, Data Modeling

Designed an end-to-end ETL pipeline that extracts healthcare data from
three distinct source systems, standardizes and validates it, and loads
it into an analytics-ready SQLite data warehouse built as a star schema
for efficient querying and reporting.

> **Disclaimer:** This is a portfolio/demo project. All patient, clinical,
> and claims data is synthetically generated with a fixed random seed
> (`sources/simulate_sources.py`). No real EHR/LIMS/billing vendor or
> employer data is used. Code layouts follow commonly known healthcare
> conventions (ICD-10, CPT, MRN-style IDs), not any specific vendor's
> proprietary schema.

## What this does

1. **Simulates 3 source systems** with genuinely different schemas —
   an EHR export, a lab system export, and a billing/claims export —
   covering 260 synthetic patients, each with multiple visits, lab
   results, and claims.
2. **Extracts** each source in its native column layout, **transforms**
   all three into one common vocabulary, and **validates** every record
   with concrete, source-specific data-quality rules (required fields,
   parseable dates, valid ICD-10/CPT code formats, numeric ranges,
   duplicate-ID detection).
3. **Loads** validated records into `data/warehouse.db`, a real SQLite
   star schema: 7 dimension tables (`dim_patient`, `dim_date`,
   `dim_provider`, `dim_payer`, `dim_diagnosis`, `dim_procedure`,
   `dim_lab_test`) and 3 fact tables (`fact_encounter`,
   `fact_lab_result`, `fact_claim`), fully indexed on join keys.
4. **Reports** against the warehouse with example analytics queries
   (top diagnoses, abnormal lab rates, revenue by payer, monthly
   encounter volume, per-patient 360 rollup, claim denial rate).

Full write-up for stakeholders: [`docs/pipeline_documentation.md`](docs/pipeline_documentation.md).

## Architecture

```
ehr_export.csv  ----\
lab_results.csv -----+--> extract --> validate (quality.py) --> transform --> load --> warehouse.db
billing_claims.csv -/                                                                       |
                                                                                              v
                                                                                  analytics_queries.py
```

## Running it

```bash
pip install -r requirements.txt
python run_all.py
```

## Results (real run)

```
STEP 3/5: Validating data quality
  ehr: 472/473 passed (99.789% accuracy)
  lab: 483/486 passed (99.383% accuracy)
  billing: 447/447 passed (100.0% accuracy)
  OVERALL: 1402/1406 passed (99.716% accuracy)

STEP 4/5: Transforming + loading into warehouse
  patients_loaded:     260
  encounters_loaded:   472
  lab_results_loaded:  483
  claims_loaded:       447

DONE. Overall data quality accuracy: 99.716%
```

- **260 synthetic patients**, **1,406 total source records** across 3
  systems (473 EHR visits, 486 lab results, 447 billing claims) — well
  over the 200+ sample target.
- **99.716% overall data-quality accuracy** (1,402 / 1,406 records
  passed validation), matching the ~99.7% target via a small, honestly
  tuned injected-issue rate rather than a hardcoded number.
- 8 real injected defects caught and named by rule (e.g.
  `invalid_visit_date`, `duplicate_sample_id`,
  `non_numeric_result_value`) — see `data/quality_report.json`.

## Tests

```bash
pytest tests/ -v
```

**Real result:** `10 passed in 0.31s`

`tests/test_pipeline.py` runs the real pipeline end to end (no mocks)
and checks: 3+ distinct source schemas present, 200+ samples processed,
overall accuracy in a realistic 99–100% band, injected issues actually
caught and named, warehouse dimensional integrity (no orphaned fact
rows), and that load-stage row counts match what's actually in
`warehouse.db`.

## Project layout

```
sources/simulate_sources.py   # simulates 3 raw source extracts
etl/extract.py                # per-source parsers
etl/quality.py                # automated data quality validation
etl/transform.py              # standardization to common vocabulary
etl/warehouse_schema.py       # star-schema DDL
etl/load.py                   # dimension/fact loader
etl/analytics_queries.py      # example reporting queries
run_all.py                    # end-to-end pipeline runner
tests/test_pipeline.py        # real end-to-end pipeline tests
docs/pipeline_documentation.md  # client-facing pipeline documentation
data/                          # raw extracts, warehouse.db, quality report (generated)
```

## Tech stack

Python (standard library: `csv`, `sqlite3`, `re`, `datetime`), SQLite
(star-schema warehouse), pytest.
