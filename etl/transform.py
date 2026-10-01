"""Transform step: standardizes validated records from all three source
schemas into a common, warehouse-ready vocabulary (shared column names,
shared types, shared reference/lookup values), independent of which
source system they came from.

Only records that passed data-quality validation (`_valid`) are carried
into the standardized fact-ready collections; dimension data (e.g. a
patient's demographics) is still standardized from any source that has
it, since a patient record itself is independently usable even if, say,
one of their lab results failed validation.
"""
from datetime import datetime

# Reference/lookup tables a real pipeline would pull from a coding-system
# master (ICD-10-CM, CPT) rather than from the noisy source extract itself.
ICD10_DESCRIPTIONS = {
    "E11.9": "Type 2 diabetes mellitus without complications",
    "I10": "Essential (primary) hypertension",
    "J45.909": "Unspecified asthma, uncomplicated",
    "M54.5": "Low back pain",
    "K21.9": "Gastro-esophageal reflux disease without esophagitis",
    "F41.1": "Generalized anxiety disorder",
    "N18.3": "Chronic kidney disease, stage 3",
    "E78.5": "Hyperlipidemia, unspecified",
    "J06.9": "Acute upper respiratory infection, unspecified",
    "R07.9": "Chest pain, unspecified",
}
CPT_DESCRIPTIONS = {
    "99213": "Office/outpatient visit, established patient",
    "99214": "Office/outpatient visit, moderate complexity",
    "80053": "Comprehensive metabolic panel",
    "85025": "Complete blood count with differential",
    "83036": "Hemoglobin A1C test",
    "99395": "Periodic preventive exam, 18-39 years",
    "99396": "Periodic preventive exam, 40-64 years",
}


def _parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def standardize_patients(validated):
    """Builds a deduplicated patient master from every source that carries
    patient identity, keyed by MRN (the one id that recurs across EHR and
    lab, and that billing's patient_identifier also happens to carry)."""
    patients = {}
    for row in validated["ehr"]:
        mrn = row.get("patient_mrn")
        if not mrn or mrn in patients:
            continue
        if row.get("patient_first") and row.get("patient_last"):
            patients[mrn] = {
                "mrn": mrn,
                "first_name": row["patient_first"],
                "last_name": row["patient_last"],
                "dob": row.get("patient_dob"),
                "gender": row.get("patient_gender"),
            }
    # fall back to lab/billing references for any patient not seen in EHR
    for row in validated["lab"]:
        mrn = row.get("mrn_reference")
        if mrn and mrn not in patients:
            patients[mrn] = {"mrn": mrn, "first_name": None, "last_name": None,
                              "dob": None, "gender": None}
    for row in validated["billing"]:
        mrn = row.get("patient_identifier")
        if mrn and mrn not in patients:
            patients[mrn] = {"mrn": mrn, "first_name": None, "last_name": None,
                              "dob": None, "gender": None}
    return list(patients.values())


def standardize_encounters(validated):
    out = []
    for row in validated["ehr"]:
        if not row["_valid"]:
            continue
        out.append({
            "visit_id": row["visit_id"],
            "patient_mrn": row["patient_mrn"],
            "visit_date": _parse_date(row["visit_date"]),
            "diagnosis_code": row["diagnosis_code"].strip(),
            "diagnosis_description": ICD10_DESCRIPTIONS.get(row["diagnosis_code"].strip(), "Unknown"),
            "visit_type": row.get("visit_type"),
            "provider_name": row.get("attending_provider"),
            "source_system": "EHR",
        })
    return out


def standardize_lab_results(validated):
    out = []
    for row in validated["lab"]:
        if not row["_valid"]:
            continue
        value = float(row["result_value"])
        out.append({
            "sample_id": row["sample_id"],
            "patient_mrn": row["mrn_reference"],
            "test_code": row["test_code"],
            "test_name": row["test_name"],
            "result_value": value,
            "result_unit": row.get("result_unit"),
            "reference_low": float(row["reference_low"]) if row.get("reference_low") not in (None, "") else None,
            "reference_high": float(row["reference_high"]) if row.get("reference_high") not in (None, "") else None,
            "result_flag": row.get("result_flag"),
            "collected_date": _parse_date(row["collected_date"]),
            "provider_name": row.get("ordering_provider"),
            "source_system": "LAB",
        })
    return out


def standardize_claims(validated):
    out = []
    for row in validated["billing"]:
        if not row["_valid"]:
            continue
        code = row["procedure_code"].strip()
        out.append({
            "claim_id": row["claim_id"],
            "patient_mrn": row["patient_identifier"],
            "service_date": _parse_date(row["service_date"]),
            "procedure_code": code,
            "procedure_description": CPT_DESCRIPTIONS.get(code, "Unknown"),
            "charge_amount": float(row["charge_amount"]),
            "payer_name": row.get("payer_name"),
            "claim_status": row.get("claim_status"),
            "source_system": "BILLING",
        })
    return out


def transform_all(validated):
    return {
        "patients": standardize_patients(validated),
        "encounters": standardize_encounters(validated),
        "lab_results": standardize_lab_results(validated),
        "claims": standardize_claims(validated),
    }
