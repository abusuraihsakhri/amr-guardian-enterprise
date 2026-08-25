#!/usr/bin/env python3
"""
Unit Test Suite for AMR Guardian Enterprise.
Covers:
- Cockcroft-Gault Creatinine Clearance & Devine Body Weight adjustments
- Renal dosing evaluations across Cefepime, Meropenem, Pip-Tazo, Levofloxacin, Vancomycin
- Bug-Drug Mismatch detection for resistant and intermediate isolates
- Pathogen-directed spectrum de-escalation (MSSA, non-ESBL Enterobacterales)
- Redundant anaerobic dual therapy detection
- IV-to-PO conversion criteria and blocking factors
- NHSN AU Metrics & SAAR computations
- HIPAA Safe Harbor PHI Guard and redaction
- Tamper-evident HMAC-SHA256 cryptographic audit trail
"""

import unittest
from amr_guardian_enterprise import (
    AMRGuardianEnterprise,
    Alert,
    AlertCategory,
    AlertSeverity,
    AuditLogger,
    CultureIsolate,
    MedicationOrder,
    Patient,
    PHIGuard,
    SecurityException,
    Susceptibility,
    calculate_adjusted_body_weight,
    calculate_cockcroft_gault_crcl,
    calculate_ibw,
    calculate_nhsn_au_metrics,
    evaluate_bug_drug_mismatch,
    evaluate_deescalation_opportunities,
    evaluate_iv_to_po_switch,
    evaluate_renal_dosing,
)


class TestRenalKinetics(unittest.TestCase):
    def test_devine_ibw_male(self):
        # 6 feet tall = 72 inches = 182.88 cm -> 12 inches over 60
        # IBW = 50 + 2.3 * 12 = 77.6 kg
        ibw = calculate_ibw("Male", 182.88)
        self.assertAlmostEqual(ibw, 77.6, delta=0.1)

    def test_devine_ibw_female(self):
        # 5 feet 4 inches = 64 inches = 162.56 cm -> 4 inches over 60
        # IBW = 45.5 + 2.3 * 4 = 54.7 kg
        ibw = calculate_ibw("Female", 162.56)
        self.assertAlmostEqual(ibw, 54.7, delta=0.1)

    def test_adjusted_body_weight_obese(self):
        ibw = 70.0
        actual = 100.0  # > 1.2 * 70 = 84
        # AdjBW = 70 + 0.4 * (100 - 70) = 70 + 12 = 82.0 kg
        adj = calculate_adjusted_body_weight(actual, ibw)
        self.assertEqual(adj, 82.0)

    def test_adjusted_body_weight_non_obese(self):
        ibw = 70.0
        actual = 75.0  # <= 84
        adj = calculate_adjusted_body_weight(actual, ibw)
        self.assertEqual(adj, 75.0)

    def test_cockcroft_gault_male(self):
        # 60 yo male, 72 kg, SCr 1.0 -> (140-60)*72 / 72 = 80 mL/min
        res = calculate_cockcroft_gault_crcl(age=60, gender="Male", weight_kg=72.0, serum_creatinine=1.0)
        self.assertAlmostEqual(res["crcl_ml_min"], 80.0, delta=0.5)
        self.assertFalse(res["is_female"])

    def test_cockcroft_gault_female(self):
        # 60 yo female, 72 kg, SCr 1.0 -> 80 * 0.85 = 68 mL/min
        res = calculate_cockcroft_gault_crcl(age=60, gender="Female", weight_kg=72.0, serum_creatinine=1.0)
        self.assertAlmostEqual(res["crcl_ml_min"], 68.0, delta=0.5)
        self.assertTrue(res["is_female"])

    def test_cockcroft_gault_invalid_inputs(self):
        with self.assertRaises(ValueError):
            calculate_cockcroft_gault_crcl(age=-5, gender="Male", weight_kg=70.0, serum_creatinine=1.0)
        with self.assertRaises(ValueError):
            calculate_cockcroft_gault_crcl(age=50, gender="Male", weight_kg=70.0, serum_creatinine=0.0)


