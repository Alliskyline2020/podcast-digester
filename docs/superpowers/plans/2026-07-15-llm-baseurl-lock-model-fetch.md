# 设置页 base_url 锁定下拉 + 模型自动拉取 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在已有 `/settings` 页面把 base_url 变成「按 provider 锁定的下拉」、把 model 变成「填前三项后自动拉取的下拉」(拉取失败可手动输入)。

**Architecture:** `PROVIDERS` 预设新增每家固定的 `base_urls` 列表(单一事实源);后端新增 `list_models(cfg)` + `POST /api/admin/llm-config/models` 走服务端拉取(key 不出服务端、SSRF 守卫);前端 base_url 渲染为锁定 `<select>`(compatible 类型退化为自由 input),model 在 provider+key+base_url 齐全时自动拉取填入 `<select>`,失败切自由输入。

**Tech Stack:** Python 3 / FastAPI / Pydantic / pytest(后端);Vue 3 `<script setup>`(plain JS)/ Vite / Vitest + @vue/test-utils(前端)。OpenAI / Anthropic SDK 自带 `.models.list()`。

## Global Constraints

- **测试先行(TDD)**:每个任务先写失败测试 → 跑红 → 实现 → 跑绿。
- **不破坏跨进程配置机制**:本特性不动 `get_config()` / `runtime_config` / WAL,只在 PROVIDERS 加字段 + 新增只读的 `/models` 端点。
- **SSRF 守卫**:`base_url` 一切入参(含 `/models`)必须过 `_assert_public_https_base_url`。
- **key 安全**:`/models` 端点 `verify_admin`;key 不入响应、不入日志;前端永不预填真实 key。
- **错误信封**:后端业务失败走 200 体 `{ok:false, detail}`(与 `/test` 一致);非 2xx 才是全局 `{message}`。前端读 `result.detail` 或 `e.message`。
- **本地提交策略**:在特性分支 `feat/llm-baseurl-lock-model-fetch` 上逐任务 `git commit`(本地回滚用);**合并 main / push 远端仅在用户明确「提交/推送」时进行**。
- **后端测试 marker**:`@pytest.mark.llm`(client 单测)、`@pytest.mark.api`(端点)、`@pytest.mark.database`(DB);沿用现有 conftest 的 `temp_db` / `cfg_env` / `clean_llm_env` fixture。
- **前端**:`data-test` 属性做选择器;不引入新依赖;scoped CSS 沿用主色 `#4f8ef7`。
- **运行命令**:后端 `cd backend && python -m pytest tests/<file>::<test> -x`;前端 `cd frontend && npx vitest run tests/views/SettingsView.spec.js`。

**参考 spec**:[../specs/2026-07-15-llm-settings-provider-models-design.md](../specs/2026-07-15-llm-settings-provider-models-design.md)

---

## File Structure

- `backend/app/llm/config.py` — PROVIDERS 加 `base_urls` 字段 + 新 `provider_base_urls()` 辅助函数。
- `backend/app/llm/protocols.py` — `OpenAIAdapter` / `AnthropicAdapter` 各加 `async list_models()`。
- `backend/app/llm/client.py` — 新 `async list_models(cfg) -> tuple[bool, list[str] | str]`。
- `backend/app/routers/llm_config.py` — `_public_providers()` 加 `base_urls`/`base_url_editable`;新 `POST /api/admin/llm-config/models` 端点。
- `backend/tests/test_llm_config.py` — 加 base_urls / helper 单测。
- `backend/tests/test_llm_models.py` — 新文件:`list_models` 单测。
- `backend/tests/test_llm_config_api.py` — 加 `/models` 端点 + GET 返回 base_urls 的测试。
- `frontend/src/api.js` — 加 `listLlmModels(cfg)`。
- `frontend/src/views/SettingsView.vue` — base_url 锁定下拉 + model 自动拉取/手动兜底。
- `frontend/tests/views/SettingsView.spec.js` — 扩展测试。

---

### Task 1: PROVIDERS base_urls 锁定列表 + helper

**Files:**
- Modify: `backend/app/llm/config.py:23-80`(PROVIDERS 整块)
- Modify: `backend/app/llm/config.py`(新增 `provider_base_urls` 函数,置于 `infer_provider_type` 之后)
- Test: `backend/tests/test_llm_config.py`(追加测试)

**Interfaces:**
- Consumes: 无(纯数据)
- Produces: `PROVIDERS[name]["base_urls"]: list[str]`(每家固定下拉列表,首项=原 `default_base_url`;compatible 两家为 `[]`);`provider_base_urls(provider: str) -> list[str]`(缺失返回 `[]`)。后续 Task 3 的 `_public_providers()` 读 `base_urls`。

- [ ] **Step 1: Write the failing tests** — 追加到 `backend/tests/test_llm_config.py` 末尾:

