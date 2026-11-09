# ODOO-PARSER (Intelligent Data Importer)

A native **Odoo 19** module that transforms raw files (Excel / CSV) into clean Odoo records through an AI-assisted ETL pipeline. Integrative Project 2 – EAFIT.

---

## 1. Application Information

### Problem
Customer data mapping is a manual task. When migrating to Odoo or receiving third-party databases (distributors, trade fairs, chambers of commerce, legacy systems), each file comes with different column headers: `NIT`, `Nit Cliente`, `Identificación`, `Doc.`, or `RUT` all mean the same thing, but Odoo expects the `vat` field. The analyst must interpret each column, rename it manually, and run the native importer, which fails at the first inconsistency, forcing them to repeat the entire process (between 2 and 5 hours per file).

### Solution
**Intelligent Data Importer** (`smart_data_importer`) automatically identifies which Odoo field corresponds to each column, cleans and validates values, detects duplicates, and displays everything to the user **before** writing to the database (*human-in-the-loop*: no data is ever written without explicit confirmation).

### Main Features
- Reads **CSV, XLSX/XLSM, and XLS** files with automatic detection of encoding, delimiter, header row, and worksheets (skips instruction sheets or sheets containing "possible values").
- **Automatic cascading column mapping** with confidence scores and explanations.
- **Reusable templates**: if headers match those from a previous import, the mapping is applied automatically.
- **Data cleansing rules** (email, phone, document/VAT, etc.).
- **Duplicate detection** with configurable criteria (VAT, email, VAT or email, automatic) and policies (update, skip, create).
- **Preview** displaying original and mapped data side by side, with manual column and value correction.
- **Value correction memory** for future imports.
- **Row-level error explanations** and error summaries (pre-validation and import).
- **Queued batch processing** for large volumes, with progress tracking.
- Supports multiple Odoo target models (e.g., `res.partner`, accounts, taxes, products).

---

## 2. How Does It Work?

```
File (CSV/Excel)
      │
      ▼
 1. Reading and detection (encoding, delimiter, headers, worksheet)
      │
      ▼
 2. Does a template with the same header signature exist? ── yes ──► apply saved mapping
      │ no
      ▼
 3. Cascading mapping (only unresolved fields move to the next level)
      ├─ Level 1 · Hash      → synonym dictionary ("NIT" → vat)
      ├─ Level 2 · Fuzzy     → text similarity using RapidFuzz (accents, capitalization, typos)
      └─ Level 3 · LLM       → semantic analysis using column names + sample values
      │
      ▼
 4. Human review: preview, confidence levels (green→red), corrections
      │
      ▼
 5. Cleansing + validation + deduplication
      │
      ▼
 6. Queued batch import ──► Odoo records
```

**Import session statuses:** `Draft → Analyzing → Mapped → Queued → Processing → Completed / Error`.

### Supported AI Providers (Configurable in Settings)
Anthropic (Claude), OpenAI, DeepSeek, Google Gemini, and any OpenAI-compatible endpoint (Ollama, Groq, OpenRouter, etc.). Includes connection testing and a configurable fuzzy similarity threshold.

> Customer data used for testing is anonymized; no real personal data is sent to the LLM provider.

---

## 3. Technologies and Development Stack

| Layer | Technology |
|---|---|
| Platform | **Odoo 19** (ORM framework, XML views, security, cron, queues) |
| Backend | **Python 3** |
| Frontend | **JavaScript (OWL)** + **XML** templates (preview table) |
| File reading | `pandas`, `openpyxl`, `chardet` |
| Fuzzy mapping | `rapidfuzz` |
| AI integration | `requests` (REST APIs for Anthropic, OpenAI, DeepSeek, Gemini, and compatible providers) |
| Database | **PostgreSQL** (through Odoo) |
| Testing | Odoo tests (`tests/`) and `pytest` for unit testing |
| Code quality | `pylint-odoo` / `ruff` |
| Deployment | Odoo.sh / Odoo 19 environment |
| Version control | Git + GitHub (Conventional Commits) |

**Python Dependencies** (`requirements.txt`): `rapidfuzz`, `pandas`, `openpyxl`, `chardet`, `requests`.

---

## 4. Repository Structure

```
ODOO-PARSER-0-V3/
├── smart_data_importer/       # Main module: intelligent data importer
│   ├── models/                # Sessions, templates, mappings, errors, rules, memory
│   │   └── mixins/            # File, progress, signature, and deduplication mixins
│   ├── services/              # Logic: file_reader, mapper_hash/fuzzy/llm, orchestrator,
│   │                          # cleansing_engine, deduplication_engine, error_explainer...
│   ├── data/                  # Synonym registry, cleansing rules, configuration, sequences
│   ├── views/                 # Views and menus
│   ├── static/src/            # Preview component (JS/XML)
│   ├── security/              # Groups and permissions
│   ├── migrations/            # Data migrations
│   └── tests/                 # Odoo and unit tests (pytest)
├──

**Product Owner:** Jesús Alberto Pérez de la Hoz (Odoo)

## Licencia

LGPL-3
