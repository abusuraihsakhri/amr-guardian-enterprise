#!/usr/bin/env python3
"""
Stewardship decision-support enrichment features for amr-guardian-enterprise.

Implements three high-impact items from specifications:

1. Antibiotic spectrum optimization engine
   Ranks empiric agents by coverage match against suspected organisms for the
   infection site, penalizing unnecessary broad-spectrum exposure and
   incorporating local antibiogram resistance rates.

2. Automated IV-to-PO conversion alerts
   Criteria-based oral-switch eligibility using bioequivalence classes
   (fluoroquinolones/linezolid/metronidazole/TMP-SMX reach near-IV exposure).

3. De-escalation opportunity detector
   Cross-references the active regimen with final culture susceptibilities to
   find narrow-spectrum switches and bug-drug mismatches.

Author: Dr. Abu Suraih Sakhri
License: MIT
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

ORGANISM_TAGS: Dict[str, Set[str]] = {
    "E. coli": {"gram_neg", "enterobacterales"},
    "Klebsiella pneumoniae": {"gram_neg", "enterobacterales"},
    "Enterobacter spp.": {"gram_neg", "enterobacterales", "ampc_risk"},
    "Pseudomonas aeruginosa": {"gram_neg", "pseudomonas"},
    "S. aureus (MSSA)": {"gram_pos", "staph_mssa"},
    "S. aureus (MRSA)": {"gram_pos", "mrsa"},
    "Streptococcus pneumoniae": {"gram_pos", "streptococcus"},
    "Enterococcus faecalis": {"gram_pos", "enterococcus"},
    "Bacteroides fragilis": {"anaerobe"},
}

COVERAGE_MATRIX: Dict[str, Set[str]] = {
    "cefazolin": {"gram_pos", "staph_mssa", "enterobacterales"},
    "ceftriaxone": {"gram_pos", "streptococcus", "enterobacterales"},
    "cefepime": {"gram_neg", "enterobacterales", "pseudomonas", "ampc_risk", "gram_pos"},
    "piperacillin-tazobactam": {"gram_neg", "enterobacterales", "pseudomonas",
                                "anaerobe", "gram_pos", "staph_mssa"},
    "meropenem": {"gram_neg", "enterobacterales", "pseudomonas", "anaerobe",
                  "gram_pos", "staph_mssa", "ampc_risk", "esbl"},
    "vancomycin": {"mrsa", "enterococcus", "gram_pos"},
    "linezolid": {"mrsa", "enterococcus", "gram_pos"},
    "levofloxacin": {"gram_neg", "enterobacterales", "pseudomonas", "gram_pos",
                     "streptococcus", "staph_mssa"},
    "metronidazole": {"anaerobe"},
    "piperacillin-tazobactam+metronidazole": {"gram_neg", "enterobacterales",
                                              "anaerobe", "gram_pos", "staph_mssa"},
    "nitrofurantoin": {"enterobacterales"},
}

SITE_REQUIREMENTS: Dict[str, Dict[str, object]] = {
    "cystitis": {"required_tags": {"enterobacterales"}, "preferred_bonus":
                 {"nitrofurantoin": 2.0}, "broad_penalty_cap": 0},
    "community_acquired_pneumonia": {"required_tags": {"streptococcus", "gram_pos"},
                                     "preferred_bonus": {}, "broad_penalty_cap": 1},
    "hospital_acquired_pneumonia": {"required_tags": {"gram_neg", "pseudomonas"},
                                    "preferred_bonus": {}, "broad_penalty_cap": 2},
    "intra_abdominal": {"required_tags": {"enterobacterales", "anaerobe"},
                        "preferred_bonus": {}, "broad_penalty_cap": 2},
}

BROAD_SPECTRUM_FLAGS = {"meropenem", "cefepime", "piperacillin-tazobactam"}


@dataclass(frozen=True)
class EmpiricOption:
    drug: str
    score: float
    covers_all_suspects: bool
    missing_coverage: frozenset = field(default_factory=frozenset)


def spectrum_optimization(site: str, suspected_organisms: List[str],
                          candidate_drugs: List[str],
                          local_resistance_pct: Optional[Dict[str, float]] = None,
                          mrsa_prevalent: bool = False) -> List[EmpiricOption]:
    """Rank empiric choices by coverage fit minus breadth and resistance penalties."""
    if site not in SITE_REQUIREMENTS:
        raise ValueError(f"unknown site {site!r}; known: {sorted(SITE_REQUIREMENTS)}")

    required: Set[str] = set(SITE_REQUIREMENTS[site]["required_tags"])
    preferred: Dict[str, float] = dict(SITE_REQUIREMENTS[site]["preferred_bonus"])
    penalty_cap = int(SITE_REQUIREMENTS[site]["broad_penalty_cap"])

    suspect_tags: Set[str] = set()
    for organism in suspected_organisms:
        if organism not in ORGANISM_TAGS:
            raise ValueError(f"unknown organism {organism!r}")
        suspect_tags |= ORGANISM_TAGS[organism]
    if site == "hospital_acquired_pneumonia" and mrsa_prevalent:
        suspect_tags.add("mrsa")

    ranked: List[EmpiricOption] = []
    resistance_pct = local_resistance_pct or {}
    for drug in candidate_drugs:
        if drug not in COVERAGE_MATRIX:
            raise ValueError(f"drug {drug!r} missing from coverage matrix")
        covered = COVERAGE_MATRIX[drug]
        missing = {tag for tag in suspect_tags if tag not in covered}
        extra = len(covered - suspect_tags)

        score = 2.0 * len(suspect_tags & covered)
        score -= min(float(extra), float(penalty_cap))
        if drug in BROAD_SPECTRUM_FLAGS and "esbl" not in suspect_tags \
                and "pseudomonas" not in suspect_tags and "ampc_risk" not in suspect_tags:
            score -= 1.5
        score += preferred.get(drug, 0.0)
        score -= resistance_pct.get(drug, 0.0) / 10.0

        ranked.append(EmpiricOption(
            drug=drug,
            score=round(score, 3),
            covers_all_suspects=not missing,
            missing_coverage=frozenset(missing),
        ))
    return sorted(ranked, key=lambda o: o.score, reverse=True)


HIGH_BIOAVAILABILITY_ORAL: Dict[str, str] = {
    "levofloxacin": "99%",
    "ciprofloxacin": "70-80%",
    "linezolid": "100%",
    "metronidazole": "~100%",
    "trimethoprim-sulfamethoxazole": "~100% (TMP), ~90% (SMX)",
    "fluconazole": ">90%",
    "doxycycline": "~95%",
    "clindamycin": "~90% (absorption not impaired by mild GI illness)",
}


def iv_to_po_eligible(drug: str, hemodynamically_stable: bool,
                      tolerating_oral_intake: bool, functioning_gi_tract: bool,
                      deep_seated_infection: bool = False,
                      neutropenic_fever: bool = False) -> Dict[str, object]:
    """Feature 3: rule-based switch alert with blocking-reason audit."""
    reasons: List[str] = []
    if not hemodynamically_stable:
        reasons.append("hemodynamic instability")
    if not tolerating_oral_intake:
        reasons.append("not tolerating oral intake")
    if not functioning_gi_tract:
        reasons.append("GI tract not functional (ileus/obstruction/high-output fistula)")
    if deep_seated_infection:
        reasons.append("deep-seated infection requiring sustained IV levels")
    if neutropenic_fever:
        reasons.append("neutropenic fever protocol requires IV therapy")

    po_equivalent = HIGH_BIOAVAILABILITY_ORAL.get(drug)
    if po_equivalent is None:
        reasons.append(f"{drug} has no reliable oral equivalent formulation")

    eligible = len(reasons) == 0
    return {
        "eligible_for_iv_to_po_switch": eligible,
        "oral_bioavailability": po_equivalent,
        "blocking_reasons": reasons,
    }


def de_escalation_review(current_regimen: List[str],
                         cultures: List[Dict[str, object]]) -> List[Dict[str, object]]:
    """Feature 7: narrow the regimen when susceptibilities allow; flag mismatches."""
    actions: List[Dict[str, object]] = []
    all_covering_narrow: List[str] = []

    for culture in cultures:
        organism = str(culture["organism"])
        sus: Dict[str, str] = culture["susceptibilities"]
        susceptible_current = [d for d in current_regimen if sus.get(d) == "S"]
        resistant_current = [d for d in current_regimen if sus.get(d) in ("R", "I")]

        for drug in resistant_current:
            actions.append({
                "action_type": "bug_drug_mismatch",
                "organism": organism,
                "detail": f"{organism} is nonsusceptible to active IV agent {drug}",
            })
        if not susceptible_current:
            continue
        narrow_candidates = [
            d for d in susceptible_current
            if d not in BROAD_SPECTRUM_FLAGS
            and COVERAGE_MATRIX.get(d, set()) & ORGANISM_TAGS.get(organism, set())
        ]
        if narrow_candidates:
            all_covering_narrow.append(min(narrow_candidates))
        else:
            all_covering_narrow.append(susceptible_current[0])

    if cultures and all_covering_narrow:
        target = max(set(all_covering_narrow), key=all_covering_narrow.count)
        if target not in current_regimen:
            actions.append({
                "action_type": "de_escalation",
                "detail": (
                    f"all cultured organisms susceptible to {target}; "
                    f"narrow from {current_regimen} to {target}"
                ),
            })
    return actions


def _demo() -> None:
    ranked = spectrum_optimization(
        site="hospital_acquired_pneumonia",
        suspected_organisms=["Pseudomonas aeruginosa", "S. aureus (MRSA)"],
        candidate_drugs=["cefepime", "piperacillin-tazobactam", "meropenem",
                         "levofloxacin", "vancomycin", "linezolid"],
        local_resistance_pct={"cefepime": 18.0, "piperacillin-tazobactam": 22.0},
        mrsa_prevalent=True,
    )
    for option in ranked[:4]:
        print({"drug": option.drug, "score": option.score,
               "covers_all": option.covers_all_suspects})

    print(iv_to_po_eligible("levofloxacin", True, True, True))

    review = de_escalation_review(
        current_regimen=["meropenem"],
        cultures=[{
            "organism": "E. coli",
            "susceptibilities": {"meropenem": "S", "ceftriaxone": "S",
                                 "ciprofloxacin": "R"},
        }],
    )
    for item in review:
        print(item)


if __name__ == "__main__":
    _demo()
