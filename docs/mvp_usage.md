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
make smoke
```

The default command uses `chexagent` from `config/default.yaml`. Its source is
`artifact_reuse`, so it reads one existing generation JSONL row and lets the
rest of the evaluation workflow run quickly.

For a smoke run that uses the old medHarness CXR manifest and real image path
while still reusing the fast artifact generator, run:

```bash
make smoke-legacy-cxr
```

## Optional Fresh Local Generation

Use `--model maira_2` to call the legacy medHarness report-generation CLI for
fresh inference:

```bash
make smoke-maira2
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
Use `config/example.yaml` as a safe copyable template for experiment-specific
configuration.

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

## API Entry

The API is a thin wrapper around the same Python workflow:

```bash
PYTHONPATH=src uvicorn medharness2.api:app --host 0.0.0.0 --port 8000
```

```bash
curl -X POST http://127.0.0.1:8000/workflow/single-case \
  -H 'Content-Type: application/json' \
  -d '{
    "report_text": "FINDINGS: No pneumothorax. IMPRESSION: No acute disease.",
    "image_path": "tests/fixtures/dummy.dcm",
    "output_path": "outputs/api_result.json",
    "modality": "cxr",
    "top_n": 1
  }'
```

Do not commit API keys or tokens.

## Full Design Commands

Build a manifest and prepared assets for the 2026-06-05 sample dataset:

```bash
PYTHONPATH=src medharness2 workflow sample-data \
  --sample-root /data/isbi/gzp/medHarness/data/sample_data_2026-06-05 \
  --output-dir outputs/sample_data_2026-06-05
```

Use `--limit 1` for a quick smoke and `--skip-ocr` when only checking DICOM and
manifest parsing. All OCR caches, converted PNG/NIfTI/contact-sheet assets, and
workflow outputs live under `outputs/` and should not be committed.

Then run the batch reader and department workflows:

```bash
PYTHONPATH=src medharness2 workflow batch-readers \
  --manifest outputs/sample_data_2026-06-05/manifest.jsonl \
  --output outputs/sample_data_2026-06-05/workflow2.json

PYTHONPATH=src medharness2 workflow department \
  --batch-result outputs/sample_data_2026-06-05/workflow2.json \
  --output outputs/sample_data_2026-06-05/workflow3.json
```

The default config stays low-cost. Explicitly request fresh local models with
`--model maira_2`, `--model merlin_fresh`, or `--model brain_gemma3d` only when
GPU memory and prepared assets are available.
