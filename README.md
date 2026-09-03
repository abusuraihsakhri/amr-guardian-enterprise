# AMR Guardian Enterprise

A pure Python hospital-grade Antimicrobial Stewardship (ASP) decision support and antimicrobial resistance surveillance engine implementing:
- **Bug-Drug In Vitro Resistance Mismatch Detection:** Flags active antibiotic orders with documented microbiological resistance (R) across blood and sterile-site isolates.
- **Renal Dosing & Neurotoxicity Safety Engine:** Evaluates Cockcroft-Gault Creatinine Clearance ($\text{CrCl}$) using Devine Ideal Body Weight (IBW) and adjusted body weight adjustments, guarding against cefepime neurotoxicity, piperacillin/tazobactam overdosing, and vancomycin accumulation.
- **De-escalation & Spectrum Optimization:** Identifies Day 2+ opportunities to narrow broad empiric anti-MRSA therapy (e.g. vancomycin $\rightarrow$ cefazolin/nafcillin upon confirmed MSSA bacteremia).
- **Automated IV-to-PO Stepdown Protocol:** High-bioavailability oral conversion alerts (Levofloxacin, Metronidazole, Linezolid, Fluconazole) for hemodynamically stable patients tolerating oral intake.
- **CDC / NHSN Antimicrobial Use (AU) Metrics:** Calculates Days of Therapy (DOT) per 1,000 patient-days and Standardized Antimicrobial Administration Ratio (SAAR) approximations.
- **HIPAA Zero-PHI Interceptor & Cryptographic Audit Trail:** AST-level regex inspection and tamper-evident HMAC-SHA256 signed event chains.
- **Batch CSV Cohort Processing:** High-throughput population-level surveillance across clinical wards and inpatient registries.

Requires Python standard library only (zero external runtime dependencies).

---

## Clinical Formulation & Pharmacokinetic Architecture

### Cockcroft-Gault Creatinine Clearance
$$\text{CrCl (mL/min)} = \frac{(140 - \text{Age}) \times \text{Weight (kg)}}{72 \times \text{Serum Creatinine (mg/dL)}} \times (0.85 \text{ if Female})$$

### Dosing Weight Decision Rule
- If $\text{Actual Weight} < \text{IBW}$, use Actual Weight.
- If $\text{Actual Weight} > 1.2 \times \text{IBW}$, use Adjusted Body Weight:
$$\text{AdjBW} = \text{IBW} + 0.4 \times (\text{Actual Weight} - \text{IBW})$$

### NHSN Antimicrobial Use Rate
$$\text{DOT Rate} = \frac{\text{Total Days of Therapy (DOT)}}{\text{Monitored Patient-Days}} \times 1,000$$

---

## Features

- **CLSI M100 & EUCAST Alignment:** Validates microbiological susceptibility reporting and discordant therapy.
- **Neurotoxicity & Nephrotoxicity Guardrails:** Enforces maximum safe daily doses under renal impairment (e.g., Cefepime max 2g q12h for $\text{CrCl} \le 50\text{ mL/min}$).
- **Surveillance Population Auditing:** Aggregates alerts across ICU and ward cohorts into prioritized clinical queues.
- **Batch CSV Processing:** High-throughput evaluation of hospital admission files.

---

## Installation & Requirements

- Python 3.10+ (tested on 3.10, 3.11, 3.12)
- Zero external runtime dependencies. `pytest` is optional for running tests.

```bash
git clone https://github.com/abusuraihsakhri/amr-guardian-enterprise.git
cd amr-guardian-enterprise
```

---

## CLI Usage

### 1. Surveillance Audit on Benchmark Inpatient Population
```bash
python cli.py --audit --json
```

### 2. Cockcroft-Gault Creatinine Clearance Calculator
```bash
python cli.py --crcl 68 M 75.0 2.4 175.0
```

### 3. Batch CSV Patient Cohort Evaluation
```bash
python cli.py --batch sample.csv results.csv
```

---

## Python API Quickstart

```python
from amr_guardian_enterprise import (
    AMRGuardianEnterprise,
    Patient,
    MedicationOrder,
    CultureIsolate,
)

# 1. Initialize Engine
guardian = AMRGuardianEnterprise()

# 2. Build Inpatient Case
patient = Patient(
    patient_id="PT-2026-01",
    age=68,
    gender="Male",
    weight_kg=75.0,
    serum_creatinine=2.4,
    orders=[
        MedicationOrder("ORD-1", "PT-2026-01", "Cefepime", dose_mg=2000.0, interval_hours=8)
    ]
)

# 3. Evaluate Alerts
alerts = guardian.audit_patient(patient)
for a in alerts:
    print(f"[{a.severity.value}] {a.title}: {a.recommendation}")
```

---

## Running Tests

Run the test suite using standard `unittest` or `pytest`:

```bash
pytest -v
```

