# medHarness2 MVP Usage

## Purpose

This MVP validates the core single-case loop while keeping local model access
pluggable:

1. Read one human report.
2. Generate candidate AI reports through local registry or cloud fallback.
3. Evaluate human and generated reports.
4. Rank generated reports.
5. Compare the human report with Top-N generated reports.
6. Write nested JSON.

## Minimal Command

```bash
cd /data/isbi/gzp/medHarness2
PYTHONPATH=src python -m medharness2.cli workflow single-case \
  --report tests/fixtures/human_report.txt \
  --image tests/fixtures/dummy.dcm \
  --modality cxr \
  --top-n 1 \
  --output outputs/mvp_result.json
```

The default command uses `chexagent` from `config/default.yaml`. Its source is
`artifact_reuse`, so it reads one existing generation JSONL row and lets the
rest of the evaluation workflow run quickly.

## Optional Fresh Local Generation

Use `--model maira_2` to call the legacy medHarness report-generation CLI for
fresh inference:

```bash
PYTHONPATH=src python -m medharness2.cli workflow single-case \
  --report tests/fixtures/human_report.txt \
  --image tests/fixtures/dummy.dcm \
  --modality cxr \
  --model maira_2 \
  --top-n 1 \
  --output outputs/maira2_result.json
```

This adapter writes a temporary one-case JSONL manifest, calls
`/data/isbi/gzp/medHarness/scripts/run_report_generation.py`, then reads the
legacy output JSONL back into the medHarness2 workflow. It is intended as a
compatibility bridge for models already checked in
`/data/isbi/gzp/medHarness/docs/report_generation_model_readiness.md`.

Because this path may load a real model on GPU, run it only when the target
device and model weights are available.

## Configuration

Default config lives at `config/default.yaml`.

- `llm.provider: mock` keeps the workflow deterministic for tests.
- `llm.provider: openai` uses the OpenAI Responses API with the key from
  `llm.api_key_env`, which defaults to `OPENAI_API_KEY`.
- `extractor.backend: cxr_rule` uses the current CXR rule extractor. It emits
  findings, graph nodes, negation status, and simple template coverage. Set it
  to `placeholder` for non-CXR smoke tests.
- `generator.local_models` contains both fast artifact reuse and fresh legacy
  medHarness adapters.
- `generator.cloud_fallback_enabled: true` allows the LLM provider to create a
  fallback report only when no local generator returns usable text.

## Output Contract

The workflow writes nested JSON with:

- input metadata.
- single-report evaluation for the human report.
- generated report records with model/source/warnings metadata.
- single-report evaluation for each generated report.
- Top-N ranking rows.
- human-vs-AI pairwise comparison results with alignment and hazard summaries.

Do not commit API keys or tokens.
