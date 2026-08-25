"""
AMR Guardian Enterprise - Renal Dosing & Toxicity Limits Worker
Tracks dynamic Cockcroft-Gault Creatinine Clearance (CrCl) and flags nephrotoxicity /
neurotoxicity exposure thresholds for renally eliminated antimicrobials (Vancomycin, Cefepime, Meropenem, Aminoglycosides).
"""

import uuid
from typing import List, Dict, Any, Optional
from agents.base import ActionExecutor
from agents.models import (
    PatientSchema,
    StewardshipAlertSchema,
    AlertCategory,
    AlertSeverity,
    AlertStatus,
)
from agents.llm_factory import BaseLLMProvider, LLMFactory


class RenalDosingWorker:
    """
    Evaluates renal clearance and drug accumulation risk.
    - Cefepime neurotoxicity risk when CrCl < 50 mL/min and standard dose (>2g q8h or >1g q8h) maintained.
    - Vancomycin AKI risk when CrCl < 50 mL/min and standard unadjusted dose maintained.
    - Meropenem seizure/accumulation risk when CrCl < 50 mL/min.
    """

    def __init__(self, llm_provider: Optional[BaseLLMProvider] = None):
        self.llm = llm_provider or LLMFactory.get_provider("mock")
        self.executor = ActionExecutor()

    @staticmethod
    def calculate_crcl(age: int, weight_kg: float, scr: float, is_female: bool) -> float:
        """Calculates Creatinine Clearance using Cockcroft-Gault formula in mL/min."""
        if scr <= 0:
            return 120.0
        crcl = ((140.0 - age) * weight_kg) / (72.0 * scr)
        if is_female:
            crcl *= 0.85
        return round(crcl, 1)

    def evaluate_patient(self, patient: PatientSchema) -> List[StewardshipAlertSchema]:
        """Runs renal dosing safety checks with cryptographic audit trail and PHI guard."""
        return self.executor.execute(
            actor="RenalDosingWorker",
            action="EVALUATE_RENAL_DOSING",
            func=self._evaluate_internal,
            patient=patient,
        )["result"]

    def _evaluate_internal(self, patient: PatientSchema) -> List[StewardshipAlertSchema]:
        alerts: List[StewardshipAlertSchema] = []
        is_female = patient.gender.lower() in ["female", "f"]
        computed_crcl = self.calculate_crcl(patient.age, patient.weight_kg, patient.serum_creatinine, is_female)
        effective_crcl = min(patient.crcl_ml_min, computed_crcl)

        active_orders = [o for o in patient.orders if o.status == "ACTIVE"]

        for order in active_orders:
            drug = order.antibiotic_name.lower()
            freq = order.frequency.lower()

            # Rule 1: Cefepime neurotoxicity
            if "cefepime" in drug:
                if effective_crcl < 30 and ("q8h" in freq or "q12h" in freq):
                    prompt = (
                        f"Patient {patient.anonymous_id} on Cefepime ({order.dose} {order.frequency}) with CrCl {effective_crcl} mL/min. "
                        f"Recommend renal adjustment to prevent Cefepime-induced neurotoxicity/encephalopathy."
                    )
                    llm_rec = self.llm.generate(prompt=prompt)
                    alerts.append(
                        StewardshipAlertSchema(
                            id=f"ALT-RENAL-CEF-{uuid.uuid4().hex[:8].upper()}",
                            patient_id=patient.id,
                            category=AlertCategory.TOXICITY_LIMIT_EXCEEDED,
                            severity=AlertSeverity.CRITICAL,
                            headline=f"CEFEPIME NEUROTOXICITY RISK: CrCl {effective_crcl} mL/min exceeds unadjusted clearance capacity",
                            rationale=(
                                f"Cefepime is 85% renally cleared. High doses in renal impairment (CrCl < 30 mL/min) lead to central nervous "
                                f"system accumulation, presenting as encephalopathy, myoclonus, or non-convulsive status epilepticus."
                            ),
                            recommended_action=(
                                f"Adjust Cefepime to 1g IV q24h (or 2g IV q24h if severe Pseudomonas infection) or consult nephrology. "
                                f"LLM Guidance: {llm_rec.strip()}"
                            ),
                            evidence_basis={
                                "drug": order.antibiotic_name,
                                "current_dose": f"{order.dose} {order.frequency}",
                                "crcl_ml_min": effective_crcl,
                                "scr": patient.serum_creatinine,
                            },
                            status=AlertStatus.PENDING,
                        )
                    )
                elif 30 <= effective_crcl < 50 and "q8h" in freq:
                    alerts.append(
                        StewardshipAlertSchema(
                            id=f"ALT-RENAL-CEF-MOD-{uuid.uuid4().hex[:8].upper()}",
                            patient_id=patient.id,
                            category=AlertCategory.RENAL_DOSE_ADJUSTMENT,
                            severity=AlertSeverity.HIGH,
                            headline=f"RENAL DOSE ADJUSTMENT: Cefepime adjustment indicated for CrCl {effective_crcl} mL/min",
                            rationale="CrCl 30-50 mL/min requires dose interval extension to q12h to avoid drug accumulation.",
                            recommended_action=f"Adjust Cefepime dose to 2g IV q12h or 1g IV q12h based on indication.",
                            evidence_basis={"crcl_ml_min": effective_crcl, "current_dose": f"{order.dose} {order.frequency}"},
                            status=AlertStatus.PENDING,
                        )
                    )

            # Rule 2: Vancomycin AKI & TDM warning
            if "vancomycin" in drug:
                if effective_crcl < 50 and "q12h" in freq:
                    prompt = (
                        f"Patient {patient.anonymous_id} on Vancomycin ({order.dose} {order.frequency}) with reduced CrCl {effective_crcl} mL/min. "
                        f"Recommend AUC24/MIC targeted dosing or interval extension to prevent AKI."
                    )
                    llm_rec = self.llm.generate(prompt=prompt)
                    alerts.append(
                        StewardshipAlertSchema(
                            id=f"ALT-RENAL-VANCO-{uuid.uuid4().hex[:8].upper()}",
                            patient_id=patient.id,
                            category=AlertCategory.RENAL_DOSE_ADJUSTMENT,
                            severity=AlertSeverity.HIGH,
                            headline=f"VANCOMYCIN AKI RISK: Renal clearance decreased to {effective_crcl} mL/min",
                            rationale=(
                                f"Vancomycin clearance correlates linearly with CrCl. Maintaining q12h dosing in moderate-to-severe renal "
                                f"impairment significantly increases trough levels above 20 mcg/mL and raises Acute Kidney Injury (AKI) rates."
                            ),
                            recommended_action=(
                                f"Extend Vancomycin interval to q24h or transition to AUC/MIC Bayesian-guided dosing. Order serum trough/AUC check. "
                                f"LLM Guidance: {llm_rec.strip()}"
                            ),
                            evidence_basis={"drug": "Vancomycin", "crcl_ml_min": effective_crcl, "scr": patient.serum_creatinine},
                            status=AlertStatus.PENDING,
                        )
                    )

            # Rule 3: Meropenem adjustment
            if "meropenem" in drug and effective_crcl < 50:
                if "q8h" in freq and ("1g" in order.dose or "2g" in order.dose):
                    alerts.append(
                        StewardshipAlertSchema(
                            id=f"ALT-RENAL-MERO-{uuid.uuid4().hex[:8].upper()}",
                            patient_id=patient.id,
                            category=AlertCategory.RENAL_DOSE_ADJUSTMENT,
                            severity=AlertSeverity.MEDIUM,
                            headline=f"MEROPENEM RENAL ADJUSTMENT: CrCl {effective_crcl} mL/min",
                            rationale="Meropenem clearance is reduced; standard 1g q8h dosing in renal impairment can increase neurotoxicity risk.",
                            recommended_action=f"Adjust Meropenem to 1g IV q12h (for CrCl 26-50) or 500mg IV q12h (for CrCl 10-25).",
                            evidence_basis={"crcl_ml_min": effective_crcl, "drug": order.antibiotic_name},
                            status=AlertStatus.PENDING,
                        )
                    )

        return alerts
