# medHarness2 MVP Usage

## Purpose

This MVP validates the core single-case loop without depending on heavyweight
local model resources:

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

## Configuration

Default config lives at `config/default.yaml`.

- `llm.provider: mock` keeps the workflow deterministic for tests.
- `llm.provider: openai` uses the OpenAI Responses API with the key from
  `llm.api_key_env`.
- `generator.local_models` is the future integration point for models already
  audited in `/data/isbi/gzp/medHarness/docs/report_generation_model_readiness.md`.

Do not commit API keys or tokens.