```python
# ==================== base_urls 锁定列表测试 ====================

def test_providers_have_base_urls_list():
    for name, p in PROVIDERS.items():
        assert "base_urls" in p, f"{name} 缺 base_urls"
        assert isinstance(p["base_urls"], list)


def test_default_base_url_is_first_in_base_urls():
    for name, p in PROVIDERS.items():
        if p["base_urls"]:
            assert p["default_base_url"] == p["base_urls"][0], name


def test_glm_has_coding_endpoint():
    assert "https://open.bigmodel.cn/api/coding/paas/v4" in PROVIDERS["glm"]["base_urls"]


def test_moonshot_has_global_endpoint():
    assert "https://api.moonshot.ai/v1" in PROVIDERS["moonshot"]["base_urls"]


def test_compatible_providers_have_empty_base_urls():
    assert PROVIDERS["openai-compatible"]["base_urls"] == []
    assert PROVIDERS["anthropic-compatible"]["base_urls"] == []


def test_provider_base_urls_helper():
    from app.llm.config import provider_base_urls
    assert provider_base_urls("glm") == PROVIDERS["glm"]["base_urls"]
    assert provider_base_urls("openai-compatible") == []
    assert provider_base_urls("totally-unknown") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_llm_config.py -k "base_urls or provider_base_urls or coding or global" -x`
Expected: FAIL — `KeyError: 'base_urls'` / `ImportError: cannot import name 'provider_base_urls'`.

- [ ] **Step 3: Implement** — 把 `backend/app/llm/config.py` 的 PROVIDERS 整块替换为:

```python
PROVIDERS: dict[str, dict] = {
    "deepseek": {
        "title": "DeepSeek",
        "provider_type": "openai_compatible",
        "default_base_url": "https://api.deepseek.com",
        "base_urls": ["https://api.deepseek.com"],
        "default_model": "deepseek-chat",
    },
    "openai": {
        "title": "OpenAI",
        "provider_type": "openai_compatible",
        "default_base_url": "https://api.openai.com/v1",
        "base_urls": ["https://api.openai.com/v1"],
        "default_model": "gpt-4o-mini",
    },
    "anthropic": {
        "title": "Anthropic (Claude)",
        "provider_type": "anthropic_compatible",
        "default_base_url": "https://api.anthropic.com",
        "base_urls": ["https://api.anthropic.com"],
        "default_model": "claude-3-5-sonnet-latest",
    },
    "glm": {
        "title": "智谱 GLM",
        "provider_type": "openai_compatible",
        "default_base_url": "https://open.bigmodel.cn/api/paas/v4",
        "base_urls": [
            "https://open.bigmodel.cn/api/paas/v4",          # 标准
            "https://open.bigmodel.cn/api/coding/paas/v4",   # 编码套件(Coding)
        ],
        "default_model": "glm-4-flash",
    },
    "qwen": {
        "title": "通义千问",
        "provider_type": "openai_compatible",
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "base_urls": ["https://dashscope.aliyuncs.com/compatible-mode/v1"],
        "default_model": "qwen-plus",
    },
    "doubao": {
        "title": "字节豆包",
        "provider_type": "openai_compatible",
        "default_base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "base_urls": ["https://ark.cn-beijing.volces.com/api/v3"],
        # 豆包模型 id 实为 endpoint id,需用户在火山控制台创建后填入(模型下拉会拉不到,走手动输入)
        "default_model": "",
    },
    "moonshot": {
        "title": "月之暗面 Kimi",
        "provider_type": "openai_compatible",
        "default_base_url": "https://api.moonshot.cn/v1",
        "base_urls": [
            "https://api.moonshot.cn/v1",   # 国内
            "https://api.moonshot.ai/v1",   # 海外
        ],
        "default_model": "moonshot-v1-8k",
    },
    # 通用兜底:用户自填 base_url / model(无锁定列表 → 前端自由输入)
    "openai-compatible": {
        "title": "OpenAI 兼容(自定义端点)",
        "provider_type": "openai_compatible",
        "default_base_url": "",
        "base_urls": [],
        "default_model": "",
    },
    "anthropic-compatible": {
        "title": "Anthropic 兼容(自定义端点)",
        "provider_type": "anthropic_compatible",
        "default_base_url": "",
        "base_urls": [],
        "default_model": "",
    },
}
```

然后在 `infer_provider_type` 函数**之后**新增:

```python
def provider_base_urls(provider: str) -> list[str]:
    """该 provider 的固定 base_url 下拉列表。空列表 = 用户可自由输入。"""
    entry = PROVIDERS.get(provider, {})
    return list(entry.get("base_urls", []))
```

