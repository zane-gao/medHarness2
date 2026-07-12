# medHarness2 Decision Log

## 2026-07-10: Quality and clinical evidence take priority

- Frontend and control-panel work is deferred by explicit user direction.
- Privacy hardening remains documented but is temporarily non-blocking while core medical quality is improved.
- The current 52-case run is a pilot engineering baseline, not clinical evidence.

## 2026-07-10: DMX-first does not mean DMX-by-default

- DMX is the preferred external provider for deidentified structured judging and education candidates.
- A model enters formal configuration only after comparison against clinician gold labels.
- Model names returned by DMX are recorded as route identifiers; upstream vendor identity is not inferred.

## 2026-07-10: Evidence tiers are mandatory

- `formal_fresh`, `exploratory_fresh`, `artifact`, `debug_fallback`, and `mock` are separate evidence classes.
- Artifact reuse, reference-assisted generation, and fallback output cannot enter formal model comparisons.
- The current qualityfix run contains 14 artifact and 67 debug_fallback reports, with zero formal_fresh reports.

## 2026-07-10: Runtime artifacts must validate recursively

- A top-level schema version is insufficient when nested finding or hazard payloads remain untyped.
- `validate-run` checks every available case, FindingGraph, GeneratedReport, HazardResult, AlignmentAuditArtifact, HazardReviewArtifact, and StructureAuditArtifact contract.
- Optional audit artifacts must carry a canonical SHA-256 that matches the alignment, hazard result, or structure diff stored in the same comparison; a syntactically valid but detached audit is rejected.
- Legacy batch artifacts are migrated at the merge boundary rather than copied into a v2 run unchanged.

## 2026-07-10: Legacy compatibility is explicit migration, not relaxed validation

- The original 52-case v1 directory intentionally fails strict recursive v2 validation.
- `schemas migrate-run` recursively converts legacy finding graphs and hazard results, preserves unknown fields under migration metadata, labels synthetic provenance as `legacy_migration`, and writes a run that can be passed directly to `validate-run`.
- The real 52-case migration completed with 52 valid cases, 277 FindingGraphs, 81 GeneratedReports, and 72 HazardResults; this proves contract compatibility only and does not create new LLM judgements or clinical evidence.

## 2026-07-10: Finding nodes represent clinical entities, not raw mentions

- Repeated observations with different locations or measurements remain distinct findings.
- Repeated mentions with the same sentence-level context are merged, retaining the richer measurement evidence.
- Alias overlap uses longest-match precedence, and negation scope stops at contrast boundaries.

## 2026-07-10: Formal LLM roles are strict and cannot silently degrade

- T1 formal five-dimension scoring requires a non-mock LLM and a complete validated response.
- T2 and T4 use deterministic templates as explicit inputs or priors, followed by LLM correction or judgement.
- T5 and T6 retain deterministic primary outputs; LLMs emit separate hash-linked audit artifacts.
- A configured formal role raises on repeated API/schema failure. Deterministic fallback remains available only in compatibility paths and is always marked.

## 2026-07-10: Reviewer output never overwrites primary judgement

- `hazard_primary` and `hazard_reviewer` receive the same minimized structured evidence independently.
- Reviewer differences are stored in `HazardReviewArtifact`; only clinician adjudication may resolve them.
- Alignment and structure audits follow the same primary-preservation rule.

## 2026-07-10: DMX remains primary; Yunwu is explicit backup

- DMX strong candidates verified in synthetic calls are `gpt-5.6-terra` and `claude-opus-4-8`.
- Yunwu uses a separate config and environment variable and is never selected by silent runtime failover.
- The complete Yunwu synthetic chain passed without fallback. The pure-DMX combined smoke remains blocked by intermittent GPT HTTP 403 despite isolated successful calls.
- Codex proxy routes are explicit only. Its Claude channel currently returns HTTP 503; the reproducible contingency profile uses codex GPT roles plus the DMX Claude reviewer and records both endpoint hosts in provenance.
- Synthetic smoke validates engineering integration only; clinician gold-set metrics decide formal model selection.

## 2026-07-11: Pure DMX full-chain recovery is engineering evidence, not clinical validation

- A frozen 11-case exploratory CXR evaluation completed T1/T2/T5/T4/T6 with 11/11 successes, 99 verified real-LLM role artifacts, and zero fallback.
- The authoritative implementation and runtime configuration hashes are `ed9d26ca0e73f777ee419fbdc3683f803fd93edac7499c492265909371e12b4a` and `2ccc541797fc011ea665a80ac7f7cfb14f6d31301f361ca539816f502a892818`.
- The prior DMX HTTP 403 limitation remains historical evidence and must not be presented as the current route status.
- This run remains single-model `exploratory_fresh`; it cannot support a formal model ranking or clinical claim.

## 2026-07-11: Prompt enums and validators share one source of truth

- T5 failed two cases because the prompt requested a free-text replacement error type while validation accepted only seven values.
- The prompt and validator now derive from the same ordered enum list. Invalid responses remain strict failures; no unknown value is silently coerced.
- Prompt/schema changes are isolated by the full evaluation implementation hash, and old/new attempts are never merged.

## 2026-07-11: Single LLM evaluations are not sufficiently repeatable

- On nine common cases, the same T1 judge route had only 11.1% exact agreement in candidate mean score and a mean absolute difference of 0.356.
- Consensus material-error count had 22.2% exact agreement and a mean absolute difference of 4.44; downstream values also include the T5 prompt change.
- Formal experiments therefore require repeated calls, a frozen aggregation rule, uncertainty reporting, and clinician calibration. Caching one stochastic draw does not establish reliability.

## 2026-07-11: OCR model selection is benchmark-first and truncation-aware

- `doubao-seed-2-1-pro-260628` is the newest strong Doubao candidate currently exposed by DMX and has passed image-only nonce plus real-report probes.
- Model recency does not determine the winner. Doubao 2.1 Pro, Doubao 1.6 Vision, `qwen-vl-ocr-latest`, and a retuned local Qwen3-VL baseline must be compared on frozen visual gold.
- Legacy OCR caches produced with `max_new_tokens=384` are ineligible for ranking when truncation is detected. Every candidate must use a non-truncating budget and pass section-completeness checks.
- Raw OCR and extractive clinical text remain separate, hash-linked artifacts; normalization cannot silently invent or rewrite report content.
