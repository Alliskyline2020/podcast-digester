# LLM Provider 区域选择器（国内 / 国际）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `/settings` 厂商下拉上方加「国内 / 国际」区域选择器，选中后只显示该区域命名厂商；兼容自定义端点始终在底部「自定义兼容端点」分组常驻。

**Architecture:** 后端 PROVIDERS 表每项加 `region` 字段作为单一事实源，GET 端点透出；前端据 `region` 渲染区域单选 + 用 `<optgroup>` 过滤/分组厂商下拉。region 纯派生、不入库，不影响 PUT、不影响 base_url 锁定、不触及 SSRF 守卫。

**Tech Stack:** FastAPI（后端）、Vue 3 原生 JS + scoped CSS（前端）、pytest / vitest（测试）。

## Global Constraints

- **region 取值**：仅 `"国内"` / `"国际"` / `""`（空 = 兼容自定义端点，地区无关）。分类：deepseek/glm/glm-coding/qwen/doubao/moonshot=国内；openai/anthropic=国际；两个 compatible=""。
- **region 不入库、不进 PUT**：纯 UI 派生；页面加载时据已存 provider 的 region 反推。
- **不动锁定 / SSRF / PUT 链路**：`provider_base_url_editable` / `resolve_effective_base_url` / `_assert_public_https_base_url` 一律不改。
- **GLM Coding Plan 保持两个独立 provider**（`glm` + `glm-coding`，均属国内），不为其单独做开关。
- **提交纪律（用户常设约束）**：实现 + 测试全绿后**不自动 commit/push**，staged 即停，等用户显式说「提交」。
- 测试约定：后端 `pytest`（asyncio_mode=auto、`--strict-markers`），前端 `vitest`。
- 后端测试命令前缀：`cd /Users/alli/podcast-digester/backend && PYTHONPATH=. ./venv/bin/python -m pytest`
- 前端命令前缀：`cd /Users/alli/podcast-digester/frontend && npm run`

---

### Task 1: 后端 — PROVIDERS 加 region + GET 透出

**Files:**
- Modify: `backend/app/llm/config.py`（PROVIDERS 表，每个条目加 `region`）
- Modify: `backend/app/routers/llm_config.py:40-51`（`_public_providers()` 多返回 `region`）
- Test: `backend/tests/test_llm_config.py`（新增 region 断言）
- Test: `backend/tests/test_llm_config_api.py`（新增 GET 透出 region 断言）

**Interfaces:**
- Consumes: 无（本任务是数据源起点）
- Produces: PROVIDERS 每项含 `"region": "国内"|"国际"|""`；GET `/api/admin/llm-config` 返回 `providers[*].region`

- [ ] **Step 1: 写失败测试（`backend/tests/test_llm_config.py` 末尾追加）**

```python
# ==================== region（国内/国际）测试 ====================

def test_providers_have_region_field():
    for name, p in PROVIDERS.items():
        assert "region" in p, f"{name} 缺 region"
        assert p["region"] in ("国内", "国际", ""), f"{name} region 取值非法: {p['region']!r}"


def test_region_classification():
    domestic = {"deepseek", "glm", "glm-coding", "qwen", "doubao", "moonshot"}
    overseas = {"openai", "anthropic"}
    compat = {"openai-compatible", "anthropic-compatible"}
    for name in domestic:
        assert PROVIDERS[name]["region"] == "国内", f"{name} 应为国内"
    for name in overseas:
        assert PROVIDERS[name]["region"] == "国际", f"{name} 应为国际"
    for name in compat:
        assert PROVIDERS[name]["region"] == "", f"{name} 应为地区无关(空)"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd /Users/alli/podcast-digester/backend && PYTHONPATH=. ./venv/bin/python -m pytest tests/test_llm_config.py::test_providers_have_region_field tests/test_llm_config.py::test_region_classification -q`
Expected: FAIL（`KeyError: 'region'`）

