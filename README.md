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
PYTHONPATH=src python -m medharness2.cli workflow single-case \
  --report tests/fixtures/human_report.txt \
  --image tests/fixtures/dummy.dcm \
  --modality cxr \
  --top-n 1 \
  --output outputs/mvp_result.json
```

By default, the MVP uses the `chexagent` artifact configured in
`config/default.yaml`. This is a fast smoke path that reuses an existing
generation JSONL rather than running fresh GPU inference.

To exercise the legacy medHarness fresh-generation adapter, request a model
explicitly:

```bash
PYTHONPATH=src python -m medharness2.cli workflow single-case \
  --report tests/fixtures/human_report.txt \
  --image tests/fixtures/dummy.dcm \
  --modality cxr \
  --model maira_2 \
  --top-n 1 \
  --output outputs/maira2_result.json
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

Do not commit API keys, GitHub tokens, model credentials, or private paths that
should not be shared. `docs/pat.txt` is intentionally ignored.

## Validation

```bash
python -m compileall src tests
python -m pytest -q
```
