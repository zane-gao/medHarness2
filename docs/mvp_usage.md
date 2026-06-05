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
When `llm.provider: mock`, OCR results are marked with `mock_ocr_used`. Add
`--require-real-ocr` to reject mock OCR and surface
`real_ocr_required_but_provider_is_mock` until a real VLM provider is configured.
OCR caches are resumable: a later real-provider run can reuse caches whose
`.ocr.json` records real provenance, and it refreshes mock or unknown caches
when `--require-real-ocr` is set. Use `--force-ocr` to deliberately regenerate
all report text caches in the selected run.

Then run the batch reader and department workflows:

```bash
PYTHONPATH=src medharness2 workflow batch-readers \
  --manifest outputs/sample_data_2026-06-05/manifest.jsonl \
  --output outputs/sample_data_2026-06-05/workflow2.json

PYTHONPATH=src medharness2 workflow department \
  --batch-result outputs/sample_data_2026-06-05/workflow2.json \
  --output outputs/sample_data_2026-06-05/workflow3.json
```

For an end-to-end run, use the orchestration entrypoint:

```bash
PYTHONPATH=src medharness2 workflow sample-full \
  --sample-root /data/isbi/gzp/medHarness/data/sample_data_2026-06-05 \
  --output-dir outputs/sample_data_2026-06-05 \
  --expected-cases 52
```

It executes `sample-data`, `batch-readers`, `department`, and `validate-run`,
then writes `run_summary.json` with paths, case counts, failed-case counts, and
validation status. Use `make sample-full-smoke` for a limit-1 structural smoke.

The default config stays low-cost. Explicitly request fresh local models with
`--model maira_2`, `--model merlin_fresh`, or `--model brain_gemma3d` only when
GPU memory and prepared assets are available.

medHarness2 also auto-discovers ready local report-generation resources from
`/data/isbi/gzp/medHarness/configs/reportgen_models.yaml`, which is the
machine-readable companion to
`/data/isbi/gzp/medHarness/docs/report_generation_model_readiness.md`. Use the
model listing command to inspect compatible local candidates:

```bash
PYTHONPATH=src medharness2 models list --modality cxr --body-part chest
PYTHONPATH=src medharness2 models list --modality ct --body-part abdomen
PYTHONPATH=src medharness2 models list --modality mri --body-part brain
```

For a local-model run, pass repeated `--model` values to `single-case`,
`batch-readers`, or `sample-full`. This keeps low-cost smoke defaults stable
while allowing the full local pool, including MAIRA-2, CheXagent SRRG,
MedGemma SRRG, Merlin artifact/fresh, and BrainGemma3D, to be used when the
device and inputs are ready.

Before launching expensive fresh inference, run a route-plan dry run:

```bash
PYTHONPATH=src medharness2 workflow sample-full \
  --sample-root /data/isbi/gzp/medHarness/data/sample_data_2026-06-05 \
  --output-dir outputs/sample_data_2026-06-05_local_route_plan \
  --dry-run \
  --all-compatible-local-models
```

This writes `route_plan.json` only. It does not run OCR, DICOM conversion,
Workflow 1/2/3, or any local model inference.

To use the local pool without launching GPU-heavy fresh models, restrict the
source to reusable artifacts:

```bash
PYTHONPATH=src medharness2 workflow sample-full \
  --sample-root /data/isbi/gzp/medHarness/data/sample_data_2026-06-05 \
  --output-dir outputs/sample_data_2026-06-05_artifact_only \
  --expected-cases 52 \
  --all-compatible-local-models \
  --model-source artifact_reuse
```

Use `--model-source medharness_cli` when the intent is fresh local inference
through the old medHarness runners. This should be combined with explicit
`--model` values or a prior dry run, because it may load large local models such
as MAIRA-2, CheXagent SRRG, MedGemma SRRG, Merlin fresh, or BrainGemma3D.

`sample-data` also writes `summary.json` with modality/body-part/warning counts.
`batch-readers` writes `failed_cases` and continues processing when an
individual case fails, so long full-dataset runs can be inspected and resumed
without losing all prior work.

Validate the completed output directory before reporting it as a usable run:

```bash
PYTHONPATH=src medharness2 workflow validate-run \
  --output-dir outputs/sample_data_2026-06-05 \
  --expected-cases 52
```

For a real evaluation run, add `--require-real-ocr`. The gate then rejects mock
OCR, `real_ocr_required_but_provider_is_mock`, and older OCR caches whose
`.ocr.json` files do not record a real provider.