- [ ] **Step 3: 实现 — `config.py` 每个 PROVIDERS 条目加 `region`**

逐条追加（保持原有字段顺序，在 `default_model` 后加 `region`）。完整新表如下，**整段替换** `PROVIDERS: dict[str, dict] = { ... }`（即 `config.py` 第 25–88 行）：

```python
PROVIDERS: dict[str, dict] = {
    "deepseek": {
        "title": "DeepSeek",
        "provider_type": "openai_compatible",
        "default_base_url": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
        "region": "国内",
    },
    "openai": {
        "title": "OpenAI",
        "provider_type": "openai_compatible",
        "default_base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "region": "国际",
    },
    "anthropic": {
        "title": "Anthropic (Claude)",
        "provider_type": "anthropic_compatible",
        "default_base_url": "https://api.anthropic.com",
        "default_model": "claude-3-5-sonnet-latest",
        "region": "国际",
    },
    "glm": {
        "title": "智谱 GLM",
        "provider_type": "openai_compatible",
        "default_base_url": "https://open.bigmodel.cn/api/paas/v4",          # 标准端点
        "default_model": "glm-4-flash",
        "region": "国内",
    },
    "glm-coding": {
        "title": "智谱 GLM Coding Plan",
        "provider_type": "openai_compatible",
        "default_base_url": "https://open.bigmodel.cn/api/coding/paas/v4",   # 编码套件(Coding)专用端点
        "default_model": "",   # 套餐模型需拉取后选择
        "region": "国内",
    },
    "qwen": {
        "title": "通义千问",
        "provider_type": "openai_compatible",
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
        "region": "国内",
    },
    "doubao": {
        "title": "字节豆包",
        "provider_type": "openai_compatible",
        "default_base_url": "https://ark.cn-beijing.volces.com/api/v3",
        # 豆包模型 id 实为 endpoint id，需用户在火山控制台创建后填入（模型下拉会拉不到，走手动输入）
        "default_model": "",
        "region": "国内",
    },
    "moonshot": {
        "title": "月之暗面 Kimi",
        "provider_type": "openai_compatible",
        "default_base_url": "https://api.moonshot.cn/v1",
        "default_model": "moonshot-v1-8k",
        "region": "国内",
    },
    # 通用兜底：用户自填 base_url / model（default_base_url 空 = 可自由输入；region 空 = 地区无关）
    "openai-compatible": {
        "title": "OpenAI 兼容(自定义端点)",
        "provider_type": "openai_compatible",
        "default_base_url": "",
        "default_model": "",
        "region": "",
    },
    "anthropic-compatible": {
        "title": "Anthropic 兼容(自定义端点)",
        "provider_type": "anthropic_compatible",
        "default_base_url": "",
        "default_model": "",
        "region": "",
    },
}
```

同步把 PROVIDERS 表上方的注释（`config.py` 第 19–24 行）补一句关于 region 的说明，整段替换为：

```python
# ==================== PROVIDERS 预设表 ====================
# 每个条目：title(展示名) / provider_type(协议) / default_base_url / default_model / region
# 设计：1 provider = 1 固定 base_url。不同端点/套餐拆成独立 provider
# （如「智谱 GLM」标准端点 vs「智谱 GLM Coding Plan」编码套件端点）。
# default_base_url 留空 = 兼容自定义端点，base_url 可由用户自由填写。
# region：国内/国际 用于设置页区域筛选；空 = 兼容自定义端点（地区无关，常驻底部）。
# URL 与模型名以厂商官方文档为准（impl 时已核对）。
```

- [ ] **Step 4: 实现 — `routers/llm_config.py` 的 `_public_providers()` 透出 region**

把 `_public_providers()`（第 40–51 行）整段替换为：

