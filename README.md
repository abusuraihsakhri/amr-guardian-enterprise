# Amr Guardian Enterprise

> **Domain:** Infectious Disease Surveillance & Microbiology  
> **Reference Guidelines & Standards:** `CLSI M100, EUCAST & CDC NHSN Clinical Standards`

<div align="center">

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.10%20%7C%203.11%20%7C%203.12-3776AB.svg?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688.svg?logo=fastapi&logoColor=white)
![Audit Trail](https://img.shields.io/badge/Audit-HMAC--SHA256_Tamper--Evident-brightgreen.svg)
![Zero-PHI Guard](https://img.shields.io/badge/Guard-Zero--PHI_Outbound-blue.svg)
![Docker](https://img.shields.io/badge/Docker-Ready-2496ED.svg?logo=docker&logoColor=white)

</div>

---

## 📖 What It Does

**Amr Guardian Enterprise** is an advanced analytical and computational platform implementing In vitro resistance discordance worker, Day 2+ MSSA de-escalation from Vancomycin, dynamic CrCl renal dosing toxicity limits, NHSN AU/AR metrics. (13/13 tests passing).

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

---

## ⚙️ Key Capabilities & Algorithmic Modules

### 🔬 Core Algorithmic & Evaluation Engines

- **`AlertSeverity`** — dedicated module for alert severity evaluation and state verification.
- **`AlertCategory`** — dedicated module for alert category evaluation and state verification.
- **`Susceptibility`** — dedicated module for susceptibility evaluation and state verification.
- **`CultureIsolate`** — dedicated module for culture isolate evaluation and state verification.
- **`MedicationOrder`** — dedicated module for medication order evaluation and state verification.
- **`Patient`** — dedicated module for patient evaluation and state verification.

---

## 📐 Mathematical Formulation & Logic

```text
  TOXICITY_RISK = "TOXICITY_RISK"
  """Calculates Devine Ideal Body Weight in kg."""
  """Calculates Adjusted Body Weight if actual weight > 1.2 * IBW."""
  Formula: CrCl = [(140 - Age) * Weight / (72 * SCr)] * (0.85 if Female)
  ibw = calculate_ibw(gender, height_cm) if height_cm else weight_kg
```

---

## 💻 CLI Quickstart & Usage

### 1. Guided Interactive Mode
```bash
python cli.py
```

### 2. Direct Parameterized Evaluation
```bash
python cli.py --- <value> --audit <value> --interactive <value> --json <value>
```

### Parameter Reference
- `---`: Specifies input measurement or parameter value.
- `--audit`: Specifies input measurement or parameter value.
- `--interactive`: Specifies input measurement or parameter value.
- `--json`: Specifies input measurement or parameter value.
- `--output`: Specifies input measurement or parameter value.
- `--crcl`: Specifies input measurement or parameter value.

### Input Data Schema

| Field | Description | Requirement |
|:------|:------------|:------------|
| `suite_name` | Parameter / observation metric | Required |
| `system_slug` | Parameter / observation metric | Required |
| `standard_reference` | Parameter / observation metric | Required |
| `test_cases` | Parameter / observation metric | Required |

---

## 🛡️ Security & Enterprise Architecture

* **Zero-PHI Outbound Interceptor:** Active AST and regex inspection blocking SSNs, MRNs, phone numbers, and patient identifiers.
* **Tamper-Evident HMAC-SHA256 Audit Trail:** Chained, cryptographically signed logs for every evaluation and state transition.
* **Air-Gapped LLM Reasoning Adapter:** Agnostic integration for local Ollama instances (`llama3`, `mistral`), Claude 3.5 Sonnet, GPT-4o, and deterministic test mocks.
* **Active Learning Bayesian Calibration:** Dynamic tracker updating worker reliability weights and monitoring Brier calibration drift.
* **FastAPI & Prometheus Telemetry:** Exposes OpenAPI 3.1 REST endpoints and operational Prometheus metrics (`/metrics`).

---

## 🧪 Testing & Verification

Run the automated test suite:

```bash
pytest -v
```

Execute high-throughput batch simulation benchmarks:

```bash
python simulator.py --tasks 1000 --concurrency 8
```

---

## 🐳 Container Deployment

```bash
docker build -t amr-guardian-enterprise .
docker run -p 8000:8000 amr-guardian-enterprise
```
