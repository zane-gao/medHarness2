# MAIRA-2 Fresh Smoke Record - 2026-05-30

## Summary

Ran one full fresh MAIRA-2 generation smoke through the medHarness2
`medharness_cli` adapter and the existing medHarness report-generation script.

## Command

```bash
CUDA_VISIBLE_DEVICES=3 make smoke-maira2
```

The smoke target used the first row from:

```text
/data/isbi/gzp/medHarness/resources/smoke_data/cxr/manifest.jsonl
```

## Runtime

- Started at: `2026-05-30T00:22:20+08:00`
- Finished at: `2026-05-30T00:23:08+08:00`
- Elapsed: `48` seconds
- Exit code: `0`
- Device mapping: `CUDA_VISIBLE_DEVICES=3`; the legacy adapter still receives
  `--device cuda:0`, mapped to physical GPU 3 by CUDA visibility.

## Result

- Input modality: `cxr`
- Generated reports: `1`
- Pairwise comparisons: `1`
- Model: `maira_2`
- Source: `medharness_cli`
- Report length: `308` characters
- Warnings: `missing_impression_section`, `maira2_generates_findings_only`

Raw outputs were written under `outputs/` and are intentionally not tracked by
git.
