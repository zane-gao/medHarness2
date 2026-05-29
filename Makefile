PYTHON ?= python
PYTHONPATH ?= src
OUTPUT_DIR ?= outputs
LEGACY_CXR_MANIFEST ?= /data/isbi/gzp/medHarness/resources/smoke_data/cxr/manifest.jsonl

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.ONESHELL:

.PHONY: test smoke smoke-legacy-cxr smoke-maira2

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
