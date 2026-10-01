"""Load step: loads standardized dimension and fact records into the
SQLite analytics warehouse, generating surrogate keys and resolving
natural keys (mrn, date, provider name, etc.) to dimension surrogate
keys along the way -- the standard dimensional-load pattern.
"""
import sqlite3
from datetime import date as date_cls
from pathlib import Path

from etl.warehouse_schema import create_schema

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "warehouse.db"


def _date_key(d: date_cls) -> int:
    return int(d.strftime("%Y%m%d"))


def get_or_create_date(conn, d: date_cls):
    key = _date_key(d)
    cur = conn.execute("SELECT date_key FROM dim_date WHERE date_key = ?", (key,))
    if cur.fetchone():
        return key
    conn.execute(
        "INSERT INTO dim_date (date_key, full_date, year, quarter, month, day, day_of_week) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (key, d.isoformat(), d.year, (d.month - 1) // 3 + 1, d.month, d.day, d.strftime("%A")),
    )
    return key


def get_or_create(conn, table, key_col, natural_col, natural_value, extra_cols=None):
    """Generic get-or-create for simple lookup dimensions keyed by one
    unique natural column, optionally inserting extra columns on create."""
    if natural_value is None:
        return None
    cur = conn.execute(f"SELECT {key_col} FROM {table} WHERE {natural_col} = ?", (natural_value,))
    row = cur.fetchone()
    if row:
        return row[0]
    extra_cols = extra_cols or {}
    cols = [natural_col] + list(extra_cols.keys())
    vals = [natural_value] + list(extra_cols.values())
    placeholders = ",".join(["?"] * len(vals))
    cur = conn.execute(f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders})", vals)
    return cur.lastrowid


def load_patients(conn, patients):
    patient_key_by_mrn = {}
    for p in patients:
        cur = conn.execute("SELECT patient_key FROM dim_patient WHERE mrn = ?", (p["mrn"],))
        row = cur.fetchone()
        if row:
            patient_key_by_mrn[p["mrn"]] = row[0]
            continue
        cur = conn.execute(
            "INSERT INTO dim_patient (mrn, first_name, last_name, dob, gender) VALUES (?, ?, ?, ?, ?)",
            (p["mrn"], p["first_name"], p["last_name"], p["dob"], p["gender"]),
        )
        patient_key_by_mrn[p["mrn"]] = cur.lastrowid
    return patient_key_by_mrn


def load_encounters(conn, encounters, patient_key_by_mrn):
    loaded = 0
    for e in encounters:
        patient_key = patient_key_by_mrn.get(e["patient_mrn"])
        if patient_key is None or e["visit_date"] is None:
            continue
        date_key = get_or_create_date(conn, e["visit_date"])
        diagnosis_key = get_or_create(
            conn, "dim_diagnosis", "diagnosis_key", "icd10_code", e["diagnosis_code"],
            {"description": e["diagnosis_description"]},
        )
        provider_key = get_or_create(conn, "dim_provider", "provider_key", "provider_name", e["provider_name"])
        try:
            conn.execute(
                "INSERT OR IGNORE INTO fact_encounter "
                "(visit_id, patient_key, date_key, diagnosis_key, provider_key, visit_type, source_system) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (e["visit_id"], patient_key, date_key, diagnosis_key, provider_key,
                 e["visit_type"], e["source_system"]),
            )
            loaded += 1
        except sqlite3.IntegrityError:
            continue
    return loaded


def load_lab_results(conn, lab_results, patient_key_by_mrn):
    loaded = 0
    for r in lab_results:
        patient_key = patient_key_by_mrn.get(r["patient_mrn"])
        if patient_key is None or r["collected_date"] is None:
            continue
        date_key = get_or_create_date(conn, r["collected_date"])
        test_key = get_or_create(
            conn, "dim_lab_test", "test_key", "test_code", r["test_code"],
            {"test_name": r["test_name"], "result_unit": r["result_unit"]},
        )
        provider_key = get_or_create(conn, "dim_provider", "provider_key", "provider_name", r["provider_name"])
        try:
            conn.execute(
                "INSERT OR IGNORE INTO fact_lab_result "
                "(sample_id, patient_key, date_key, test_key, provider_key, result_value, "
                "reference_low, reference_high, result_flag, source_system) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (r["sample_id"], patient_key, date_key, test_key, provider_key, r["result_value"],
                 r["reference_low"], r["reference_high"], r["result_flag"], r["source_system"]),
            )
            loaded += 1
        except sqlite3.IntegrityError:
            continue
    return loaded


def load_claims(conn, claims, patient_key_by_mrn):
    loaded = 0
    for c in claims:
        patient_key = patient_key_by_mrn.get(c["patient_mrn"])
        if patient_key is None or c["service_date"] is None:
            continue
        date_key = get_or_create_date(conn, c["service_date"])
        procedure_key = get_or_create(
            conn, "dim_procedure", "procedure_key", "cpt_code", c["procedure_code"],
            {"description": c["procedure_description"]},
        )
        payer_key = get_or_create(conn, "dim_payer", "payer_key", "payer_name", c["payer_name"])
        try:
            conn.execute(
                "INSERT OR IGNORE INTO fact_claim "
                "(claim_id, patient_key, date_key, procedure_key, payer_key, charge_amount, "
                "claim_status, source_system) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (c["claim_id"], patient_key, date_key, procedure_key, payer_key,
                 c["charge_amount"], c["claim_status"], c["source_system"]),
            )
            loaded += 1
        except sqlite3.IntegrityError:
            continue
    return loaded


def log_run(conn, report):
    import datetime as dt
    conn.execute(
        "INSERT INTO etl_run_log (run_timestamp, total_records, passed_records, failed_records, accuracy_pct) "
        "VALUES (?, ?, ?, ?, ?)",
        (dt.datetime.now().isoformat(timespec="seconds"), report["total_records"],
         report["total_passed"], report["total_failed"], report["overall_accuracy_pct"]),
    )


def load_all(transformed, quality_report, db_path=None):
    db_path = db_path or DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        create_schema(conn)
        patient_key_by_mrn = load_patients(conn, transformed["patients"])
        n_encounters = load_encounters(conn, transformed["encounters"], patient_key_by_mrn)
        n_labs = load_lab_results(conn, transformed["lab_results"], patient_key_by_mrn)
        n_claims = load_claims(conn, transformed["claims"], patient_key_by_mrn)
        log_run(conn, quality_report)
        conn.commit()
        return {
            "patients_loaded": len(patient_key_by_mrn),
            "encounters_loaded": n_encounters,
            "lab_results_loaded": n_labs,
            "claims_loaded": n_claims,
        }
    finally:
        conn.close()
