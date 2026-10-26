"""Tests for the independent lab conversion path.

These tests are deliberately about *independence* as well as arithmetic: the
module must not import the project's shared table, and its bands must agree
with the shared table only because both encode the same documented demo values
(a drift in either file should break the test).
"""
import copy
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from clinforge import lab_standards
from clinforge.hpo_knowledge import REFERENCE_INTERVALS


class MolarMassTest(unittest.TestCase):
    def test_glucose_molar_mass(self):
        self.assertAlmostEqual(lab_standards.molar_mass('GLUCOSE'), 180.156, places=3)

    def test_creatinine_molar_mass(self):
        self.assertAlmostEqual(lab_standards.molar_mass('CREATININE'), 113.120, places=3)


class ConversionTest(unittest.TestCase):
    def test_glucose_mgdl_to_mmoll(self):
        # 92 mg/dL * 10 / 180.156 = 5.1067 -> 5.11
        self.assertAlmostEqual(lab_standards.to_standard_unit(92, 'mg/dL', 'GLUCOSE'), 5.11, places=2)

    def test_creatinine_mgdl_to_umoll(self):
        # 1 mg/dL * 10 / 113.12 * 1000 = 88.40
        self.assertAlmostEqual(lab_standards.to_standard_unit(1.0, 'mg/dL', 'CREATININE'), 88.40, places=2)

    def test_hemoglobin_gdl_to_gl(self):
        self.assertEqual(lab_standards.to_standard_unit(12.0, 'g/dL', 'HGB'), 120.0)

    def test_identity_units(self):
        self.assertEqual(lab_standards.to_standard_unit(35, 'U/L', 'ALT'), 35.0)
        self.assertEqual(lab_standards.to_standard_unit(5.4, 'mmol/L', 'GLUCOSE'), 5.4)

    def test_unsupported_unit_raises(self):
        with self.assertRaises(ValueError):
            lab_standards.to_standard_unit(5.4, 'mg/dL', 'HGB')

    def test_roundtrip_through_alt_unit(self):
        for value, unit, analyte in ((92, 'mg/dL', 'GLUCOSE'), (12.4, 'g/dL', 'HGB'),
                                     (1.1, 'mg/dL', 'CREATININE')):
            standard = lab_standards.to_standard_unit(value, unit, analyte)
            back = lab_standards.from_standard_unit(standard, unit, analyte)
            # The standard unit is rounded to 2 decimals, so the roundtrip error
            # is bounded by half a unit of that rounding (0.005 mmol/L * 18.02).
            self.assertAlmostEqual(back, value, delta=0.1, msg=f'{analyte} roundtrip')


class DirectionTest(unittest.TestCase):
    def test_direction_is_unit_invariant(self):
        cases = [(92, 'mg/dL', 'GLUCOSE', 'mmol/L'),
                 (12.4, 'g/dL', 'HGB', 'g/L')]
        for alt_value, alt_unit, analyte, std_unit in cases:
            alt = lab_standards.to_standard_unit(alt_value, alt_unit, analyte)
            std = lab_standards.to_standard_unit(alt, std_unit, analyte)
            self.assertEqual(lab_standards.classify(alt, analyte),
                             lab_standards.classify(std, analyte))

    def test_check_value_flags_tampered_recorded_value(self):
        # 92 mg/dL is 5.11 mmol/L; claiming 5.00 must fail the conversion check.
        result = lab_standards.check_value(92, 'mg/dL', 'GLUCOSE', 'normal', 5.00)
        self.assertFalse(result['conversion_ok'])
        self.assertAlmostEqual(result['recomputed_si'], 5.11, places=2)

    def test_check_value_accepts_consistent_record(self):
        result = lab_standards.check_value(35, 'U/L', 'ALT', 'normal', 35)
        self.assertTrue(result['conversion_ok'])
        self.assertTrue(result['direction_ok'])


class IndependenceTest(unittest.TestCase):
    def test_module_has_no_import_of_project_table(self):
        source = (ROOT / 'clinforge/lab_standards.py').read_text(encoding='utf-8')
        imports = [line for line in source.splitlines()
                   if re.match(r'\s*(from|import)\s+', line)]
        self.assertFalse(any('hpo_knowledge' in line for line in imports))

    def test_bands_match_documented_project_values(self):
        for analyte, band in lab_standards.BANDS.items():
            ref = REFERENCE_INTERVALS[analyte]
            self.assertEqual((band['lo'], band['hi']), (ref['lo'], ref['hi']), msg=analyte)

    def test_perturbation_experiment_restores_shared_table(self):
        from scripts.audit_lab_independence import perturbation_experiment
        before = copy.deepcopy(REFERENCE_INTERVALS)
        result = perturbation_experiment(n_cases=20, seed=7)
        self.assertEqual(before, REFERENCE_INTERVALS)
        self.assertEqual(result['arm_shared_table']['conversion_mismatch'], 0)
        self.assertGreaterEqual(result['arm_independent_table']['conversion_mismatch'], 0)


if __name__ == '__main__':
    unittest.main()
