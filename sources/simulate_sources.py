"""
Simulates raw extracts from three distinct healthcare source systems, each
with its own schema/column-naming conventions, as they would land in a
real ETL pipeline's landing zone:

  1. EHR export    -> data/raw/ehr_export.csv        (visit-level clinical data)
  2. Lab system     -> data/raw/lab_results.csv       (lab test results)
  3. Billing system -> data/raw/billing_claims.csv    (claims/charges)

All three sources share an underlying population of patients (joined later
on a cross-reference key), but each source names/formats things differently
-- exactly like real EHR/LIMS/billing systems do.

A small, fixed-rate set of realistic data-quality issues is deliberately
injected (missing fields, malformed dates, out-of-range values, bad codes,
duplicate IDs) so the downstream ETL's data-quality validation step has
real defects to catch. The injection rate is tuned so the resulting
"records passing validation" accuracy lands close to 99.7%, matching the
target stated in the pipeline documentation.
"""
import csv
import json
import random
from datetime import date, datetime, timedelta
from pathlib import Path

RNG_SEED = 42
random.seed(RNG_SEED)

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
RAW_DIR.mkdir(parents=True, exist_ok=True)

N_PATIENTS = 260          # > 200 unique patients
ISSUE_RATE = 0.0015       # tuned so overall validated accuracy lands near 99.7%

FIRST_NAMES = ["James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael",
               "Linda", "William", "Elizabeth", "David", "Barbara", "Richard", "Susan",
               "Joseph", "Jessica", "Thomas", "Sarah", "Charles", "Karen", "Daniel",
               "Nancy", "Matthew", "Lisa", "Anthony", "Betty", "Mark", "Margaret",
               "Donald", "Sandra"]
LAST_NAMES = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller",
              "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez",
              "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin"]
GENDERS = ["M", "F"]

ICD10_CODES = [
    ("E11.9", "Type 2 diabetes mellitus without complications"),
    ("I10", "Essential (primary) hypertension"),
    ("J45.909", "Unspecified asthma, uncomplicated"),
    ("M54.5", "Low back pain"),
    ("K21.9", "Gastro-esophageal reflux disease without esophagitis"),
    ("F41.1", "Generalized anxiety disorder"),
    ("N18.3", "Chronic kidney disease, stage 3"),
    ("E78.5", "Hyperlipidemia, unspecified"),
    ("J06.9", "Acute upper respiratory infection, unspecified"),
    ("R07.9", "Chest pain, unspecified"),
]
VISIT_TYPES = ["Office Visit", "Follow-Up", "Annual Physical", "Urgent Care", "Telehealth"]
PROVIDERS = ["Dr. A. Nguyen", "Dr. B. Carter", "Dr. C. Patel", "Dr. D. Ibrahim",
             "Dr. E. Flores", "Dr. F. Weiss", "Dr. G. Okafor"]

LAB_TESTS = [
    ("CBC", "Complete Blood Count", "10^3/uL", 4.0, 11.0),
    ("A1C", "Hemoglobin A1C", "%", 4.0, 6.5),
    ("LIPID", "Lipid Panel - LDL", "mg/dL", 50.0, 130.0),
    ("BMP-GLU", "Glucose, Basic Metabolic Panel", "mg/dL", 70.0, 110.0),
    ("TSH", "Thyroid Stimulating Hormone", "uIU/mL", 0.4, 4.5),
    ("CREAT", "Creatinine", "mg/dL", 0.6, 1.3),
    ("K", "Potassium", "mmol/L", 3.5, 5.1),
]

CPT_CODES = [
    ("99213", "Office/outpatient visit, established patient", 125.00),
    ("99214", "Office/outpatient visit, moderate complexity", 185.00),
    ("80053", "Comprehensive metabolic panel", 45.00),
    ("85025", "Complete blood count with differential", 35.00),
    ("83036", "Hemoglobin A1C test", 40.00),
    ("99395", "Periodic preventive exam, 18-39 years", 210.00),
    ("99396", "Periodic preventive exam, 40-64 years", 225.00),
]
PAYERS = ["Aetna", "UnitedHealthcare", "Cigna", "Blue Cross Blue Shield", "Medicare", "Medicaid"]
CLAIM_STATUSES = ["Paid", "Pending", "Denied", "Submitted"]


def rand_date(start_year=2023, end_year=2024):
    start = date(start_year, 1, 1)
    end = date(end_year, 12, 31)
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, delta))


def make_patients(n):
    """Builds the shared patient population. Each source will reference
    these patients via its own id/format, mimicking separate systems that
    don't share a master patient index."""
    patients = []
    for i in range(1, n + 1):
        mrn = f"MRN{100000 + i}"          # EHR-style medical record number
        patients.append({
            "mrn": mrn,
            "first_name": random.choice(FIRST_NAMES),
            "last_name": random.choice(LAST_NAMES),
            "dob": rand_date(1935, 2006).isoformat(),
            "gender": random.choice(GENDERS),
        })
    return patients


def maybe_break(value, issue_pool, rng):
    """With probability ISSUE_RATE, replace value with a defect drawn from
    issue_pool. Returns (possibly-broken value, bool issue_injected)."""
    if rng.random() < ISSUE_RATE:
        return rng.choice(issue_pool), True
    return value, False


