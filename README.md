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
