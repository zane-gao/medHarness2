# 真实医生标注交接说明（2026-07-17）

## 当前包

本轮从 52 例运行产物中确定性筛出 10 例，覆盖 `cxr`、`ct`、`mri`：

```text
outputs/annotation/pilot10_20260717/
```

包内每个病例都包含：

- 脱敏后的参考报告文本；
- 脱敏、盲化的候选报告；
- `reader_a`、`reader_b`、`adjudication` 三个空标注槽位；
- `source_case_sha256`，用于源数据漂移核对。

模型身份映射位于 `internal/model_blinding_map.json`，只供项目管理员在两位 reader 完成后进行分析，不得发给 reader。

## 标注流程

1. 将整个 `outputs/annotation/pilot10_20260717/` 复制到 reader A 和 reader B 各自隔离的工作目录；
2. 两位 reader 独立填写各自槽位，不查看另一位 reader 的文件，不修改候选顺序；
3. 两位 reader 都完成后，项目管理员合并到 adjudication 工作目录；
4. 只有两位 reader 都是 `complete` 后，才允许填写 `adjudication`；
5. 完成后运行：

```bash
PYTHONPATH=src .venv/bin/python -m medharness2.cli \
  annotation validate \
  --package-dir outputs/annotation/pilot10_20260717
```

当前预期结果是 `status=not_started`、`case_count=10`；完成真实标注后才会变为 `in_progress` 或 `complete`。

## 证据边界

- 自动生成的候选、规则抽取和模型建议不是医生标注；
- 不要把任何合成草稿复制到 `reader_a`、`reader_b` 或 `adjudication` 槽位；
- 这 10 例是临床标注准备/校准集，尚未升级为正式临床 gold 或 formal benchmark；
- 标注完成后仍需进行双读一致性、adjudication 和独立统计审查。

## OCR 与论文实验交接

研究 manifest 位于：

```text
outputs/research/20260717/
```

重新生成命令：

```bash
PYTHONPATH=src .venv/bin/python -m medharness2.cli \
  research prepare-manifests \
  --pilot-dir outputs/annotation/pilot10_20260717 \
  --output-dir outputs/research/20260717
```

当前 OCR `winner_status=blocked`，原因是缺少真实 clinical gold 和真实 provider 双次运行；在这两项证据就位前不得发布 winner 或论文正式结果。
