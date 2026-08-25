"""
AMR Guardian Enterprise - Supervisor & Orchestrator
Coordinates multi-worker antimicrobial surveillance, aggregates NHSN metrics,
manages patient registry, and powers conversational clinical decision support.
"""

from typing import List, Dict, Any, Optional
from agents.base import PHIGuard, ActionExecutor, AuditLogger
from agents.models import (
    PatientSchema,
    StewardshipAlertSchema,
    CultureIsolateSchema,
    MedicationOrderSchema,
    AlertStatus,
)
from agents.mismatch_worker import BugDrugMismatchWorker
from agents.deescalation_worker import SpectrumDeescalationWorker
from agents.renal_worker import RenalDosingWorker
from agents.llm_factory import BaseLLMProvider, LLMFactory


class AMRSupervisor:
    """
    Central Orchestration Engine for Antimicrobial Stewardship.
    Coordinates specialized workers, calculates NHSN AU/AR stewardship quality metrics,
    and handles chat inquiries safely without PHI leakage.
    """

    def __init__(self, llm_provider: Optional[BaseLLMProvider] = None):
        self.llm = llm_provider or LLMFactory.get_provider("mock")
        self.audit_logger = AuditLogger()
        self.executor = ActionExecutor(self.audit_logger)
        
        # Initialize Workers
        self.mismatch_worker = BugDrugMismatchWorker(self.llm)
        self.deescalation_worker = SpectrumDeescalationWorker(self.llm)
        self.renal_worker = RenalDosingWorker(self.llm)

        # In-memory patient store
        self.patients: Dict[str, PatientSchema] = {}
        self.alerts: List[StewardshipAlertSchema] = []

    def register_patient(self, patient: PatientSchema) -> None:
        """Registers or updates a patient in the surveillance registry."""
        self.patients[patient.id] = patient

    def run_full_surveillance(self, patient_id: Optional[str] = None) -> List[StewardshipAlertSchema]:
        """
        Runs comprehensive multi-worker surveillance across registered patients.
        """
        return self.executor.execute(
            actor="AMRSupervisor",
            action="RUN_FULL_SURVEILLANCE",
            func=self._surveillance_internal,
            patient_id=patient_id,
        )["result"]

    def _surveillance_internal(self, patient_id: Optional[str] = None) -> List[StewardshipAlertSchema]:
        targets = [self.patients[patient_id]] if patient_id and patient_id in self.patients else list(self.patients.values())
        collected_alerts: List[StewardshipAlertSchema] = []

        for pt in targets:
            mismatch_alerts = self.mismatch_worker.evaluate_patient(pt)
            deesc_alerts = self.deescalation_worker.evaluate_patient(pt)
            renal_alerts = self.renal_worker.evaluate_patient(pt)

            pt_alerts = mismatch_alerts + deesc_alerts + renal_alerts
            pt.alerts.extend(pt_alerts)
            collected_alerts.extend(pt_alerts)
            self.alerts.extend(pt_alerts)

        return collected_alerts

    def calculate_nhsn_metrics(self) -> Dict[str, Any]:
        """
        Calculates NHSN (National Healthcare Safety Network) Antimicrobial Use & Resistance metrics.
        e.g., Days of Therapy (DOT), SAAR (Standardized Antimicrobial Administration Ratio) proxy,
        and alert resolution rates.
        """
        total_patients = len(self.patients)
        total_active_orders = sum(
            len([o for o in p.orders if o.status == "ACTIVE"]) for p in self.patients.values()
        )
        total_dot = sum(
            sum(o.day_of_therapy for o in p.orders if o.status == "ACTIVE")
            for p in self.patients.values()
        )

        broad_spectrum_agents = ["meropenem", "vancomycin", "cefepime", "piperacillin/tazobactam", "piperacillin-tazobactam"]
        broad_spectrum_dot = sum(
            sum(o.day_of_therapy for o in p.orders if o.status == "ACTIVE" and any(b in o.antibiotic_name.lower() for b in broad_spectrum_agents))
            for p in self.patients.values()
        )

        total_alerts = len(self.alerts)
        pending_alerts = len([a for a in self.alerts if a.status == AlertStatus.PENDING])
        accepted_alerts = len([a for a in self.alerts if a.status == AlertStatus.ACCEPTED])

        # SAAR Benchmark Proxy: Observed broad DOT / (Total Patients * Expected Benchmark rate 0.4)
        expected_broad_dot = max(total_patients * 2.5, 1.0)
        saar_proxy = round(broad_spectrum_dot / expected_broad_dot, 2)

        return {
            "total_monitored_patients": total_patients,
            "total_active_antibiotic_orders": total_active_orders,
            "total_days_of_therapy_dot": total_dot,
            "broad_spectrum_dot": broad_spectrum_dot,
            "saar_proxy_score": saar_proxy,
            "stewardship_alerts_generated": total_alerts,
            "alerts_pending_review": pending_alerts,
            "alerts_accepted": accepted_alerts,
            "interventions_per_1000_pt_days": round((total_alerts / max(total_dot, 1)) * 1000, 2),
        }

    def chat_query(self, query: str, context_patient_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Clinical Assistant Chat Interface for Infectious Diseases Specialists.
        Guarantees outbound PHI scrubbing.
        """
        # Guard against inbound direct identifiers
        PHIGuard.assert_no_phi(query)

        context_info = ""
        if context_patient_id and context_patient_id in self.patients:
            pt = self.patients[context_patient_id]
            context_info = (
                f"Patient ID: {pt.anonymous_id}\n"
                f"Age/Gender: {pt.age}yo {pt.gender}, Wt: {pt.weight_kg}kg, CrCl: {pt.crcl_ml_min} mL/min, SCr: {pt.serum_creatinine} mg/dL\n"
                f"Active Orders: {', '.join([f'{o.antibiotic_name} {o.dose} {o.frequency}' for o in pt.orders])}\n"
                f"Microbiology Isolates: {', '.join([f'{i.organism_name} ({i.specimen_source}): {i.antibiogram}' for i in pt.isolates])}\n"
                f"Active Alerts: {len(pt.alerts)}\n"
            )

        prompt = (
            f"You are the AMR-Guardian Infectious Diseases AI Consultant.\n"
            f"{context_info}\n"
            f"Clinical Question: {query}\n"
            f"Provide an evidence-based, guideline-aligned antimicrobial stewardship response."
        )

        response_text = self.llm.generate(
            prompt=prompt,
            system_prompt="You are an expert infectious disease physician and antimicrobial stewardship specialist."
        )

        # Enforce no outbound PHI leakage
        PHIGuard.assert_no_phi(response_text)

        return {
            "query": query,
            "context_patient": context_patient_id,
            "response": response_text,
            "status": "SUCCESS"
        }
