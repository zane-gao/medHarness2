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

## Validation

```bash
python -m compileall src tests
python -m pytest -q
```
