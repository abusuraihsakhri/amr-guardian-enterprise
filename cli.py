#!/usr/bin/env python3
"""
AMR Guardian Enterprise - Command Line Interface (CLI)

Surveillance audit, renal dosing evaluation, de-escalation checks,
IV-to-PO switch assessments, NHSN AU metrics, and interactive clinical queries.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List

from amr_guardian_enterprise import (
    AMRGuardianEnterprise,
    Alert,
    AlertCategory,
    AlertSeverity,
    CultureIsolate,
    MedicationOrder,
    Patient,
    PHIGuard,
    SecurityException,
    Susceptibility,
    calculate_cockcroft_gault_crcl,
    calculate_nhsn_au_metrics,
    evaluate_bug_drug_mismatch,
    evaluate_deescalation_opportunities,
    evaluate_iv_to_po_switch,
    evaluate_renal_dosing,
)


def create_demo_patients() -> List[Patient]:
    """Generates standard benchmark clinical scenarios for demonstration and testing."""
    return [
        Patient(
            patient_id="PT-001",
            anonymous_id="ANON-KLEB-401",
            age=68,
            gender="Male",
            weight_kg=75.0,
            height_cm=175.0,
            serum_creatinine=2.4,  # Impaired renal function (CrCl ~29 mL/min)
            location="MICU-Bed04",
            hemodynamically_stable=True,
            tolerating_oral=False,
            functioning_gi=True,
            isolates=[
                CultureIsolate(
                    isolate_id="ISO-001",
                    patient_id="PT-001",
                    specimen_source="Blood",
                    organism="Klebsiella pneumoniae (ESBL+)",
                    susceptibilities={
                        "Piperacillin-Tazobactam": "R",
                        "Ceftriaxone": "R",
                        "Cefepime": "R",
                        "Meropenem": "S",
                        "Amikacin": "S",
                    },
                    resistance_markers=["ESBL"]
                )
            ],
            orders=[
                MedicationOrder(
                    order_id="ORD-001",
                    patient_id="PT-001",
                    drug="Piperacillin-Tazobactam",
                    dose_mg=3375.0,
                    interval_hours=6,
                    route="IV",
                    day_of_therapy=3,
                    is_active=True,
                ),
                MedicationOrder(
                    order_id="ORD-002",
                    patient_id="PT-001",
                    drug="Cefepime",
                    dose_mg=2000.0,
                    interval_hours=8,
                    route="IV",
                    day_of_therapy=1,
                    is_active=True,
                )
            ]
        ),
        Patient(
            patient_id="PT-002",
            anonymous_id="ANON-MSSA-882",
            age=54,
            gender="Female",
            weight_kg=62.0,
            height_cm=162.0,
            serum_creatinine=0.8,
            location="StepDown-12",
            hemodynamically_stable=True,
            tolerating_oral=True,
            functioning_gi=True,
            isolates=[
                CultureIsolate(
                    isolate_id="ISO-002",
                    patient_id="PT-002",
                    specimen_source="Blood",
                    organism="Staphylococcus aureus (MSSA)",
                    susceptibilities={
                        "Oxacillin": "S",
                        "Cefazolin": "S",
                        "Vancomycin": "S",
                        "Levofloxacin": "S"
                    }
                )
            ],
            orders=[
                MedicationOrder(
                    order_id="ORD-003",
                    patient_id="PT-002",
                    drug="Vancomycin",
                    dose_mg=1250.0,
                    interval_hours=12,
                    route="IV",
                    day_of_therapy=3,
                    is_active=True,
                )
            ]
        ),
        Patient(
            patient_id="PT-003",
            anonymous_id="ANON-CAP-103",
            age=45,
            gender="Male",
            weight_kg=80.0,
            height_cm=180.0,
            serum_creatinine=0.9,
            location="Floor-4W",
            hemodynamically_stable=True,
            tolerating_oral=True,
            functioning_gi=True,
            isolates=[],
            orders=[
                MedicationOrder(
                    order_id="ORD-004",
                    patient_id="PT-003",
                    drug="Levofloxacin",
                    dose_mg=750.0,
                    interval_hours=24,
                    route="IV",
                    day_of_therapy=3,
                    is_active=True,
                ),
                MedicationOrder(
                    order_id="ORD-005",
                    patient_id="PT-003",
                    drug="Metronidazole",
                    dose_mg=500.0,
                    interval_hours=8,
                    route="IV",
                    day_of_therapy=3,
                    is_active=True,
                )
            ]
        )
    ]


def run_audit(json_output: bool = False, output_file: str | None = None) -> None:
    """Executes antimicrobial stewardship surveillance audit on demo patient panel."""
    guardian = AMRGuardianEnterprise()
    patients = create_demo_patients()
    result = guardian.audit_population(patients, patient_days=250)

    if json_output:
        out_str = json.dumps(result, indent=2)
        if output_file:
            with open(output_file, "w", encoding="utf-8") as f:
                f.write(out_str)
            print(f"Audit results successfully written to {output_file}")
        else:
            print(out_str)
        return

    print("=" * 76)
    print("      AMR GUARDIAN ENTERPRISE - STEWARDSHIP SURVEILLANCE REPORT       ")
    print("=" * 76)
    print(f" Total Monitored Patients : {result['total_patients']}")
    print(f" Total Identified Alerts  : {result['total_alerts']}")
    print(f" Critical Urgency Alerts  : {result['critical_alerts']}")
    print(f" High Urgency Alerts      : {result['high_alerts']}")
    print(f" Audit Trail Events Signed: {result['audit_trail_count']}")
    print("-" * 76)
    print(" ACTIVE CLINICAL ALERTS:")
    print("-" * 76)

    for i, a in enumerate(result["alerts"], 1):
        sev = a["severity"]
        cat = a["category"]
        title = a["title"]
        pid = a["patient_id"]
        print(f" [{i}] [{sev}] [{cat}] (Patient: {pid})")
        print(f"     Title: {title}")
        print(f"     Issue: {a['description']}")
        print(f"     Action: {a['recommendation']}")
        print()

    print("-" * 76)
    print(" CDC / NHSN ANTIMICROBIAL USE (AU) BENCHMARKS:")
    print("-" * 76)
    au = result["nhsn_au_metrics"]
    print(f" Monitored Patient Days  : {au['total_patient_days']}")
    print(f" Total Days of Therapy   : {au['total_dot']}")
    print(f" DOT / 1,000 Patient Days: {au['dot_per_1000_patient_days']:.2f}")
    print(f" Standardized SAAR Ratio : {au['saar_estimates']}")
    print("=" * 76)


def run_crcl_calculator(age: int, gender: str, weight: float, scr: float, height: float | None = None) -> None:
    """Calculates Cockcroft-Gault CrCl and ideal/adjusted weight."""
    res = calculate_cockcroft_gault_crcl(age, gender, weight, scr, height)
    print("--- Renal Function Evaluation ---")
    print(f" Creatinine Clearance (CrCl) : {res['crcl_ml_min']} mL/min")
    print(f" Ideal Body Weight (IBW)     : {res['ibw_kg']} kg")
    print(f" Dosing Weight Used          : {res['dosing_weight_kg']} kg")
    print(f" Adjusted Weight Applied     : {res['used_adjusted_weight']}")


def interactive_mode() -> None:
    """Interactive CLI terminal for evaluating clinical antimicrobial cases."""
    print("Starting AMR Guardian Enterprise Interactive Terminal...")
    print("Type 'help' for commands, 'demo' for sample audit, 'exit' to quit.\n")
    guardian = AMRGuardianEnterprise()

    while True:
        try:
            cmd = input("amr-enterprise> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not cmd:
            continue
        if cmd.lower() in ("exit", "quit"):
            print("Session ended.")
            break
        elif cmd.lower() == "help":
            print("Commands:")
            print("  audit                  - Run full surveillance audit on benchmark cases")
            print("  crcl <age> <M/F> <wt_kg> <scr> [ht_cm] - Calculate CrCl")
            print("  phi <text>             - Test text against HIPAA PHI outbound guard")
            print("  exit                   - Quit terminal")
        elif cmd.lower() == "audit":
            run_audit(json_output=False)
        elif cmd.lower().startswith("phi "):
            text = cmd[4:].strip()
            try:
                PHIGuard.assert_no_phi(text)
                print("[SAFE] No PHI detected in string.")
            except SecurityException as e:
                print(f"[ALERT] {e}")
                print(f"Sanitized string: {PHIGuard.redact_phi(text)}")
        elif cmd.lower().startswith("crcl "):
            parts = cmd.split()[1:]
            if len(parts) < 4:
                print("Usage: crcl <age> <M/F> <wt_kg> <scr> [ht_cm]")
                continue
            try:
                age = int(parts[0])
                gender = parts[1]
                weight = float(parts[2])
                scr = float(parts[3])
                ht = float(parts[4]) if len(parts) >= 5 else None
                run_crcl_calculator(age, gender, weight, scr, ht)
            except Exception as ex:
                print(f"Error calculating CrCl: {ex}")
        else:
            print(f"Unknown command: {cmd}. Type 'help' for available commands.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AMR Guardian Enterprise - Antimicrobial Stewardship Decision Support"
    )
    parser.add_argument("--audit", action="store_true", help="Execute full surveillance audit")
    parser.add_argument("--interactive", "-i", action="store_true", help="Launch interactive CLI")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format")
    parser.add_argument("--output", "-o", type=str, help="Write output to specified file")
    parser.add_argument("--crcl", nargs="+", help="Calculate CrCl: <age> <gender(M/F)> <weight_kg> <scr_mg_dl> [height_cm]")

    args = parser.parse_args()

    if args.crcl:
        if len(args.crcl) < 4:
            print("Error: CrCl calculation requires at least: <age> <M/F> <weight_kg> <scr_mg_dl>")
            sys.exit(1)
        age = int(args.crcl[0])
        gender = args.crcl[1]
        weight = float(args.crcl[2])
        scr = float(args.crcl[3])
        ht = float(args.crcl[4]) if len(args.crcl) > 4 else None
        run_crcl_calculator(age, gender, weight, scr, ht)
    elif args.interactive:
        interactive_mode()
    elif args.audit or len(sys.argv) == 1:
        run_audit(json_output=args.json, output_file=args.output)


if __name__ == "__main__":
    main()
