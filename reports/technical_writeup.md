# Technical Write-Up — Agentic Multimodal Monitor

**Track B (Extended), AI Generalist assignment, Jyot AI Division.**

Every number below comes from `reports/eval_benchmark.json`, the JSONL traces under
`traces/`, or the replay digests. Where a required behaviour exists in code but is not
exercised by any recorded trace, it is flagged as a gap rather than claimed as working.

## 1. Architecture

The pipeline is a set of small, typed modules wired together in `jyot_monitor/cli.py:build_system`.

- **Ingestion** — RSS (`ingestion/rss.py`, persistent cursors) and offline replay
  (`ingestion/replay.py`, zero network access, the mandatory `--replay` path).
- **Extraction** — preprocessing profiles, Tesseract, a vision engine, a routing layer,
  PDF rendering and a structured-notice extractor (`extraction/`).
- **Intelligence** — classification, scoring, deduplication, clustering, verification.
- **Agent** — planner, controller loop, typed tools, JSONL tracer (`agent/`).
- **Safety** — injection, PII, spam and network guards (`safety/`).
- **Persistence & reporting** — SQLite (items, cursors, caches, clusters, proposals, history),
  digest generation, change tracking and the approval service.

Every item passes through the same agent loop in `controller.process_item`; the planner
decides how far each one goes.

## 2. Agent design, and the fixed-pipeline comparison

The loop is hand-rolled rather than framework-driven so that budget enforcement, tool
permissions and tracing are explicit and inspectable. The planner
(`agent/planner.py:decide_next_action`) has exactly two modes:

1. **LLM mode** — a local Ollama model is asked for a JSON `AgentAction` (schema-validated
   by Pydantic), the chosen tool must be in `ALLOWED_TOOLS`, and the call is retried up to
   `max_retries` times with `temperature 0.1`.
2. **Deterministic fallback** — if the model is unavailable or retries are exhausted, a
   rule-based expert policy (`_deterministic_plan`) runs. Its ordering is: run OCR if an
   attachment exists → escalate to `vision_describe` if OCR needs a second opinion →
   `verify_claim` at urgency ≥ 75 → `propose_alert` when urgency ≥ 70 and verified →
   `search_memory` at relevance ≥ 80 → `finish`.

Budgets are enforced in the controller: `max_steps_per_item` (default 6), a per-item USD
budget and a per-run USD budget; hitting either marks the item `partially_processed` and
writes a `budget_limit_reached`/`run_budget_exceeded` trace step.

**Honest position on "beats a fixed pipeline":** architecturally the agent gives adaptive,
per-item escalation (text items finish in one step; attachment items escalate; failures
degrade). But in the offline environment the Ollama planner is unreachable, so *every*
trace is `planner_model: "deterministic_expert_fallback"`. On the current 6-item fixture
the agent therefore behaves like a deterministic policy, and we have **not** produced the
ablation (agent-vs-fixed-pipeline on quality and cost) the brief requires. This is the
single largest evidence gap in the submission.

## 3. OCR strategy and trade-offs

Two engines are wired behind `extraction/router.py`. The router's logged decision
(`router_rationale`) shows it preferring Tesseract and falling back to the vision model
when the Tesseract binary is absent. Preprocessing is profile-based and applied before the
classical engine.

Measured result: **Tesseract is not installed and Ollama is offline**
(`tesseract_available: false`), so no OCR text was recovered and the measured OCR score is
the worst possible — `mean_cer = 1.0`, `mean_wer = 1.0` with and without preprocessing,
`cer_reduction_pct = 0.0`, over 4 gold pages. Preprocessing therefore shows **no measured
benefit** here, and we report that rather than hiding it. Structured extraction
(`structured_fields.py`) parses organisation, notice type, batch number, date and action
into a Pydantic `StructuredNotice` and records `uncertainty_flags` instead of guessing.

## 4. Scoring, classification, deduplication, memory

Classification is a keyword-taxonomy classifier (`classification.py`) over five public-safety
topics with a `General / Uncategorized` fallback. Urgency scoring (`scoring.py`) is a
transparent linear combination — a content-severity term plus **non-LLM signals**: source
credibility, recency decay and corroboration/batch bonuses. The combined formula is
documented in the source. Deduplication and clustering (`deduplication.py`, `clustering.py`)
group related items and keep a representative; SQLite persists clusters, cursors and
seen-items so successive digests can say what is new, escalated or unchanged
(`change_tracking.py`).

