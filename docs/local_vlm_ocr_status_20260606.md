# Local VLM OCR Status 2026-06-06

## 目的

为避免报告 OCR 只能依赖云端 API，medHarness2 已新增 `llm.provider: local_vlm_cli`。
该 provider 会把扫描 PDF 渲染成临时 PNG，然后调用旧项目
`/data/isbi/gzp/medHarness/scripts/run_report_generation.py` 中的本地 VLM adapter。

推荐配置入口：

```yaml
llm:
  provider: local_vlm_cli
  model: qwen25vl_7b_instruct
  local_cli_script: /data/isbi/gzp/medHarness/scripts/run_report_generation.py
  local_cli_config_path: /data/isbi/gzp/medHarness/configs/reportgen_models.yaml
  local_cli_device: cuda:0
  local_cli_dtype: bf16
  local_cli_max_new_tokens: 512
```

## 已实现

- `LLMClient` 支持 `local_vlm_cli` / `medharness_cli_vlm`。
- 普通图片会作为 `image_paths` 传入旧项目 runner。
- PDF 会先渲染成临时 PNG，再作为图片输入。
- OCR cache 的 `.ocr.json` 会记录 `provider: local_vlm_cli` 和本地模型名。
- 单元测试覆盖本地 runner 调用和 PDF 渲染路径。

## 当前资源状态

本机旧项目配置中存在 `qwen25vl_7b_instruct`，但当前 dry-run 结果为不可用：

```bash
python /data/isbi/gzp/medHarness/scripts/run_report_generation.py \
  --model-key qwen25vl_7b_instruct \
  --dry-run
```

结果：

```text
status=debug_asset_missing
missing_paths=/data/isbi/gzp/medHarness/resources/models/qwen25vl_7b_instruct
```

该路径是一个软链：

```text
/data/isbi/gzp/medHarness/resources/models/qwen25vl_7b_instruct
-> /home/ubuntu/.cache/huggingface/hub/models--Qwen--Qwen2.5-VL-7B-Instruct/snapshots/cc594898137f460bfe9f0759e9844b3ce807cfb5
```

但当前 `/home/ubuntu/.cache/huggingface/hub` 下没有对应 Qwen snapshot。因此现在只能说：

- 本地 VLM OCR 接口已经接好。
- `qwen25vl_7b_instruct` 资源当前不可用，不能声称真实本地 OCR 已跑通。
- 修复方式是恢复该 HF cache snapshot，或把软链改到实际存在的本地 Qwen2.5-VL 权重目录。

## 验证

```bash
python -m compileall src tests
python -m pytest -q
```

结果：`73 passed, 9 warnings`。

## 对样本全流程的影响

`/data/isbi/gzp/medHarness/data/sample_data_2026-06-05` 的 PDF 报告没有文本层，
正式评测必须先完成真实 OCR。当前可选路径如下：

1. 修复本地 `qwen25vl_7b_instruct` 权重路径后，用 `local_vlm_cli` 跑 OCR。
2. 使用新增的 `local_hf_vlm` 直连本地 HF VLM 权重目录。
3. 使用云端 VLM OCR。
4. 继续使用 mock OCR 只做工程闭环验证，但不能作为正式评价结果。

## Qwen3-VL 4B 本地路径

进一步扫描本机后，发现可用的 Qwen3-VL 4B 权重：

```text
/data/cyf/shared_data/hd_data/qwen3-vl-4B
```

该目录包含 `config.json`、`preprocessor_config.json`、`tokenizer_config.json`、
`model.safetensors.index.json` 和 2 个 safetensors shard。medHarness2 已新增
`llm.provider: local_hf_vlm`，可直接使用该目录，不依赖旧项目 registry。

配置示例：

```yaml
llm:
  provider: local_hf_vlm
  model: qwen3-vl-4b
  local_hf_model_path: /data/cyf/shared_data/hd_data/qwen3-vl-4B
  local_hf_device: cuda:0
  local_hf_dtype: bf16
  local_hf_max_new_tokens: 384
```

仓库内也提供了可直接使用的配置文件：

```text
config/local_hf_qwen3vl4b.yaml
```

## Qwen3-VL 4B OCR Smoke

已对样本集 1 例扫描 PDF 执行真实本地 OCR：

```bash
CUDA_VISIBLE_DEVICES=0 PYTHONPATH=src python - <<'PY'
from medharness2.config import LLMConfig, load_config
from medharness2.data.sample_data import prepare_sample_dataset

cfg = load_config()
cfg.llm = LLMConfig(
    provider="local_hf_vlm",
    model="qwen3-vl-4b",
    local_hf_model_path="/data/cyf/shared_data/hd_data/qwen3-vl-4B",
    local_hf_device="cuda:0",
    local_hf_dtype="bf16",
    local_hf_max_new_tokens=384,
)
prepare_sample_dataset(
    "/data/isbi/gzp/medHarness/data/sample_data_2026-06-05",
    "outputs/sample_data_2026-06-05_local_hf_qwen3vl4b_ocr_limit1_20260606",
    config=cfg,
    limit=1,
    run_ocr=True,
    require_real_ocr=True,
    force_ocr=True,
)
PY
```

校验：

```bash
PYTHONPATH=src python -m medharness2.cli workflow validate-run \
  --output-dir outputs/sample_data_2026-06-05_local_hf_qwen3vl4b_ocr_limit1_20260606 \
  --expected-cases 1 \
  --require-real-ocr \
  --no-require-workflows
```

结果：`passed=true`，`real_ocr_count=1`，`mock_ocr_count=0`，`unknown_ocr_count=0`。
OCR 文本成功提取中文报告正文，包括检查所见、诊断印象、报告医生和审核时间。

随后已扩展到 52 例样本：

```text
outputs/sample_data_2026-06-05_local_hf_qwen3vl4b_ocr_52_20260606
```

结果：`cases=52`，`with_report_text=52`，`warnings={}`。

最终校验：

```text
passed=true
real_ocr_count=52
mock_ocr_count=0
unknown_ocr_count=0
failed_case_count=0
```

详见：

```text
docs/sample_data_2026-06-05_real_ocr_qwen3vl4b_20260606.md
```
