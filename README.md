# Jyot Agentic Monitor

An agentic, multimodal public-safety and product-recall monitor. It ingests news feeds
and free-text notices, extracts text from image and PDF attachments, scores and
deduplicates stories, and produces a prioritized human-review digest. Alerts are never
sent automatically: the system only *proposes* them, and a human must explicitly approve
or reject each one.

This is the deliverable for the **Track B (Extended)** AI Generalist assignment (Jyot AI
Division). All behavior described below is implemented in `jyot_monitor/` and was read
directly from the source; every command and path was checked against the current tree.

> Scope note: the metrics and behaviours reported here were produced in an offline
> environment (no Tesseract binary, no reachable Ollama model service). The system
> degrades deterministically and never fabricates extracted text — see
> [Known Limitations](#known-limitations).

---

## Overview

Each item runs through one agent loop. A planner decides the next tool to call based on
what has already been executed, and a controller enforces per-item steps, USD budgets,
tool permissions, and step-by-step tracing. Text-only items typically finish in one step;
items with attachments escalate through OCR (and optionally a vision second opinion).
Downstream, items are deduplicated, clustered, classified, scored by urgency, and rendered
into a Markdown digest that highlights what changed since the previous run.

## Key Features

Implemented and exercised by the code and tests in this repository:

- **Two ingestion paths** — offline replay (`--replay`, guaranteed zero network access)
  and live RSS/JSON feeds (`--sources`, with persistent cursors).
- **Multimodal extraction** — image preprocessing profiles, Tesseract OCR, a local vision
  engine (Ollama), an explicit OCR router, PDF rendering, and a structured-notice field
  extractor.
- **Agent loop** — a planner with an LLM mode and a deterministic fallback, a controller
  with step and budget guards, and typed, schema-validated tools.
- **Typed tool set** — `ocr_extract`, `vision_describe`, `search_memory`, `verify_claim`,
  `propose_alert`, `finish` (plus `fetch_attachment`, denied during replay).
- **Intelligence layer** — keyword-taxonomy classification, transparent urgency scoring
  with non-LLM signals, cross-modal deduplication, story clustering, and an urgency
  verifier.
- **Safety layer** — prompt-injection detection (text and OCR text), PII redaction,
  spam/coordination heuristics, and SSRF/network guards (scheme allow-list, private-IP
  blocking, size/type limits, magic-byte sniffing).
- **Persistence and reporting** — SQLite for items, caches, clusters, proposals and
  history; Markdown digest generation with change tracking; a human approval queue with
  `approve` / `reject` CLI commands.
- **Observability** — one JSONL trace step per agent action under `traces/`, including
  planner model, chosen tool, rationale, result summary, success, latency, cost, and
  OCR routing metadata.
- **Controlled fault injection** — a replay-only `--fault-injection` flag that forces a
  deterministic OCR failure to test graceful degradation.

## Architecture and Processing Workflow

The pipeline is a set of small, typed modules wired together in
`jyot_monitor/cli.py:build_system`.

```
jyot_monitor/
  cli.py                 CLI entry point (run / approve / reject / eval)
  config.py              Environment-driven AppConfig (pydantic + dotenv)
  database.py            SQLite persistence and caches
  schemas.py             Pydantic schemas (items, scoring, proposals, traces, ...)
  agent/
    planner.py           LLM planner + deterministic fallback policy
    controller.py        Agent loop, budget guards, pre-loop safety scans, tracing
    tools.py             Typed tool registry and permission gating
    trace.py             JSONL trace writer
    prompts.py           Planner / critique / vision prompt text
  extraction/
    preprocess.py        Image preprocessing profiles
    tesseract_engine.py  Classical OCR engine
    vision_engine.py     Vision-language engine (Ollama)
    router.py            Multi-engine routing with fallback
    pdf.py               PDF text extraction and page rendering
    structured_fields.py Structured notice field extraction
  intelligence/
    classification.py    Keyword-taxonomy topic classifier
    scoring.py           Urgency/relevance scoring (transparent, non-LLM signals)
    deduplication.py     Cross-modal dedup (rapidfuzz + imagehash)
    clustering.py        Story clustering and representative selection
    verification.py      Deterministic urgency verification/critique
  safety/
    injection.py         Prompt-injection detection
    pii.py               Email/phone/SSN redaction
    spam.py              Spam/coordination heuristics
    network.py           SSRF guard and safe attachment fetching
  ingestion/
    replay.py            Offline fixture loader (zero network)
    rss.py               Live RSS/JSON ingestion with cursors
  reporting/
    digest.py            Markdown digest generator
    change_tracking.py   New/escalated/unchanged story tracking
  alerting/
    proposals.py         Proposal creation (redacted evidence)
    approval.py          Human approve/reject service
  evaluation/
    run_eval.py          Gold-dataset evaluation harness
    metrics.py           CER, WER, classification, NDCG, percentiles
```

**Workflow for one `run`:**

1. **Ingest** — load items from `--replay <dir|json>` or `--sources <sources.json>`.
2. **Cluster** — group related items (`StoryClusterer`, cross-modal dedup).
3. **Per item:**
   - Pre-loop safety scans (injection, spam) and baseline scoring.
   - Agent loop: the planner picks the next tool until `finish`, budget exhaustion, or the
     step limit. Every step is appended to the JSONL trace.
4. **Persist** — save items, updated clusters, and caches to SQLite.
5. **Digest** — render the Markdown digest with change tracking.

**Deterministic planner ordering** (`agent/planner.py:_deterministic_plan`): run OCR if an
attachment exists -> escalate to `vision_describe` if OCR needs a second opinion ->
`verify_claim` at urgency >= 75 -> `propose_alert` when urgency >= 70 and verified ->
`search_memory` at relevance >= 80 -> `finish`.

**Budgets and limits** (`agent/controller.py`, defaults from `config.py`):
`max_steps_per_item = 6`, item budget `$0.05`, run budget `$1.00`. Hitting either writes a
`budget_limit_reached` / `run_budget_exceeded` trace step and marks the item
`partially_processed`.

## Technology Stack

- **Language/runtime:** Python 3.13 (developed against Python 3.13.7 in `.venv`).
- **Data/validation:** Pydantic v2.
- **Persistence:** SQLite via the standard-library `sqlite3` module (`database.py`).
- **Imaging/OCR/PDF:** Pillow, pytesseract (+ external Tesseract binary), PyMuPDF, imagehash.
- **Text matching:** rapidfuzz.
- **Local model calls:** `requests` against a local Ollama endpoint (HTTP) for the planner
  and the vision-language model. No cloud model service is used.
- **Feeds/config:** feedparser, python-dotenv.
- **Testing:** pytest.
- **No web framework** — the only interface is the command-line tool.

Dependencies are pinned in `requirements.txt`:

```
pydantic>=2.7.0
pillow>=10.3.0
pymupdf>=1.24.0
rapidfuzz>=3.8.0
imagehash>=4.3.1
pytesseract>=0.3.10
requests>=2.31.0
feedparser>=6.0.11
python-dotenv>=1.0.1
pytest>=8.1.0
```

## Prerequisites

- **Python 3.10+** (this repo was run on 3.13.7).
- **Windows PowerShell** for the commands below (they also translate to `bash` by
  swapping the venv activation and path separators).
- Optional, for full live functionality:
  - **Tesseract OCR** installed and on `PATH` (or set `TESSERACT_CMD`).
  - **Ollama** running at `OLLAMA_BASE_URL` (default `http://localhost:11434`) with the
    planner model (`llama3.2` by default) and vision model (`llava` by default) pulled.
  - If these are absent, the system still runs: OCR returns empty results and the planner
    uses its deterministic fallback (see [Known Limitations](#known-limitations)).

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If PowerShell blocks activation, either allow local scripts for the session or call the
interpreter directly:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
# or skip activation and use:  .\.venv\Scripts\python.exe <args>
```

Optional configuration: copy `.env.example` to `.env` and adjust values (model names,
paths, budgets, thresholds). All settings are read through `config.py`.

## Usage (PowerShell)

All commands are shown with an activated virtual environment. If you did not activate it,
replace `python` with `.\.venv\Scripts\python.exe` (or `py`).

### 1. Show the CLI help

```powershell
python -m jyot_monitor --help
python -m jyot_monitor run --help
python -m jyot_monitor eval --help
```

The CLI exposes four subcommands: `run`, `approve`, `reject`, `eval`.

### 2. Replay the bundled sample dataset

The sample dataset lives in `data/sample_dataset` (6 gold items plus image/PDF fixtures and
`gold_manifest.json`).

```powershell
python -m jyot_monitor run `
  --replay data/sample_dataset `
  --digest reports/sample_replay_digest.md `
  --db data/sample_replay.db
```

This writes a Markdown digest to `reports/sample_replay_digest.md` and a JSONL trace under
`traces/`. Replay mode performs **zero network requests** (attachment fetching is denied by
design). Add `--max-items 3` to limit the number of items processed.

Live ingestion (requires reachable feeds and network) uses a sources file instead:

```powershell
python -m jyot_monitor run --sources sources.json --digest reports/digest.md
```

### 3. Run the evaluation harness

```powershell
python -m jyot_monitor eval `
  --dataset data/sample_dataset `
  --report reports/eval_benchmark.json
```

The harness reads `gold_manifest.json`, computes CER/WER (with and without preprocessing),
classification accuracy/precision/recall/F1, NDCG@5/@10, injection-detection and PII
redaction rates, and latency/cost statistics, then writes the JSON report and prints it.

### 4. Execute the tests

```powershell
python -m pytest -q
```

Or run a single test module:

```powershell
python -m pytest tests/test_cli_replay.py -q
```

### 5. Review alert proposals (human gate)

Alerts are only ever proposed, never sent. To act on a pending proposal:

```powershell
python -m jyot_monitor approve <proposal_id> --reviewer alice
python -m jyot_monitor reject  <proposal_id> --reviewer alice --reason "unverified"
```

## Controlled Fault Injection

Fault injection is supported for **replay runs only**. When enabled, the `ocr_extract` tool
returns a deterministic failure
(`{"success": false, "error": "fault-injection-simulated-ocr-failure", "needs_second_opinion": true}`,
`engine: "tesseract"`) so the run exercises graceful degradation rather than a crash.

```powershell
python -m jyot_monitor run `
  --replay data/sample_dataset `
  --digest reports/sample_fault_digest.md `
  --db data/sample_fault.db `
  --fault-injection
```

Notes verified against the code and tests:

- `--fault-injection` requires `--replay`; passing it without `--replay` exits with code 1
  (`tests/test_cli_replay.py::test_fault_injection_without_replay_rejected`).
- A fault-injection run still completes with exit code 0 and produces a valid digest.
- The callback deliberately suppresses the OCR second-opinion path, so faulted items finish
  in fewer steps; this is a documented robustness gap, not a recovery.

## Output Locations

| Artifact | Location |
| --- | --- |
| Evaluation metrics (JSON) | `reports/eval_benchmark.json` |
| Replay digest | `reports/sample_replay_digest.md` |
| Fault-injection digest | `reports/sample_fault_digest.md`, `reports/fault_injection_digest.md` |
| Full-run digest | `reports/digest.md` |
| JSONL traces | `traces/*.jsonl` (one file per run, named `run_<UTC>_<hex>.jsonl`) |
| Test-run traces | `traces_test/`, `fault_test_traces/` |
| Technical write-up | `reports/technical_writeup.md` |
| Trace walkthrough | `reports/trace_walkthrough.md` |
| Prompt documentation | `docs/prompt_documentation.md` |
| SQLite databases | `data/*.db` (e.g. `data/jyot_monitor.db`, `data/eval.db`) |

Traces are also written to the directory configured by `TRACES_DIR` (default `traces`).

## Test Results

The suite was executed in this environment and passed:

```
26 passed in 2.85s
```

Command used:

```powershell
python -m pytest -q
```

Coverage by module (see `tests/`):

- `test_cli_replay.py` — replay execution, zero-network guarantee, digest generation, and
  `--fault-injection` behavior.
- `test_extraction.py` — image preprocessing, PDF inspection/rendering, OCR routing signals,
  structured field extraction.
- `test_intelligence.py` — classification, non-LLM scoring, cross-modal dedup, clustering,
  urgency verification.
- `test_safety.py` — injection detection, PII redaction, SSRF blocking, magic-byte
  detection, spam detection.
- `test_alerting.py` — proposal lifecycle and human approval/rejection.
- `test_database.py` — item/cache/proposal persistence.

These tests validate plumbing and behavior, not model accuracy. Evaluation quality metrics
are separate and are reported below.

## Known Limitations

Verified against the current code and recorded artifacts; nothing here is a claim of
recovery or accuracy.

- **Offline model service.** In the environment that produced the recorded reports and
  traces, Ollama was unreachable at `http://localhost:11434`. `reports/eval_benchmark.json`
  records `tesseract_available: false` and a vision-service connection-timeout message.
- **Deterministic fallback planning.** Because the planner LLM is unavailable, every
  recorded trace step is `planner_model: "deterministic_expert_fallback"` with
  `is_fallback: true`. The LLM planning branch is implemented but unexercised in the
  recorded runs.
- **OCR failures, no fabricated text.** With the Tesseract binary absent, the OCR router
  logs `"Tesseract binary unavailable on host; routing to vision model engine."` and OCR
  returns empty text at confidence `0.0`. Consequently
  `reports/eval_benchmark.json` reports `mean_cer = 1.0` and `mean_wer = 1.0` (with and
  without preprocessing) over 4 pages, with `cer_reduction_pct = 0.0`. No OCR text was
  recovered, and no recovery is claimed.
- **Placeholder tool outputs.** The `vision_describe` tool returns the literal sentinel
  `[Vision describe unavailable: Offline replay mode active; external network disabled.]`
  when the vision model is unreachable; this is a stub, not a model analysis. In replay
  mode `fetch_attachment` is denied outright to guarantee zero network access.
- **Unfired agent branches.** `verify_claim`, `propose_alert` and `search_memory` are
  implemented but do not fire in any recorded trace, because baseline deterministic urgency
  stays below the `>= 75` verification threshold. Those branches are therefore not proven
  end-to-end.
- **Small evaluation set.** `reports/eval_benchmark.json` covers 6 samples (4 OCR pages, 1
  injection sample, 1 PII sample). This is below the assignment's gold-data minimums (15+
  OCR pages, 60+ labelled items, 10+ duplicate groups, 8+ adversarial cases), and the
  security rates (`1.0`) are each derived from a single sample. These numbers are not a
  production-readiness claim.
- **CLI flag naming drift.** The assignment brief references `run --live/--top-n/--budget-usd`
  and `eval --gold`; the implemented interface is
  `run --sources/--replay/--digest/--max-items/--db/--fault-injection` and
  `eval --dataset/--report/--db`. Equivalent capability exists, but the exact flag names
  differ.
- **Replay is intentionally offline.** Design guarantees zero network requests in replay
  mode (enforced and tested), so live-fetch behaviour is not exercised by the sample run.

## Development Workflow

Antigravity and OpenCode were used as AI-assisted development tools during the development
of Jyot Agentic Monitor. They supported implementation, code exploration, debugging, and
documentation workflows. The resulting code and behavior were validated through project
tests and execution-based checks.

These tools were used during development and are not necessarily runtime dependencies of
the application.

## Repository Layout

```
E:\jyot-monitor
  README.md                 This file
  requirements.txt          Python dependencies
  .env.example              Configuration template
  jyot_monitor/             Application package (source)
  tests/                    Pytest suite
  data/                     Sample dataset, gold manifest, SQLite databases
  reports/                  Evaluation report, digests, write-ups
  docs/                     Prompt documentation
  traces/                   JSONL run traces
  traces_test/              Traces produced by test runs
  fault_test_traces/        Traces produced by fault-injection tests
```
