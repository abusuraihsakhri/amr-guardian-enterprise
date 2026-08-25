# AMR Guardian Enterprise
*Clinical Antimicrobial Stewardship Program (ASP) & Decision Support System*

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10+-brightgreen.svg)](https://python.org)
[![Tests: 100% Pass](https://img.shields.io/badge/Tests-26%20Passed-success.svg)]()

AMR Guardian Enterprise is a production-grade Clinical Antimicrobial Stewardship Decision Support System. It provides real-time surveillance across inpatient panels, actively screening for bug-drug mismatches, organ-function-adjusted dosing anomalies (e.g., Cefepime neurotoxicity prevention), pathogen-directed de-escalation pathways, evidence-based IV-to-oral stepdowns, CDC/NHSN Antimicrobial Use (AU) benchmarks, and cryptographically verified audit trails.

---

## Key Clinical Features & Formulas

### 1. Renal Function & Pharmacokinetic Dosing Engine
Renal clearance is calculated using the **Cockcroft-Gault equation** incorporating **Devine Ideal Body Weight (IBW)** and **Adjusted Body Weight (AdjBW)** for obese patients ($\text{Actual} > 1.2 \times \text{IBW}$):

$$\text{IBW}_{\text{Male}} = 50.0 + 2.3 \times (\text{Height}_{\text{inches}} - 60)$$
$$\text{IBW}_{\text{Female}} = 45.5 + 2.3 \times (\text{Height}_{\text{inches}} - 60)$$
$$\text{AdjBW} = \text{IBW} + 0.4 \times (\text{Actual Weight} - \text{IBW})$$
$$\text{CrCl} = \frac{(140 - \text{Age}) \times \text{Dosing Weight}}{72 \times S_{\text{cr}}} \times [0.85 \text{ if Female}]$$

#### Renal Dose Thresholds:
- **Cefepime**: High-risk neurotoxicity screening. If $\text{CrCl} < 60\text{ mL/min}$, standard $2\text{g q8h}$ triggers a `CRITICAL` alert; recommended adjustments down to $1\text{g q24h}$ for severe impairment.
- **Meropenem**: Adjusted from $1000\text{mg q8h}$ down to $500\text{mg q24h}$ for $\text{CrCl} < 10\text{ mL/min}$.
- **Piperacillin-Tazobactam**: Adjusted from $3.375\text{g q6h}$ to $2.25\text{g q8h}$ for $\text{CrCl} < 20\text{ mL/min}$.
- **Vancomycin**: Interval extensions ($q12h \to q24h \to q48h$ / trough level monitoring).

### 2. In Vitro Bug-Drug Mismatch Detector
Cross-references active medication orders against microbiology culture isolates.
- Generates `CRITICAL` alerts for confirmed in vitro resistance (`R`).
- Generates `HIGH` alerts for intermediate susceptibility (`I`) with exposure risk.

### 3. Pathogen-Directed Spectrum De-Escalation Engine
- **MSSA Bacteremia / Infection**: Identifies patients with Methicillin-Susceptible *S. aureus* still receiving broad-spectrum MRSA agents (Vancomycin, Linezolid, Daptomycin) and recommends de-escalation to Cefazolin or Oxacillin/Nafcillin.
- **Wild-Type Enterobacterales**: Prompts de-escalation from carbapenems (Meropenem, Ertapenem) to narrow beta-lactams (Ceftriaxone, Cefazolin) when isolates test susceptible.
- **Duplicate Anaerobic Coverage**: Detects redundant Metronidazole when an active agent already provides comprehensive anaerobic activity (e.g., Piperacillin-Tazobactam, Meropenem).

### 4. Evidence-Based IV-to-PO Stepdown Evaluator
Screens candidates on IV therapy with high oral bioavailability ($>90\%$) agents:
- Fluoroquinolones (Levofloxacin $99\%$, Moxifloxacin $90\%$, Ciprofloxacin $80\%$)
- Linezolid ($100\%$)
- Metronidazole ($100\%$)
- Trimethoprim-Sulfamethoxazole ($95\%$)
- Fluconazole ($95\%$), Doxycycline ($95\%$), Clindamycin ($90\%$)

**Clinical Eligibility Rules**:
$$\text{Eligible} = (\text{Day of Therapy} \ge 2) \land \text{Hemodynamically Stable} \land \text{Tolerating PO} \land \text{Functional GI} \land \neg \text{Deep-Seated} \land \neg \text{Neutropenic Fever}$$

### 5. CDC / NHSN Antimicrobial Use (AU) & SAAR Metrics
Computes standardized surveillance metrics across inpatient cohorts:
$$\text{Days of Therapy (DOT)} / 1,000 \text{ Patient Days} = \left( \frac{\sum \text{DOT}}{\text{Patient Days}} \right) \times 1,000$$
$$\text{SAAR} = \frac{\text{Observed DOT}}{\text{Predicted DOT}}$$

### 6. HIPAA PHI Guard & HMAC-SHA256 Audit Trail
- Automated outbound scan preventing transmission of 18 HIPAA Safe Harbor identifiers (SSN, MRN, phone numbers, emails, unmasked patient names).
- Tamper-evident HMAC-SHA256 digital signature recorded for every decision event.

---

## Installation & Requirements

AMR Guardian Enterprise is built with pure Python 3.10+ standard library. Zero external dependencies required.

```bash
# Clone the repository
git clone https://github.com/example/amr-guardian-enterprise.git
cd amr-guardian-enterprise
```

---

## CLI Usage

The CLI supports batch surveillance audits, individual renal clearance calculations, interactive decision querying, and JSON export.

### 1. Run Full Stewardship Surveillance Audit
```bash
python cli.py --audit
```

### 2. Export Audit to JSON
```bash
python cli.py --audit --json --output audit_report.json
```

### 3. Calculate Patient Creatinine Clearance
```bash
# Syntax: python cli.py --crcl <age> <gender: M/F> <weight_kg> <serum_creatinine_mg_dl> [height_cm]
python cli.py --crcl 68 M 75 2.4 175
```
Output:
```text
--- Renal Function Evaluation ---
 Creatinine Clearance (CrCl) : 29.4 mL/min
 Ideal Body Weight (IBW)     : 70.7 kg
 Dosing Weight Used          : 72.42 kg
 Adjusted Weight Applied     : True
```

### 4. Launch Interactive Terminal
```bash
python cli.py --interactive
```

---

## Test Suite Execution

Execute the comprehensive 26-test suite using Python's standard unittest framework:

```bash
python -m unittest discover -s tests
# Or run direct test runner:
python -m unittest test_amr_guardian_enterprise.py
```

All 26 test cases validate normal operating paths, edge cases, formula precision, resistance alerts, and security validations with 100% pass rate.

---

## License
MIT License. Developed for clinical antimicrobial stewardship research and healthcare decision support.
