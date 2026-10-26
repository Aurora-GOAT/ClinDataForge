"""Allowlisted aggregate audit of a previously processed public demo derivative.

Never export source identifiers, arbitrary category strings, or patient records.
This does not establish the provenance or licensing of an arbitrary input file.
"""
from __future__ import annotations
import collections
import math
from .pipeline import load_jsonl

MEASUREMENT_FIELDS = ("acuity", "dbp", "heartrate", "o2sat", "resprate", "sbp", "temperature")
DIAGNOSIS_SYSTEMS = frozenset(("ICD-10-CM", "ICD-9-CM"))
FLAG_CATEGORIES = frozenset(("blood_pressure_order", "broad_range_flag", "pain_outside_numeric_0_10"))
COMPLAINT_TAGS = frozenset(("cardiorespiratory", "gastrointestinal", "metabolic", "neurologic", "trauma", "unclassified"))
TEMPERATURE_UNITS = {"degF": "F", "°F": "F", "F": "F", "degC": "C", "°C": "C", "C": "C"}


def _category(value, allowed):
    return value if isinstance(value, str) and value in allowed else "OTHER"


def _identifier(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    return str(value).strip() or None


def _finite(value):
    if isinstance(value, bool):
        raise ValueError("Boolean is not a measurement")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite measurement")
    return number


def audit_public_structured(path):
    """Return only fixed keys and allowlisted categories; reject invalid structures."""
    rows = 0
    patients, stays = set(), set()
    duplicate_stays = missing_subjects = missing_stays = 0
    diagnosis_rows = diagnosed_stays = seq_unparsable = 0
    diagnosis_systems, flags, complaint_tags = (collections.Counter() for _ in range(3))
    missing = collections.Counter()
    invalid = collections.Counter()
    unknown_measurement_keys = 0
    temp_pairs = temp_mismatches = temp_invalid = temp_unknown_units = 0
    temp_error_sum = 0.0
    for record in load_jsonl(path):
        if not isinstance(record, dict):
            raise ValueError("Public aggregate input rows must be objects")
        measurements = record.get("measurements", {})
        diagnoses = record.get("diagnoses", [])
        record_flags = record.get("flags", [])
        tags = record.get("chiefcomplaint_search_tags_not_diagnoses", [])
        if (not isinstance(measurements, dict) or not isinstance(diagnoses, list)
                or not isinstance(record_flags, list) or not isinstance(tags, list)
                or any(not isinstance(d, dict) for d in diagnoses)):
            raise ValueError("Invalid public aggregate input structure")
        rows += 1
        subject = _identifier(record.get("subject_id"))
        stay = _identifier(record.get("stay_id"))
        if subject is None:
            missing_subjects += 1
        else:
            patients.add(subject)
        if stay is None:
            missing_stays += 1
        else:
            duplicate_stays += stay in stays
            stays.add(stay)
        diagnosed_stays += bool(diagnoses)
        diagnosis_rows += len(diagnoses)
        for diagnosis in diagnoses:
            diagnosis_systems[_category(diagnosis.get("system"), DIAGNOSIS_SYSTEMS)] += 1
            seq = diagnosis.get("seq_num")
            try:
                if isinstance(seq, bool) or not isinstance(seq, (str, int)):
                    raise ValueError("Invalid sequence")
                int(seq)
            except (TypeError, ValueError):
                seq_unparsable += 1
        for flag in record_flags:
            value = flag.get("issue") if isinstance(flag, dict) else flag
            flags[_category(value, FLAG_CATEGORIES)] += 1
        for tag in tags:
            complaint_tags[_category(tag, COMPLAINT_TAGS)] += 1
        unknown_measurement_keys += sum(field not in MEASUREMENT_FIELDS for field in measurements)
        for field in MEASUREMENT_FIELDS:
            obj = measurements.get(field)
            if not isinstance(obj, dict) or obj.get("value") is None:
                missing[field] += 1
            else:
                try:
                    _finite(obj["value"])
                except (ValueError, TypeError, OverflowError):
                    invalid[field] += 1
        temperature = measurements.get("temperature")
        actual = record.get("temperature_celsius_derived")
        if isinstance(temperature, dict) and temperature.get("value") is not None and actual is not None:
            unit = temperature.get("unit")
            normalized_unit = TEMPERATURE_UNITS.get(unit) if isinstance(unit, str) else None
            if normalized_unit is None:
                temp_unknown_units += 1
                continue
            try:
                source = _finite(temperature["value"])
                expected = (source - 32) * 5 / 9 if normalized_unit == "F" else source
                error = abs(expected - _finite(actual))
                if not math.isfinite(error):
                    raise ValueError("Non-finite conversion")
            except (TypeError, ValueError, OverflowError):
                temp_invalid += 1
                continue
            temp_pairs += 1
            temp_error_sum += error
            if not math.isfinite(temp_error_sum):
                raise ValueError("Temperature aggregate exceeds finite numeric range")
            temp_mismatches += error > 0.011
    return {
        "provenance": "User-provided previously processed MIMIC-IV-ED public demo derived JSONL; identity not established by this function",
        "rows": rows, "unique_subject_ids": len(patients), "unique_stay_ids": len(stays),
        "missing_subject_id_rows": missing_subjects, "missing_stay_id_rows": missing_stays,
        "duplicate_stay_ids": duplicate_stays,
        "diagnosis_links": diagnosis_rows, "stays_with_diagnoses": diagnosed_stays,
        "stays_without_diagnoses": rows - diagnosed_stays,
        "diagnosis_record_coverage": round(diagnosed_stays / rows, 4) if rows else None,
        "diagnosis_code_system_counts": dict(sorted(diagnosis_systems.items())),
        "diagnosis_seq_unparsable": seq_unparsable,
        "missing_measurements": {field: {"count": missing[field], "rate": round(missing[field] / rows, 4)} for field in MEASUREMENT_FIELDS} if rows else {},
        "invalid_measurements": {field: {"count": invalid[field], "rate": round(invalid[field] / rows, 4)} for field in MEASUREMENT_FIELDS} if rows else {},
        "unknown_measurement_key_occurrences": unknown_measurement_keys,
        "temperature_f_to_c": {"paired_records": temp_pairs,
            "mean_absolute_error_in_c": round(temp_error_sum / temp_pairs, 5) if temp_pairs else None,
            "mismatch_over_0_011_c": temp_mismatches, "invalid_numeric_pairs": temp_invalid,
            "unsupported_unit_pairs": temp_unknown_units},
        "complaint_search_tag_counts": dict(sorted(complaint_tags.items())),
        "flag_counts": dict(sorted(flags.items())), "no_patient_level_data_exported": True,
        "limits": ["Counts reflect a prior processed file, not raw PhysioNet re-download.",
            "Complaint tags and flags are counted from source metadata, not independently diagnosed or recomputed.",
            "Missing means absent/non-object/null; invalid counts present non-numeric, boolean or non-finite values separately.",
            "Unknown categories are aggregated as OTHER; no arbitrary source strings are exported.",
            "Do not generalize to all MIMIC patients or hospitals."]}