> 注意:原 `openai`/`anthropic` 的 `default_base_url` 是空串(SDK 默认)。本任务把它们**显式化**为官方端点(写进 `base_urls` 且 `default_base_url` 同步)。这会让「未配置时走 SDK 默认」变成「走显式官方端点」——对 OpenAI/Anthropic 官方而言二者等价(都是官方域名),无行为变化。若担心,可保留 `default_base_url=""`、仅新增 `base_urls`——但那样下拉首项与 default 不一致。采用显式化更一致。

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_llm_config.py -x`
Expected: PASS(含原有所有用例 + 新增 6 个)。

- [ ] **Step 5: Commit**

```bash
git add backend/app/llm/config.py backend/tests/test_llm_config.py
git commit -m "feat(llm): 给 PROVIDERS 加固定 base_urls 下拉列表 + provider_base_urls()"
```

---

### Task 2: adapter list_models + client.list_models

**Files:**
- Modify: `backend/app/llm/protocols.py`(`OpenAIAdapter` 与 `AnthropicAdapter` 各加方法)
- Modify: `backend/app/llm/client.py`(新增 `list_models`,置于 `ping_llm` 之后)
- Test: `backend/tests/test_llm_models.py`(新建)

**Interfaces:**
- Consumes: `LLMConfig`(Task 1 既有);`_get_adapter(cfg, timeout)`、`_humanize_llm_error(err)`(client.py 既有)。
- Produces: `OpenAIAdapter.list_models(self) -> list[str]`、`AnthropicAdapter.list_models(self) -> list[str]`(各自调 `self._client.models.list()` 取 `.id`);`client.list_models(cfg: LLMConfig) -> tuple[bool, list[str] | str]`(去重保序;异常走 `_humanize_llm_error`)。Task 3 的 `/models` 端点调用 `list_models`。

- [ ] **Step 1: Write the failing tests** — 新建 `backend/tests/test_llm_models.py`:

```python
"""list_models: 拉取端点可用模型列表。"""
import pytest

from app.llm.config import LLMConfig


def _cfg():
    return LLMConfig(
        provider="deepseek", provider_type="openai_compatible", api_key="sk-x",
        base_url="https://api.deepseek.com", model="deepseek-chat",
        temperature=0.3, max_tokens=None, timeout=60.0,
    )


@pytest.mark.llm
async def test_list_models_success_dedup(monkeypatch):
    import app.llm.client as client

    class _Ok:
        async def list_models(self):
            return ["deepseek-chat", "deepseek-reasoner", "deepseek-chat"]  # 含重复

    monkeypatch.setattr(client, "_get_adapter", lambda cfg, timeout: _Ok())
    ok, val = await client.list_models(_cfg())
    assert ok is True
    assert val == ["deepseek-chat", "deepseek-reasoner"]   # 去重保序


@pytest.mark.llm
async def test_list_models_auth_failure(monkeypatch):
    import app.llm.client as client

    class _Fail:
        async def list_models(self):
            raise Exception("401 Unauthorized: invalid api key")

    monkeypatch.setattr(client, "_get_adapter", lambda cfg, timeout: _Fail())
    ok, val = await client.list_models(_cfg())
    assert ok is False
    assert "API Key" in val or "401" in val


@pytest.mark.llm
async def test_list_models_timeout(monkeypatch):
    import app.llm.client as client

    class _Timeout:
        async def list_models(self):
            raise Exception("connection timeout")

    monkeypatch.setattr(client, "_get_adapter", lambda cfg, timeout: _Timeout())
    ok, val = await client.list_models(_cfg())
    assert ok is False
    assert "超时" in val or "timeout" in val.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_llm_models.py -x`
Expected: FAIL — `AttributeError: module 'app.llm.client' has no attribute 'list_models'`(及 adapter 无 `list_models`)。

- [ ] **Step 3: Implement adapter methods** — 在 `backend/app/llm/protocols.py` 的 `OpenAIAdapter.complete` 方法**之后**新增(同缩进,类方法):

```python
    async def list_models(self) -> list[str]:
        """返回该端点可用模型 id 列表(OpenAI 兼容 GET /models)。"""
        page = await self._client.models.list()
        return [m.id for m in page.data]
```

在 `AnthropicAdapter.complete` 方法**之后**新增同样方法(Anthropic SDK 同名方法,命中 `/v1/models`):

```python
    async def list_models(self) -> list[str]:
        """返回该端点可用模型 id 列表(Anthropic GET /v1/models)。"""
        page = await self._client.models.list()
        return [m.id for m in page.data]
