# DMX Doubao OCR Benchmark Design

## Goal

Select and integrate the highest-quality OCR route for scanned radiology report
PDFs. Model recency or naming is not accepted as evidence of OCR quality. The
decision must be based on frozen inputs, exact model IDs, reproducible outputs,
and clinically relevant transcription metrics.

This work does not include a frontend or control panel.

## Approaches Considered

1. **Use the newest Doubao model directly.** This is the shortest path, but a
   newer general model may not accept images through DMX or may be weaker than
   an older vision-specific model at exact transcription.
2. **Select one model through a blind benchmark.** This is reproducible and
   keeps production simple, but a single model can still make rare, clinically
   important errors.
3. **Benchmark first, then deploy adaptively.** Select the best single model if
   it clearly dominates; otherwise use a primary OCR model plus an independent
   verifier for disagreement detection. This is the chosen design because
   quality is the primary constraint and API cost is secondary.

## Candidate Discovery And Capability Gate

The benchmark records the SHA-256 of the DMX `/v1/models` response and freezes
the exact candidate IDs. The initial quality-first candidate set is:

- newest available Doubao Pro model, currently
  `doubao-seed-2-1-pro-260628`;
- newest explicit Doubao vision model, currently
  `doubao-seed-1-6-vision-250815`;
- `qwen-vl-ocr-latest` as an OCR-specialized cloud comparator;
- local `qwen3-vl-4b` as the existing reproducible baseline.

Every candidate uses a frozen, non-truncating output budget. In particular, the
local baseline is rerun with a substantially larger `max_new_tokens` value than
the legacy value of `384` and must pass the same section-completeness checks.
Legacy truncated cache text is not an eligible baseline result.

Before the clinical benchmark, each cloud candidate receives a synthetic image
containing an image-only nonce and exact report-like text. A model advances only
if it returns the nonce and text from the image. Text-only replies, unsupported
image errors, empty output, or provider substitution fail the capability gate.
No route silently changes model or provider.

## Frozen Evaluation Set

Use 10 reports from the existing 52-case set, stratified as four CR, four CT,
and two MRI cases. Within each modality, select cases across page ink-density
and OCR-text-length quantiles so the set contains both sparse and dense reports.
The frozen manifest records case ID, modality, source PDF SHA-256, selected page
numbers, rendered page SHA-256, and selection rationale.

Each PDF is rendered page by page as lossless RGB PNG at 300 DPI. Pages below a
deterministic dark-pixel ratio threshold of `0.01` are marked blank and skipped.
The current 52 PDFs have two pages and the second page is effectively blank,
but the implementation remains multi-page.

Gold text has two layers:

- exact full-page transcription;
- exact clinical text for findings and impression.

Gold is produced by model-agreement seeding followed by line-by-line visual
adjudication against the rendered page. Raw clinical text remains under
`outputs/` and is not committed; the experiment manifest stores hashes and
annotation status.

## OCR Data Flow

1. Hash the source PDF and resolve a versioned OCR route.
2. Render every page and compute page-level image and ink-density metadata.
3. Skip deterministic blank pages.
4. Call the selected model once per retained page with an exact-transcription
   prompt: do not summarize, correct, translate, infer, or add Markdown; preserve
   section headers, punctuation, negation, measurements, dates, and line order.
5. Store the raw page response without rewriting it.
6. Join pages in source order.
7. Derive clinical findings/impression text separately. Normalization is
   extractive: output characters must be traceable to raw OCR spans.
8. Check provider finish reason, token usage, section completeness, sentence
   termination, and response shape. A suspected length truncation retries with
   a larger explicit output budget and remains a failure if still incomplete.
9. Write the versioned OCR artifact and text cache only after quality checks.

The generic LLM client continues to accept a single image. PDF rendering and
page iteration belong in the OCR module, avoiding a broad multimodal API change.

## Artifact And Cache Contract

Each OCR artifact records at least:

- schema and prompt versions;
- case ID and source PDF SHA-256;
- retained and skipped pages;
- render DPI, image dimensions, ink ratio, and page image SHA-256;
- provider, exact model, endpoint host, role, and route snapshot hash;
- attempt count, latency, provider finish reason, token usage, output-token
  budget, and explicit errors;
- raw page-response SHA-256 and combined raw-text SHA-256;
- extractive clinical-text SHA-256 and source-span mapping;
- quality warnings and fallback status.

The cache key includes source PDF hash, page image hashes, render settings,
prompt version, implementation version, provider, model, endpoint, and relevant
call options. A stale cache, source change, model change, or prompt change is a
cache miss. Failed or schema-invalid calls are never persisted as successful
OCR. Cache metadata from the legacy implementation is treated as unverifiable
when strict OCR provenance is required.

## Metrics And Selection Rule

Primary metric:

- clinical-text character error rate (CER).

Secondary metrics:

- full-page CER;
- findings/impression section completeness;
- digit, unit, laterality, and negation token accuracy;
- hallucinated character and line rate;
- empty/failure rate;
- normalized run-to-run edit distance over two repeated cloud calls;
- latency, reported separately and never allowed to outweigh quality.

The best single model is selected only if it has the lowest clinical CER, no
clinically material transcription error in the pilot, and no material weakness
in hallucination, number/negation accuracy, or stability. Otherwise production
uses the two strongest independent routes: the primary output is retained, and
disagreements are emitted as an audit artifact for adjudication. A verifier may
flag or select source spans but may not silently rewrite the primary text.

## Failure Handling

- Unsupported vision input fails the candidate capability gate.
- An API or schema failure is recorded against that exact route; no silent
  provider/model fallback is allowed.
- Blank-page filtering decisions remain inspectable and can be overridden by a
  force flag.
- Missing findings or impression triggers a quality warning and optional
  explicit second OCR route, not fabricated content.
- A length finish reason, missing visible terminal section, or output ending in
  the middle of a report sentence is treated as truncation and cannot satisfy
  strict OCR success.
- Any non-extractive clinical normalization fails closed and preserves raw OCR.

## Verification

Unit tests cover PDF rendering, blank-page filtering, page order, role routing,
prompt invariants, provenance, cache invalidation, extractive normalization,
and failure behavior. Golden tests use synthetic report pages with Chinese and
English headers, negation, measurements, and repeated sections. A DMX
integration smoke is gated on credentials and verifies image-only nonce recovery
without exposing a secret.

The pilot produces a frozen manifest, per-call JSONL, per-case/model metric CSV,
aggregate comparison CSV, raw outputs, disagreement artifacts, and a concise
decision report. Only after those artifacts pass integrity checks is the winner
added to the production OCR role configuration.
