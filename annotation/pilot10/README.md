# medHarness2 Finding/Hazard Pilot Annotation Package

当前可交接的 10 例包由 52 例运行产物生成，已随仓库提交，位置为：

```text
annotation/pilot10/
```

完整交接说明见 `docs/real_clinician_handoff_20260717.md`。若重新生成：

```bash
PYTHONPATH=src .venv/bin/python -m medharness2.cli \
  annotation build-pilot \
  --run-dir outputs/sample_data_2026-06-05_final_local_routed_52_20260606_reeval_v2_qualityfix_20260710 \
  --output-dir annotation/pilot10 \
  --limit 10
```

给真实 reader 交付隔离副本（只保留指定 reader 的槽位，不包含内部模型映射）：

```bash
PYTHONPATH=src .venv/bin/python -m medharness2.cli \
  annotation export-reader \
  --package-dir annotation/pilot10 \
  --output-dir /path/to/reader_a_package \
  --reader reader_a
```

`reader_b` 使用同一命令替换 `--reader`。导出的副本完成后，直接对该副本运行
`annotation validate`；管理员回收时再将对应 `cases/` 合并回主包，不能把两个 reader
的副本直接互相覆盖。

- Cases: 10
- Blinding: model identities and source case identifiers are not included.
- Readers: reader_a and reader_b annotate independently; adjudication is completed only after both readers finish.
- Finding guidance: `annotation/guidelines/finding_annotation.md`.
- Hazard guidance: `annotation/guidelines/hazard_annotation.md`.
- This pilot is for guideline calibration and must not be used as a formal test set.
