PYTHON ?= python
PYTHONPATH ?= src
OUTPUT_DIR ?= outputs
LEGACY_CXR_MANIFEST ?= /data/isbi/gzp/medHarness/resources/smoke_data/cxr/manifest.jsonl
SAMPLE_ROOT ?= /data/isbi/gzp/medHarness/data/sample_data_2026-06-05
SAMPLE_OUTPUT_DIR ?= $(OUTPUT_DIR)/sample_data_2026-06-05_full
SAMPLE_LIMIT ?= 1
FINAL_SAMPLE_OUTPUT_DIR ?= $(OUTPUT_DIR)/sample_data_2026-06-05_final_local_routed_52_20260606
FINAL_SAMPLE_ANALYSIS_DIR ?= $(FINAL_SAMPLE_OUTPUT_DIR)/analysis
FINAL_SAMPLE_EXPECTED_CASES ?= 52

SHELL := /bin/bash
.SHELLFLAGS := -e -o pipefail -c
.ONESHELL:

.PHONY: test smoke smoke-legacy-cxr smoke-maira2 sample-full-smoke final-sample-validate final-sample-analyze final-sample-check

test:
	$(PYTHON) -m compileall src tests
	$(PYTHON) -m pytest -q

smoke:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m medharness2.cli workflow single-case \
		--report tests/fixtures/human_report.txt \
		--image tests/fixtures/dummy.dcm \
		--modality cxr \
		--top-n 1 \
		--output $(OUTPUT_DIR)/mvp_result.json

smoke-legacy-cxr:
	mkdir -p $(OUTPUT_DIR)
	image_path="$$(PYTHONPATH=$(PYTHONPATH) $(PYTHON) -c 'import json; from pathlib import Path; row = json.loads(Path("$(LEGACY_CXR_MANIFEST)").read_text(encoding="utf-8").splitlines()[0]); Path("$(OUTPUT_DIR)/legacy_cxr_reference.txt").write_text(row["reference_report"] + "\n", encoding="utf-8"); print(row["image_paths"][0])')"
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m medharness2.cli workflow single-case \
		--report $(OUTPUT_DIR)/legacy_cxr_reference.txt \
		--image "$$image_path" \
		--modality cxr \
		--top-n 1 \
		--output $(OUTPUT_DIR)/legacy_cxr_smoke_result.json

smoke-maira2:
	mkdir -p $(OUTPUT_DIR)
	image_path="$$(PYTHONPATH=$(PYTHONPATH) $(PYTHON) -c 'import json; from pathlib import Path; row = json.loads(Path("$(LEGACY_CXR_MANIFEST)").read_text(encoding="utf-8").splitlines()[0]); Path("$(OUTPUT_DIR)/maira2_reference.txt").write_text(row["reference_report"] + "\n", encoding="utf-8"); print(row["image_paths"][0])')"
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m medharness2.cli workflow single-case \
		--report $(OUTPUT_DIR)/maira2_reference.txt \
		--image "$$image_path" \
		--modality cxr \
		--model maira_2 \
		--top-n 1 \
		--output $(OUTPUT_DIR)/maira2_smoke_result.json

sample-full-smoke:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m medharness2.cli workflow sample-full \
		--sample-root $(SAMPLE_ROOT) \
		--output-dir $(SAMPLE_OUTPUT_DIR) \
		--limit $(SAMPLE_LIMIT) \
		--expected-cases $(SAMPLE_LIMIT)

final-sample-validate:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m medharness2.cli workflow validate-run \
		--output-dir $(FINAL_SAMPLE_OUTPUT_DIR) \
		--expected-cases $(FINAL_SAMPLE_EXPECTED_CASES) \
		--require-real-ocr

final-sample-analyze:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) -m medharness2.cli workflow analyze-run \
		--output-dir $(FINAL_SAMPLE_OUTPUT_DIR) \
		--analysis-dir $(FINAL_SAMPLE_ANALYSIS_DIR)

final-sample-check: final-sample-validate final-sample-analyze
	for file in \
		analysis_summary.json \
		analysis_summary.md \
		case_routes.csv \
		model_source_summary.csv \
		reader_summary.csv \
		modality_body_part_summary.csv \
		quality_gate_failures.csv; do \
		test -f "$(FINAL_SAMPLE_ANALYSIS_DIR)/$$file"; \
	done
	echo "final sample analysis artifacts ok: $(FINAL_SAMPLE_ANALYSIS_DIR)"
