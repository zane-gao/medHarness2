# 盲区扫描前端集成说明

## 快速预览

前端页面现在包含完整的代码审计与盲区扫描结果展示。

### 访问方式

在浏览器中打开：
```
file:///nfsdata_a40/isbi/gzp/medHarness2/web/index.html
```

或者启动本地服务器：
```bash
cd /nfsdata_a40/isbi/gzp/medHarness2/web
python3 -m http.server 8080
# 然后访问 http://localhost:8080/index.html
```

### 新增内容

**⑥.7 代码审计与盲区扫描**章节包含：

1. **统计摘要**（5 个 KPI）
   - 原始发现：54 条 → 验证后 37 条
   - CRITICAL：1 条
   - HIGH：17 条  
   - MEDIUM：13 条
   - 已核实非缺陷：4 条

2. **CRITICAL 级别问题**（安全红线）
   - C1: FastAPI 全部端点无鉴权 + 任意文件读写

3. **HIGH 级别问题**（17 条，分 5 类）
   - 安全与隐私（4 条）
   - 统计有效性（4 条）
   - 数据质量与 Mock 泄漏（3 条）
   - 复现性与测试（4 条）
   - LLM 集成（2 条）

4. **MEDIUM 级别问题**（13 条，可折叠）

5. **修复优先级路线图**（三梯队）
   - 梯队 1：数字可信度地基
   - 梯队 2：合规红线
   - 梯队 3：评委可靠性

6. **已验证的正面结论**
   - 权威 benchmark 未被 mock/fallback 污染
   - LLMClient 完整实现
   - 安全检查通过

## 重新构建

修改盲区扫描文档后，重新生成前端页面：

```bash
cd /nfsdata_a40/isbi/gzp/medHarness2
python web/build_panel.py
```

输出示例：
```
✔ 已生成 /nfsdata_a40/isbi/gzp/medHarness2/web/index.html
  盲区扫描: C:1 H:17 M:13 L:6 | 审计方法: 62 agents + 对抗性验证
```

## 数据来源

- **源文档**：`docs/blindspot_audit_20260714.md`
- **提取函数**：`web/build_panel.py::extract_blindspot_audit()`
- **渲染代码**：`web/panel_template.html`（JavaScript 部分）

## 技术实现

### 后端（Python）

```python
def extract_blindspot_audit(path: Path) -> dict | None:
    """从 markdown 文档提取结构化问题列表"""
    # 使用正则表达式解析 markdown
    # 提取 CRITICAL/HIGH/MEDIUM 问题
    # 提取修复优先级
    # 提取核心结论
    return {
        "stats": {...},
        "critical_issues": [...],
        "high_issues": [...],
        "medium_issues": [...],
        "fix_priority": {...},
        "core_conclusion": "...",
    }
```

### 前端（JavaScript）

```javascript
const BA = DATA.blindspot_audit;
if (BA) {
  // 渲染 5 个 KPI 卡片
  // 渲染问题列表（带颜色和折叠）
  // 渲染修复优先级（三梯队）
}
```

## 自定义样式

所有审计相关的 CSS 类：

- `.audit-summary` - 统计摘要网格
- `.audit-kpi` - KPI 卡片
- `.issue-card` - 问题卡片（带 `.critical`, `.high`, `.medium` 修饰符）
- `.tier-section` - 修复优先级分梯队
- `.conclusion-box` - 核心结论高亮框

## 问题反馈

如果发现问题或需要改进，请：
1. 检查 `docs/blindspot_audit_20260714.md` 格式是否正确
2. 查看构建日志是否有错误
3. 在浏览器开发者工具中检查 JavaScript 错误

## 版本历史

- **2026-07-15**：初始集成完成
  - 新增代码审计章节
  - 实现数据提取和渲染
  - 完成 1 CRITICAL + 17 HIGH + 13 MEDIUM 问题展示
