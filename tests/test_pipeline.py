"""Real, end-to-end pipeline tests. Each test runs against actual pipeline
output (simulated sources + validated/transformed/loaded warehouse), not
mocks -- a session-scoped fixture runs the full pipeline once and every
test asserts against its real artifacts (data/*.json, data/warehouse.db).
"""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from sources import simulate_sources
from etl import extract, quality, transform, load


@pytest.fixture(scope="session")
def pipeline_output(tmp_path_factory):
    simulate_sources.main()
    raw = extract.extract_all()
    validated, report = quality.run_validation(raw)
    standardized = transform.transform_all(validated)

    db_path = tmp_path_factory.mktemp("wh") / "warehouse_test.db"
    load_stats = load.load_all(standardized, report, db_path=db_path)

    return {
        "raw": raw,
        "report": report,
        "standardized": standardized,
        "load_stats": load_stats,
        "db_path": db_path,
    }


# ---------------- source simulation ----------------

def test_three_or_more_distinct_sources_present(pipeline_output):
    raw = pipeline_output["raw"]
    assert set(raw.keys()) >= {"ehr", "lab", "billing"}
    assert len(raw) >= 3
    for rows in raw.values():
        assert len(rows) > 0


def test_distinct_source_schemas(pipeline_output):
    """Each source must have genuinely different column names, not just
    different file names wrapping the same schema."""
    raw = pipeline_output["raw"]
    ehr_cols = set(raw["ehr"][0].keys())
    lab_cols = set(raw["lab"][0].keys())
    billing_cols = set(raw["billing"][0].keys())
    assert ehr_cols != lab_cols
    assert lab_cols != billing_cols
    assert ehr_cols != billing_cols


def test_200_plus_samples(pipeline_output):
    """200+ patient samples overall, and specifically 200+ lab test
    samples, as called for by the deliverable."""
    raw = pipeline_output["raw"]
    total_records = sum(len(rows) for rows in raw.values())
    assert total_records >= 200
    assert len(raw["lab"]) >= 200

    patients = pipeline_output["standardized"]["patients"]
    assert len(patients) >= 200


# ---------------- data quality validation ----------------

def test_accuracy_in_reasonable_band(pipeline_output):
    """Target accuracy is ~99.7% (a small, honest injected-issue rate).
    Allow a realistic band rather than an exact match since it depends on
    random injection."""
    accuracy = pipeline_output["report"]["overall_accuracy_pct"]
    assert 99.0 <= accuracy <= 100.0


def test_injected_issues_are_actually_caught(pipeline_output):
    """Sanity check that validation is real, not a no-op: at least one
    record across the sources must have failed, and failure reasons must
    be populated with real, specific rule names."""
    report = pipeline_output["report"]
    assert report["total_failed"] >= 1
    all_reasons = set()
    for src_stats in report["sources"].values():
        all_reasons.update(src_stats["failure_reasons"].keys())
    assert len(all_reasons) >= 1
    known_reasons = {
        "missing_patient_mrn", "missing_patient_name", "invalid_visit_date",
        "invalid_diagnosis_code", "missing_sample_id", "duplicate_sample_id",
        "missing_patient_reference", "invalid_collected_date",
        "result_value_out_of_range", "non_numeric_result_value",
        "missing_claim_id", "invalid_service_date", "invalid_procedure_code",
        "charge_amount_out_of_range", "non_numeric_charge_amount",
    }
    assert all_reasons <= known_reasons


def test_quality_report_internally_consistent(pipeline_output):
    report = pipeline_output["report"]
    assert report["total_passed"] + report["total_failed"] == report["total_records"]
    for stats in report["sources"].values():
        assert stats["passed"] + stats["failed"] == stats["total_records"]


# ---------------- warehouse / star schema ----------------

def test_warehouse_has_dims_and_facts(pipeline_output):
    conn = sqlite3.connect(pipeline_output["db_path"])
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()
    expected_dims = {"dim_patient", "dim_date", "dim_provider", "dim_payer",
                      "dim_diagnosis", "dim_procedure", "dim_lab_test"}
    expected_facts = {"fact_encounter", "fact_lab_result", "fact_claim"}
    assert expected_dims <= tables
    assert expected_facts <= tables


def test_warehouse_facts_reference_valid_dimension_keys(pipeline_output):
    conn = sqlite3.connect(pipeline_output["db_path"])
    orphans = conn.execute(
        "SELECT COUNT(*) FROM fact_encounter f "
        "LEFT JOIN dim_patient p ON p.patient_key = f.patient_key "
        "WHERE p.patient_key IS NULL"
    ).fetchone()[0]
    conn.close()
    assert orphans == 0


def test_warehouse_row_counts_match_load_stats(pipeline_output):
    conn = sqlite3.connect(pipeline_output["db_path"])
    n_patients = conn.execute("SELECT COUNT(*) FROM dim_patient").fetchone()[0]
    n_encounters = conn.execute("SELECT COUNT(*) FROM fact_encounter").fetchone()[0]
    n_labs = conn.execute("SELECT COUNT(*) FROM fact_lab_result").fetchone()[0]
    n_claims = conn.execute("SELECT COUNT(*) FROM fact_claim").fetchone()[0]
    conn.close()

    stats = pipeline_output["load_stats"]
    assert n_patients == stats["patients_loaded"]
    assert n_encounters == stats["encounters_loaded"]
    assert n_labs == stats["lab_results_loaded"]
    assert n_claims == stats["claims_loaded"]


def test_analytics_query_runs_and_returns_rows(pipeline_output):
    conn = sqlite3.connect(pipeline_output["db_path"])
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT d.icd10_code, COUNT(*) AS n
        FROM fact_encounter f JOIN dim_diagnosis d ON d.diagnosis_key = f.diagnosis_key
        GROUP BY d.icd10_code ORDER BY n DESC LIMIT 5
    """).fetchall()
    conn.close()
    assert len(rows) > 0
    assert rows[0]["n"] > 0