```python
def _public_providers() -> dict:
    """给下拉用的预设（全是展示字段，无敏感信息）。"""
    return {
        name: {
            "title": p["title"],
            "provider_type": p["provider_type"],
            "default_base_url": p["default_base_url"],
            "base_url_editable": provider_base_url_editable(name),
            "default_model": p["default_model"],
            "region": p.get("region", ""),
        }
        for name, p in PROVIDERS.items()
    }
```

- [ ] **Step 5: 运行确认 Task 1 两个新测试通过**

Run: `cd /Users/alli/podcast-digester/backend && PYTHONPATH=. ./venv/bin/python -m pytest tests/test_llm_config.py::test_providers_have_region_field tests/test_llm_config.py::test_region_classification -q`
Expected: PASS

- [ ] **Step 6: 写失败测试 — GET 透出 region（`backend/tests/test_llm_config_api.py` 末尾追加）**

```python
@pytest.mark.api
async def test_get_exposes_region(cfg_env, monkeypatch):
    from app.llm.runtime_config import write_runtime_override
    await write_runtime_override({"provider": "deepseek", "api_key": "sk-x"})
    body = _client().get("/api/admin/llm-config").json()
    assert body["providers"]["deepseek"]["region"] == "国内"
    assert body["providers"]["openai"]["region"] == "国际"
    assert body["providers"]["openai-compatible"]["region"] == ""
```

- [ ] **Step 7: 运行确认通过（实现已在 Step 4 完成，应直接绿）**

Run: `cd /Users/alli/podcast-digester/backend && PYTHONPATH=. ./venv/bin/python -m pytest tests/test_llm_config_api.py::test_get_exposes_region -q`
Expected: PASS

- [ ] **Step 8: 跑后端全量回归**

Run: `cd /Users/alli/podcast-digester/backend && PYTHONPATH=. ./venv/bin/python -m pytest -q`
Expected: 全绿（上一轮基线 426 passed + 本任务 3 个新增）

- [ ] **Step 9: 暂存（不 commit）**

Run: `cd /Users/alli/podcast-digester && git add backend/app/llm/config.py backend/app/routers/llm_config.py backend/tests/test_llm_config.py backend/tests/test_llm_config_api.py`
（按 Global Constraints，**不执行 git commit**，等用户显式「提交」。）

---

### Task 2: 前端 — 区域选择器 + 厂商过滤分组

**Files:**
- Modify: `frontend/src/views/SettingsView.vue`（模板加区域单选 + optgroup；script 加 region/计算属性/watch/load 反推；style 加 `.region-switch`）
- Test: `frontend/tests/views/SettingsView.spec.js`（新增 region 测试；既有 fixture 补 region 字段）

**Interfaces:**
- Consumes: Task 1 的 `GET providers[*].region`（`"国内"|"国际"|""`）
- Produces: 无新对外接口（纯 UI）

- [ ] **Step 1: 给既有测试 fixture 补 region 字段（先让「现状」明确）**

`frontend/tests/views/SettingsView.spec.js` 的 `deepseekProviders()`（第 18–26 行）整体替换为（加 `region: '国内'`）：

```javascript
function deepseekProviders(overrides = {}) {
  return {
    deepseek: Object.assign({
      title: 'DeepSeek', provider_type: 'openai_compatible',
      default_base_url: 'https://api.deepseek.com',
      base_url_editable: false, default_model: 'deepseek-chat', region: '国内',
    }, overrides),
  }
}
```

「lists GLM and GLM Coding Plan」用例（第 104–131 行）的 `providers` 对象里，给 `glm` 和 `'glm-coding'` 各加 `region: '国内'`（在 `default_model` 那行后）。即：

```javascript
providers: {
  glm: {
    title: '智谱 GLM', provider_type: 'openai_compatible',
    default_base_url: 'https://open.bigmodel.cn/api/paas/v4',
    base_url_editable: false, default_model: 'glm-4-flash', region: '国内',
  },
  'glm-coding': {
    title: '智谱 GLM Coding Plan', provider_type: 'openai_compatible',
    default_base_url: 'https://open.bigmodel.cn/api/coding/paas/v4',
    base_url_editable: false, default_model: '', region: '国内',
  },
},
```