Evaluation on the 6-sample gold set yields classification `accuracy = 0.6667`,
`macro_f1 = 0.7895`, and `ndcg_at_5 = ndcg_at_10 = 0.9999`. **These are small-sample
numbers and must not be read as production readiness**; the brief's minimums (≥15 OCR
pages, ≥60 labelled items, ≥10 duplicate groups, ≥8 adversarial cases) are not met.

## 5. Injection threat model and safety

Threat model: all source text and OCR output is untrusted; an attacker may hide in an
image a request to ignore instructions, raise its own urgency, force an alert, exfiltrate
the system prompt, or execute code. Defences:

- `safety/injection.py` matches instruction-override, persona-hijack, forced-tool,
  forced-score, exfiltration and delimiter-spoofing patterns, and can wrap untrusted
  content in an explicit `BEGIN UNTRUSTED DATA` container.
- `controller.process_item` scans both the item text and any OCR text, appending
  `injection_*` / `ocr_injection_*` flags and setting `FLAGGED_INJECTION`.
- Alerts can only be *proposed*, never sent; `alerting/approval.py` requires an explicit
  human `approve`/`reject`.
- `safety/pii.py` redacts emails, phones and SSNs; `safety/network.py` enforces schemes,
  private-IP blocking and size/type limits.

Measured: `prompt_injection_detection_rate = 1.0` and `pii_redaction_rate = 1.0` — but each
is computed from a **single** adversarial/PII sample (`gold_item_05`, `gold_item_06`), so
the confidence interval is essentially the whole interval. The replay digest shows the
adversarial item correctly flagged (`injection_instruction_override`,
`injection_persona_hijack`, `injection_forced_score_manipulation`,
`injection_forced_tool_execution`) and *not* escalated.

## 6. Reliability, cost and fault injection

Runs are idempotent at the item level (seen-items + content hash), caches key OCR/LLM
results, and degrade gracefully when engines or budgets are unavailable. The
`--fault-injection` flag is replay-only: `ocr_extract` deterministically returns
`{"success": false, "error": "fault-injection-simulated-ocr-failure", "needs_second_opinion": true}`,
and the run completes with exit code 0 and a valid digest
(`reports/sample_fault_digest.md`, `traces/run_20261012_122318_eac9bd.jsonl`). The benchmark's
estimated cost is `$0.0018` for 6 items (~$0.0003/item).

## 7. Scaling plan (100x)

At 100x volume the bottlenecks are OCR/vision compute and duplicate API calls, not the loop.
Planned work: a real worker queue with per-source token buckets and exponential backoff with
jitter (respecting `Retry-After`); aggressive content-hash caching so identical screenshots
are OCR'd once; batched local vision inference on GPU; a cheap-first routing policy (text →
classical OCR → vision only on low confidence); and source-sharded horizontal scaling over a
shared dedup index. Spam/coordination defence (`safety/spam.py`) would move from per-item
heuristics to source-level rate and burst analysis.

## 8. Known limitations

- **Evaluation is far below the required gold-data minimums**; all quality metrics are
  small-sample and OCR is currently unmeasurable (engines absent).
- **No agent-vs-fixed-pipeline ablation was produced.**
- **`verify_claim`, `propose_alert` and `search_memory` are implemented but never fire in
  any recorded trace**, because baseline deterministic urgency stays below the 75 verify
  threshold; the self-checking and alerting branches are therefore unproven end-to-end.
- **CLI contract drift:** the brief specifies `run --live`, `--top-n`, `--budget-usd` and
  `eval --gold`; the implemented interface is `run --sources/--replay --digest --max-items
  --fault-injection` and `eval --dataset --report`. Equivalent capability exists, but the
  exact flag names differ.

## 9. What I would do with another two weeks

1. Stand up Tesseract + a local vision model and rebuild the gold set to the required size
   (15+ pages incl. rotated/non-Latin, 60+ labelled items, 10+ duplicate groups, 8+
   adversarial cases) and re-measure CER/WER, F1, NDCG and attack-success.
2. Produce the mandated ablation: agent loop versus a fixed linear pipeline on the same gold
   set, reporting quality, average steps/tool calls, cost and fallback rate.
3. Tune thresholds so the `verify_claim` → `propose_alert` path fires, then record and
   annotate those trajectories; align the CLI with the required flags (`--live`, `--top-n`,
   `--budget-usd`, `--gold`).