class TestRenalDosingAlerts(unittest.TestCase):
    def test_cefepime_neurotoxicity_alert_in_renal_failure(self):
        # 70 yo male, SCr 2.5 -> CrCl ~24 mL/min. Given standard 2g q8h = 6000mg/day (max safe: 2000mg/day)
        p = Patient(
            patient_id="P-CEF",
            anonymous_id="ANON-CEF",
            age=70,
            gender="Male",
            weight_kg=72.0,
            height_cm=175.0,
            serum_creatinine=2.5,
            orders=[
                MedicationOrder("O1", "P-CEF", "Cefepime", dose_mg=2000.0, interval_hours=8, is_active=True)
            ]
        )
        alerts = evaluate_renal_dosing(p)
        self.assertTrue(len(alerts) > 0)
        self.assertEqual(alerts[0].category, AlertCategory.RENAL_DOSE_ADJUSTMENT)
        self.assertEqual(alerts[0].severity, AlertSeverity.CRITICAL)
        self.assertIn("Neurotoxicity", alerts[0].title)

    def test_meropenem_dose_adjustment(self):
        # 80 yo female, SCr 2.0 -> CrCl ~18 mL/min. Given 1g q8h = 3000mg/day (max: 1000mg/day)
        p = Patient(
            patient_id="P-MERO",
            anonymous_id="ANON-MERO",
            age=80,
            gender="Female",
            weight_kg=60.0,
            height_cm=160.0,
            serum_creatinine=2.0,
            orders=[
                MedicationOrder("O2", "P-MERO", "Meropenem", dose_mg=1000.0, interval_hours=8, is_active=True)
            ]
        )
        alerts = evaluate_renal_dosing(p)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].category, AlertCategory.RENAL_DOSE_ADJUSTMENT)
        self.assertIn("Meropenem", alerts[0].title)

    def test_normal_renal_function_no_alert(self):
        p = Patient(
            patient_id="P-NORM",
            anonymous_id="ANON-NORM",
            age=30,
            gender="Male",
            weight_kg=75.0,
            height_cm=175.0,
            serum_creatinine=0.8,
            orders=[
                MedicationOrder("O3", "P-NORM", "Cefepime", dose_mg=2000.0, interval_hours=8, is_active=True)
            ]
        )
        alerts = evaluate_renal_dosing(p)
        self.assertEqual(len(alerts), 0)


class TestBugDrugMismatch(unittest.TestCase):
    def test_resistant_isolate_generates_critical_alert(self):
        p = Patient(
            patient_id="P-MIS",
            anonymous_id="ANON-MIS",
            age=50,
            gender="Male",
            weight_kg=70.0,
            height_cm=175.0,
            serum_creatinine=1.0,
            isolates=[
                CultureIsolate(
                    isolate_id="ISO-1",
                    patient_id="P-MIS",
                    specimen_source="Blood",
                    organism="Klebsiella pneumoniae",
                    susceptibilities={"Ceftriaxone": "R", "Meropenem": "S"}
                )
            ],
            orders=[
                MedicationOrder("O4", "P-MIS", "Ceftriaxone", dose_mg=2000.0, interval_hours=24, is_active=True)
            ]
        )
        alerts = evaluate_bug_drug_mismatch(p)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].severity, AlertSeverity.CRITICAL)
        self.assertEqual(alerts[0].category, AlertCategory.BUG_DRUG_MISMATCH)

    def test_intermediate_isolate_generates_high_alert(self):
        p = Patient(
            patient_id="P-INT",
            anonymous_id="ANON-INT",
            age=50,
            gender="Male",
            weight_kg=70.0,
            height_cm=175.0,
            serum_creatinine=1.0,
            isolates=[
                CultureIsolate(
                    isolate_id="ISO-2",
                    patient_id="P-INT",
                    specimen_source="Urine",
                    organism="Pseudomonas aeruginosa",
                    susceptibilities={"Cefepime": "I"}
                )
            ],
            orders=[
                MedicationOrder("O5", "P-INT", "Cefepime", dose_mg=2000.0, interval_hours=8, is_active=True)
            ]
        )
        alerts = evaluate_bug_drug_mismatch(p)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].severity, AlertSeverity.HIGH)