「renders free-text input for compatible providers」用例（第 133–147 行）的 `'openai-compatible'` 加 `region: ''`：

```javascript
providers: { 'openai-compatible': {
  title: 'OpenAI 兼容(自定义端点)', provider_type: 'openai_compatible',
  default_base_url: '', base_url_editable: true, default_model: '', region: '',
} },
```

- [ ] **Step 2: 写失败测试 — 在文件末尾 `})` 之前追加（先加 fixture 辅助 + 5 个用例）**

```javascript
function fullProviders() {
  return {
    deepseek: { title: 'DeepSeek', provider_type: 'openai_compatible', default_base_url: 'https://api.deepseek.com', base_url_editable: false, default_model: 'deepseek-chat', region: '国内' },
    openai: { title: 'OpenAI', provider_type: 'openai_compatible', default_base_url: 'https://api.openai.com/v1', base_url_editable: false, default_model: 'gpt-4o-mini', region: '国际' },
    glm: { title: '智谱 GLM', provider_type: 'openai_compatible', default_base_url: 'https://open.bigmodel.cn/api/paas/v4', base_url_editable: false, default_model: 'glm-4-flash', region: '国内' },
    'glm-coding': { title: '智谱 GLM Coding Plan', provider_type: 'openai_compatible', default_base_url: 'https://open.bigmodel.cn/api/coding/paas/v4', base_url_editable: false, default_model: '', region: '国内' },
    'openai-compatible': { title: 'OpenAI 兼容(自定义端点)', provider_type: 'openai_compatible', default_base_url: '', base_url_editable: true, default_model: '', region: '' },
  }
}

it('renders a 国内/国际 region switch with two radios', async () => {
  const w = await mountView({
    provider: 'deepseek', provider_type: 'openai_compatible',
    base_url: 'https://api.deepseek.com', model: 'deepseek-chat',
    has_api_key: true, api_key_masked: '****1234', providers: fullProviders(),
  })
  const radios = w.findAll('.region-switch input[type="radio"]')
  expect(radios.length).toBe(2)
  expect(radios.map(r => r.element.value).sort()).toEqual(['国际', '国内'])
})

it('国内 lists domestic vendors and compat; 国际 lists overseas and compat', async () => {
  const w = await mountView({
    provider: 'deepseek', provider_type: 'openai_compatible',
    base_url: 'https://api.deepseek.com', model: 'deepseek-chat',
    has_api_key: true, api_key_masked: '****1234', providers: fullProviders(),
  })
  let opts = w.find('#provider').findAll('option').map(o => o.text())
  expect(opts).toContain('DeepSeek')
  expect(opts).toContain('智谱 GLM Coding Plan')
  expect(opts).not.toContain('OpenAI')            // 国际厂商不在国内列表
  expect(opts).toContain('OpenAI 兼容(自定义端点)') // 兼容常驻

  // 切到国际
  await w.find('.region-switch input[value="国际"]').setValue()
  await flushPromises()
  opts = w.find('#provider').findAll('option').map(o => o.text())
  expect(opts).toContain('OpenAI')
  expect(opts).not.toContain('DeepSeek')          // 国内厂商被滤掉
  expect(opts).toContain('OpenAI 兼容(自定义端点)') // 兼容仍常驻
})

it('switching region resets provider to first vendor of new region', async () => {
  const w = await mountView({
    provider: 'deepseek', provider_type: 'openai_compatible',
    base_url: 'https://api.deepseek.com', model: 'deepseek-chat',
    has_api_key: true, api_key_masked: '****1234', providers: fullProviders(),
  })
  await w.find('.region-switch input[value="国际"]').setValue()
  await flushPromises()
  expect(w.find('#provider').element.value).toBe('openai')   // deepseek→openai
})

it('derives region from saved provider on load', async () => {
  const w = await mountView({
    provider: 'openai', provider_type: 'openai_compatible',
    base_url: 'https://api.openai.com/v1', model: 'gpt-4o-mini',
    has_api_key: true, api_key_masked: '****9999', providers: fullProviders(),
  })
  const checked = w.findAll('.region-switch input[type="radio"]')
    .filter(r => r.element.checked).map(r => r.element.value)
  expect(checked).toEqual(['国际'])
})

it('defaults region to 国内 when saved provider is compat and keeps provider', async () => {
  const w = await mountView({
    provider: 'openai-compatible', provider_type: 'openai_compatible',
    base_url: 'https://my-proxy/v1', model: 'gpt-4o',
    has_api_key: true, api_key_masked: '****1', providers: fullProviders(),
  })
  const checked = w.findAll('.region-switch input[type="radio"]')
    .filter(r => r.element.checked).map(r => r.element.value)
  expect(checked).toEqual(['国内'])
  expect(w.find('#provider').element.value).toBe('openai-compatible')
})
```

