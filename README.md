# medHarness2

MVP radiology report evaluation harness.

The current MVP implements one single-case workflow:

```text
human report + image path
  -> generate AI reports
  -> evaluate reports
  -> rank Top-N generated reports
  -> compare human report against Top-N
  -> write JSON
```

The core is a Python library. The CLI is a thin smoke-test and batch entrypoint.

The expanded design also includes sample-data ingestion, VLM OCR hooks, DICOM
asset preparation, batch reader evaluation, and department-level statistics.

Report generation can use the local resources already prepared under
`/data/isbi/gzp/medHarness`. medHarness2 auto-discovers ready legacy report
generation models from
`/data/isbi/gzp/medHarness/configs/reportgen_models.yaml`; cloud APIs are only
one fallback path, not the required generation path.

## Install

```bash
cd /data/isbi/gzp/medHarness2
python -m pip install -e ".[test]"
```

## Quick Smoke

```bash
cd /data/isbi/gzp/medHarness2
make smoke
```

By default, the MVP uses the `chexagent` artifact configured in
`config/default.yaml`. This is a fast smoke path that reuses an existing
generation JSONL rather than running fresh GPU inference.

To exercise the legacy medHarness fresh-generation adapter, request a model
explicitly:

```bash
make smoke-maira2
```

That path calls `/data/isbi/gzp/medHarness/scripts/run_report_generation.py`
with the model settings in `/data/isbi/gzp/medHarness/configs/reportgen_models.yaml`.
It may require GPU memory and can take substantially longer than the default
artifact smoke.

## Sample Data Pipeline

The hospital sample-data runner builds a manifest, prepares DICOM-derived
assets, extracts scanned PDF report text through the configured VLM/OCR
provider, and writes all generated artifacts under `outputs/`:

```bash
PYTHONPATH=src medharness2 workflow sample-data \
  --sample-root /data/isbi/gzp/medHarness/data/sample_data_2026-06-05 \
  --output-dir outputs/sample_data_2026-06-05
```

For a low-cost structural check, keep the default `llm.provider: mock` or add
`--skip-ocr`. With an OpenAI provider configured, report PDFs are sent through
the multimodal Responses API; credentials must come from environment variables.
Mock OCR is marked with `mock_ocr_used`; use `--require-real-ocr` when preparing
data for real evaluation so mock text cannot be mistaken for extracted reports.
Existing OCR caches are reused only when their `.ocr.json` provenance is
compatible with the requested mode. Add `--force-ocr` to refresh report text
caches deliberately.

Run the batch and department workflows from the generated manifest:

```bash
PYTHONPATH=src medharness2 workflow batch-readers \
  --manifest outputs/sample_data_2026-06-05/manifest.jsonl \
  --output outputs/sample_data_2026-06-05/workflow2.json

PYTHONPATH=src medharness2 workflow department \
  --batch-result outputs/sample_data_2026-06-05/workflow2.json \
  --output outputs/sample_data_2026-06-05/workflow3.json
```

Or run the full sample-data chain in one command:

```bash
PYTHONPATH=src medharness2 workflow sample-full \
  --sample-root /data/isbi/gzp/medHarness/data/sample_data_2026-06-05 \
  --output-dir outputs/sample_data_2026-06-05 \
  --expected-cases 52
```

This writes `manifest.jsonl`, `workflow2.json`, `workflow3.json`, and
`run_summary.json`, then runs the validation gate.

Model routing filters local generators by modality and body part. Unsupported
cases use the configured fallback provider, which can be a local VLM, cloud
VLM/API, or mock provider. The generated JSON records the exact
`source`/warning, such as `local_vlm_fallback_used`, `cloud_fallback_used`, or
`mock_fallback_used`.

Inspect compatible local generators before a run:

```bash
PYTHONPATH=src medharness2 models list --modality cxr --body-part chest
PYTHONPATH=src medharness2 models list --modality ct --body-part abdomen
PYTHONPATH=src medharness2 models list --modality mri --body-part brain
```

Preview local-model coverage for the whole sample dataset without running OCR,
DICOM conversion, or model inference:

```bash
PYTHONPATH=src medharness2 workflow sample-full \
  --sample-root /data/isbi/gzp/medHarness/data/sample_data_2026-06-05 \
  --output-dir outputs/sample_data_2026-06-05_local_route_plan \
  --dry-run \
  --all-compatible-local-models
```

To avoid launching GPU-heavy fresh models, restrict the local pool to reusable
artifacts:

```bash
PYTHONPATH=src medharness2 workflow sample-full \
  --sample-root /data/isbi/gzp/medHarness/data/sample_data_2026-06-05 \
  --output-dir outputs/sample_data_2026-06-05_artifact_only \
  --expected-cases 52 \
  --all-compatible-local-models \
  --model-source artifact_reuse
```

Select local models explicitly with repeated `--model`, for example:

```bash
PYTHONPATH=src medharness2 workflow sample-full \
  --sample-root /data/isbi/gzp/medHarness/data/sample_data_2026-06-05 \
  --output-dir outputs/sample_data_2026-06-05_local \
  --expected-cases 52 \
  --model maira_2 \
  --model chexagent_srrg_findings_full \
  --model medgemma_srrg_findings \
  --model merlin \
  --model brain_gemma3d
```

Validate a completed sample-data run before treating it as an evaluable result:

```bash
PYTHONPATH=src medharness2 workflow validate-run \
  --output-dir outputs/sample_data_2026-06-05 \
  --expected-cases 52
```

Add `--require-real-ocr` for non-mock evaluation. This checks each report text
cache for explicit OCR provenance and rejects mock or unknown OCR outputs.

When expensive local batches are run by modality/body-part subsets, merge the
validated batch outputs into one auditable 52-case result without rerunning
models:

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

The merged output writes `workflow2.json`, `workflow3.json`, `run_summary.json`,
and one copied Workflow 1 JSON per case under `workflow2_cases/`.

Create report-ready CSV and Markdown summaries from a completed run:

```bash
PYTHONPATH=src medharness2 workflow analyze-run \
  --output-dir outputs/sample_data_2026-06-05_final_local_routed_52_20260606 \
  --analysis-dir outputs/sample_data_2026-06-05_final_local_routed_52_20260606/analysis
```

This writes case routing, model/source, reader, modality/body-part, and quality
gate failure tables without rerunning OCR or generation.

## Configuration

`config/default.yaml` keeps provider choices outside the code:

- `llm.provider: mock` is deterministic and used by default.
- `llm.provider: openai` calls the OpenAI Responses API with
  `OPENAI_API_KEY`.
- `extractor.backend: cxr_rule` enables the current rule-based CXR graph
  extractor; non-CXR work can still use `placeholder`.
- `generator.local_models` defines local artifacts and fresh medHarness
  adapters.

Use `config/example.yaml` as the copyable template when creating local
experiment-specific configs.

Do not commit API keys, GitHub tokens, model credentials, or private paths that
should not be shared. `docs/pat.txt` is intentionally ignored.

## API Smoke

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

## Validation

```bash
make test
```