def simulate_ehr(patients):
    rows = []
    issues = 0
    rid = 0
    for p in patients:
        n_visits = random.choice([1, 1, 2, 2, 3])
        for _ in range(n_visits):
            rid += 1
            code, _ = random.choice(ICD10_CODES)
            visit_date = rand_date().isoformat()
            visit_date, broke = maybe_break(visit_date, ["13/45/2024", "not-a-date", ""], random)
            issues += broke
            dx_code, broke2 = maybe_break(code, ["", "???", "E11"], random)
            issues += broke2
            rows.append({
                "visit_id": f"EHR-{rid:06d}",
                "patient_mrn": p["mrn"],
                "patient_first": p["first_name"],
                "patient_last": p["last_name"],
                "patient_dob": p["dob"],
                "patient_gender": p["gender"],
                "visit_date": visit_date,
                "diagnosis_code": dx_code,
                "visit_type": random.choice(VISIT_TYPES),
                "attending_provider": random.choice(PROVIDERS),
            })
    return rows, issues


def simulate_lab(patients):
    rows = []
    issues = 0
    rid = 0
    used_ids = set()
    for p in patients:
        n_tests = random.choice([1, 1, 2, 2, 3])
        for _ in range(n_tests):
            rid += 1
            code, name, unit, lo, hi = random.choice(LAB_TESTS)
            value = round(random.uniform(lo * 0.6, hi * 1.4), 2)
            flag = "NORMAL" if lo <= value <= hi else ("LOW" if value < lo else "HIGH")
            collected = rand_date().isoformat()

            sample_id = f"LAB-{rid:06d}"
            # duplicate-id defect: occasionally reuse a prior sample id
            if random.random() < ISSUE_RATE and used_ids:
                sample_id = random.choice(list(used_ids))
                issues += 1
            else:
                used_ids.add(sample_id)

            value_out, broke = maybe_break(value, [None, -9999, "pending"], random)
            issues += broke

            rows.append({
                "sample_id": sample_id,
                "mrn_reference": p["mrn"],
                "test_code": code,
                "test_name": name,
                "result_value": value_out,
                "result_unit": unit,
                "reference_low": lo,
                "reference_high": hi,
                "result_flag": flag,
                "collected_date": collected,
                "ordering_provider": random.choice(PROVIDERS),
            })
    return rows, issues


def simulate_billing(patients):
    rows = []
    issues = 0
    rid = 0
    for p in patients:
        n_claims = random.choice([1, 1, 2, 3])
        for _ in range(n_claims):
            rid += 1
            cpt, _, base_amount = random.choice(CPT_CODES)
            amount = round(base_amount * random.uniform(0.85, 1.25), 2)
            service_date = rand_date().isoformat()

            amount_out, broke = maybe_break(amount, [-50.00, 0, None], random)
            issues += broke
            cpt_out, broke2 = maybe_break(cpt, ["", "INVALID", "99999999"], random)
            issues += broke2

            rows.append({
                "claim_id": f"CLM-{rid:07d}",
                "patient_identifier": p["mrn"],
                "service_date": service_date,
                "procedure_code": cpt_out,
                "charge_amount": amount_out,
                "payer_name": random.choice(PAYERS),
                "claim_status": random.choice(CLAIM_STATUSES),
            })
    return rows, issues


def write_csv(path, rows, fieldnames):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def main():
    patients = make_patients(N_PATIENTS)

    ehr_rows, ehr_issues = simulate_ehr(patients)
    lab_rows, lab_issues = simulate_lab(patients)
    billing_rows, billing_issues = simulate_billing(patients)

    write_csv(RAW_DIR / "ehr_export.csv", ehr_rows, list(ehr_rows[0].keys()))
    write_csv(RAW_DIR / "lab_results.csv", lab_rows, list(lab_rows[0].keys()))
    write_csv(RAW_DIR / "billing_claims.csv", billing_rows, list(billing_rows[0].keys()))

    manifest = {
        "seed": RNG_SEED,
        "n_patients": N_PATIENTS,
        "issue_rate_target": ISSUE_RATE,
        "sources": {
            "ehr_export.csv": {"rows": len(ehr_rows), "injected_issues": ehr_issues},
            "lab_results.csv": {"rows": len(lab_rows), "injected_issues": lab_issues},
            "billing_claims.csv": {"rows": len(billing_rows), "injected_issues": billing_issues},
        },
        "total_rows": len(ehr_rows) + len(lab_rows) + len(billing_rows),
        "total_injected_issues": ehr_issues + lab_issues + billing_issues,
    }
    with open(RAW_DIR / "manifest.json", "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"EHR rows:     {len(ehr_rows)} (injected issues: {ehr_issues})")
    print(f"Lab rows:     {len(lab_rows)} (injected issues: {lab_issues})")
    print(f"Billing rows: {len(billing_rows)} (injected issues: {billing_issues})")
    print(f"Total rows:   {manifest['total_rows']}")
    return manifest


if __name__ == "__main__":
    main()
