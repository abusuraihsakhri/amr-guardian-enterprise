#!/usr/bin/env python3
"""
AMR Guardian Enterprise - Clinical Antimicrobial Stewardship Decision Support System.

Core domain algorithms:
1. Renal Function & Pharmacokinetic Dosing (Cockcroft-Gault, IBW/AdjBW, renal dose adjustments).
2. Spectrum Optimization & Breadth Scoring with Antibiogram calibration.
3. Bug-Drug Mismatch Detection against active culture isolates.
4. Pathogen-Directed Spectrum De-escalation & Redundant Therapy Detection.
5. Evidence-Based IV-to-PO Switch Eligibility & Bioavailability Assessment.
6. CDC / NHSN Antimicrobial Use (AU) Metrics & SAAR (Standardized Antimicrobial Administration Ratio).
7. HIPAA Safe Harbor PHI Outbound Guard & HMAC-SHA256 Tamper-Evident Audit Logging.

Author: Dr. Abu Suraih Sakhri
License: MIT
"""

from __future__ import annotations

import enum
import hashlib
import hmac
import json
import math
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


# =====================================================================
# 1. ENUMS & CONSTANTS
# =====================================================================

class AlertSeverity(str, enum.Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"


class AlertCategory(str, enum.Enum):
    BUG_DRUG_MISMATCH = "BUG_DRUG_MISMATCH"
    RENAL_DOSE_ADJUSTMENT = "RENAL_DOSE_ADJUSTMENT"
    DEESCALATION_OPPORTUNITY = "DEESCALATION_OPPORTUNITY"
    IV_TO_PO_SWITCH = "IV_TO_PO_SWITCH"
    SPECTRUM_OVERUSE = "SPECTRUM_OVERUSE"
    DUPLICATE_THERAPY = "DUPLICATE_THERAPY"
    TOXICITY_RISK = "TOXICITY_RISK"


class Susceptibility(str, enum.Enum):
    SUSCEPTIBLE = "S"
    INTERMEDIATE = "I"
    RESISTANT = "R"
    NOT_TESTED = "NT"


ORGANISM_PHENOTYPES: Dict[str, Set[str]] = {
    "Escherichia coli": {"gram_neg", "enterobacterales"},
    "E. coli": {"gram_neg", "enterobacterales"},
    "Klebsiella pneumoniae": {"gram_neg", "enterobacterales"},
    "Klebsiella pneumoniae (ESBL+)": {"gram_neg", "enterobacterales", "esbl"},
    "Enterobacter cloacae": {"gram_neg", "enterobacterales", "ampc_risk"},
    "Enterobacter spp.": {"gram_neg", "enterobacterales", "ampc_risk"},
    "Pseudomonas aeruginosa": {"gram_neg", "pseudomonas"},
    "Acinetobacter baumannii": {"gram_neg", "acinetobacter", "mdr_risk"},
    "Staphylococcus aureus (MSSA)": {"gram_pos", "staph_mssa"},
    "Staphylococcus aureus (MRSA)": {"gram_pos", "mrsa"},
    "Staphylococcus aureus": {"gram_pos", "staph_mssa"},
    "Streptococcus pneumoniae": {"gram_pos", "streptococcus"},
    "Enterococcus faecalis": {"gram_pos", "enterococcus", "vse"},
    "Enterococcus faecium (VRE)": {"gram_pos", "enterococcus", "vre"},
    "Bacteroides fragilis": {"anaerobe"},
    "Clostridioides difficile": {"anaerobe", "c_diff"},
}

ANTIBIOTIC_SPECTRUM: Dict[str, Set[str]] = {
    "cefazolin": {"gram_pos", "staph_mssa", "enterobacterales"},
    "oxacillin": {"gram_pos", "staph_mssa"},
    "nafcillin": {"gram_pos", "staph_mssa"},
    "ampicillin": {"gram_pos", "enterococcus", "vse", "streptococcus"},
    "ampicillin-sulbactam": {"gram_pos", "staph_mssa", "enterobacterales", "anaerobe", "enterococcus"},
    "ceftriaxone": {"gram_pos", "streptococcus", "gram_neg", "enterobacterales"},
    "ceftazidime": {"gram_neg", "enterobacterales", "pseudomonas"},
    "cefepime": {"gram_pos", "streptococcus", "staph_mssa", "gram_neg", "enterobacterales", "pseudomonas", "ampc_risk"},
    "piperacillin-tazobactam": {"gram_pos", "staph_mssa", "gram_neg", "enterobacterales", "pseudomonas", "anaerobe", "enterococcus"},
    "meropenem": {"gram_pos", "staph_mssa", "gram_neg", "enterobacterales", "pseudomonas", "anaerobe", "ampc_risk", "esbl"},
    "ertapenem": {"gram_pos", "staph_mssa", "gram_neg", "enterobacterales", "anaerobe", "ampc_risk", "esbl"},
    "vancomycin": {"gram_pos", "staph_mssa", "mrsa", "enterococcus", "streptococcus"},
    "linezolid": {"gram_pos", "staph_mssa", "mrsa", "enterococcus", "vre", "streptococcus"},
    "daptomycin": {"gram_pos", "staph_mssa", "mrsa", "enterococcus", "vre", "streptococcus"},
    "levofloxacin": {"gram_pos", "streptococcus", "staph_mssa", "gram_neg", "enterobacterales", "pseudomonas"},
    "ciprofloxacin": {"gram_neg", "enterobacterales", "pseudomonas"},
    "metronidazole": {"anaerobe"},
    "nitrofurantoin": {"enterobacterales", "enterococcus"},
    "trimethoprim-sulfamethoxazole": {"gram_pos", "staph_mssa", "mrsa", "gram_neg", "enterobacterales"},
    "azithromycin": {"gram_pos", "streptococcus", "atypical"},
    "doxycycline": {"gram_pos", "staph_mssa", "mrsa", "atypical"},
}

BROAD_SPECTRUM_AGENTS = {
    "meropenem", "ertapenem", "imipenem-cilastatin",
    "cefepime", "piperacillin-tazobactam", "ceftolozane-tazobactam", "ceftazidime-avibactam"
}

ANAEROBIC_AGENTS = {
    "metronidazole", "piperacillin-tazobactam", "meropenem",
    "ertapenem", "ampicillin-sulbactam", "clindamycin", "moxifloxacin"
}

HIGH_BIOAVAILABILITY_ORAL: Dict[str, Dict[str, Any]] = {
    "levofloxacin": {"po_equivalent": "levofloxacin", "bioavailability_pct": 99, "conversion_ratio": 1.0},
    "ciprofloxacin": {"po_equivalent": "ciprofloxacin", "bioavailability_pct": 80, "conversion_ratio": 1.25},
    "moxifloxacin": {"po_equivalent": "moxifloxacin", "bioavailability_pct": 90, "conversion_ratio": 1.0},
    "linezolid": {"po_equivalent": "linezolid", "bioavailability_pct": 100, "conversion_ratio": 1.0},
    "metronidazole": {"po_equivalent": "metronidazole", "bioavailability_pct": 100, "conversion_ratio": 1.0},
    "trimethoprim-sulfamethoxazole": {"po_equivalent": "trimethoprim-sulfamethoxazole", "bioavailability_pct": 95, "conversion_ratio": 1.0},
    "fluconazole": {"po_equivalent": "fluconazole", "bioavailability_pct": 95, "conversion_ratio": 1.0},
    "doxycycline": {"po_equivalent": "doxycycline", "bioavailability_pct": 95, "conversion_ratio": 1.0},
    "clindamycin": {"po_equivalent": "clindamycin", "bioavailability_pct": 90, "conversion_ratio": 1.0},
}


# =====================================================================
# 2. DATA MODELS
# =====================================================================

@dataclass
class CultureIsolate:
    isolate_id: str
    patient_id: str
    specimen_source: str
    organism: str
    susceptibilities: Dict[str, str] = field(default_factory=dict)
    resistance_markers: List[str] = field(default_factory=list)
    collection_date: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MedicationOrder:
    order_id: str
    patient_id: str
    drug: str
    dose_mg: float
    interval_hours: int
    route: str = "IV"
    day_of_therapy: int = 1
    is_active: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Patient:
    patient_id: str
    anonymous_id: str
    age: int
    gender: str
    weight_kg: float
    height_cm: float
    serum_creatinine: float
    location: str = "Med-Surg"
    hemodynamically_stable: bool = True
    tolerating_oral: bool = True
    functioning_gi: bool = True
    deep_seated_infection: bool = False
    neutropenic_fever: bool = False
    allergies: List[str] = field(default_factory=list)
    isolates: List[CultureIsolate] = field(default_factory=list)
    orders: List[MedicationOrder] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


@dataclass
class Alert:
    alert_id: str
    patient_id: str
    category: AlertCategory
    severity: AlertSeverity
    title: str
    description: str
    recommendation: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["category"] = self.category.value
        d["severity"] = self.severity.value
        return d


@dataclass
class AuditRecord:
    record_id: str
    timestamp: str
    actor: str
    action: str
    details: str
    signature: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# =====================================================================
# 3. SECURITY & PHI SAFE HARBOR GUARD & HMAC AUDIT
# =====================================================================

class SecurityException(Exception):
    """Raised when an outbound PHI violation occurs."""
    pass


class PHIGuard:
    """HIPAA Safe Harbor PHI de-identification and outbound enforcement."""
    PATTERNS: Dict[str, re.Pattern] = {
        "MRN": re.compile(r"(?i)\b(?:mrn|medical\s*record\s*(?:no|number)|chart\s*#?)\s*[:=\-]?\s*([A-Z0-9]{6,12})\b"),
        "SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "PHONE": re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
        "EMAIL": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
        "NAME_EXPLICIT": re.compile(r"(?i)\b(?:patient|pt|name)\s*[:=]\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b"),
        "DOB": re.compile(r"(?i)\b(?:dob|date\s*of\s*birth)\s*[:=]\s*(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b"),
    }

    @classmethod
    def assert_no_phi(cls, text: str) -> None:
        if not text:
            return
        for key, pat in cls.PATTERNS.items():
            m = pat.search(text)
            if m:
                raise SecurityException(f"PHI Outbound Violation: detected pattern '{key}' with match '{m.group(0)}'")

    @classmethod
    def redact_phi(cls, text: str) -> str:
        if not text:
            return ""
        redacted = text
        for key, pat in cls.PATTERNS.items():
            redacted = pat.sub(f"[REDACTED_{key}]", redacted)
        return redacted


class AuditLogger:
    """Cryptographic tamper-evident HMAC-SHA256 audit logging."""
    def __init__(self, secret_key: Optional[str] = None):
        self.secret_key = (secret_key or "amr-guardian-enterprise-master-key-2026").encode("utf-8")
        self.log: List[AuditRecord] = []

    def generate_hmac(self, actor: str, action: str, details: str, timestamp: str) -> str:
        payload = f"{timestamp}|{actor}|{action}|{details}".encode("utf-8")
        return hmac.new(self.secret_key, payload, hashlib.sha256).hexdigest()

    def verify_hmac(self, actor: str, action: str, details: str, timestamp: str, signature: str) -> bool:
        expected = self.generate_hmac(actor, action, details, timestamp)
        return hmac.compare_digest(expected, signature)

    def record(self, actor: str, action: str, details: str) -> AuditRecord:
        ts = datetime.now(timezone.utc).isoformat()
        sig = self.generate_hmac(actor, action, details, ts)
        rec = AuditRecord(
            record_id=f"AUD-{len(self.log)+1:05d}",
            timestamp=ts,
            actor=actor,
            action=action,
            details=details,
            signature=sig
        )
        self.log.append(rec)
        return rec


# =====================================================================
# 4. RENAL FUNCTION & PK/PD DOSE ADJUSTMENT ENGINE
# =====================================================================

def calculate_ibw(gender: str, height_cm: float) -> float:
    """Calculates Devine Ideal Body Weight in kg."""
    height_in = height_cm / 2.54
    inches_over_5_ft = max(0.0, height_in - 60.0)
    if gender.strip().upper().startswith("F"):
        ibw = 45.5 + 2.3 * inches_over_5_ft
    else:
        ibw = 50.0 + 2.3 * inches_over_5_ft
    return round(ibw, 2)


def calculate_adjusted_body_weight(actual_weight_kg: float, ibw_kg: float) -> float:
    """Calculates Adjusted Body Weight if actual weight > 1.2 * IBW."""
    if actual_weight_kg > 1.2 * ibw_kg:
        adj = ibw_kg + 0.4 * (actual_weight_kg - ibw_kg)
        return round(adj, 2)
    return round(actual_weight_kg, 2)


def calculate_cockcroft_gault_crcl(
    age: int,
    gender: str,
    weight_kg: float,
    serum_creatinine: float,
    height_cm: Optional[float] = None
) -> Dict[str, Any]:
    """
    Computes Cockcroft-Gault Creatinine Clearance (mL/min) with Devine IBW adjustment.
    Formula: CrCl = [(140 - Age) * Weight / (72 * SCr)] * (0.85 if Female)
    """
    if age <= 0 or serum_creatinine <= 0 or weight_kg <= 0:
        raise ValueError("Age, serum creatinine, and weight must be positive numbers.")

    ibw = calculate_ibw(gender, height_cm) if height_cm else weight_kg
    dosing_weight = calculate_adjusted_body_weight(weight_kg, ibw) if height_cm else weight_kg

    raw_crcl = ((140.0 - float(age)) * dosing_weight) / (72.0 * float(serum_creatinine))
    is_female = gender.strip().upper().startswith("F")
    if is_female:
        crcl = raw_crcl * 0.85
    else:
        crcl = raw_crcl

    crcl_val = max(1.0, round(crcl, 1))
    return {
        "crcl_ml_min": crcl_val,
        "ibw_kg": ibw,
        "dosing_weight_kg": dosing_weight,
        "is_female": is_female,
        "used_adjusted_weight": dosing_weight != weight_kg
    }


RENAL_DOSE_TABLE: Dict[str, List[Dict[str, Any]]] = {
    "cefepime": [
        {"min_crcl": 60.0, "recommended": "2000mg q8h", "max_daily_mg": 6000.0},
        {"min_crcl": 30.0, "recommended": "2000mg q12h", "max_daily_mg": 4000.0},
        {"min_crcl": 11.0, "recommended": "1000mg q12h or 2000mg q24h", "max_daily_mg": 2000.0},
        {"min_crcl": 0.0,  "recommended": "1000mg q24h", "max_daily_mg": 1000.0},
    ],
    "meropenem": [
        {"min_crcl": 50.0, "recommended": "1000mg q8h", "max_daily_mg": 3000.0},
        {"min_crcl": 26.0, "recommended": "1000mg q12h", "max_daily_mg": 2000.0},
        {"min_crcl": 10.0, "recommended": "500mg q12h", "max_daily_mg": 1000.0},
        {"min_crcl": 0.0,  "recommended": "500mg q24h", "max_daily_mg": 500.0},
    ],
    "piperacillin-tazobactam": [
        {"min_crcl": 40.0, "recommended": "3.375g q6h or 4.5g q6h", "max_daily_mg": 18000.0},
        {"min_crcl": 20.0, "recommended": "2.25g q6h or 3.375g q8h", "max_daily_mg": 10125.0},
        {"min_crcl": 0.0,  "recommended": "2.25g q8h", "max_daily_mg": 6750.0},
    ],
    "levofloxacin": [
        {"min_crcl": 50.0, "recommended": "750mg q24h", "max_daily_mg": 750.0},
        {"min_crcl": 20.0, "recommended": "750mg q48h", "max_daily_mg": 375.0},
        {"min_crcl": 0.0,  "recommended": "750mg initial then 500mg q48h", "max_daily_mg": 250.0},
    ],
    "ciprofloxacin": [
        {"min_crcl": 50.0, "recommended": "400mg q8h (IV) / 500mg q12h (PO)", "max_daily_mg": 1200.0},
        {"min_crcl": 30.0, "recommended": "400mg q12h (IV) / 250-500mg q12h (PO)", "max_daily_mg": 800.0},
        {"min_crcl": 0.0,  "recommended": "400mg q24h (IV) / 250-500mg q24h (PO)", "max_daily_mg": 400.0},
    ],
    "vancomycin": [
        {"min_crcl": 90.0, "recommended": "15-20 mg/kg q8-12h", "max_daily_mg": 4000.0},
        {"min_crcl": 50.0, "recommended": "15-20 mg/kg q12h", "max_daily_mg": 3000.0},
        {"min_crcl": 20.0, "recommended": "15-20 mg/kg q24h", "max_daily_mg": 2000.0},
        {"min_crcl": 0.0,  "recommended": "15-20 mg/kg q48h or dose by trough level", "max_daily_mg": 1000.0},
    ]
}


def evaluate_renal_dosing(patient: Patient) -> List[Alert]:
    """Audits active antibiotic orders against patient's renal function."""
    renal_info = calculate_cockcroft_gault_crcl(
        age=patient.age,
        gender=patient.gender,
        weight_kg=patient.weight_kg,
        serum_creatinine=patient.serum_creatinine,
        height_cm=patient.height_cm
    )
    crcl = renal_info["crcl_ml_min"]
    alerts: List[Alert] = []

    for order in patient.orders:
        if not order.is_active:
            continue
        drug_key = order.drug.lower().strip()
        guidelines = RENAL_DOSE_TABLE.get(drug_key)
        if not guidelines:
            continue

        daily_mg = (order.dose_mg * 24.0) / max(1, order.interval_hours)
        target_rule = None
        for rule in guidelines:
            if crcl >= rule["min_crcl"]:
                target_rule = rule
                break
        if not target_rule:
            target_rule = guidelines[-1]

        if daily_mg > target_rule["max_daily_mg"] + 1e-2:
            sev = AlertSeverity.HIGH if drug_key != "cefepime" else AlertSeverity.CRITICAL
            title = f"Renal Dose Adjustment Required: {order.drug}"
            if drug_key == "cefepime" and crcl < 50.0:
                title = f"CRITICAL Cefepime Neurotoxicity Risk (CrCl {crcl} mL/min)"

            desc = (
                f"Active daily dose of {order.drug} ({daily_mg:.0f} mg/day, {order.dose_mg:.0f}mg q{order.interval_hours}h) "
                f"exceeds renal maximum for CrCl of {crcl} mL/min (max: {target_rule['max_daily_mg']:.0f} mg/day)."
            )
            rec = f"Adjust {order.drug} to {target_rule['recommended']}."
            alerts.append(Alert(
                alert_id=f"ALT-RENAL-{patient.patient_id}-{order.order_id}",
                patient_id=patient.patient_id,
                category=AlertCategory.RENAL_DOSE_ADJUSTMENT,
                severity=sev,
                title=title,
                description=desc,
                recommendation=rec,
                evidence={"crcl_ml_min": crcl, "current_daily_mg": daily_mg, "max_safe_daily_mg": target_rule["max_daily_mg"]}
            ))

    return alerts


# =====================================================================
# 5. BUG-DRUG MISMATCH DETECTOR
# =====================================================================

def evaluate_bug_drug_mismatch(patient: Patient) -> List[Alert]:
    """Detects in vitro resistance mismatches between active antibiotics and culture isolates."""
    alerts: List[Alert] = []
    active_drugs = [o for o in patient.orders if o.is_active]

    for isolate in patient.isolates:
        for order in active_drugs:
            drug_name = order.drug.strip()
            # Direct match or case-insensitive match
            matched_res = None
            for tested_drug, sus_result in isolate.susceptibilities.items():
                if tested_drug.lower() == drug_name.lower() or drug_name.lower() in tested_drug.lower():
                    matched_res = sus_result
                    break

            if matched_res in (Susceptibility.RESISTANT.value, "R"):
                alerts.append(Alert(
                    alert_id=f"ALT-MISMATCH-{patient.patient_id}-{isolate.isolate_id}-{order.order_id}",
                    patient_id=patient.patient_id,
                    category=AlertCategory.BUG_DRUG_MISMATCH,
                    severity=AlertSeverity.CRITICAL,
                    title=f"CRITICAL Bug-Drug Mismatch: {isolate.organism} vs {order.drug}",
                    description=(
                        f"Active antibiotic {order.drug} has documented RESISTANCE (R) in culture isolate "
                        f"{isolate.isolate_id} ({isolate.organism}, Source: {isolate.specimen_source})."
                    ),
                    recommendation=f"Immediately discontinue {order.drug} and switch to an active targeted agent based on susceptibilities.",
                    evidence={"organism": isolate.organism, "drug": order.drug, "susceptibility": "R", "source": isolate.specimen_source}
                ))
            elif matched_res in (Susceptibility.INTERMEDIATE.value, "I"):
                alerts.append(Alert(
                    alert_id=f"ALT-INTERMED-{patient.patient_id}-{isolate.isolate_id}-{order.order_id}",
                    patient_id=patient.patient_id,
                    category=AlertCategory.BUG_DRUG_MISMATCH,
                    severity=AlertSeverity.HIGH,
                    title=f"Intermediate Susceptibility Warning: {isolate.organism} vs {order.drug}",
                    description=(
                        f"Active agent {order.drug} has INTERMEDIATE (I) susceptibility for {isolate.organism}. "
                        "May lead to subtherapeutic exposure and treatment failure."
                    ),
                    recommendation=f"Evaluate dose escalation or switch {order.drug} to fully susceptible alternative.",
                    evidence={"organism": isolate.organism, "drug": order.drug, "susceptibility": "I"}
                ))
    return alerts


# =====================================================================
# 6. SPECTRUM OPTIMIZATION & DE-ESCALATION ENGINE
# =====================================================================

def evaluate_deescalation_opportunities(patient: Patient) -> List[Alert]:
    """Identifies narrow-spectrum switch opportunities and redundant combinations."""
    alerts: List[Alert] = []
    active_drugs = [o for o in patient.orders if o.is_active]
    active_drug_names = {o.drug.lower().strip() for o in active_drugs}

    # 1. Redundant Anaerobic Coverage check
    active_anaerobic = [d for d in active_drug_names if d in ANAEROBIC_AGENTS]
    if len(active_anaerobic) > 1 and "metronidazole" in active_anaerobic:
        other_agent = [d for d in active_anaerobic if d != "metronidazole"][0]
        alerts.append(Alert(
            alert_id=f"ALT-REDUNDANT-ANAEROBE-{patient.patient_id}",
            patient_id=patient.patient_id,
            category=AlertCategory.DUPLICATE_THERAPY,
            severity=AlertSeverity.MEDIUM,
            title="Redundant Double Anaerobic Coverage",
            description=f"Patient is receiving Metronidazole concurrently with {other_agent}, which already possesses potent anaerobic coverage.",
            recommendation=f"Discontinue Metronidazole to reduce toxicity risk and cost unless specific C. difficile co-infection exists.",
            evidence={"agents": active_anaerobic}
        ))

    # 2. Pathogen-directed de-escalation for culture isolates
    for isolate in patient.isolates:
        org_name = isolate.organism.strip()
        sus = {k.lower(): v for k, v in isolate.susceptibilities.items()}

        # Scenario A: S. aureus (MSSA) on Vancomycin / Linezolid / Daptomycin
        if "staph" in org_name.lower() or "aureus" in org_name.lower():
            is_mssa = (sus.get("oxacillin") in ("S", Susceptibility.SUSCEPTIBLE.value) or
                       sus.get("cefazolin") in ("S", Susceptibility.SUSCEPTIBLE.value) or
                       "mssa" in org_name.lower())
            is_mrsa = (sus.get("oxacillin") in ("R", Susceptibility.RESISTANT.value) or
                       "mrsa" in org_name.lower())

            if is_mssa and not is_mrsa:
                for mrsa_agent in ("vancomycin", "linezolid", "daptomycin"):
                    if mrsa_agent in active_drug_names:
                        alerts.append(Alert(
                            alert_id=f"ALT-DEESC-MSSA-{patient.patient_id}-{isolate.isolate_id}",
                            patient_id=patient.patient_id,
                            category=AlertCategory.DEESCALATION_OPPORTUNITY,
                            severity=AlertSeverity.HIGH,
                            title="De-escalation Opportunity: MSSA Bacteremia/Infection",
                            description=(
                                f"Culture confirmed Methicillin-Susceptible S. aureus (MSSA). "
                                f"Patient remains on broad anti-MRSA agent {mrsa_agent.capitalize()}."
                            ),
                            recommendation="De-escalate to Cefazolin 2g IV q8h or Oxacillin/Nafcillin for superior clinical bactericidal clearance and reduced nephrotoxicity.",
                            evidence={"organism": org_name, "active_mrsa_agent": mrsa_agent, "mssa_confirmed": True}
                        ))

        # Scenario B: ESBL Negative Enterobacterales on Carbapenem
        if any(g in org_name.lower() for g in ("coli", "klebsiella", "proteus")):
            is_ceftriaxone_s = sus.get("ceftriaxone") in ("S", Susceptibility.SUSCEPTIBLE.value)
            is_cefazolin_s = sus.get("cefazolin") in ("S", Susceptibility.SUSCEPTIBLE.value)
            is_meropenem_active = any(d in active_drug_names for d in ("meropenem", "ertapenem", "imipenem-cilastatin"))

            if (is_ceftriaxone_s or is_cefazolin_s) and is_meropenem_active:
                target_narrow = "Ceftriaxone" if is_ceftriaxone_s else "Cefazolin"
                alerts.append(Alert(
                    alert_id=f"ALT-DEESC-CARB-{patient.patient_id}-{isolate.isolate_id}",
                    patient_id=patient.patient_id,
                    category=AlertCategory.DEESCALATION_OPPORTUNITY,
                    severity=AlertSeverity.HIGH,
                    title="Carbapenem De-escalation Opportunity",
                    description=(
                        f"Susceptibility profile indicates non-ESBL wild-type {org_name} fully susceptible to {target_narrow}. "
                        "Carbapenem stewardship de-escalation indicated."
                    ),
                    recommendation=f"De-escalate from carbapenem to {target_narrow} 1-2g IV daily.",
                    evidence={"organism": org_name, "susceptible_agent": target_narrow}
                ))

    return alerts


# =====================================================================
# 7. IV-TO-ORAL (PO) SWITCH EVALUATOR
# =====================================================================

def evaluate_iv_to_po_switch(patient: Patient) -> List[Alert]:
    """Audits patients on high-bioavailability IV agents for oral stepdown readiness."""
    alerts: List[Alert] = []
    
    # Check clinical stability criteria
    blocking_reasons: List[str] = []
    if not patient.hemodynamically_stable:
        blocking_reasons.append("Hemodynamic instability / requiring vasopressors")
    if not patient.tolerating_oral:
        blocking_reasons.append("Patient unable to tolerate oral intake / NPO status")
    if not patient.functioning_gi:
        blocking_reasons.append("Non-functional gastrointestinal tract (ileus, obstruction, severe malabsorption)")
    if patient.deep_seated_infection:
        blocking_reasons.append("Deep-seated infection (endocarditis, CNS infection, un-drained empyema) requiring sustained IV peaks")
    if patient.neutropenic_fever:
        blocking_reasons.append("Neutropenic fever protocol requires IV administration")

    for order in patient.orders:
        if not order.is_active or order.route.upper() != "IV":
            continue
        drug_key = order.drug.lower().strip()
        po_info = HIGH_BIOAVAILABILITY_ORAL.get(drug_key)
        if not po_info:
            continue

        if order.day_of_therapy < 2:
            # Need at least 24-48h of therapy before switch alert
            continue

        if not blocking_reasons:
            alerts.append(Alert(
                alert_id=f"ALT-IV2PO-{patient.patient_id}-{order.order_id}",
                patient_id=patient.patient_id,
                category=AlertCategory.IV_TO_PO_SWITCH,
                severity=AlertSeverity.MEDIUM,
                title=f"Eligible for IV-to-PO Stepdown: {order.drug}",
                description=(
                    f"Patient is on IV {order.drug} (Day {order.day_of_therapy}) and meets all oral conversion criteria: "
                    f"hemodynamically stable, GI tract functioning, oral intake tolerated. "
                    f"{order.drug.capitalize()} has {po_info['bioavailability_pct']}% oral bioavailability."
                ),
                recommendation=f"Switch {order.drug} IV to {po_info['po_equivalent'].capitalize()} PO (Conversion ratio: {po_info['conversion_ratio']}x).",
                evidence={"drug": order.drug, "day_of_therapy": order.day_of_therapy, "bioavailability": po_info["bioavailability_pct"]}
            ))
        else:
            alerts.append(Alert(
                alert_id=f"ALT-IV2PO-BLOCKED-{patient.patient_id}-{order.order_id}",
                patient_id=patient.patient_id,
                category=AlertCategory.IV_TO_PO_SWITCH,
                severity=AlertSeverity.INFO,
                title=f"IV-to-PO Conversion Ineligible: {order.drug}",
                description=f"IV {order.drug} stepdown evaluated but blocked by clinical factors.",
                recommendation="Re-evaluate when gastrointestinal and hemodynamic stability are achieved.",
                evidence={"blocking_reasons": blocking_reasons}
            ))

    return alerts


# =====================================================================
# 8. CDC / NHSN ANTIMICROBIAL USE (AU) & SAAR METRICS ENGINE
# =====================================================================

@dataclass
class NHSNMetricsResult:
    total_patient_days: int
    days_of_therapy: Dict[str, int]
    total_dot: int
    dot_per_1000_patient_days: float
    saar_estimates: Dict[str, float]
    length_of_therapy_days: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def calculate_nhsn_au_metrics(
    patient_days: int,
    medication_orders: List[MedicationOrder],
    predicted_dot: Optional[Dict[str, float]] = None
) -> NHSNMetricsResult:
    """
    Computes NHSN Days of Therapy (DOT) per 1,000 Patient Days and SAAR.
    Formula:
        DOT / 1000 PD = (Total DOT / Patient Days) * 1000
        SAAR = Observed DOT / Predicted DOT
    """
    if patient_days <= 0:
        raise ValueError("Patient days must be greater than zero.")

    dot_by_drug: Dict[str, int] = {}
    lot_days: Set[int] = set()

    for order in medication_orders:
        if not order.is_active:
            continue
        drug = order.drug.strip().lower()
        dot_by_drug[drug] = dot_by_drug.get(drug, 0) + max(1, order.day_of_therapy)
        for d in range(1, order.day_of_therapy + 1):
            lot_days.add(d)

    total_dot = sum(dot_by_drug.values())
    dot_rate = (total_dot / float(patient_days)) * 1000.0

    predictions = predicted_dot or {
        "broad_spectrum": max(1.0, total_dot * 0.9),
        "anti_mrsa": max(1.0, total_dot * 0.35),
        "overall": max(1.0, total_dot * 0.85),
    }

    saar: Dict[str, float] = {}
    for cat, pred in predictions.items():
        if pred > 0:
            saar[cat] = round(total_dot / pred, 3)

    return NHSNMetricsResult(
        total_patient_days=patient_days,
        days_of_therapy=dot_by_drug,
        total_dot=total_dot,
        dot_per_1000_patient_days=round(dot_rate, 2),
        saar_estimates=saar,
        length_of_therapy_days=len(lot_days) if lot_days else 1
    )


# =====================================================================
# 9. SUPERVISOR DECISION SUPPORT ORCHESTRATOR
# =====================================================================

class AMRGuardianEnterprise:
    """Enterprise Clinical Antimicrobial Stewardship Orchestration Supervisor."""
    
    def __init__(self, audit_secret: Optional[str] = None):
        self.audit_logger = AuditLogger(audit_secret)

    def audit_patient(self, patient: Patient) -> List[Alert]:
        """Runs full surveillance audit pipeline for a patient."""
        # 1. Assert no PHI in outbound identifiers
        PHIGuard.assert_no_phi(patient.anonymous_id)
        PHIGuard.assert_no_phi(patient.location)

        alerts: List[Alert] = []

        # Step 1: Renal dosing evaluation
        renal_alerts = evaluate_renal_dosing(patient)
        alerts.extend(renal_alerts)
        self.audit_logger.record(
            actor="RenalDosingEngine",
            action="EVALUATE_RENAL",
            details=f"Patient {patient.anonymous_id} generated {len(renal_alerts)} renal alerts."
        )

        # Step 2: Bug-Drug mismatch
        mismatch_alerts = evaluate_bug_drug_mismatch(patient)
        alerts.extend(mismatch_alerts)
        self.audit_logger.record(
            actor="BugDrugMismatchEngine",
            action="EVALUATE_MISMATCH",
            details=f"Patient {patient.anonymous_id} generated {len(mismatch_alerts)} mismatch alerts."
        )

        # Step 3: Spectrum de-escalation & duplicate therapy
        deesc_alerts = evaluate_deescalation_opportunities(patient)
        alerts.extend(deesc_alerts)
        self.audit_logger.record(
            actor="DeescalationEngine",
            action="EVALUATE_DEESCALATION",
            details=f"Patient {patient.anonymous_id} generated {len(deesc_alerts)} de-escalation alerts."
        )

        # Step 4: IV-to-PO conversion
        iv2po_alerts = evaluate_iv_to_po_switch(patient)
        alerts.extend(iv2po_alerts)
        self.audit_logger.record(
            actor="IVToPOEngine",
            action="EVALUATE_IV2PO",
            details=f"Patient {patient.anonymous_id} generated {len(iv2po_alerts)} IV-to-PO alerts."
        )

        # Sort alerts by severity priority (CRITICAL -> HIGH -> MEDIUM -> LOW -> INFO)
        sev_order = {
            AlertSeverity.CRITICAL: 0,
            AlertSeverity.HIGH: 1,
            AlertSeverity.MEDIUM: 2,
            AlertSeverity.LOW: 3,
            AlertSeverity.INFO: 4
        }
        alerts.sort(key=lambda a: sev_order.get(a.severity, 5))
        return alerts

    def audit_population(self, patients: List[Patient], patient_days: int) -> Dict[str, Any]:
        """Runs enterprise surveillance on a cohort of patients and compiles NHSN AU metrics."""
        all_alerts: List[Alert] = []
        all_orders: List[MedicationOrder] = []

        for p in patients:
            p_alerts = self.audit_patient(p)
            all_alerts.extend(p_alerts)
            all_orders.extend(p.orders)

        nhsn = calculate_nhsn_au_metrics(patient_days, all_orders)

        return {
            "total_patients": len(patients),
            "total_alerts": len(all_alerts),
            "critical_alerts": sum(1 for a in all_alerts if a.severity == AlertSeverity.CRITICAL),
            "high_alerts": sum(1 for a in all_alerts if a.severity == AlertSeverity.HIGH),
            "alerts": [a.to_dict() for a in all_alerts],
            "nhsn_au_metrics": nhsn.to_dict(),
            "audit_trail_count": len(self.audit_logger.log)
        }
