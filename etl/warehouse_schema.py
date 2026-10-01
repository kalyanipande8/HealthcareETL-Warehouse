"""Defines and creates the analytics-ready SQLite data warehouse schema:
a star schema with shared conformed dimensions (patient, date, provider,
payer, diagnosis, procedure, lab test) and three fact tables, one per
clinical event grain (encounter, lab result, claim) -- a standard
multi-fact-table star schema for a healthcare data mart, optimized for
querying/reporting (indexed foreign keys, pre-joined descriptive attributes
on dimensions).
"""
import sqlite3

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

-- ============ DIMENSIONS ============

CREATE TABLE IF NOT EXISTS dim_patient (
    patient_key   INTEGER PRIMARY KEY AUTOINCREMENT,
    mrn           TEXT UNIQUE NOT NULL,
    first_name    TEXT,
    last_name     TEXT,
    dob           TEXT,
    gender        TEXT
);

CREATE TABLE IF NOT EXISTS dim_date (
    date_key      INTEGER PRIMARY KEY,   -- YYYYMMDD
    full_date     TEXT UNIQUE NOT NULL,
    year          INTEGER NOT NULL,
    quarter       INTEGER NOT NULL,
    month         INTEGER NOT NULL,
    day           INTEGER NOT NULL,
    day_of_week   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_provider (
    provider_key  INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_payer (
    payer_key     INTEGER PRIMARY KEY AUTOINCREMENT,
    payer_name    TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS dim_diagnosis (
    diagnosis_key INTEGER PRIMARY KEY AUTOINCREMENT,
    icd10_code    TEXT UNIQUE NOT NULL,
    description   TEXT
);

CREATE TABLE IF NOT EXISTS dim_procedure (
    procedure_key INTEGER PRIMARY KEY AUTOINCREMENT,
    cpt_code      TEXT UNIQUE NOT NULL,
    description   TEXT
);

CREATE TABLE IF NOT EXISTS dim_lab_test (
    test_key      INTEGER PRIMARY KEY AUTOINCREMENT,
    test_code     TEXT UNIQUE NOT NULL,
    test_name     TEXT,
    result_unit   TEXT
);

-- ============ FACTS ============

CREATE TABLE IF NOT EXISTS fact_encounter (
    encounter_key   INTEGER PRIMARY KEY AUTOINCREMENT,
    visit_id        TEXT UNIQUE NOT NULL,
    patient_key     INTEGER NOT NULL REFERENCES dim_patient(patient_key),
    date_key        INTEGER NOT NULL REFERENCES dim_date(date_key),
    diagnosis_key   INTEGER REFERENCES dim_diagnosis(diagnosis_key),
    provider_key    INTEGER REFERENCES dim_provider(provider_key),
    visit_type      TEXT,
    source_system   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fact_encounter_patient ON fact_encounter(patient_key);
CREATE INDEX IF NOT EXISTS idx_fact_encounter_date ON fact_encounter(date_key);

CREATE TABLE IF NOT EXISTS fact_lab_result (
    lab_result_key  INTEGER PRIMARY KEY AUTOINCREMENT,
    sample_id       TEXT UNIQUE NOT NULL,
    patient_key     INTEGER NOT NULL REFERENCES dim_patient(patient_key),
    date_key        INTEGER NOT NULL REFERENCES dim_date(date_key),
    test_key        INTEGER NOT NULL REFERENCES dim_lab_test(test_key),
    provider_key    INTEGER REFERENCES dim_provider(provider_key),
    result_value    REAL NOT NULL,
    reference_low   REAL,
    reference_high  REAL,
    result_flag     TEXT,
    source_system   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fact_lab_patient ON fact_lab_result(patient_key);
CREATE INDEX IF NOT EXISTS idx_fact_lab_date ON fact_lab_result(date_key);
CREATE INDEX IF NOT EXISTS idx_fact_lab_test ON fact_lab_result(test_key);

CREATE TABLE IF NOT EXISTS fact_claim (
    claim_key       INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id        TEXT UNIQUE NOT NULL,
    patient_key     INTEGER NOT NULL REFERENCES dim_patient(patient_key),
    date_key        INTEGER NOT NULL REFERENCES dim_date(date_key),
    procedure_key   INTEGER REFERENCES dim_procedure(procedure_key),
    payer_key       INTEGER REFERENCES dim_payer(payer_key),
    charge_amount   REAL NOT NULL,
    claim_status    TEXT,
    source_system   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fact_claim_patient ON fact_claim(patient_key);
CREATE INDEX IF NOT EXISTS idx_fact_claim_date ON fact_claim(date_key);
CREATE INDEX IF NOT EXISTS idx_fact_claim_payer ON fact_claim(payer_key);

-- ============ METADATA ============

CREATE TABLE IF NOT EXISTS etl_run_log (
    run_key         INTEGER PRIMARY KEY AUTOINCREMENT,
    run_timestamp   TEXT NOT NULL,
    total_records   INTEGER,
    passed_records  INTEGER,
    failed_records  INTEGER,
    accuracy_pct    REAL
);
"""


def create_schema(conn: sqlite3.Connection):
    conn.executescript(SCHEMA_SQL)
    conn.commit()