- [ ] **Step 3: 运行确认失败**

Run: `cd /Users/alli/podcast-digester/frontend && npm run test -- --run`
Expected: 新增 5 个用例 FAIL（找不到 `.region-switch`）；既有用例因 Step 1 补字段仍应绿。

- [ ] **Step 4: 实现 — 模板：区域单选 + optgroup（替换 `SettingsView.vue` 第 15–20 行的 provider field 块）**

```html
      <div class="field">
        <label for="provider">Provider</label>
        <div class="region-switch" role="group" aria-label="厂商地区">
          <label><input type="radio" value="国内" v-model="region" /> 国内</label>
          <label><input type="radio" value="国际" v-model="region" /> 国际</label>
        </div>
        <select id="provider" v-model="form.provider" @change="onProviderChange">
          <optgroup :label="region">
            <option v-for="(p, key) in namedProvidersInRegion" :key="key" :value="key">{{ p.title || key }}</option>
          </optgroup>
          <optgroup label="自定义兼容端点">
            <option v-for="(p, key) in compatProviders" :key="key" :value="key">{{ p.title || key }}</option>
          </optgroup>
        </select>
      </div>
```

- [ ] **Step 5: 实现 — script：import watch + region 状态 + 计算属性**

`SettingsView.vue` 第 90 行的 import 整行替换为（加 `watch`）：

```javascript
import { reactive, ref, computed, watch, onMounted, onUnmounted } from 'vue'
```

在第 106 行 `const baseUrlEditable = ref(false)` 之后、第 107 行注释之前插入区域状态与计算属性：

```javascript
// 区域筛选（国内/国际）；兼容自定义端点 region="" 永远常驻底部
const region = ref('国内')
const namedProvidersInRegion = computed(() => {
  const out = {}
  for (const [key, p] of Object.entries(providers.value)) {
    if ((p.region ?? '') === region.value) out[key] = p
  }
  return out
})
const compatProviders = computed(() => {
  const out = {}
  for (const [key, p] of Object.entries(providers.value)) {
    if ((p.region ?? '') === '') out[key] = p
  }
  return out
})
// 切换区域：若当前是命名厂商且不在新区域，重置到新区域第一个厂商
watch(region, (nv) => {
  const cur = providers.value[form.provider]
  if (cur && (cur.region ?? '') !== '' && (cur.region ?? '') !== nv) {
    const firstNamed = Object.keys(namedProvidersInRegion.value)[0]
    if (firstNamed) { form.provider = firstNamed; onProviderChange() }
  }
})
```

- [ ] **Step 6: 实现 — `load()` 反推 region**

在 `load()`（第 159–176 行）里，`form.provider = cfg.provider || 'deepseek'`（第 163 行）之后插入一行反推 region：

