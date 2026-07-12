# Benchmark Tool Checkpoints Design

## Goal

Make interrupted strict benchmark evaluation resumable within a case without
repeating already validated LLM work. Whole-case artifacts remain the only
completed evaluation outputs; checkpoints are internal recovery evidence.

## Chosen Design

Use content-addressed, typed checkpoints at the expensive Tool boundaries:

- T1 Likert judgement for reference and candidate reports
- T2 finding extraction for reference and candidate reports
- T5 alignment audit and complete error adjudication
- T4 primary hazard judgement, independent review, and third adjudication
- T6 clinical structure audit

Deterministic operations such as structure parsing, graph alignment, ranking,
and quality gates are recomputed. Raw provider responses and failed/schema-
invalid attempts are not cached.

Each checkpoint key hashes all semantically relevant inputs: report content,
image content/path, modality, upstream artifacts, strictness flags, schema
attempt count, Tool/prompt version, and explicit provider/model/endpoint call
options. API key values are never included. A route or input change therefore
creates a different checkpoint rather than silently reusing stale output.

## Integrity And Failure Behavior

Checkpoint envelopes contain the stage name, input SHA-256, output SHA-256,
and validated JSON output. Writes are atomic and guarded by a per-key file
lock. Reads fail closed on malformed JSON, stage/key mismatch, output hash
mismatch, or contract validation failure. A failed computation writes no
checkpoint.

`benchmark evaluate` enables checkpoint reuse only when resume is enabled.
`--no-resume` performs fresh Tool calls. Case success/failure artifacts and the
benchmark summary record checkpoint hits, misses, writes, and paths so reused
work cannot be mistaken for a fresh call in that attempt.

## Validation

Tests must prove:

1. identical inputs compute once and are reused across store instances;
2. changed inputs produce a cache miss;
3. tampered outputs fail before producer execution;
4. invalid outputs and producer failures are not persisted;
5. single-report T1/T2 and pairwise T5/T4/T6 integrations reuse only validated
   stage artifacts;
6. whole-case strict LLM verification remains unchanged.