```

- [ ] **Step 4: Implement client.list_models** — 在 `backend/app/llm/client.py` 的 `ping_llm` 函数**之后**新增:

```python
async def list_models(cfg: LLMConfig) -> tuple[bool, list[str] | str]:
    """拉取该端点可用模型列表。

    用传入的 cfg(而非 get_config()),这样能拉「未保存的草稿值」。
    返回 (True, [model_id...]) 或 (False, 中文原因)。绝不抛错。
    """
    adapter = _get_adapter(cfg, min(cfg.timeout, 20.0))
    try:
        ids = await adapter.list_models()
    except Exception as e:
        return False, _humanize_llm_error(e)
    # 去重保序
    seen: set[str] = set()
    dedup: list[str] = []
    for mid in ids:
        if mid and mid not in seen:
            seen.add(mid)
            dedup.append(mid)
    return True, dedup
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_llm_models.py -x`
Expected: PASS(3 个)。

- [ ] **Step 6: Commit**

```bash
git add backend/app/llm/protocols.py backend/app/llm/client.py backend/tests/test_llm_models.py
git commit -m "feat(llm): 新增 adapter.list_models + client.list_models(去重保序+错误归一)"
```

---

### Task 3: /models 端点 + _public_providers 扩字段

**Files:**
- Modify: `backend/app/routers/llm_config.py`(import、`_public_providers`、新端点)
- Test: `backend/tests/test_llm_config_api.py`(追加测试)

**Interfaces:**
- Consumes: `list_models`(Task 2)、`_resolve_config`/`infer_provider_type`/`_assert_public_https_base_url`/`LLMConfig`(既有)、`PROVIDERS["base_urls"]`(Task 1)。
- Produces: `POST /api/admin/llm-config/models` 入参 `LLMConfigUpdate`、出参 `{ok, models?}` 或 `{ok:false, detail}`;`GET /api/admin/llm-config` 的 `providers[*]` 新增 `base_urls: list[str]` 与 `base_url_editable: bool`。前端 Task 4 消费。

- [ ] **Step 1: Write the failing tests** — 追加到 `backend/tests/test_llm_config_api.py` 末尾:

```python
@pytest.mark.api
async def test_models_endpoint_ok(cfg_env, monkeypatch):
    import app.routers.llm_config as router
    async def _ok(cfg):
        return True, ["deepseek-chat", "deepseek-reasoner"]
    monkeypatch.setattr(router, "list_models", _ok)
    resp = _client().post("/api/admin/llm-config/models", json={
        "api_key": "sk-x", "base_url": "https://api.deepseek.com", "provider": "deepseek",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["models"] == ["deepseek-chat", "deepseek-reasoner"]


@pytest.mark.api
async def test_models_endpoint_failure_detail(cfg_env, monkeypatch):
    import app.routers.llm_config as router
    async def _fail(cfg):
        return False, "API Key 无效或未授权(401)"
    monkeypatch.setattr(router, "list_models", _fail)
    resp = _client().post("/api/admin/llm-config/models", json={
        "api_key": "sk-x", "base_url": "https://api.deepseek.com", "provider": "deepseek",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "API Key" in body["detail"]


@pytest.mark.api
async def test_models_endpoint_ssrf_blocked(cfg_env, monkeypatch):
    resp = _client().post("/api/admin/llm-config/models", json={
        "api_key": "sk-x", "base_url": "http://127.0.0.1:8080", "provider": "deepseek",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "base_url" in body["detail"]


@pytest.mark.api
async def test_models_endpoint_no_key(cfg_env, monkeypatch):
    resp = _client().post("/api/admin/llm-config/models", json={"provider": "deepseek"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is False


@pytest.mark.api
async def test_get_returns_base_urls_and_editable(cfg_env, monkeypatch):
    from app.llm.runtime_config import write_runtime_override
    await write_runtime_override({"provider": "glm", "api_key": "sk-glm"})
    body = _client().get("/api/admin/llm-config").json()
    glm = body["providers"]["glm"]
    assert "https://open.bigmodel.cn/api/coding/paas/v4" in glm["base_urls"]
    assert glm["base_url_editable"] is False
    assert body["providers"]["openai-compatible"]["base_url_editable"] is True
    assert body["providers"]["openai-compatible"]["base_urls"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_llm_config_api.py -k "models_endpoint or base_urls" -x`
Expected: FAIL — `/models` 路由 404;`base_urls`/`base_url_editable` KeyError。

- [ ] **Step 3: Implement** — 修改 `backend/app/routers/llm_config.py`:

(a) 顶部 import 的 `from ..llm.client import ping_llm` 改为:

```python
from ..llm.client import ping_llm, list_models
```

(b) import 行补 `provider_base_urls`(Step a 的 import 块下方单独一行即可,或并入现有 config import):

```python
from ..llm.config import (
    PROVIDERS, _resolve_config, _assert_public_https_base_url, infer_provider_type,
    provider_base_urls,
)
```

(c) `_public_providers()` 替换为(加 `base_urls` + `base_url_editable`,复用 Task 1 的 helper):

```python
def _public_providers() -> dict:
    """给下拉用的预设(全是展示字段,无敏感信息)。"""
    return {
        name: {
            "title": p["title"],
            "provider_type": p["provider_type"],
            "default_base_url": p["default_base_url"],
            "base_urls": provider_base_urls(name),
            "base_url_editable": not provider_base_urls(name),
            "default_model": p["default_model"],
        }
        for name, p in PROVIDERS.items()
    }
```

(d) 在 `test_llm_config` 路由**之后**新增端点(与 `/test` 同构):

```python
@router.post("/api/admin/llm-config/models")
async def list_llm_models(req: LLMConfigUpdate) -> dict:
    """据草稿值(provider/key/base_url)拉取该端点可用模型列表。不落库、不打日志 key。"""
    from ..llm.config import LLMConfig

    base = _resolve_config(require_key=False)
    provider = req.provider or base.provider
    provider_type = req.provider_type or infer_provider_type(provider)

    if req.provider_type and req.provider_type not in (
        "openai_compatible", "anthropic_compatible"
    ):
        return {"ok": False, "detail": "provider_type 非法"}

    api_key = req.api_key or base.api_key
    base_url = req.base_url if req.base_url is not None else base.base_url

    if not api_key:
        return {"ok": False, "detail": "未填写 API Key"}
    if base_url:
        try:
            _assert_public_https_base_url(base_url)
        except ValueError as e:
            return {"ok": False, "detail": str(e)}

    cfg = LLMConfig(
        provider=provider, provider_type=provider_type, api_key=api_key,
        base_url=base_url, model=req.model or base.model,
        temperature=base.temperature, max_tokens=base.max_tokens, timeout=base.timeout,
    )
    ok, val = await list_models(cfg)
    if ok:
        return {"ok": True, "models": val}
    return {"ok": False, "detail": val}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_llm_config_api.py -x`
Expected: PASS(含原有 + 新增 5 个)。

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/llm_config.py backend/tests/test_llm_config_api.py
git commit -m "feat(api): 新增 POST /api/admin/llm-config/models + provider base_urls/editable"
```

---

### Task 4: 前端 api.js + SettingsView.vue + spec

**Files:**
- Modify: `frontend/src/api.js`(加 `listLlmModels`)
- Modify: `frontend/src/views/SettingsView.vue`(模板 + script + 样式)
- Modify: `frontend/tests/views/SettingsView.spec.js`(扩展测试)

**Interfaces:**
- Consumes: `getLlmConfig`(返回体现含 `providers[*].base_urls`/`base_url_editable`)、新 `POST /api/admin/llm-config/models`。
- Produces: `listLlmModels(cfg)` → `{ok, models?, detail?}`;UI:base_url 锁定 `<select>`(compatible 退化为 `<input>`)+ model 自动拉取 `<select>`(失败切 `<input>`)。

- [ ] **Step 1: Write the failing tests** — 重写 `frontend/tests/views/SettingsView.spec.js` 为(加入 `listLlmModels` mock、共享 `wrapper` + `afterEach` 卸载、base_url 下拉、自动拉取、手动按钮、失败兜底):

```javascript
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import SettingsView from '@/views/SettingsView.vue'

const mockGetLlmConfig = vi.fn()
const mockSaveLlmConfig = vi.fn()
const mockTestLlmConfig = vi.fn()
const mockListLlmModels = vi.fn()

vi.mock('@/api', () => ({
  getLlmConfig: () => mockGetLlmConfig(),
  saveLlmConfig: (cfg) => mockSaveLlmConfig(cfg),
  testLlmConfig: (cfg) => mockTestLlmConfig(cfg),
  listLlmModels: (cfg) => mockListLlmModels(cfg),
}))

function deepseekProviders(overrides = {}) {
  return {
    deepseek: Object.assign({
      title: 'DeepSeek', provider_type: 'openai_compatible',
      default_base_url: 'https://api.deepseek.com',
      base_urls: ['https://api.deepseek.com'],
      base_url_editable: false, default_model: 'deepseek-chat',
    }, overrides),
  }
}

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/settings', name: 'settings', component: SettingsView },
      { path: '/', name: 'library', component: { template: '<div/>' } },
    ],
  })
}

describe('SettingsView', () => {
  let wrapper

  beforeEach(() => {
    mockGetLlmConfig.mockReset()
    mockSaveLlmConfig.mockReset()
    mockTestLlmConfig.mockReset()
    mockListLlmModels.mockReset()
    // 默认无害返回,避免任何意外拉取污染断言
    mockListLlmModels.mockResolvedValue({ ok: false, detail: '' })
  })
  afterEach(() => { wrapper?.unmount(); wrapper = undefined })

  async function mountView(getCfg) {
    mockGetLlmConfig.mockResolvedValue(getCfg)
    const router = makeRouter()
    router.push('/settings'); await router.isReady()
    wrapper = mount(SettingsView, { global: { plugins: [router] } })
    await flushPromises()
    await flushPromises()
    return wrapper
  }

  it('masks the saved key and locks base_url to a select for deepseek', async () => {
    const w = await mountView({
      provider: 'deepseek', provider_type: 'openai_compatible',
      base_url: 'https://api.deepseek.com', model: 'deepseek-chat',
      has_api_key: true, api_key_masked: '****1234', providers: deepseekProviders(),
    })
    expect(w.find('[data-test="key-status"]').text()).toContain('****1234')
    const base = w.find('[data-test="base-url"]')
    expect(base.element.tagName).toBe('SELECT')
    expect(base.element.value).toBe('https://api.deepseek.com')
    expect(base.findAll('option').length).toBe(1)
  })

  it('save posts only changed fields (no api_key when untouched)', async () => {
    const w = await mountView({
      provider: 'deepseek', provider_type: 'openai_compatible',
      base_url: 'https://api.deepseek.com', model: 'deepseek-chat',
      has_api_key: true, api_key_masked: '****1234', providers: deepseekProviders(),
    })
    mockSaveLlmConfig.mockResolvedValue({ ok: true })
    await w.find('[data-test="save"]').trigger('click')
    await flushPromises()
    expect(mockSaveLlmConfig).toHaveBeenCalledTimes(1)
    const sent = mockSaveLlmConfig.mock.calls[0][0]
    expect(sent.api_key).toBeUndefined()
    expect(sent.provider).toBe('deepseek')
  })

  it('test calls testLlmConfig and shows the result', async () => {
    const w = await mountView({
      provider: 'deepseek', provider_type: 'openai_compatible',
      base_url: 'https://api.deepseek.com', model: 'deepseek-chat',
      has_api_key: false, api_key_masked: '', providers: deepseekProviders(),
    })
    mockTestLlmConfig.mockResolvedValue({ ok: true, detail: '连通(模型 deepseek-chat)' })
    await w.find('[data-test="api-key"]').setValue('sk-test-1234')
    await w.find('[data-test="test"]').trigger('click')
    await flushPromises()
    expect(mockTestLlmConfig).toHaveBeenCalledTimes(1)
    expect(w.find('[data-test="test-result"]').text()).toContain('连通')
  })

  it('renders glm coding endpoint as a second base_url option', async () => {
    const w = await mountView({
      provider: 'glm', provider_type: 'openai_compatible',
      base_url: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-4-flash',
      has_api_key: false, api_key_masked: '',
      providers: { glm: {
        title: '智谱 GLM', provider_type: 'openai_compatible',
        default_base_url: 'https://open.bigmodel.cn/api/paas/v4',
        base_urls: ['https://open.bigmodel.cn/api/paas/v4', 'https://open.bigmodel.cn/api/coding/paas/v4'],
        base_url_editable: false, default_model: 'glm-4-flash',
      } },
    })
    const base = w.find('[data-test="base-url"]')
    expect(base.element.tagName).toBe('SELECT')
    expect(base.findAll('option').length).toBe(2)
  })

  it('renders free-text input for compatible providers', async () => {
    const w = await mountView({
      provider: 'openai-compatible', provider_type: 'openai_compatible',
      base_url: 'https://my-proxy.local/v1', model: 'gpt-4o',
      has_api_key: true, api_key_masked: '****9999',
      providers: { 'openai-compatible': {
        title: 'OpenAI 兼容(自定义端点)', provider_type: 'openai_compatible',
        default_base_url: '', base_urls: [], base_url_editable: true, default_model: '',
      } },
    })
    const base = w.find('[data-test="base-url"]')
    expect(base.element.tagName).toBe('INPUT')
    expect(base.element.value).toBe('https://my-proxy.local/v1')
  })

  it('auto-fetches models on load when provider+key+base_url ready', async () => {
    mockListLlmModels.mockResolvedValue({ ok: true, models: ['deepseek-chat', 'deepseek-reasoner'] })
    const w = await mountView({
      provider: 'deepseek', provider_type: 'openai_compatible',
      base_url: 'https://api.deepseek.com', model: 'deepseek-chat',
      has_api_key: true, api_key_masked: '****1234', providers: deepseekProviders(),
    })
    expect(mockListLlmModels).toHaveBeenCalledTimes(1)
    const model = w.find('[data-test="model"]')
    expect(model.element.tagName).toBe('SELECT')
    expect(model.findAll('option').length).toBe(2)
  })

  it('manual fetch button populates the model select', async () => {
    mockListLlmModels.mockResolvedValue({ ok: true, models: ['deepseek-chat', 'deepseek-reasoner'] })
    const w = await mountView({
      provider: 'deepseek', provider_type: 'openai_compatible',
      base_url: 'https://api.deepseek.com', model: 'deepseek-chat',
      has_api_key: false, api_key_masked: '', providers: deepseekProviders(),
    })
    // 初始 hasKey=false → 不自动拉取;手动填 key 后点「↻ 拉取」
    mockListLlmModels.mockClear()
    await w.find('[data-test="api-key"]').setValue('sk-test-1234')
    await w.find('[data-test="fetch-models"]').trigger('click')
    await flushPromises(); await flushPromises()
    expect(mockListLlmModels).toHaveBeenCalledTimes(1)
    const model = w.find('[data-test="model"]')
    expect(model.element.tagName).toBe('SELECT')
    expect(model.findAll('option').length).toBe(2)
  })

  it('falls back to manual input when fetch fails', async () => {
    mockListLlmModels.mockResolvedValue({ ok: false, detail: 'API Key 无效或未授权(401)' })
    const w = await mountView({
      provider: 'deepseek', provider_type: 'openai_compatible',
      base_url: 'https://api.deepseek.com', model: '',
      has_api_key: true, api_key_masked: '****1234', providers: deepseekProviders(),
    })
    await w.find('[data-test="fetch-models"]').trigger('click')
    await flushPromises(); await flushPromises()
    expect(w.find('[data-test="fetch-status"]').text()).toContain('API Key')
    expect(w.find('[data-test="model"]').element.tagName).toBe('INPUT')
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run tests/views/SettingsView.spec.js`
Expected: FAIL — `listLlmModels` 未导出 / `base-url` 仍是 INPUT(锁定 case) / 无 `[data-test="fetch-models"]` 等。

- [ ] **Step 3: Implement api.js** — 在 `frontend/src/api.js` 的 `testLlmConfig` 之后新增:

```javascript
/**
 * 拉取端点可用模型列表(服务端调用,key 不出浏览器)。
 * @param {Object} cfg - { provider?, provider_type?, api_key?, base_url? }
 * @returns {Promise<{ok:boolean, models?:string[], detail?:string}>}
 */
export async function listLlmModels(cfg) {
  const res = await fetchWithTimeout(`${API_BASE}/admin/llm-config/models`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(cfg),
  }, 20000)
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || '拉取模型列表失败')
  }
  return await res.json()
}
```

- [ ] **Step 4: Implement SettingsView.vue template** — 把 base_url 与 model 两个 `.field` 块替换为:

```html
      <div class="field">
        <label for="base-url">API 链接（base_url）</label>
        <select v-if="!baseUrlEditable" id="base-url" data-test="base-url" v-model="form.base_url">
          <option v-for="u in baseUrlOptions" :key="u" :value="u">{{ u }}</option>
        </select>
        <input v-else id="base-url" data-test="base-url" v-model="form.base_url"
               placeholder="https://your-endpoint/v1" />
      </div>

      <div class="field">
        <label for="model">模型</label>
        <div class="model-row">
          <select v-if="!manualModel && modelOptions.length" id="model" data-test="model"
                  v-model="form.model" :disabled="fetchingModels">
            <option v-for="m in modelOptions" :key="m" :value="m">{{ m }}</option>
          </select>
          <input v-else id="model" data-test="model" v-model="form.model"
                 :placeholder="fetchModelsError ? '手动输入模型名…' : '如 deepseek-chat'" />
          <button type="button" class="fetch-btn" data-test="fetch-models"
                  @click="fetchModels" :disabled="!canFetchModels || fetchingModels"
                  :title="canFetchModels ? '拉取模型列表' : '先填好 provider / key / base_url'">
            {{ fetchingModels ? '…' : '↻ 拉取' }}
          </button>
        </div>
        <p v-if="fetchingModels" data-test="fetch-status" class="hint">拉取模型中…</p>
        <p v-else-if="fetchModelsError" data-test="fetch-status" class="hint">{{ fetchModelsError }}</p>
      </div>
```

- [ ] **Step 5: Implement SettingsView.vue script** — 替换 `<script setup>` 整块为:

```javascript
<script setup>
import { reactive, ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { getLlmConfig, saveLlmConfig, testLlmConfig, listLlmModels } from '@/api'

const router = useRouter()

const loaded = ref(false)
const loadError = ref('')
const providers = ref({})
const hasKey = ref(false)
const maskedKey = ref('')

const form = reactive({ provider: 'deepseek', api_key: '', base_url: '', model: '' })
const showKey = ref(false)

// base_url 锁定下拉状态
const baseUrlOptions = ref([])
const baseUrlEditable = ref(false)
// 模型自动拉取状态
const modelOptions = ref([])
const fetchingModels = ref(false)
const fetchModelsError = ref('')
const manualModel = ref(false)

const testing = ref(false)
const testResult = ref(null)
const saving = ref(false)
const saveMsg = ref('')
const saveError = ref('')

let fetchTimer = null
onUnmounted(() => { if (fetchTimer) clearTimeout(fetchTimer) })

const canFetchModels = computed(() =>
  !!form.provider && !!form.base_url && (!!form.api_key.trim() || hasKey.value)
)

function goBack() {
  if (window.history.length > 1) router.back()
  else router.push('/')
}

function applyProviderBaseUrls() {
  const p = providers.value[form.provider] || {}
  baseUrlOptions.value = p.base_urls || []
  // 缺 base_url_editable 字段时:无锁定列表即视为可自由输入
  baseUrlEditable.value = p.base_url_editable ?? baseUrlOptions.value.length === 0
  if (baseUrlEditable.value) {
    if (!form.base_url) form.base_url = p.default_base_url || ''
  } else if (!baseUrlOptions.value.includes(form.base_url)) {
    form.base_url = baseUrlOptions.value[0] || ''
  }
}

function onProviderChange() {
  const p = providers.value[form.provider] || {}
  applyProviderBaseUrls()
  if (!form.model) form.model = p.default_model || ''
  modelOptions.value = []
  fetchModelsError.value = ''
  manualModel.value = false
  if (canFetchModels.value) fetchModels()
}

function onKeyInput() {
  // 输入 key 时防抖拉取(对应「填前三项后自动拉取」)
  if (fetchTimer) clearTimeout(fetchTimer)
  fetchTimer = setTimeout(() => { fetchModels() }, 400)
}

async function load() {
  try {
    const cfg = await getLlmConfig()
    providers.value = cfg.providers || {}
    form.provider = cfg.provider || 'deepseek'
    form.base_url = cfg.base_url || ''
    form.model = cfg.model || ''
    hasKey.value = !!cfg.has_api_key
    maskedKey.value = cfg.api_key_masked || ''
    form.api_key = ''  // 永不预填真实 key;留空 = 不改
    applyProviderBaseUrls()
    loaded.value = true
    if (canFetchModels.value) fetchModels()  // 进入页若三项齐全,自动拉一次
  } catch (e) {
    loadError.value = e.message || '加载配置失败'
    loaded.value = true
  }
}

/** 构造提交体(保存/测试用):只含非空字段;api_key 留空不发。 */
function buildPayload({ includeKeyIfAny }) {
  const body = {}
  if (form.provider) body.provider = form.provider
  if (form.base_url) body.base_url = form.base_url
  if (form.model) body.model = form.model
  if (includeKeyIfAny && form.api_key.trim()) body.api_key = form.api_key.trim()
  return body
}

/** 构造模型拉取请求体:带 provider_type 让后端选对 adapter;空 key 不发(后端用已保存值)。 */
function buildModelsPayload() {
  const body = { provider: form.provider, base_url: form.base_url }
  if (form.api_key.trim()) body.api_key = form.api_key.trim()
  const p = providers.value[form.provider]
  if (p && p.provider_type) body.provider_type = p.provider_type
  return body
}

async function fetchModels() {
  if (!canFetchModels.value) return
  fetchingModels.value = true
  fetchModelsError.value = ''
  try {
    const res = await listLlmModels(buildModelsPayload())
    if (res.ok && Array.isArray(res.models) && res.models.length) {
      modelOptions.value = res.models
      manualModel.value = false
      if (!modelOptions.value.includes(form.model)) form.model = modelOptions.value[0]
    } else {
      modelOptions.value = []
      fetchModelsError.value = (res && res.detail) || '该端点未返回模型列表,可手动输入'
      manualModel.value = true
    }
  } catch (e) {
    modelOptions.value = []
    fetchModelsError.value = e.message || '拉取失败,可手动输入'
    manualModel.value = true
  } finally {
    fetchingModels.value = false
  }
}

async function onTest() {
  testing.value = true
  testResult.value = null
  try {
    testResult.value = await testLlmConfig(buildPayload({ includeKeyIfAny: true }))
  } catch (e) {
    testResult.value = { ok: false, detail: e.message || '测试失败' }
  } finally {
    testing.value = false
  }
}

async function onSave() {
  saving.value = true
  saveMsg.value = ''
  saveError.value = ''
  try {
    await saveLlmConfig(buildPayload({ includeKeyIfAny: true }))
    saveMsg.value = '已保存。下一次处理播客即生效(API 与 Worker 均立即生效)。'
    hasKey.value = hasKey.value || !!form.api_key.trim()
    form.api_key = ''
    showKey.value = false
    await load()
  } catch (e) {
    saveError.value = e.message || '保存失败'
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>
```

> 模板里 api-key 的 `<input>` 需加 `@input="onKeyInput"`(见 Step 6)。

- [ ] **Step 6: Wire api-key input** — 在 api-key 的 `<input>` 标签上增加 `@input="onKeyInput"`(与现有 `v-model` 并存):

```html
        <input
          id="api-key" data-test="api-key"
          v-model="form.api_key" :type="showKey ? 'text' : 'password'"
          @input="onKeyInput"
          :placeholder="hasKey ? '已保存(如需更换请在此输入新 key)' : '粘贴你的 API Key...'"
          autocomplete="off"
        />
```

- [ ] **Step 7: Add styles** — 在 `<style scoped>` 末尾(`.error-message` 之后)新增:

```css
.model-row {
  display: flex;
  gap: 8px;
  align-items: stretch;
}
.model-row select, .model-row input {
  flex: 1;
}
.fetch-btn {
  padding: 0 14px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  background: #fff;
  color: #374151;
  white-space: nowrap;
}
.fetch-btn:hover:not(:disabled) { border-color: #4f8ef7; color: #4f8ef7; }
.fetch-btn:disabled { opacity: 0.5; cursor: not-allowed; }
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd frontend && npx vitest run tests/views/SettingsView.spec.js`
Expected: PASS(8 个用例)。

- [ ] **Step 9: Commit**

```bash
git add frontend/src/api.js frontend/src/views/SettingsView.vue frontend/tests/views/SettingsView.spec.js
git commit -m "feat(ui): base_url 按 provider 锁定下拉 + 模型自动拉取/手动兜底"
```

---

### Task 5: 手动验证(无代码)

**Files:** 无(仅人工核对)

- [ ] **Step 1: 全量跑测试**

Run: `cd backend && python -m pytest tests/test_llm_config.py tests/test_llm_models.py tests/test_llm_config_api.py -q` → 全绿。
Run: `cd frontend && npx vitest run` → 全绿。

- [ ] **Step 2: 启动 / 刷新前端,过 `/settings` 实操**(不要重启正在跑的 launchd 服务;前端若已由 com.podcast-digester.frontend 托管,`cd frontend && npm run build` 后由其静态服务提供,或本地 `npm run dev` 临时验证)

核对清单:
- [ ] 切到 deepseek → base_url 是只读下拉(仅 1 项 `https://api.deepseek.com`)。
- [ ] 切到 智谱 GLM → base_url 下拉有「标准 / 编码套件(coding)」两项;切到 coding 端点能保存。
- [ ] 切到 月之暗面 → base_url 有「国内 / 海外」两项。
- [ ] 切到 OpenAI 兼容(自定义) → base_url 变自由输入框。
- [ ] 填好 provider + base_url + 真实 key 后,模型下拉自动拉取并填入;选中模型 → 「测试连接」通过 → 「保存」。
- [ ] 切到 豆包 → 模型拉取预期拉不到 → 自动切「手动输入」(endpoint id 手填),不被卡住。
- [ ] 保存后用该 provider/key 实际处理一集播客,确认走的是新配置(API 与 Worker 都生效)。

- [ ] **Step 3: 汇报**(不自动合并/推送) — 把改动清单、测试结果、手测结论交给用户,等待「合并 main / 推送 / 重启服务」指示。
