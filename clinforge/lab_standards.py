"""Independent laboratory unit conversion and reference-band checks.

Why this module exists
----------------------
The generator (`clinforge/synthgen.py`) and the validator
(`scripts/validate_synth.py`) both import `REFERENCE_INTERVALS` from
`clinforge/hpo_knowledge.py`.  They therefore share the same conversion factors
and the same bands: if a factor or an interval were wrong, both would be wrong
in the same direction and validation would still pass.  That is a circular
check at the constant level.

This module is a **second, independent path**:

* conversion factors are derived from molar masses built from CIAAW standard
  atomic weights, not from `REFERENCE_INTERVALS`;
* `g/dL -> g/L` is the SI prefix definition, not a table lookup;
* ALT/AST are catalytic activity concentrations (U/L) with no mass conversion;
* the reference bands below are *demo* bands, independently transcribed for
  cross-checking only.  They are **not** a clinical standard and must not be
  cited as one.

Nothing here changes the gold labels.  It can be used to audit them.

Sources: `data/external/lab_standards_sources.json`.
"""
from __future__ import annotations

# CIAAW abridged standard atomic weights (2021).  Values are the conventional
# abridged weights, sufficient for four-significant-figure clinical conversions.
ATOMIC_WEIGHTS = {
    'C': 12.011,
    'H': 1.008,
    'N': 14.007,
    'O': 15.999,
}

# Molecular formulas of the two analytes that need a molar-mass conversion.
MOLECULAR_FORMULAS = {
    'GLUCOSE': {'C': 6, 'H': 12, 'O': 6},      # C6H12O6
    'CREATININE': {'C': 4, 'H': 7, 'N': 3, 'O': 1},  # C4H7N3O
}


def molar_mass(analyte: str) -> float:
    formula = MOLECULAR_FORMULAS[analyte]
    return sum(ATOMIC_WEIGHTS[element] * count for element, count in formula.items())


# Conversion factors to the project's standard units.
#   glucose    mg/dL -> mmol/L : (mg/dL * 10 mg/L) / (g/mol) = / 18.0156
#   creatinine mg/dL -> umol/L : (mg/dL * 10) / 113.120 * 1000 = * 88.402
#   hemoglobin g/dL  -> g/L    : * 10   (SI prefix, no molar mass)
FACTORS = {
    'GLUCOSE': {'from': 'mg/dL', 'to': 'mmol/L', 'factor': 10.0 / molar_mass('GLUCOSE')},
    'CREATININE': {'from': 'mg/dL', 'to': 'umol/L', 'factor': 10.0 / molar_mass('CREATININE') * 1000.0},
    'HGB': {'from': 'g/dL', 'to': 'g/L', 'factor': 10.0},
    'ALT': {'from': 'U/L', 'to': 'U/L', 'factor': 1.0},
    'AST': {'from': 'U/L', 'to': 'U/L', 'factor': 1.0},
}

STANDARD_UNITS = {
    'GLUCOSE': 'mmol/L',
    'CREATININE': 'umol/L',
    'HGB': 'g/L',
    'ALT': 'U/L',
    'AST': 'U/L',
}

# Demo reference bands, SI units.  Independently transcribed; NOT clinical
# standards.  A real laboratory interval is method- and population-specific.
BANDS = {
    'ALT': {'lo': 7.0, 'hi': 40.0, 'unit': 'U/L'},
    'AST': {'lo': 8.0, 'hi': 40.0, 'unit': 'U/L'},
    'GLUCOSE': {'lo': 3.9, 'hi': 6.1, 'unit': 'mmol/L'},
    'HGB': {'lo': 115.0, 'hi': 175.0, 'unit': 'g/L'},
}

BAND_STATUS = 'demo values for pipeline testing; not a clinical reference standard'

# Normalised aliases found in the synthetic corpus.
UNIT_ALIASES = {
    'mg/dl': 'mg/dL',
    'mmol/l': 'mmol/L',
    'g/dl': 'g/dL',
    'g/l': 'g/L',
    'u/l': 'U/L',
    'umol/l': 'umol/L',
    'µmol/l': 'umol/L',
}


def normalise_unit(unit: str) -> str:
    key = unit.strip().lower().replace('μ', 'µ')
    return UNIT_ALIASES.get(key, unit.strip())


def to_standard_unit(value: float, unit: str, analyte: str) -> float:
    """Convert a displayed value to the project's standard unit.

    Raises ValueError for an unknown analyte/unit pair instead of silently
    returning the input, so a typo cannot pass as a valid conversion.
    """
    unit = normalise_unit(unit)
    standard = STANDARD_UNITS[analyte]
    if unit == standard:
        return round(float(value), 2)
    spec = FACTORS[analyte]
    if unit != spec['from']:
        raise ValueError(f'unsupported unit {unit!r} for {analyte}')
    return round(float(value) * spec['factor'], 2)


def from_standard_unit(value: float, unit: str, analyte: str) -> float:
    unit = normalise_unit(unit)
    standard = STANDARD_UNITS[analyte]
    if unit == standard:
        return round(float(value), 2)
    spec = FACTORS[analyte]
    if unit != spec['from']:
        raise ValueError(f'unsupported unit {unit!r} for {analyte}')
    return round(float(value) / spec['factor'], 2)


def classify(value_si: float, analyte: str) -> str:
    band = BANDS[analyte]
    if value_si < band['lo']:
        return 'low'
    if value_si > band['hi']:
        return 'high'
    return 'normal'


def check_value(raw_value: float, raw_unit: str, analyte: str,
                direction: str, recorded_si: float,
                relative_tolerance: float = 0.01,
                absolute_tolerance: float = 0.02) -> dict:
    """Recompute one lab value on the independent path and compare.

    Returns a dict with:
      recomputed_si, delta, conversion_ok, direction_ok, recomputed_direction
    """
    recomputed = to_standard_unit(raw_value, raw_unit, analyte)
    delta = abs(recomputed - float(recorded_si))
    tolerance = max(absolute_tolerance, relative_tolerance * abs(float(recorded_si)))
    recomputed_direction = classify(recomputed, analyte)
    return {
        'recomputed_si': recomputed,
        'delta': round(delta, 6),
        'tolerance': round(tolerance, 6),
        'conversion_ok': delta <= tolerance,
        'recomputed_direction': recomputed_direction,
        'direction_ok': recomputed_direction == direction,
    }


def table_fingerprint() -> dict:
    """Constants + derivation inputs, for the audit report."""
    return {
        'atomic_weights': ATOMIC_WEIGHTS,
        'molar_mass': {analyte: round(molar_mass(analyte), 4) for analyte in MOLECULAR_FORMULAS},
        'factors': {analyte: round(spec['factor'], 6) for analyte, spec in FACTORS.items()},
        'bands': BANDS,
        'band_status': BAND_STATUS,
    }
