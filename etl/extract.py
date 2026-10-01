"""Extract step: per-source parsers that read each raw source file exactly
as that system exports it (own column names, own id conventions) and hand
back plain list-of-dict records for the transform step."""
import csv
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"


def _read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def extract_ehr():
    """EHR export: visit-level clinical records, keyed by patient_mrn."""
    return _read_csv(RAW_DIR / "ehr_export.csv")


def extract_lab():
    """Lab system export: individual lab test results, keyed by sample_id
    and mrn_reference."""
    return _read_csv(RAW_DIR / "lab_results.csv")


def extract_billing():
    """Billing system export: claim-level charges, keyed by claim_id and
    patient_identifier."""
    return _read_csv(RAW_DIR / "billing_claims.csv")


def extract_all():
    return {
        "ehr": extract_ehr(),
        "lab": extract_lab(),
        "billing": extract_billing(),
    }
