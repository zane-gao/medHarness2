# medHarness2 Finding/Hazard Pilot Annotation Package

当前可交接的 10 例包由 52 例运行产物生成，位置为：

```text
outputs/annotation/pilot10_20260717/
```

完整交接说明见 `docs/real_clinician_handoff_20260717.md`。若重新生成：

```bash
PYTHONPATH=src .venv/bin/python -m medharness2.cli \
  annotation build-pilot \
  --run-dir outputs/sample_data_2026-06-05_final_local_routed_52_20260606_reeval_v2_qualityfix_20260710 \
  --output-dir outputs/annotation/pilot10_20260717 \
  --limit 10
```

- Cases: 10
- Blinding: model identities and source case identifiers are not included.
- Readers: reader_a and reader_b annotate independently; adjudication is completed only after both readers finish.
- Finding guidance: `annotation/guidelines/finding_annotation.md`.
- Hazard guidance: `annotation/guidelines/hazard_annotation.md`.
- This pilot is for guideline calibration and must not be used as a formal test set.
