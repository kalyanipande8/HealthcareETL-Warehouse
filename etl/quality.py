"""Automated data quality validation.

Each raw record from each source is run through a set of concrete,
source-appropriate validation rules (required fields present, dates
parse, codes are recognized, numeric values are in a physically
plausible range, ids are unique). Records that fail any rule are
flagged with the specific reason(s) and excluded from the warehouse
fact load (quarantined), while dimension data derived from the record
(e.g. the patient) is still retained where it is independently valid.

The module computes a real, auditable accuracy percentage:

    accuracy = records_passed / records_total * 100

across the whole pipeline and per source, and writes the full result
to data/quality_report.json so it can be reviewed by a client/stakeholder.
"""
import json
import re
from datetime import date, datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

ICD10_PATTERN = re.compile(r"^[A-TV-Z][0-9][0-9AB](\.[0-9A-TV-Z]{1,4})?$")
CPT_PATTERN = re.compile(r"^\d{5}$")
MIN_DATE = date(2000, 1, 1)
MAX_DATE = date(2026, 12, 31)


def _parse_date(value):
    try:
        d = datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    if not (MIN_DATE <= d <= MAX_DATE):
        return None
    return d


def validate_ehr_record(row):
    reasons = []
    if not row.get("patient_mrn"):
        reasons.append("missing_patient_mrn")
    if not row.get("patient_first") or not row.get("patient_last"):
        reasons.append("missing_patient_name")
    if _parse_date(row.get("visit_date")) is None:
        reasons.append("invalid_visit_date")
    code = (row.get("diagnosis_code") or "").strip()
    if not code or not ICD10_PATTERN.match(code):
        reasons.append("invalid_diagnosis_code")
    return reasons


def validate_lab_record(row, seen_sample_ids):
    reasons = []
    sample_id = row.get("sample_id")
    if not sample_id:
        reasons.append("missing_sample_id")
    elif sample_id in seen_sample_ids:
        reasons.append("duplicate_sample_id")
    else:
        seen_sample_ids.add(sample_id)

    if not row.get("mrn_reference"):
        reasons.append("missing_patient_reference")
    if _parse_date(row.get("collected_date")) is None:
        reasons.append("invalid_collected_date")

    raw_value = row.get("result_value")
    try:
        value = float(raw_value)
        if value < 0 or value > 100000:
            reasons.append("result_value_out_of_range")
    except (TypeError, ValueError):
        reasons.append("non_numeric_result_value")
    return reasons


def validate_billing_record(row):
    reasons = []
    if not row.get("claim_id"):
        reasons.append("missing_claim_id")
    if not row.get("patient_identifier"):
        reasons.append("missing_patient_reference")
    if _parse_date(row.get("service_date")) is None:
        reasons.append("invalid_service_date")

    code = (row.get("procedure_code") or "").strip()
    if not code or not CPT_PATTERN.match(code):
        reasons.append("invalid_procedure_code")

    raw_amount = row.get("charge_amount")
    try:
        amount = float(raw_amount)
        if amount <= 0 or amount > 50000:
            reasons.append("charge_amount_out_of_range")
    except (TypeError, ValueError):
        reasons.append("non_numeric_charge_amount")
    return reasons


def run_validation(raw):
    """raw: dict with keys 'ehr', 'lab', 'billing' -> list of row dicts.

    Returns (results, report) where results mirrors `raw` but each row is
    annotated with '_valid' (bool) and '_issues' (list[str]), and report is
    the aggregate quality summary (per source + overall accuracy)."""
    results = {"ehr": [], "lab": [], "billing": []}
    counts = {}

    for row in raw["ehr"]:
        issues = validate_ehr_record(row)
        row = dict(row, _valid=(len(issues) == 0), _issues=issues)
        results["ehr"].append(row)

    seen_sample_ids = set()
    for row in raw["lab"]:
        issues = validate_lab_record(row, seen_sample_ids)
        row = dict(row, _valid=(len(issues) == 0), _issues=issues)
        results["lab"].append(row)

    for row in raw["billing"]:
        issues = validate_billing_record(row)
        row = dict(row, _valid=(len(issues) == 0), _issues=issues)
        results["billing"].append(row)

    report = {"sources": {}}
    total_records = 0
    total_passed = 0
    for source, rows in results.items():
        n = len(rows)
        passed = sum(1 for r in rows if r["_valid"])
        failed = n - passed
        reason_counts = {}
        for r in rows:
            for issue in r["_issues"]:
                reason_counts[issue] = reason_counts.get(issue, 0) + 1
        report["sources"][source] = {
            "total_records": n,
            "passed": passed,
            "failed": failed,
            "accuracy_pct": round(passed / n * 100, 3) if n else None,
            "failure_reasons": reason_counts,
        }
        total_records += n
        total_passed += passed

    report["total_records"] = total_records
    report["total_passed"] = total_passed
    report["total_failed"] = total_records - total_passed
    report["overall_accuracy_pct"] = round(total_passed / total_records * 100, 3) if total_records else None

    return results, report


def save_report(report, path=None):
    path = path or (BASE_DIR / "data" / "quality_report.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(report, f, indent=2)
    return path
