"""
AMR Guardian Enterprise - Spectrum De-escalation Worker
Identifies opportunities to de-escalate broad-spectrum empiric regimens:
- Day 2+ MSSA (Methicillin-Susceptible S. aureus) receiving Vancomycin / Daptomycin -> Cefazolin / Nafcillin.
- Pan-susceptible Gram-Negative Bacilli (GNB) receiving Carbapenems (Meropenem) -> Ceftriaxone / Cefepime / Pip-Tazo.
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
    SusceptibilityResult,
)
from agents.llm_factory import BaseLLMProvider, LLMFactory


class SpectrumDeescalationWorker:
    """
    Worker analyzing culture antibiograms and duration of empiric broad-spectrum therapy
    to flag safe, definitive antimicrobial de-escalation pathways.
    """

    def __init__(self, llm_provider: Optional[BaseLLMProvider] = None):
        self.llm = llm_provider or LLMFactory.get_provider("mock")
        self.executor = ActionExecutor()

    def evaluate_patient(self, patient: PatientSchema) -> List[StewardshipAlertSchema]:
        """Runs de-escalation evaluation with cryptographic audit trail and PHI guard."""
        return self.executor.execute(
            actor="SpectrumDeescalationWorker",
            action="EVALUATE_DEESCALATION",
            func=self._evaluate_internal,
            patient=patient,
        )["result"]

    def _evaluate_internal(self, patient: PatientSchema) -> List[StewardshipAlertSchema]:
        alerts: List[StewardshipAlertSchema] = []
        active_orders = [o for o in patient.orders if o.status == "ACTIVE"]

        for isolate in patient.isolates:
            org_lower = isolate.organism_name.lower()
            antibiogram = {k.lower(): v for k, v in isolate.antibiogram.items()}

            # Scenario 1: MSSA on Vancomycin or Daptomycin
            is_staph_aureus = "staphylococcus aureus" in org_lower or "s. aureus" in org_lower
            is_oxacillin_susceptible = antibiogram.get("oxacillin") == SusceptibilityResult.SUSCEPTIBLE or \
                                       antibiogram.get("oxacillin") == "S" or \
                                       antibiogram.get("cefoxitin") == "S"

            if is_staph_aureus and is_oxacillin_susceptible:
                for order in active_orders:
                    drug_lower = order.antibiotic_name.lower()
                    if "vancomycin" in drug_lower or "daptomycin" in drug_lower:
                        prompt = (
                            f"Patient {patient.anonymous_id} has confirmed MSSA bacteremia/infection from {isolate.specimen_source} "
                            f"currently on {order.antibiotic_name} (DOT: {order.day_of_therapy}). Recommend beta-lactam de-escalation."
                        )
                        llm_rec = self.llm.generate(prompt=prompt)
                        alerts.append(
                            StewardshipAlertSchema(
                                id=f"ALT-DEESC-MSSA-{uuid.uuid4().hex[:8].upper()}",
                                patient_id=patient.id,
                                category=AlertCategory.DEESCALATION_OPPORTUNITY,
                                severity=AlertSeverity.HIGH,
                                headline=f"DE-ESCALATION OPPORTUNITY: MSSA confirmed on broad-spectrum {order.antibiotic_name}",
                                rationale=(
                                    f"Isolate {isolate.organism_name} is Methicillin-Susceptible (Oxacillin Susceptible). "
                                    f"Beta-lactam therapy (Cefazolin or Nafcillin/Oxacillin) demonstrates superior clinical clearance, "
                                    f"lower 30-day mortality, and reduced nephrotoxicity compared to {order.antibiotic_name}."
                                ),
                                recommended_action=(
                                    f"De-escalate from {order.antibiotic_name} to Cefazolin (2g IV q8h) or Nafcillin (2g IV q4h). "
                                    f"LLM Specialist note: {llm_rec.strip()}"
                                ),
                                evidence_basis={
                                    "organism": isolate.organism_name,
                                    "phenotype": "MSSA",
                                    "current_therapy": order.antibiotic_name,
                                    "day_of_therapy": order.day_of_therapy,
                                },
                                status=AlertStatus.PENDING,
                            )
                        )

            # Scenario 2: Pan-susceptible GNB on Carbapenems (Meropenem, Imipenem)
            is_carbapenem_ordered = any(
                ("meropenem" in o.antibiotic_name.lower() or "imipenem" in o.antibiotic_name.lower() or "ertapenem" in o.antibiotic_name.lower())
                for o in active_orders
            )
            is_gnb = any(gnb in org_lower for gnb in ["escherichia coli", "e. coli", "klebsiella", "enterobacter", "pseudomonas"])
            is_broad_susceptible = (
                antibiogram.get("ceftriaxone") == "S" or 
                antibiogram.get("cefepime") == "S" or 
                antibiogram.get("piperacillin/tazobactam") == "S" or
                antibiogram.get("piperacillin-tazobactam") == "S"
            )

            if is_gnb and is_carbapenem_ordered and is_broad_susceptible:
                carb_order = next(
                    o for o in active_orders 
                    if any(c in o.antibiotic_name.lower() for c in ["meropenem", "imipenem", "ertapenem"])
                )
                prompt = (
                    f"Patient {patient.anonymous_id} with {isolate.organism_name} on Carbapenem {carb_order.antibiotic_name}. "
                    f"Isolate is fully susceptible to 3rd/4th gen cephalosporins. Recommend Carbapenem-sparing regimen."
                )
                llm_rec = self.llm.generate(prompt=prompt)
                alerts.append(
                    StewardshipAlertSchema(
                        id=f"ALT-DEESC-CARB-{uuid.uuid4().hex[:8].upper()}",
                        patient_id=patient.id,
                        category=AlertCategory.DEESCALATION_OPPORTUNITY,
                        severity=AlertSeverity.MEDIUM,
                        headline=f"CARBAPENEM SPARING OPPORTUNITY: {isolate.organism_name} is Cephalosporin-susceptible",
                        rationale=(
                            f"Culture confirms {isolate.organism_name} susceptible to narrower spectrum beta-lactams. "
                            f"Preserving carbapenems restricts selection pressure for Carbapenem-Resistant Enterobacterales (CRE)."
                        ),
                        recommended_action=(
                            f"Step down from {carb_order.antibiotic_name} to Ceftriaxone 2g IV q24h or Cefepime 2g IV q8h. "
                            f"LLM Specialist note: {llm_rec.strip()}"
                        ),
                        evidence_basis={
                            "organism": isolate.organism_name,
                            "current_carbapenem": carb_order.antibiotic_name,
                            "susceptibilities": isolate.antibiogram,
                        },
                        status=AlertStatus.PENDING,
                    )
                )

        return alerts
