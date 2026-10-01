"""Example analytics/reporting queries demonstrating that the star schema
is efficient to query: every question here is answered with a single
indexed join across the fact and a small number of dimension tables,
no post-hoc joining across raw source files required.
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "warehouse.db"

QUERIES = {
    "top_diagnoses": """
        SELECT d.icd10_code, d.description, COUNT(*) AS encounter_count
        FROM fact_encounter f
        JOIN dim_diagnosis d ON d.diagnosis_key = f.diagnosis_key
        GROUP BY d.icd10_code, d.description
        ORDER BY encounter_count DESC
        LIMIT 5;
    """,
    "abnormal_lab_rate_by_test": """
        SELECT t.test_name,
               COUNT(*) AS total_results,
               SUM(CASE WHEN f.result_flag != 'NORMAL' THEN 1 ELSE 0 END) AS abnormal_results,
               ROUND(100.0 * SUM(CASE WHEN f.result_flag != 'NORMAL' THEN 1 ELSE 0 END) / COUNT(*), 1) AS abnormal_pct
        FROM fact_lab_result f
        JOIN dim_lab_test t ON t.test_key = f.test_key
        GROUP BY t.test_name
        ORDER BY abnormal_pct DESC;
    """,
    "revenue_by_payer": """
        SELECT p.payer_name,
               COUNT(*) AS claim_count,
               ROUND(SUM(f.charge_amount), 2) AS total_charges,
               ROUND(AVG(f.charge_amount), 2) AS avg_charge
        FROM fact_claim f
        JOIN dim_payer p ON p.payer_key = f.payer_key
        GROUP BY p.payer_name
        ORDER BY total_charges DESC;
    """,
    "monthly_encounter_volume": """
        SELECT dt.year, dt.month, COUNT(*) AS encounters
        FROM fact_encounter f
        JOIN dim_date dt ON dt.date_key = f.date_key
        GROUP BY dt.year, dt.month
        ORDER BY dt.year, dt.month;
    """,
    "patient_360_sample": """
        SELECT pt.mrn, pt.first_name, pt.last_name,
               (SELECT COUNT(*) FROM fact_encounter fe WHERE fe.patient_key = pt.patient_key) AS n_encounters,
               (SELECT COUNT(*) FROM fact_lab_result fl WHERE fl.patient_key = pt.patient_key) AS n_lab_results,
               (SELECT COUNT(*) FROM fact_claim fc WHERE fc.patient_key = pt.patient_key) AS n_claims,
               (SELECT ROUND(SUM(fc.charge_amount), 2) FROM fact_claim fc WHERE fc.patient_key = pt.patient_key) AS total_charges
        FROM dim_patient pt
        ORDER BY n_encounters + n_lab_results + n_claims DESC
        LIMIT 5;
    """,
    "claim_denial_rate_by_procedure": """
        SELECT pr.cpt_code, pr.description,
               COUNT(*) AS claims,
               SUM(CASE WHEN f.claim_status = 'Denied' THEN 1 ELSE 0 END) AS denied,
               ROUND(100.0 * SUM(CASE WHEN f.claim_status = 'Denied' THEN 1 ELSE 0 END) / COUNT(*), 1) AS denial_pct
        FROM fact_claim f
        JOIN dim_procedure pr ON pr.procedure_key = f.procedure_key
        GROUP BY pr.cpt_code, pr.description
        ORDER BY denial_pct DESC;
    """,
}


def run_all_queries(db_path=None, verbose=True):
    db_path = db_path or DB_PATH
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    results = {}
    try:
        for name, sql in QUERIES.items():
            rows = [dict(r) for r in conn.execute(sql).fetchall()]
            results[name] = rows
            if verbose:
                print(f"\n=== {name} ===")
                for r in rows:
                    print(r)
        return results
    finally:
        conn.close()


if __name__ == "__main__":
    run_all_queries()
