"""
AMR Guardian Enterprise - Bug-Drug Mismatch Worker
Evaluates isolated bacterial pathogens with in vitro resistance profiles against
active medication orders to trigger critical antimicrobial mismatch alerts.
"""

import uuid
from typing import List, Dict, Any, Optional
from agents.base import PHIGuard, ActionExecutor
from agents.models import (
    PatientSchema,
    StewardshipAlertSchema,
    AlertCategory,
    AlertSeverity,
    AlertStatus,
    SusceptibilityResult,
)
from agents.llm_factory import BaseLLMProvider, LLMFactory


class BugDrugMismatchWorker:
    """
    Worker evaluating culture isolates and active antibiotic orders for resistance mismatches.
    e.g., Patient on Piperacillin-Tazobactam with ESBL/CRE Klebsiella showing Piperacillin-Tazobactam: R.
    """

    def __init__(self, llm_provider: Optional[BaseLLMProvider] = None):
        self.llm = llm_provider or LLMFactory.get_provider("mock")
        self.executor = ActionExecutor()

    def evaluate_patient(self, patient: PatientSchema) -> List[StewardshipAlertSchema]:
        """
        Executes bug-drug mismatch analysis on a patient.
        Guaranteed to be PHI-safe and tamper-logged.
        """
        return self.executor.execute(
            actor="BugDrugMismatchWorker",
            action="EVALUATE_MISMATCH",
            func=self._evaluate_internal,
            patient=patient,
        )["result"]

    def _evaluate_internal(self, patient: PatientSchema) -> List[StewardshipAlertSchema]:
        alerts: List[StewardshipAlertSchema] = []
        active_orders = [o for o in patient.orders if o.status == "ACTIVE"]

        for isolate in patient.isolates:
            for order in active_orders:
                antibiotic = order.antibiotic_name
                # Normalize drug name check in antibiogram
                susceptibility = None
                for drug_key, s_val in isolate.antibiogram.items():
                    if drug_key.lower() in antibiotic.lower() or antibiotic.lower() in drug_key.lower():
                        susceptibility = s_val
                        break

                if susceptibility == SusceptibilityResult.RESISTANT or str(susceptibility).upper() == "R":
                    # Prompt LLM for structured rationale and recommendation
                    prompt = (
                        f"Patient {patient.anonymous_id} has isolate {isolate.organism_name} from {isolate.specimen_source} "
                        f"resistant to current therapy {antibiotic} ({order.dose} {order.frequency}). "
                        f"Provide clinical rationale and immediate alternative options based on IDSA/EUCAST guidelines."
                    )
                    llm_recommendation = self.llm.generate(
                        prompt=prompt,
                        system_prompt="You are a clinical infectious diseases pharmacist specialist."
                    )

                    alert = StewardshipAlertSchema(
                        id=f"ALT-MISMATCH-{uuid.uuid4().hex[:8].upper()}",
                        patient_id=patient.id,
                        category=AlertCategory.BUG_DRUG_MISMATCH,
                        severity=AlertSeverity.CRITICAL,
                        headline=f"CRITICAL BUG-DRUG MISMATCH: {isolate.organism_name} resistant to active {antibiotic}",
                        rationale=(
                            f"Microbiology report confirms {isolate.organism_name} (Source: {isolate.specimen_source}) "
                            f"is RESISTANT to active regimen {antibiotic}. Continued therapy poses high risk of clinical failure."
                        ),
                        recommended_action=(
                            f"Discontinue {antibiotic} immediately. Adjust regimen to an in vitro active agent. "
                            f"LLM Guidance: {llm_recommendation.strip()}"
                        ),
                        evidence_basis={
                            "organism": isolate.organism_name,
                            "source": isolate.specimen_source,
                            "offending_antibiotic": antibiotic,
                            "resistance_profile": isolate.antibiogram,
                            "order_id": order.id,
                        },
                        status=AlertStatus.PENDING,
                    )
                    alerts.append(alert)

        return alerts
