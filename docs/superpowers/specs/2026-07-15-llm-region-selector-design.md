# LLM Provider 区域选择器（国内 / 国际）设计

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this spec task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 在 `/settings` 的厂商下拉上方增加「国内 / 国际」区域选择器，选中后只显示该区域的命名厂商；兼容自定义端点始终在底部「自定义兼容端点」分组常驻。

**Architecture:** 区域是后端 PROVIDERS 表上的一个 `region` 字段（单一事实源）。GET 端点透出该字段，前端据此渲染区域选择器并过滤厂商下拉。region 是纯派生、不入库的 UI 分组维度，不影响 PUT、不影响 base_url 锁定逻辑、不触及 SSRF 守卫。

**Tech Stack:** FastAPI（后端）、Vue 3 + 原生 JS + scoped CSS（前端）、pytest / vitest（测试）。

## 背景与约束（继承自上一轮重构）

- 上一轮已统一为「1 provider = 1 固定 base_url」：命名厂商 `default_base_url` 非空 = 锁定只读；兼容自定义端点 `default_base_url` 为空 = 可编辑输入。
- GLM 已拆成两个独立 provider：`glm`（标准端点 paas/v4）与 `glm-coding`（编码套件 coding/paas/v4）。本轮**保持不变**。
- 锁定逻辑由 `provider_base_url_editable()` / `resolve_effective_base_url()` 负责，本轮**不改动**。
- SSRF 守卫 `_assert_public_https_base_url()` 对所有 base_url 输入生效，本轮**不改动**。

## 区域分类（事实，非设计选择）

| region | providers |
|---|---|
| `"国内"` | `deepseek`, `glm`, `glm-coding`, `qwen`, `doubao`, `moonshot` |
| `"国际"` | `openai`, `anthropic` |
| `""`（地区无关） | `openai-compatible`, `anthropic-compatible` |

判定依据：`deepseek`（深度求索，中国）、`glm`/`glm-coding`（智谱）、`qwen`（阿里）、`doubao`（字节）、`moonshot`（月之暗面）均属国内厂商；`openai`/`anthropic` 属国际；兼容自定义端点可指向任意地区，故地区无关。

## 后端改动

### `backend/app/llm/config.py` — PROVIDERS 加 region 字段

每个 provider 条目增加 `"region"` 键，取值为 `"国内"` / `"国际"` / `""`（空 = 兼容自定义端点）。示例：

```python
"deepseek": {
    "title": "DeepSeek",
    "provider_type": "openai_compatible",
    "default_base_url": "https://api.deepseek.com",
    "default_model": "deepseek-chat",
    "region": "国内",
},
# ... openai / anthropic => "国际"
# ... glm / glm-coding / qwen / doubao / moonshot => "国内"
# ... openai-compatible / anthropic-compatible => ""
```

### `backend/app/routers/llm_config.py` — GET 透出 region

`_public_providers()` 对每个 provider 增加返回字段：

```python
region=preset.get("region", "")
```

其余字段（title / provider_type / default_base_url / default_model / base_url_editable）不变。PUT 端点**不接收** region（派生值，不入库）。

### API 契约

GET `/api/admin/llm-config` 返回的 `providers[*]` 多一个 `region`，类型为字符串：

```jsonc
"providers": {
  "deepseek":          { "title": "DeepSeek", "...": ..., "region": "国内" },
  "openai":            { "...": ..., "region": "国际" },
  "openai-compatible": { "...": ..., "region": "" }
}
```

## 前端改动（`frontend/src/views/SettingsView.vue`）

### 区域选择器

厂商 `<select>` 上方新增两个单选按钮（segmented 风格）：

```html
<div class="region-switch" role="group" aria-label="厂商地区">
  <label><input type="radio" value="国内" v-model="region" /> 国内</label>
  <label><input type="radio" value="国际" v-model="region" /> 国际</label>
</div>
```

区域选项直接取 `["国内", "国际"]`（固定顺序，无需从 providers 派生）。

### 厂商下拉过滤与分组

厂商 `<select>` 用两个 `<optgroup>`：