class TestDeescalationOpportunities(unittest.TestCase):
    def test_mssa_deescalation_from_vancomycin(self):
        p = Patient(
            patient_id="P-MSSA",
            anonymous_id="ANON-MSSA",
            age=55,
            gender="Female",
            weight_kg=65.0,
            height_cm=165.0,
            serum_creatinine=0.9,
            isolates=[
                CultureIsolate(
                    isolate_id="ISO-MSSA",
                    patient_id="P-MSSA",
                    specimen_source="Blood",
                    organism="Staphylococcus aureus",
                    susceptibilities={"Oxacillin": "S", "Cefazolin": "S", "Vancomycin": "S"}
                )
            ],
            orders=[
                MedicationOrder("O-VANCO", "P-MSSA", "Vancomycin", dose_mg=1000.0, interval_hours=12, is_active=True)
            ]
        )
        alerts = evaluate_deescalation_opportunities(p)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].category, AlertCategory.DEESCALATION_OPPORTUNITY)
        self.assertIn("MSSA", alerts[0].title)
        self.assertIn("Cefazolin", alerts[0].recommendation)

    def test_carbapenem_deescalation_for_susceptible_ecoli(self):
        p = Patient(
            patient_id="P-ECOLI",
            anonymous_id="ANON-ECOLI",
            age=62,
            gender="Male",
            weight_kg=78.0,
            height_cm=178.0,
            serum_creatinine=1.1,
            isolates=[
                CultureIsolate(
                    isolate_id="ISO-EC",
                    patient_id="P-ECOLI",
                    specimen_source="Blood",
                    organism="Escherichia coli",
                    susceptibilities={"Ceftriaxone": "S", "Meropenem": "S"}
                )
            ],
            orders=[
                MedicationOrder("O-MERO", "P-ECOLI", "Meropenem", dose_mg=1000.0, interval_hours=8, is_active=True)
            ]
        )
        alerts = evaluate_deescalation_opportunities(p)
        self.assertTrue(any(a.category == AlertCategory.DEESCALATION_OPPORTUNITY for a in alerts))

    def test_redundant_anaerobic_coverage(self):
        p = Patient(
            patient_id="P-ANA",
            anonymous_id="ANON-ANA",
            age=50,
            gender="Male",
            weight_kg=70.0,
            height_cm=175.0,
            serum_creatinine=1.0,
            orders=[
                MedicationOrder("O-PIP", "P-ANA", "Piperacillin-Tazobactam", dose_mg=3375.0, interval_hours=6, is_active=True),
                MedicationOrder("O-FLAG", "P-ANA", "Metronidazole", dose_mg=500.0, interval_hours=8, is_active=True)
            ]
        )
        alerts = evaluate_deescalation_opportunities(p)
        self.assertTrue(any(a.category == AlertCategory.DUPLICATE_THERAPY for a in alerts))


class TestIVToPOSwitch(unittest.TestCase):
    def test_eligible_iv_to_po_switch(self):
        p = Patient(
            patient_id="P-IVPO",
            anonymous_id="ANON-IVPO",
            age=45,
            gender="Male",
            weight_kg=80.0,
            height_cm=180.0,
            serum_creatinine=0.9,
            hemodynamically_stable=True,
            tolerating_oral=True,
            functioning_gi=True,
            deep_seated_infection=False,
            neutropenic_fever=False,
            orders=[
                MedicationOrder("O-LEVO", "P-IVPO", "Levofloxacin", dose_mg=750.0, interval_hours=24, route="IV", day_of_therapy=3, is_active=True)
            ]
        )
        alerts = evaluate_iv_to_po_switch(p)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].category, AlertCategory.IV_TO_PO_SWITCH)
        self.assertEqual(alerts[0].severity, AlertSeverity.MEDIUM)
        self.assertIn("Eligible", alerts[0].title)

    def test_ineligible_blocked_by_gi_failure(self):
        p = Patient(
            patient_id="P-GI",
            anonymous_id="ANON-GI",
            age=45,
            gender="Male",
            weight_kg=80.0,
            height_cm=180.0,
            serum_creatinine=0.9,
            hemodynamically_stable=True,
            tolerating_oral=False,  # NPO
            functioning_gi=False,  # Ileus
            orders=[
                MedicationOrder("O-LIN", "P-GI", "Linezolid", dose_mg=600.0, interval_hours=12, route="IV", day_of_therapy=3, is_active=True)
            ]
        )
        alerts = evaluate_iv_to_po_switch(p)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].severity, AlertSeverity.INFO)
        self.assertIn("Ineligible", alerts[0].title)


