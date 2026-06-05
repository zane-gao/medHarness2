# medHarness2 MVP Usage

## Purpose

This MVP validates the core single-case loop while keeping local model access
pluggable:

1. Read one human report.
2. Generate candidate AI reports through local registry or configured fallback.
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
- `generator.cloud_fallback_enabled: true` keeps the legacy config switch for
  generation fallback. The actual fallback can still be local when
  `llm.provider` is `local_hf_vlm` or `local_vlm_cli`; JSON records whether the
  output came from `local_vlm_fallback`, `cloud_fallback`, or `mock_fallback`.

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
The real provider does not have to be a cloud API. To use the local Qwen2.5-VL
debug fallback that is already registered in medHarness, copy `config/example.yaml`
and set:

```yaml
llm:
  provider: local_vlm_cli
  model: qwen25vl_7b_instruct
```

This renders scanned PDF pages to temporary PNG files and calls the legacy
`/data/isbi/gzp/medHarness/scripts/run_report_generation.py` runner. Its OCR
metadata is recorded as `provider: local_vlm_cli`; keep in mind that
`qwen25vl_7b_instruct` is a debug/OCR fallback, not a formal report-trained
candidate for model ranking.

On this machine, the medHarness Qwen2.5-VL soft link is currently missing its
HF snapshot. The directly available local Qwen3-VL 4B path works for OCR smoke:

```yaml
llm:
  provider: local_hf_vlm
  model: qwen3-vl-4b
  local_hf_model_path: /data/cyf/shared_data/hd_data/qwen3-vl-4B
  local_hf_device: cuda:0
  local_hf_dtype: bf16
```

Run a gate check before an expensive sample run:

```bash
PYTHONPATH=src medharness2 workflow preflight \
  --sample-root /data/isbi/gzp/medHarness/data/sample_data_2026-06-05 \
  --output outputs/sample_data_2026-06-05_preflight/preflight.json \
  --require-real-ocr \
  --all-compatible-local-models \
  --config config/local_hf_qwen3vl4b.yaml
```

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
For MAIRA-2, medHarness2's default config uses
`/data/miniconda3/envs/deepseek_2/bin/python`, which currently matches the
`transformers 4.48.2` environment described by the old readiness notes.

`workflow batch-readers` groups pure `medharness_cli` requests by model before
calling the old medHarness runner. This reduces repeated model loading for
fresh local runs. Mixed source requests, such as fresh models plus artifact
reuse, keep the per-case path so artifact candidates are not dropped.

Generated reports pass through a lightweight modality/body-part consistency
gate before ranking. Obvious off-domain outputs, such as a brain MRI model
returning a hip radiograph report, are kept in JSON with `quality_gate_failed`
metadata but are excluded from Top-N and pairwise comparison.

`sample-data` also writes `summary.json` with modality/body-part/warning counts.
`batch-readers` writes `failed_cases` and continues processing when an
individual case fails, so long full-dataset runs can be inspected and resumed
without losing all prior work.

When the full dataset is split into modality/body-part batches to avoid
reloading heavy local models unnecessarily, combine the verified batch outputs
with `merge-batches`:

```bash
PYTHONPATH=src medharness2 workflow merge-batches \
  --manifest outputs/sample_data_2026-06-05_local_hf_qwen3vl4b_ocr_52_20260606/manifest.jsonl \
  --output-dir outputs/sample_data_2026-06-05_final_local_routed_52_20260606 \
  --expected-cases 52 \
  --require-real-ocr \
  --batch-result outputs/cxr_real_ocr_three_fresh_11_20260606/workflow2.json \
  --batch-result outputs/merlin_real_ocr_ct_abdomen_7_20260606/workflow2.json \
  --batch-result outputs/braingemma3d_real_ocr_mri_brain_series_prompt_7_20260606/workflow2.json \
  --batch-result outputs/ct_chest_real_ocr_artifact_7_20260606/workflow2.json \
  --batch-result outputs/local_hf_fallback_remaining_20_qualityfix_20260606/workflow2.json
```

This creates a unified result directory and verifies manifest coverage. It does
not rerun OCR or generation; each case keeps `source_batch_result` provenance.

Generate CSV and Markdown analysis tables from a completed run:

```bash
PYTHONPATH=src medharness2 workflow analyze-run \
  --output-dir outputs/sample_data_2026-06-05_final_local_routed_52_20260606 \
  --analysis-dir outputs/sample_data_2026-06-05_final_local_routed_52_20260606/analysis
```

The analysis output includes `case_routes.csv`, `model_source_summary.csv`,
`reader_summary.csv`, `modality_body_part_summary.csv`,
`quality_gate_failures.csv`, `analysis_summary.json`, and
`analysis_summary.md`.

Validate the completed output directory before reporting it as a usable run:

```bash
PYTHONPATH=src medharness2 workflow validate-run \
  --output-dir outputs/sample_data_2026-06-05 \
  --expected-cases 52
```

For a real evaluation run, add `--require-real-ocr`. The gate then rejects mock
OCR, `real_ocr_required_but_provider_is_mock`, and older OCR caches whose
`.ocr.json` files do not record a real provider.