```html
<select id="provider" v-model="form.provider">
  <optgroup :label="region">
    <option v-for="(p, key) in namedProvidersInRegion" :key="key" :value="key">{{ p.title }}</option>
  </optgroup>
  <optgroup label="自定义兼容端点">
    <option v-for="(p, key) in compatProviders" :key="key" :value="key">{{ p.title }}</option>
  </optgroup>
</select>
```

计算属性：

- `namedProvidersInRegion`：`providers` 中 `region === region.value`（非空）的命名厂商。
- `compatProviders`：`providers` 中 `region === ""` 的兼容端点（**永远显示**，不受区域切换影响）。

### 区域与厂商的联动

- **页面加载**（拿到 GET 返回后）：用已存 `provider` 的 `region` 反推并设置 `region.value`；若该 provider 为兼容项（region 为空），`region.value` 默认 `"国内"`。provider 本身不变。
- **切换区域**：watch `region`，若当前 `form.provider` 是命名厂商且其 region 不等于新区域，则把 `form.provider` 重置为新区域的第一个命名厂商；兼容项地区无关，切换区域不踢出兼容项。
- 切换厂商后仍调用既有的 `applyProviderDefaults()`（填默认 base_url / 锁定只读 / 拉取模型），逻辑复用、不改。

### 样式

`.region-switch` 用 flex 排列两个 radio，与既有表单视觉风格一致；不引入新依赖。

## 不做的事（YAGNI）

- region **不入库**、不持久化为配置字段；只从已存 provider 派生。
- **不新增第三个区域选项**（保持「国内/国际」两项）。
- **不为 GLM 单独做 coding 开关**：coding plan 维持 `glm` / `glm-coding` 两个独立 provider，二者同属「国内」。
- 不改动 base_url 锁定、SSRF 守卫、PUT 写入链路。

## 错误处理

- GET 返回缺失 `region` 字段时（向后兼容旧后端）：前端 `p.region ?? ""`，兼容端点归入底部分组，命名厂商仍按 title 展示（不会崩）。
- 若某区域无命名厂商（理论不会发生，除非预设表被清空）：第一个 optgroup 为空，只显示兼容端点分组，不报错。

## 测试

### 后端（pytest，`backend/tests/test_llm_config.py` / `test_llm_config_api.py`）

- 每个 PROVIDERS 条目都有 `region` 键，取值 ∈ {`"国内"`, `"国际"`, `""`}。
- 分类正确：deepseek/glm/glm-coding/qwen/doubao/moonshot = 国内；openai/anthropic = 国际；两个 compatible = 空。
- GET `/api/admin/llm-config` 的 `providers[*]` 含 `region` 字段且值正确。

### 前端（vitest，`frontend/tests/views/SettingsView.spec.js`）

- 渲染出区域选择器（两个 radio：国内 / 国际）。
- 选「国内」：厂商下拉含 DeepSeek / 智谱 GLM / 智谱 GLM Coding Plan 等国内厂商；选「国际」：含 OpenAI / Anthropic。
- 兼容自定义端点在「国内」「国际」两个区域下**都常驻**显示在底部「自定义兼容端点」分组。
- 加载时按已存 provider 反推区域：存 deepseek → 选中「国内」；存 openai → 选中「国际」；存 openai-compatible → 默认「国内」、provider 仍为 openai-compatible。
- 切换区域时，若当前命名厂商不在新区域，自动切到新区域第一个厂商（断言 `form.provider` 变化）。

### 实测（探针）

- 复用 `/tmp/verify_v2.py` 模式，新增断言：GET providers 含 region；deepseek=国内、openai=国际、openai-compatible=""。锁定与 DeepSeek 真实拉取回归不受影响。

## 验收标准

- [ ] 后端：PROVIDERS 全部含 region；GET 透出 region；分类正确。
- [ ] 前端：区域选择器渲染；过滤与分组正确；加载反推 + 切区域联动正确。
- [ ] 兼容端点两区常驻。
- [ ] 既有锁定 / SSRF / DeepSeek 真实拉取回归全绿。
- [ ] 后端测试全过、前端测试全过、前端 build 通过。
