# 真实医生标注交接说明（2026-07-17）

## 当前包

本轮从 52 例运行产物中确定性筛出 10 例，覆盖 `cxr`、`ct`、`mri`：

```text
annotation/pilot10/
```

包内每个病例都包含：

- 脱敏后的参考报告文本；
- 脱敏、盲化的候选报告；
- `reader_a`、`reader_b`、`adjudication` 三个空标注槽位；
- `source_case_sha256`，用于源数据漂移核对。

当前 OCR/文本 benchmark 的 gold 输入为北川参考报告（`gold_source=beichuan_reference_report`）。本包中的 reader 槽位用于后续临床校准，不会替换或回写该文本 gold。

模型身份映射位于 `internal/model_blinding_map.json`，只供项目管理员在两位 reader 完成后进行分析，不得发给 reader。

## 标注流程

1. 使用 `annotation export-reader` 分别生成只含一个 reader 槽位的隔离副本：

   ```bash
   PYTHONPATH=src .venv/bin/python -m medharness2.cli \
     annotation export-reader \
     --package-dir annotation/pilot10 \
     --output-dir /path/to/reader_a_package \
     --reader reader_a
   ```

   `reader_b` 使用同一命令替换 `--reader`。导出命令不会复制 `internal/model_blinding_map.json`，
   也会清空另一个 reader 和 adjudication 槽位，避免交叉泄漏。
2. 两位 reader 独立填写各自副本，不查看另一位 reader 的文件，不修改候选顺序；
3. 两位 reader 都完成后，项目管理员合并到 adjudication 工作目录；
4. 只有两位 reader 都是 `complete` 后，才允许填写 `adjudication`；
5. 完成后运行：

```bash
PYTHONPATH=src .venv/bin/python -m medharness2.cli \
  annotation validate \
  --package-dir annotation/pilot10
```

当前预期结果是 `status=not_started`、`case_count=10`；完成真实标注后才会变为 `in_progress` 或 `complete`。

导出副本回收前也必须单独运行 `annotation validate --package-dir <reader_package>`；管理员合并后，
再对主包运行一次 validate，确保病例数、候选顺序和三个槽位均未漂移。

管理员回收命令（以 reader A 为例）：

```bash
PYTHONPATH=src .venv/bin/python -m medharness2.cli \
  annotation import-reader \
  --package-dir annotation/pilot10 \
  --reader-package-dir /path/to/reader_a_package \
  --reader reader_a
```

回收过程只写入指定 reader 槽位，并拒绝源 hash、病例身份、模态、部位或候选文本发生漂移的副本；
主包已有的 complete 槽位也会拒绝覆盖。回收后必须再次运行主包 validate。

回收采用同目录暂存、备份与失败回滚；如果某个病例写回失败，之前已写入的病例文件和主 manifest 会恢复，
不会留下“部分 reader 已合并”的主包。参考报告和 `instructions_version` 也必须与主包一致。

## 证据边界

- 自动生成的候选、规则抽取和模型建议不是医生标注；
- 不要把任何合成草稿复制到 `reader_a`、`reader_b` 或 `adjudication` 槽位；
- 这 10 例是临床标注准备/校准集；完成双读和 adjudication 后，才可用于临床一致性分析与 formal benchmark 门禁；
- 标注完成后仍需进行双读一致性、adjudication 和独立统计审查。

## OCR 与论文实验交接

研究 manifest 位于：

```text
outputs/research/20260717/（本地 outputs/ 产物，被忽略规则排除；可用命令重建）
```

重新生成命令：

```bash
PYTHONPATH=src .venv/bin/python -m medharness2.cli \
  research prepare-manifests \
  --pilot-dir annotation/pilot10 \
  --output-dir outputs/research/20260717
```

当前 OCR `winner_status=blocked`：北川 gold 已可用，但真实 provider 双次运行尚未完成；在候选覆盖、质量和重复一致性门禁通过前不得发布 winner 或论文正式结果。
