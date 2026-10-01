# Healthcare Data ETL Pipeline & Warehouse — Pipeline Documentation

**Audience:** client stakeholders, analysts, and engineers who will run,
extend, or query this pipeline.

**Scope:** end-to-end ETL from three source healthcare systems into an
analytics-ready SQLite data warehouse, with automated data-quality
validation at load time.

---

## 1. Overview

This pipeline integrates data from three operationally distinct source
systems that a typical healthcare organization runs side by side:

| Source | What it represents | Raw file |
|---|---|---|
| EHR (Electronic Health Record) export | Clinical visits/encounters, diagnoses | `data/raw/ehr_export.csv` |
| Lab system export | Individual lab test results | `data/raw/lab_results.csv` |
| Billing/claims system export | Charges submitted to payers | `data/raw/billing_claims.csv` |

Each source has its own column naming, its own patient-identifier
convention, and its own quirks — exactly as real EHR, LIMS, and billing
systems do not share a common export format. The pipeline extracts each
in its native shape, standardizes them into one common vocabulary, runs
automated quality checks, and loads the result into a queryable star
schema.

> **Disclaimer:** All data in this repository is synthetically generated
> (`sources/simulate_sources.py`, fixed random seed) for demonstration
> purposes. No real patient, provider, or payer data is used. Column
> layouts are modeled on commonly known healthcare data conventions
> (ICD-10, CPT, MRN-style identifiers), not on any specific vendor's
> proprietary schema.

---

## 2. Architecture

```
 ehr_export.csv  ----\
 lab_results.csv -----+--> extract.py --> quality.py --> transform.py --> load.py --> warehouse.db
 billing_claims.csv -/        (per-source      (validation,      (standardize        (star schema:
                                parsers)         quarantine        to common          dims + facts)
                                                 failed rows)      vocabulary)
                                                                                           |
                                                                                           v
                                                                              analytics_queries.py
                                                                            (reporting queries)
```

Pipeline stages, each a separate module under `etl/`:

1. **Extract** (`etl/extract.py`) — reads each raw CSV with its native
   column names; no transformation happens here, so the extract layer is
   a faithful record of exactly what each source system produced.
2. **Validate** (`etl/quality.py`) — runs concrete, source-appropriate
   rules against every record (see §4) and tags each with `_valid` /
   `_issues`. Invalid records are quarantined (excluded from fact
   tables) rather than silently loaded or silently dropped.
3. **Transform** (`etl/transform.py`) — standardizes valid records from
   all three sources into one common schema/vocabulary (shared date
   format, shared patient key, ICD-10/CPT descriptions resolved from a
   reference table), independent of which source they came from.
4. **Load** (`etl/load.py`) — loads standardized records into the
   SQLite warehouse, generating/resolving surrogate keys for each
   dimension and inserting into the appropriate fact table.
5. **Report** (`etl/analytics_queries.py`) — a library of example
   reporting queries proving the warehouse is efficient to query.

`run_all.py` runs all five stages end to end in one command.

---

## 3. Warehouse data model (star schema)

The warehouse (`data/warehouse.db`, SQLite) is a conformed-dimension
star schema with **one fact table per clinical event grain** — a
standard pattern for a healthcare data mart, since an encounter, a lab
result, and a claim are different grains of event that would otherwise
force awkward nulls into a single fact table.

**Dimensions** (shared/conformed across all three facts where applicable):

- `dim_patient` — one row per patient (deduplicated by MRN across all
  three sources)
- `dim_date` — standard date dimension (year/quarter/month/day/weekday)
- `dim_provider` — attending/ordering providers
- `dim_payer` — insurance payers
- `dim_diagnosis` — ICD-10 codes + descriptions
- `dim_procedure` — CPT codes + descriptions
- `dim_lab_test` — lab test codes, names, units

**Facts:**

- `fact_encounter` — one row per EHR visit (→ patient, date, diagnosis,
  provider)
- `fact_lab_result` — one row per lab test result (→ patient, date,
  test, provider, numeric result + reference range)
- `fact_claim` — one row per billing claim (→ patient, date, procedure,
  payer, charge amount, status)

All fact-to-dimension relationships are declared as SQL foreign keys and
indexed on every join column, so reporting queries (§5) run as simple,
indexed joins rather than full scans.

`etl_run_log` records each pipeline run's record counts and measured
accuracy, giving an audit trail across repeated runs.

---

## 4. Data quality validation

Validation runs **before** load, per source, with concrete rules:

| Source | Rules checked |
|---|---|
| EHR | patient MRN present; patient name present; visit date parses and is in range; diagnosis code matches ICD-10 format |
| Lab | sample ID present and unique (no duplicate sample IDs); patient reference present; collected date parses and is in range; result value is numeric and within a physically plausible range |
| Billing | claim ID present; patient reference present; service date parses and is in range; procedure code matches 5-digit CPT format; charge amount is numeric, positive, and within a plausible range |

A record that fails **any** rule is tagged with the specific failure
reason(s) and excluded from the relevant fact table (quarantined, not
silently coerced or silently dropped — the reasons are preserved in
`data/quality_report.json` for audit).

**Accuracy** is computed honestly from real validation outcomes:

```
accuracy_pct = records_passed / records_total * 100
```

computed per source and overall, and written to
`data/quality_report.json` and the console on every run. See the README
for the latest real measured run.

---

## 5. Example analytics / reporting queries

`etl/analytics_queries.py` ships runnable example queries demonstrating
that the warehouse is designed for efficient reporting — each is a
single indexed join, no raw-source joining required:

- **Top diagnoses** by encounter volume
- **Abnormal lab result rate** by test type
- **Revenue by payer** (claim count, total and average charge)
- **Monthly encounter volume** (time-series trend)
- **Patient 360** — per-patient rollup across encounters, labs, and
  claims in one query
- **Claim denial rate by procedure**

Run them with `python -m etl.analytics_queries` (or they run
automatically as the last step of `run_all.py`).

---

## 6. Running the pipeline

```bash
pip install -r requirements.txt
python run_all.py
```

This regenerates the simulated source files, re-runs extract/validate/
transform/load, and re-runs the example analytics queries, printing
real record counts and real accuracy at every stage.

## 7. Testing

```bash
pytest tests/ -v
```

`tests/test_pipeline.py` runs the real pipeline (no mocks) and asserts:
3+ distinct source schemas are present, 200+ samples are processed,
overall accuracy lands in a realistic band, injected issues are actually
caught by name, and the warehouse's dimensional integrity (no orphaned
fact rows, row counts match load stats) holds.

## 8. Extending the pipeline

- **Adding a fourth source**: write a new `extract_<source>()` function,
  a `validate_<source>_record()` rule set in `quality.py`, a
  `standardize_<source>()` function in `transform.py`, and a
  `load_<source>()` loader that resolves to existing dimensions
  (patient, date, provider, etc.) wherever possible — new dimensions
  only where the new source genuinely introduces a new entity.
- **Changing validation thresholds**: all rules live in
  `etl/quality.py` as plain Python functions; each returns a list of
  human-readable reason strings, which flow straight into the quality
  report with no extra plumbing required.
- **Querying the warehouse directly**: `data/warehouse.db` is a
  standard SQLite file; open it with any SQLite client
  (`sqlite3 data/warehouse.db`) or connect with any SQL/BI tool that
  supports SQLite.