```javascript
    form.provider = cfg.provider || 'deepseek'
    // 据已存 provider 的 region 反推区域；兼容项(region '')默认国内
    const savedP = providers.value[form.provider]
    region.value = (savedP && savedP.region) || '国内'
```

（注意：`onProviderChange` 在此文件第 143 行已定义，被 Step 5 的 watch 引用——`watch`/函数在 `<script setup>` 中均为顶层声明，提升顺序不影响运行时引用，无需调整顺序。）

- [ ] **Step 7: 实现 — style 加 `.region-switch`**

在 `<style scoped>` 内 `.field input, .field select {` 规则块（第 303–311 行）之后插入：

```css
.region-switch {
  display: flex;
  gap: 16px;
  margin-bottom: 2px;
}
.region-switch label {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 14px;
  font-weight: 500;
  color: #374151;
  cursor: pointer;
}
.region-switch input[type="radio"] {
  width: auto;
  margin: 0;
  accent-color: #4f8ef7;
}
```

- [ ] **Step 8: 运行确认全部前端测试通过**

Run: `cd /Users/alli/podcast-digester/frontend && npm run test -- --run`
Expected: PASS（上一轮基线 112 passed + 本任务 5 个新增）

- [ ] **Step 9: 前端 build 通过**

Run: `cd /Users/alli/podcast-digester/frontend && npm run build`
Expected: build 成功（无报错）

- [ ] **Step 10: 暂存（不 commit）**

Run: `cd /Users/alli/podcast-digester && git add frontend/src/views/SettingsView.vue frontend/tests/views/SettingsView.spec.js`
（按 Global Constraints，**不执行 git commit**，等用户显式「提交」。）

---

### Task 3: 全量回归 + 实测探针

**Files:**
- 无源码改动；只跑验证。

- [ ] **Step 1: 后端全量**

Run: `cd /Users/alli/podcast-digester/backend && PYTHONPATH=. ./venv/bin/python -m pytest -q`
Expected: 全绿

- [ ] **Step 2: 前端全量**

Run: `cd /Users/alli/podcast-digester/frontend && npm run test -- --run`
Expected: 全绿

- [ ] **Step 3: 前端 build**

Run: `cd /Users/alli/podcast-digester/frontend && npm run build`
Expected: 成功

- [ ] **Step 4: 实测探针 — 复用 `/tmp/verify_v2.py` 模式，在 GET 断言里加 region 校验**

在 `/tmp/verify_v2.py` 的「=== 4. HTTP GET 返回 editable + glm-coding, 无 base_urls ===」段末尾追加 3 行断言（用现有 `body` 变量，无需新请求）：

```python
check("deepseek region=国内", body["providers"]["deepseek"]["region"] == "国内")
check("openai region=国际", body["providers"]["openai"]["region"] == "国际")
check("openai-compatible region=空", body["providers"]["openai-compatible"]["region"] == "")
```

Run: `PYTHONPATH=/Users/alli/podcast-digester/backend /Users/alli/podcast-digester/backend/venv/bin/python /tmp/verify_v2.py 2>&1`
Expected: `ALL CHECKS PASSED`（上一轮 24 + 本任务 3 = 27 PASS / 0 FAIL）

- [ ] **Step 5: 汇报**

向用户汇报：后端/前端测试数、build、探针 27/27；改动已 staged、未 commit，等「提交」指令。

---

## Self-Review（已做）

1. **Spec coverage**：region 字段（Task1）✓；GET 透出（Task1）✓；区域单选（Task2）✓；过滤+optgroup（Task2）✓；兼容常驻（Task2）✓；load 反推（Task2）✓；切区域重置（Task2）✓；回归+探针（Task3）✓。
2. **Placeholder scan**：无 TBD/TODO；每个 step 都有完整代码与命令。
3. **Type consistency**：后端 `region` 字符串与前端 `p.region`、radio `value` 一致；`namedProvidersInRegion`/`compatProviders` 名前后一致；`onProviderChange` 复用既有函数。