class TestNHSNMetrics(unittest.TestCase):
    def test_au_metrics_calculation(self):
        orders = [
            MedicationOrder("O1", "P1", "Cefepime", dose_mg=2000, interval_hours=8, day_of_therapy=5, is_active=True),
            MedicationOrder("O2", "P1", "Vancomycin", dose_mg=1000, interval_hours=12, day_of_therapy=5, is_active=True),
            MedicationOrder("O3", "P2", "Meropenem", dose_mg=1000, interval_hours=8, day_of_therapy=4, is_active=True),
        ]
        result = calculate_nhsn_au_metrics(patient_days=100, medication_orders=orders)
        self.assertEqual(result.total_patient_days, 100)
        self.assertEqual(result.total_dot, 14)  # 5 + 5 + 4
        self.assertEqual(result.dot_per_1000_patient_days, 140.0)
        self.assertTrue("overall" in result.saar_estimates)

    def test_invalid_patient_days_raises(self):
        with self.assertRaises(ValueError):
            calculate_nhsn_au_metrics(patient_days=0, medication_orders=[])


class TestSecurityAndAudit(unittest.TestCase):
    def test_phi_guard_clean_text(self):
        text = "Patient ANON-101 has blood culture positive for MSSA."
        PHIGuard.assert_no_phi(text)

    def test_phi_guard_catches_mrn(self):
        with self.assertRaises(SecurityException):
            PHIGuard.assert_no_phi("Patient MRN: 94827104 was admitted.")

    def test_phi_guard_catches_ssn(self):
        with self.assertRaises(SecurityException):
            PHIGuard.assert_no_phi("Identifier SSN 123-45-6789 detected.")

    def test_phi_redaction(self):
        text = "Contact 555-123-4567 or email john.doe@hospital.org"
        redacted = PHIGuard.redact_phi(text)
        self.assertNotIn("555-123-4567", redacted)
        self.assertNotIn("john.doe@hospital.org", redacted)
        self.assertIn("[REDACTED_", redacted)

    def test_hmac_audit_logger(self):
        logger = AuditLogger("test-secret-key")
        rec = logger.record(actor="Supervisor", action="AUDIT", details="Test run")
        self.assertTrue(logger.verify_hmac(rec.actor, rec.action, rec.details, rec.timestamp, rec.signature))
        # Tampering check
        self.assertFalse(logger.verify_hmac(rec.actor, rec.action, "Tampered details", rec.timestamp, rec.signature))


class TestAMRGuardianEnterpriseOrchestration(unittest.TestCase):
    def test_full_patient_audit(self):
        guardian = AMRGuardianEnterprise()
        p = Patient(
            patient_id="PT-TEST",
            anonymous_id="ANON-TEST-001",
            age=68,
            gender="Male",
            weight_kg=75.0,
            height_cm=175.0,
            serum_creatinine=2.4,
            isolates=[
                CultureIsolate(
                    isolate_id="ISO-T",
                    patient_id="PT-TEST",
                    specimen_source="Blood",
                    organism="Klebsiella pneumoniae",
                    susceptibilities={"Piperacillin-Tazobactam": "R", "Meropenem": "S"}
                )
            ],
            orders=[
                MedicationOrder("ORD-1", "PT-TEST", "Piperacillin-Tazobactam", dose_mg=3375, interval_hours=6, is_active=True),
                MedicationOrder("ORD-2", "PT-TEST", "Cefepime", dose_mg=2000, interval_hours=8, is_active=True)
            ]
        )
        alerts = guardian.audit_patient(p)
        self.assertTrue(len(alerts) >= 2)
        # Should be sorted with CRITICAL first
        self.assertEqual(alerts[0].severity, AlertSeverity.CRITICAL)

    def test_population_audit(self):
        guardian = AMRGuardianEnterprise()
        p = Patient(
            patient_id="PT-1",
            anonymous_id="ANON-1",
            age=50,
            gender="Male",
            weight_kg=70.0,
            height_cm=175.0,
            serum_creatinine=1.0,
            orders=[
                MedicationOrder("ORD-A", "PT-1", "Vancomycin", dose_mg=1000, interval_hours=12, day_of_therapy=3, is_active=True)
            ]
        )
        pop_res = guardian.audit_population([p], patient_days=50)
        self.assertEqual(pop_res["total_patients"], 1)
        self.assertIn("nhsn_au_metrics", pop_res)


if __name__ == "__main__":
    unittest.main()
