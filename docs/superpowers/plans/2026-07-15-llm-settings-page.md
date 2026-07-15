# LLM API 设置页 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a frontend `/settings` page where the user fills in provider / API key / base_url / model, saves it, and the change takes effect immediately for both the API and Worker processes — plus a "test connection" button.

**Architecture:** A runtime config override layer. A new `app_setting` table stores one JSON row (`key='llm_config'`). `get_config()` reads it on every call (sync `sqlite3`, sub-ms, cross-process-safe under WAL) and overlays it on the env-derived config; `.env` remains the boot fallback. Three admin endpoints (`GET`/`PUT`/`POST test`) under `verify_admin` read/write/test it. The frontend mirrors the existing `fetchWithTimeout` + scoped-CSS patterns.

**Tech Stack:** Python 3.11–3.13, FastAPI, aiosqlite + sqlite3 (stdlib), pydantic, pytest; Vue 3 + Vite (plain JS), vue-router, Vitest + @vue/test-utils.

## Global Constraints

- Python 3.11–3.13 only (3.14 unsupported — faster-whisper/pydantic wheels). Do not touch `requirements.txt` (no new deps: `sqlite3` is stdlib).
- Backend tests: `pytest`, `asyncio_mode = auto`, markers `unit/integration/api/database/llm`. The autouse conftest fixture bypasses `verify_admin` and rate-limit; override `verify_admin` only if a test specifically tests auth.
- `temp_db` fixture swaps `app.database.DB_PATH` to a temp file and runs `init_db()`. Any code reading the DB at runtime must read the **live** `app.database.DB_PATH` attribute (not an import-time copy) so the swap is honored.
- API key is a secret: never return it in full from any endpoint; mask it (`****` + last 4). `base_url` must pass the existing SSRF guard `_assert_public_https_base_url`.
- Frontend: plain JS (no TS), scoped CSS, primary `#4f8ef7`, no dark mode. All API calls via `fetchWithTimeout` in `src/api.js`, which auto-injects `X-Admin-Token`. Chinese user-facing copy.
- Commits: conventional (`feat:`/`test:`/`refactor:`), no `Co-Authored-By` attribution. Commit per task.

---

## File Structure

**Backend (create/modify):**
- Modify `backend/app/database.py` — add `app_setting` table to `init_db()`.
- Create `backend/app/llm/runtime_config.py` — `read_runtime_override()` (sync) + `write_runtime_override()` (async) over `app_setting`.
- Modify `backend/app/llm/config.py` — split `get_config()` into `_resolve_config(require_key)`, apply override.
- Modify `backend/app/llm/client.py` — add `ping_llm(cfg)`.
- Create `backend/app/routers/llm_config.py` — `GET`/`PUT`/`POST test` endpoints.
- Modify `backend/app/main.py` — mount the new router.
- Modify `backend/tests/test_llm_config.py` — extend with override tests + neutralize DB in `clean_llm_env`.
- Create `backend/tests/test_llm_config_api.py` — endpoint tests.
- Create `backend/tests/test_llm_ping.py` — `ping_llm` unit test.

**Frontend (create/modify):**
- Modify `frontend/src/api.js` — `getLlmConfig` / `saveLlmConfig` / `testLlmConfig`.
- Modify `frontend/src/router.js` — `/settings` route.
- Create `frontend/src/views/SettingsView.vue` — the settings page.
- Modify `frontend/src/views/LibraryView.vue` — gear-icon entry in the header.
- Create `frontend/tests/views/SettingsView.spec.js` — Vitest.

---

### Task 1: Add `app_setting` table

**Files:**
- Modify: `backend/app/database.py` (inside `init_db()`'s `executescript`, after the last `CREATE TABLE`)
- Test: `backend/tests/test_database.py` (append one test)

**Interfaces:**
- Produces: table `app_setting(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL)`, created idempotently by `init_db()`.

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_database.py`:

```python
@pytest.mark.database
async def test_init_db_creates_app_setting_table(temp_db):
    """init_db 必须建出 app_setting 表（运行时配置覆写用）。"""
    import aiosqlite
    from app import database as _db
    async with aiosqlite.connect(str(_db.DB_PATH)) as db:
        cur = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='app_setting'"
        )
        row = await cur.fetchone()
    assert row is not None
    assert row[0] == "app_setting"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && source venv/bin/activate && pytest tests/test_database.py::test_init_db_creates_app_setting_table -v`
Expected: FAIL — table does not exist.

- [ ] **Step 3: Add the table to `init_db()`**

In `backend/app/database.py`, inside the `init_db()` `executescript("""...""")` string, after the last existing `CREATE TABLE IF NOT EXISTS ...` block (before the closing `"""`), add:

```sql

        -- 运行时配置覆写（前端「LLM 设置页」写入；get_config() 读取）
        CREATE TABLE IF NOT EXISTS app_setting (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && source venv/bin/activate && pytest tests/test_database.py::test_init_db_creates_app_setting_table -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git -C /Users/alli/podcast-digester add backend/app/database.py backend/tests/test_database.py
git -C /Users/alli/podcast-digester commit -m "feat(db): add app_setting table for runtime config override"
```

---

### Task 2: `runtime_config.py` read/write helpers

**Files:**
- Create: `backend/app/llm/runtime_config.py`
- Create: `backend/tests/test_runtime_config.py`

**Interfaces:**
- Consumes: live `app.database.DB_PATH` (read inside the function so `temp_db` swap is honored).
- Produces:
  - `read_runtime_override() -> dict` (sync) — reads `app_setting` row `key='llm_config'`; returns `{}` if db/table/row missing or any error (never raises).
  - `write_runtime_override(override: dict) -> None` (async) — upserts the row.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_runtime_config.py`:

```python
"""runtime_config: 运行时 LLM 配置覆写的读写。"""
import json

import pytest

from app.llm.runtime_config import (
    OVERRIDE_KEY,
    read_runtime_override,
    write_runtime_override,
)


@pytest.mark.database
async def test_write_then_read_roundtrip(temp_db):
    await write_runtime_override({"provider": "glm", "api_key": "sk-x", "model": "glm-4-flash"})
    got = read_runtime_override()
    assert got["provider"] == "glm"
    assert got["api_key"] == "sk-x"
    assert got["model"] == "glm-4-flash"


@pytest.mark.database
async def test_write_upserts_existing_row(temp_db):
    await write_runtime_override({"provider": "deepseek"})
    await write_runtime_override({"provider": "openai", "model": "gpt-4o-mini"})
    got = read_runtime_override()
    assert got == {"provider": "openai", "model": "gpt-4o-mini"}


@pytest.mark.unit
def test_read_returns_empty_when_db_missing(monkeypatch):
    # 指向一个不存在的路径：不得建文件、不得抛错
    from app import database as _db
    monkeypatch.setattr(_db, "DB_PATH", __import__("pathlib").Path("/tmp/pd-nonexistent-rt.db"))
    assert read_runtime_override() == {}


@pytest.mark.unit
def test_read_returns_empty_when_no_row(temp_db):
    # 表已建但无记录
    assert read_runtime_override() == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source venv/bin/activate && pytest tests/test_runtime_config.py -v`
Expected: FAIL — module `app.llm.runtime_config` does not exist.

- [ ] **Step 3: Implement `runtime_config.py`**

Create `backend/app/llm/runtime_config.py`:

```python
"""运行时 LLM 配置覆写：读写 app_setting.llm_config。

get_config() 每次同步读这里的 read_runtime_override()，使前端设置页
保存后对 API 与 Worker 两进程都即时生效（SQLite WAL 下跨进程读后写安全）。
"""
import json
import sqlite3
from datetime import datetime, timezone

OVERRIDE_KEY = "llm_config"


def _db_path():
    """取「当前生效」的 DB 路径。

    故意每次进函数读 app.database.DB_PATH 属性（而非 import 时拷贝），
    这样 conftest 的 temp_db fixture 替换该属性时能被正确感知。
    """
    from app import database  # 局部 import，避免与 config 的加载顺序耦合
    return database.DB_PATH


def read_runtime_override() -> dict:
    """同步读取运行时覆写。DB/表/记录缺失或任何异常都返回 {}，绝不抛错。"""
    try:
        path = _db_path()
        if not path.exists():
            return {}
        with sqlite3.connect(str(path)) as conn:
            row = conn.execute(
                "SELECT value FROM app_setting WHERE key=?", (OVERRIDE_KEY,)
            ).fetchone()
        return json.loads(row[0]) if row else {}
    except sqlite3.OperationalError:
        # 表尚未建（init_db 未跑过）
        return {}
    except Exception:
        # 任何意外都回退到「无覆写」，绝不阻塞 get_config()
        return {}


async def write_runtime_override(override: dict) -> None:
    """异步写入覆写（upsert）。供 PUT /api/admin/llm-config 使用。"""
    import aiosqlite

    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(str(_db_path())) as db:
        await db.execute(
            "INSERT INTO app_setting(key, value, updated_at) VALUES(?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (OVERRIDE_KEY, json.dumps(override, ensure_ascii=False), now),
        )
        await db.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && source venv/bin/activate && pytest tests/test_runtime_config.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git -C /Users/alli/podcast-digester add backend/app/llm/runtime_config.py backend/tests/test_runtime_config.py
git -C /Users/alli/podcast-digester commit -m "feat(llm): add runtime config override read/write helpers"
```

---

### Task 3: Apply override in `get_config()`

**Files:**
- Modify: `backend/app/llm/config.py`
- Modify: `backend/tests/test_llm_config.py`

**Interfaces:**
- Consumes: `read_runtime_override()` from Task 2.
- Produces:
  - `get_config() -> LLMConfig` (unchanged signature; now overlays DB override).
  - `_resolve_config(require_key: bool = True) -> LLMConfig` — the refactored resolver; `require_key=False` is used by the GET endpoint so the page loads even before any key is set.

**Critical:** existing env-only tests must stay hermetic. The real dev DB may later hold a saved override, which would pollute `get_config()` in unit tests. So `clean_llm_env` must also neutralize `app.database.DB_PATH`.

- [ ] **Step 1: Neutralize DB in `clean_llm_env` + add override tests**

In `backend/tests/test_llm_config.py`:

(a) Replace the `clean_llm_env` fixture body with (adds DB neutralization):

```python
@pytest.fixture
def clean_llm_env(monkeypatch):
    """清空所有 LLM/DEEPSEEK 环境变量，并把运行时覆写 DB 指向不存在的路径，
    使 get_config() 在单测里只受 env 影响（不被真实库里的覆写污染）。"""
    from pathlib import Path
    for k in list(__import__("os").environ):
        if k.startswith(("LLM_", "DEEPSEEK_")):
            monkeypatch.delenv(k, raising=False)
    from app import database as _db
    monkeypatch.setattr(_db, "DB_PATH", Path("/tmp/pd-nonexistent-clellm.db"))
    return monkeypatch
```

(b) Add a dedicated async fixture + override tests at the end of the file:

```python
@pytest.fixture
async def override_env(temp_db, monkeypatch):
    """temp_db（带 app_setting 表的真实临时库）+ 清空 env，供覆写测试用。"""
    for k in list(__import__("os").environ):
        if k.startswith(("LLM_", "DEEPSEEK_")):
            monkeypatch.delenv(k, raising=False)
    return monkeypatch


@pytest.mark.database
async def test_override_in_db_takes_effect(override_env, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-env")
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    from app.llm.runtime_config import write_runtime_override
    await write_runtime_override({"provider": "openai", "api_key": "sk-db"})
    cfg = get_config()
    assert cfg.provider == "openai"
    assert cfg.api_key == "sk-db"


@pytest.mark.database
async def test_override_partial_fields_keep_env_defaults(override_env, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-env")
    monkeypatch.setenv("LLM_MODEL", "deepseek-chat")
    from app.llm.runtime_config import write_runtime_override
    await write_runtime_override({"base_url": "https://api.openai.com"})
    cfg = get_config()
    # 未被覆写的字段仍来自 env
    assert cfg.api_key == "sk-env"
    assert cfg.model == "deepseek-chat"
    assert cfg.base_url == "https://api.openai.com"


@pytest.mark.unit
def test_resolve_config_no_require_key_does_not_raise(clean_llm_env):
    # 无 key 也不抛，供 GET 端点加载页面用
    cfg = _resolve_config(require_key=False)
    assert cfg.api_key == ""
```

(c) Add `_resolve_config` to the top import:

```python
from app.llm.config import (
    PROVIDERS, get_config, infer_provider_type, LLMConfig, _resolve_config,
)
```

- [ ] **Step 2: Run the new + existing tests to verify failures**

Run: `cd backend && source venv/bin/activate && pytest tests/test_llm_config.py -v`
Expected: FAIL — `_resolve_config` not defined / override tests fail (override ignored).

- [ ] **Step 3: Refactor `config.py`**

In `backend/app/llm/config.py`:

(a) Add import near the top (after the existing imports, before `logger`):

```python
from .runtime_config import read_runtime_override
```

(b) Replace the existing `get_config()` function (lines ~127–171) with:

```python
# ==================== 统一配置读取 ====================
def _resolve_config(require_key: bool = True) -> LLMConfig:
    """解析 LLM 配置。

    优先级：运行时覆写(app_setting) > LLM_* 环境变量 > DEEPSEEK_* 别名 > PROVIDERS 预设默认。

    require_key=False 时不强制 api_key（供「设置页」在未配置时也能加载）。
    """
    override = read_runtime_override()

    provider = override.get("provider") or os.getenv("LLM_PROVIDER", "deepseek")
    provider_type = (
        override.get("provider_type")
        or os.getenv("LLM_PROVIDER_TYPE")
        or infer_provider_type(provider)
    )

    preset = PROVIDERS.get(provider, {})

    # api_key：覆写里有就用覆写；否则 env 链
    if "api_key" in override:
        api_key = override.get("api_key") or ""
    else:
        api_key = os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY", "")

    if "base_url" in override:
        base_url = override.get("base_url") or preset.get("default_base_url", "")
    else:
        base_url = (
            os.getenv("LLM_BASE_URL")
            or os.getenv("DEEPSEEK_BASE_URL", "")
            or preset.get("default_base_url", "")
        )

    if "model" in override:
        model = override.get("model") or preset.get("default_model", "")
    else:
        model = (
            os.getenv("LLM_MODEL")
            or os.getenv("DEEPSEEK_MODEL", "")
            or preset.get("default_model", "")
        )

    temperature = float(os.getenv("LLM_TEMPERATURE", "0.3"))
    max_tokens_raw = os.getenv("LLM_MAX_TOKENS")
    max_tokens = int(max_tokens_raw) if max_tokens_raw else None
    timeout = float(os.getenv("LLM_TIMEOUT", "60"))

    if require_key and not api_key:
        raise ValueError(
            "LLM_API_KEY 未配置（也可用旧名 DEEPSEEK_API_KEY）。请在环境变量或设置页中设置。"
        )
    _assert_public_https_base_url(base_url)

    return LLMConfig(
        provider=provider,
        provider_type=provider_type,
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )


def get_config() -> LLMConfig:
    """从环境变量 + 运行时覆写读取并校验 LLM 配置（要求 api_key）。"""
    return _resolve_config(require_key=True)
```

- [ ] **Step 4: Run the full LLM config suite to verify it passes**

Run: `cd backend && source venv/bin/activate && pytest tests/test_llm_config.py -v`
Expected: PASS — all old tests (now DB-neutralized) + new override tests green.

- [ ] **Step 5: Sanity-run the broader suite (no regressions)**

Run: `cd backend && source venv/bin/activate && pytest tests/test_llm_client.py tests/test_llm_cost.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git -C /Users/alli/podcast-digester add backend/app/llm/config.py backend/tests/test_llm_config.py
git -C /Users/alli/podcast-digester commit -m "feat(llm): overlay runtime override in get_config (DB > env > preset)"
```

---

### Task 4: `ping_llm(cfg)` connectivity probe

**Files:**
- Modify: `backend/app/llm/client.py`
- Create: `backend/tests/test_llm_ping.py`

**Interfaces:**
- Consumes: `_get_adapter(cfg, timeout)` (already in `client.py`), `LLMConfig`.
- Produces: `async def ping_llm(cfg: LLMConfig) -> tuple[bool, str]` — issues a ~5-token completion with a 15s cap; returns `(True, "<model> 连通")` or `(False, "<human reason>")`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_llm_ping.py`:

```python
"""ping_llm: 连通性探测。"""
import pytest

from app.llm.config import LLMConfig
from app.llm.protocols import LLMResponse


def _cfg():
    return LLMConfig(
        provider="deepseek", provider_type="openai_compatible", api_key="sk-x",
        base_url="https://api.deepseek.com", model="deepseek-chat",
        temperature=0.3, max_tokens=None, timeout=60.0,
    )


@pytest.mark.llm
async def test_ping_success(monkeypatch):
    import app.llm.client as client

    class _Ok:
        async def complete(self, *, model, messages, temperature, max_tokens, response_format):
            return LLMResponse(content="pong", model=model, usage={},
                               finish_reason="stop", cost_usd=0.0)

    monkeypatch.setattr(client, "_get_adapter", lambda cfg, timeout: _Ok())
    ok, detail = await client.ping_llm(_cfg())
    assert ok is True
    assert "连通" in detail


@pytest.mark.llm
async def test_ping_auth_failure(monkeypatch):
    import app.llm.client as client

    class _AuthFail:
        async def complete(self, **kwargs):
            raise Exception("401 Unauthorized: invalid api key")

    monkeypatch.setattr(client, "_get_adapter", lambda cfg, timeout: _AuthFail())
    ok, detail = await client.ping_llm(_cfg())
    assert ok is False
    assert "API Key" in detail or "401" in detail


@pytest.mark.llm
async def test_ping_timeout(monkeypatch):
    import app.llm.client as client

    class _Timeout:
        async def complete(self, **kwargs):
            raise Exception("connection timeout")

    monkeypatch.setattr(client, "_get_adapter", lambda cfg, timeout: _Timeout())
    ok, detail = await client.ping_llm(_cfg())
    assert ok is False
    assert "超时" in detail or "timeout" in detail.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source venv/bin/activate && pytest tests/test_llm_ping.py -v`
Expected: FAIL — `ping_llm` not defined.

- [ ] **Step 3: Implement `ping_llm` + error humanizer**

Append to `backend/app/llm/client.py`:

```python
def _humanize_llm_error(err: Exception) -> str:
    """把 SDK/网络错误翻译成给用户看的一句话。"""
    s = str(err).lower()
    if "401" in s or "invalid api key" in s or "unauthorized" in s:
        return "API Key 无效或未授权（401）"
    if "403" in s or "forbidden" in s:
        return "拒绝访问（403），可能是 Key 无该模型权限"
    if "404" in s or "model" in s and "not found" in s:
        return "模型名或端点不对（404）"
    if "timeout" in s or "timed out" in s:
        return "请求超时（检查网络或 base_url 是否可达）"
    if "connection" in s or "name or service" in s or "getaddrinfo" in s:
        return "无法连接到该 API 地址（域名不通 / base_url 错误）"
    return f"请求失败：{err}"


async def ping_llm(cfg: LLMConfig) -> tuple[bool, str]:
    """用给定配置发一个极小请求，验证 key/端点/模型可用。

    用传入的 cfg（而非 get_config()），这样能测「未保存的草稿值」。
    返回 (ok, 中文说明)。
    """
    adapter = _get_adapter(cfg, min(cfg.timeout, 15.0))
    try:
        resp = await adapter.complete(
            model=cfg.model,
            messages=[{"role": "user", "content": "ping"}],
            temperature=0.0,
            max_tokens=5,
            response_format=None,
        )
        return True, f"连通（模型 {resp.model}）"
    except Exception as e:
        return False, _humanize_llm_error(e)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && source venv/bin/activate && pytest tests/test_llm_ping.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git -C /Users/alli/podcast-digester add backend/app/llm/client.py backend/tests/test_llm_ping.py
git -C /Users/alli/podcast-digester commit -m "feat(llm): add ping_llm connectivity probe with humanized errors"
```

---

### Task 5: `routers/llm_config.py` endpoints + mount

**Files:**
- Create: `backend/app/routers/llm_config.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_llm_config_api.py`

**Interfaces:**
- Consumes: `_resolve_config`, `PROVIDERS`, `_assert_public_https_base_url` (from `app.llm.config`); `read_runtime_override`/`write_runtime_override` (Task 2); `ping_llm` (Task 4); `LLMConfig`; `verify_admin`.
- Produces HTTP (all under `verify_admin`):
  - `GET /api/admin/llm-config` → `{provider, provider_type, base_url, model, has_api_key, api_key_masked, providers}`.
  - `PUT /api/admin/llm-config` (body: optional `provider/provider_type/api_key/base_url/model`) → `{ok: true, ...masked}`. 400 on SSRF fail.
  - `POST /api/admin/llm-config/test` (same body shape) → `{ok, detail}`.

**Masking rule:** `api_key_masked = "****" + key[-4:]` when `len(key) >= 4`, else `"****"`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_llm_config_api.py`:

```python
"""LLM 配置设置端点测试。"""
import pytest
from fastapi.testclient import TestClient


def _client():
    from app.main import app
    return TestClient(app)


@pytest.fixture
async def cfg_env(temp_db, monkeypatch):
    """临时库 + 清空 env，让端点行为可预测。"""
    for k in list(__import__("os").environ):
        if k.startswith(("LLM_", "DEEPSEEK_")):
            monkeypatch.delenv(k, raising=False)
    return monkeypatch


@pytest.mark.api
async def test_get_returns_masked_key_and_providers(cfg_env, monkeypatch):
    from app.llm.runtime_config import write_runtime_override
    await write_runtime_override({"provider": "deepseek", "api_key": "sk-abcd1234",
                                  "model": "deepseek-chat"})
    resp = _client().get("/api/admin/llm-config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "deepseek"
    assert body["model"] == "deepseek-chat"
    assert body["has_api_key"] is True
    assert body["api_key_masked"].endswith("1234")
    assert body["api_key_masked"].startswith("****")
    assert "deepseek" in body["providers"]


@pytest.mark.api
async def test_put_writes_override(cfg_env, monkeypatch):
    resp = _client().put("/api/admin/llm-config", json={
        "provider": "glm", "api_key": "sk-glm-xyz", "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4-flash",
    })
    assert resp.status_code == 200
    # 读回验证
    body = _client().get("/api/admin/llm-config").json()
    assert body["provider"] == "glm"
    assert body["has_api_key"] is True
    assert body["api_key_masked"].endswith("xyz")


@pytest.mark.api
async def test_put_without_api_key_keeps_old(cfg_env, monkeypatch):
    from app.llm.runtime_config import write_runtime_override
    await write_runtime_override({"api_key": "sk-old-9999"})
    _client().put("/api/admin/llm-config", json={"model": "gpt-4o-mini"})
    body = _client().get("/api/admin/llm-config").json()
    assert body["api_key_masked"].endswith("9999")  # 旧 key 保留


@pytest.mark.api
async def test_put_rejects_ssrf_base_url(cfg_env, monkeypatch):
    resp = _client().put("/api/admin/llm-config", json={
        "api_key": "sk-x", "base_url": "http://127.0.0.1:8080",
    })
    assert resp.status_code == 400
    assert "base_url" in resp.json()["detail"]


@pytest.mark.api
async def test_test_endpoint_ok(cfg_env, monkeypatch):
    import app.routers.llm_config as router
    monkeypatch.setattr(router, "ping_llm",
                        lambda cfg: (lambda c: (async lambda: (True, "连通"))())())
    # 上面 lambda 不好用，改用 async helper
    async def _ok(cfg):
        return True, "连通（模型 x）"
    monkeypatch.setattr(router, "ping_llm", _ok)
    resp = _client().post("/api/admin/llm-config/test", json={
        "api_key": "sk-x", "model": "m", "base_url": "https://api.deepseek.com",
        "provider": "deepseek",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True


@pytest.mark.api
async def test_test_endpoint_no_key(cfg_env, monkeypatch):
    resp = _client().post("/api/admin/llm-config/test", json={"provider": "deepseek"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is False
```

> Note: the first `_test_endpoint_ok` body has a throwaway line — use the clean `async def _ok` version (the `monkeypatch.setattr(router, "ping_llm", _ok)` line is the one that sticks). When implementing, keep only the `async def _ok` + `monkeypatch.setattr` lines; delete the lambda line.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && source venv/bin/activate && pytest tests/test_llm_config_api.py -v`
Expected: FAIL — route does not exist (404).

- [ ] **Step 3: Create the router**

Create `backend/app/routers/llm_config.py`:

```python
"""LLM 配置设置端点：前端「设置页」读 / 写 / 测试连接。

所有路由通过 verify_admin 保护（与 admin.py 一致）。
api_key 永不完整回传；base_url 过 SSRF 守卫。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..deps import verify_admin
from ..llm.client import ping_llm
from ..llm.config import (
    PROVIDERS, _resolve_config, _assert_public_https_base_url, infer_provider_type,
)
from ..llm.runtime_config import read_runtime_override, write_runtime_override

router = APIRouter(dependencies=[Depends(verify_admin)])
logger = logging.getLogger(__name__)


# ==================== Schemas ====================

class LLMConfigUpdate(BaseModel):
    """设置页提交体：所有字段可选，未提供 = 不改。"""
    provider: str | None = None
    provider_type: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None


# ==================== Helpers ====================

def _mask(key: str) -> str:
    return ("****" + key[-4:]) if key and len(key) >= 4 else "****"


def _public_providers() -> dict:
    """给下拉用的预设（全是展示字段，无敏感信息）。"""
    return {
        name: {
            "title": p["title"],
            "provider_type": p["provider_type"],
            "default_base_url": p["default_base_url"],
            "default_model": p["default_model"],
        }
        for name, p in PROVIDERS.items()
    }


# ==================== Routes ====================

@router.get("/api/admin/llm-config")
async def get_llm_config() -> dict:
    """返回当前生效配置（key 掩码）+ provider 预设。未配 key 也不报错。"""
    cfg = _resolve_config(require_key=False)
    return {
        "provider": cfg.provider,
        "provider_type": cfg.provider_type,
        "base_url": cfg.base_url,
        "model": cfg.model,
        "has_api_key": bool(cfg.api_key),
        "api_key_masked": _mask(cfg.api_key),
        "providers": _public_providers(),
    }


@router.put("/api/admin/llm-config")
async def put_llm_config(req: LLMConfigUpdate) -> dict:
    """写入运行时覆写。未提供 api_key 时保留旧值。"""
    if req.base_url:
        try:
            _assert_public_https_base_url(req.base_url)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    if req.provider_type and req.provider_type not in (
        "openai_compatible", "anthropic_compatible"
    ):
        raise HTTPException(status_code=400, detail="provider_type 非法")

    override = read_runtime_override() or {}
    for field in ("provider", "provider_type", "base_url", "model"):
        val = getattr(req, field)
        if val:
            override[field] = val
    # api_key：仅在用户真的填了新值时覆盖（None/空 = 保持不变）
    if req.api_key:
        override["api_key"] = req.api_key

    await write_runtime_override(override)
    logger.info("LLM 配置已更新（provider=%s）", override.get("provider"))

    cfg = _resolve_config(require_key=False)
    return {
        "ok": True,
        "provider": cfg.provider,
        "has_api_key": bool(cfg.api_key),
        "api_key_masked": _mask(cfg.api_key),
    }


@router.post("/api/admin/llm-config/test")
async def test_llm_config(req: LLMConfigUpdate) -> dict:
    """用提交中的值（未保存也能测）发一个极小请求验证连通性。"""
    from ..llm.config import LLMConfig

    base = _resolve_config(require_key=False)
    provider = req.provider or base.provider
    provider_type = req.provider_type or infer_provider_type(provider)
    api_key = req.api_key or base.api_key
    base_url = req.base_url if req.base_url is not None else base.base_url
    model = req.model or base.model

    if not api_key:
        return {"ok": False, "detail": "未填写 API Key"}
    if base_url:
        try:
            _assert_public_https_base_url(base_url)
        except ValueError as e:
            return {"ok": False, "detail": str(e)}

    cfg = LLMConfig(
        provider=provider, provider_type=provider_type, api_key=api_key,
        base_url=base_url, model=model,
        temperature=base.temperature, max_tokens=base.max_tokens, timeout=base.timeout,
    )
    ok, detail = await ping_llm(cfg)
    return {"ok": ok, "detail": detail}
```

- [ ] **Step 4: Mount the router in `main.py`**

In `backend/app/main.py`:

(a) Add the import next to the other router imports (after `from .routers import episodes as episodes_router`):

```python
from .routers import llm_config as llm_config_router
```

(b) Add the include next to the other includes (after `app.include_router(episodes_router.router)`):

```python
app.include_router(llm_config_router.router)
```

- [ ] **Step 5: Run the endpoint tests to verify they pass**

Run: `cd backend && source venv/bin/activate && pytest tests/test_llm_config_api.py -v`
Expected: PASS (6 tests). (Make sure the `_test_endpoint_ok` body uses only the `async def _ok` monkeypatch — delete the throwaway lambda line noted in Step 1.)

- [ ] **Step 6: Commit**

```bash
git -C /Users/alli/podcast-digester add backend/app/routers/llm_config.py backend/app/main.py backend/tests/test_llm_config_api.py
git -C /Users/alli/podcast-digester commit -m "feat(api): add /api/admin/llm-config GET/PUT/test endpoints"
```

---

### Task 6: Frontend API client methods

**Files:**
- Modify: `frontend/src/api.js`

**Interfaces:**
- Produces: `getLlmConfig()`, `saveLlmConfig(cfg)`, `testLlmConfig(cfg)` — all via `fetchWithTimeout`, auto `X-Admin-Token`.

- [ ] **Step 1: Append the three functions to `src/api.js`**

At the end of `frontend/src/api.js`:

```javascript
/**
 * 获取当前 LLM 配置（api_key 掩码）+ provider 预设列表
 * @returns {Promise<{provider,provider_type,base_url,model,has_api_key,api_key_masked,providers}>}
 */
export async function getLlmConfig() {
  const res = await fetchWithTimeout(`${API_BASE}/admin/llm-config`)
  if (!res.ok) throw new Error('获取 LLM 配置失败')
  return await res.json()
}

/**
 * 保存 LLM 配置。未改的字段（如 api_key）不要传。
 * @param {Object} cfg - { provider?, provider_type?, api_key?, base_url?, model? }
 */
export async function saveLlmConfig(cfg) {
  const res = await fetchWithTimeout(`${API_BASE}/admin/llm-config`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(cfg),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || '保存失败')
  }
  return await res.json()
}

/**
 * 测试连接（用当前表单值，无需先保存）。
 * @param {Object} cfg - 同 saveLlmConfig
 * @returns {Promise<{ok:boolean, detail:string}>}
 */
export async function testLlmConfig(cfg) {
  // 真实 LLM 调用，给 20s 余量
  const res = await fetchWithTimeout(`${API_BASE}/admin/llm-config/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(cfg),
  }, 20000)
  if (!res.ok) throw new Error('测试请求失败')
  return await res.json()
}
```

- [ ] **Step 2: Verify it parses**

Run: `cd frontend && node --check src/api.js`
Expected: no output (syntax OK).

- [ ] **Step 3: Commit**

```bash
git -C /Users/alli/podcast-digester add frontend/src/api.js
git -C /Users/alli/podcast-digester commit -m "feat(frontend): add LLM config API client methods"
```

---

### Task 7: `/settings` route

**Files:**
- Modify: `frontend/src/router.js`

- [ ] **Step 1: Add the route**

In `frontend/src/router.js`, add to the `routes` array (after the `player` route):

```javascript
  {
    path: '/settings',
    name: 'settings',
    component: () => import('@/views/SettingsView.vue'),
  },
```

- [ ] **Step 2: Commit**

```bash
git -C /Users/alli/podcast-digester add frontend/src/router.js
git -C /Users/alli/podcast-digester commit -m "feat(frontend): add /settings route"
```

---

### Task 8: `SettingsView.vue` + gear entry

**Files:**
- Create: `frontend/src/views/SettingsView.vue`
- Modify: `frontend/src/views/LibraryView.vue` (header)
- Create: `frontend/tests/views/SettingsView.spec.js`

**Interfaces:**
- Consumes: `getLlmConfig`, `saveLlmConfig`, `testLlmConfig` (Task 6); vue-router.
- The page fills `provider` (select), `api_key` (password, masked placeholder), `base_url`, `model`; switches provider → fills preset defaults; Test + Save buttons; back button.

- [ ] **Step 1: Write the failing test**

Create `frontend/tests/views/SettingsView.spec.js`:

```javascript
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import SettingsView from '@/views/SettingsView.vue'

const mockGetLlmConfig = vi.fn()
const mockSaveLlmConfig = vi.fn()
const mockTestLlmConfig = vi.fn()

vi.mock('@/api', () => ({
  getLlmConfig: () => mockGetLlmConfig(),
  saveLlmConfig: (cfg) => mockSaveLlmConfig(cfg),
  testLlmConfig: (cfg) => mockTestLlmConfig(cfg),
}))

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
  beforeEach(() => {
    mockGetLlmConfig.mockReset()
    mockSaveLlmConfig.mockReset()
    mockTestLlmConfig.mockReset()
  })

  it('loads current config and masks the key', async () => {
    mockGetLlmConfig.mockResolvedValue({
      provider: 'deepseek', provider_type: 'openai_compatible',
      base_url: 'https://api.deepseek.com', model: 'deepseek-chat',
      has_api_key: true, api_key_masked: '****1234',
      providers: { deepseek: { title: 'DeepSeek', provider_type: 'openai_compatible',
        default_base_url: 'https://api.deepseek.com', default_model: 'deepseek-chat' } },
    })
    const router = makeRouter()
    router.push('/settings')
    await router.isReady()
    const w = mount(SettingsView, { global: { plugins: [router] } })
    await flushPromises()
    expect(w.find('select').element.value).toBe('deepseek')
    expect(w.find('[data-test="base-url"]').element.value).toBe('https://api.deepseek.com')
    expect(w.find('[data-test="key-status"]').text()).toContain('****1234')
  })

  it('save posts only changed fields (no api_key when untouched)', async () => {
    mockGetLlmConfig.mockResolvedValue({
      provider: 'deepseek', provider_type: 'openai_compatible',
      base_url: 'https://api.deepseek.com', model: 'deepseek-chat',
      has_api_key: true, api_key_masked: '****1234', providers: {},
    })
    mockSaveLlmConfig.mockResolvedValue({ ok: true })
    const router = makeRouter()
    router.push('/settings'); await router.isReady()
    const w = mount(SettingsView, { global: { plugins: [router] } })
    await flushPromises()
    await w.find('[data-test="save"]').trigger('click')
    await flushPromises()
    expect(mockSaveLlmConfig).toHaveBeenCalledTimes(1)
    const sent = mockSaveLlmConfig.mock.calls[0][0]
    expect(sent.api_key).toBeUndefined()       // 未改 key，不发
    expect(sent.provider).toBe('deepseek')
  })

  it('test calls testLlmConfig and shows the result', async () => {
    mockGetLlmConfig.mockResolvedValue({
      provider: 'deepseek', provider_type: 'openai_compatible',
      base_url: 'https://api.deepseek.com', model: 'deepseek-chat',
      has_api_key: false, api_key_masked: '', providers: {},
    })
    mockTestLlmConfig.mockResolvedValue({ ok: true, detail: '连通（模型 deepseek-chat）' })
    const router = makeRouter()
    router.push('/settings'); await router.isReady()
    const w = mount(SettingsView, { global: { plugins: [router] } })
    await flushPromises()
    // 填一个 key
    await w.find('[data-test="api-key"]').setValue('sk-test-1234')
    await w.find('[data-test="test"]').trigger('click')
    await flushPromises()
    expect(mockTestLlmConfig).toHaveBeenCalledTimes(1)
    expect(w.find('[data-test="test-result"]').text()).toContain('连通')
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npx vitest run tests/views/SettingsView.spec.js`
Expected: FAIL — module `@/views/SettingsView.vue` not found.

- [ ] **Step 3: Create `SettingsView.vue`**

Create `frontend/src/views/SettingsView.vue`:

```vue
<template>
  <div class="settings-view">
    <header class="settings-header">
      <button @click="goBack" class="icon-btn" title="返回">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M19 12H5M12 19l-7-7 7-7"/>
        </svg>
      </button>
      <h1 class="settings-title">LLM API 设置</h1>
    </header>

    <div v-if="loadError" class="error-message" role="alert">{{ loadError }}</div>

    <section v-if="loaded" class="settings-form">
      <div class="field">
        <label for="provider">Provider</label>
        <select id="provider" v-model="form.provider" @change="onProviderChange">
          <option v-for="(p, key) in providers" :key="key" :value="key">{{ p.title || key }}</option>
        </select>
      </div>

      <div class="field">
        <label for="api-key">API Key</label>
        <input
          id="api-key" data-test="api-key"
          v-model="form.api_key" :type="showKey ? 'text' : 'password'"
          :placeholder="hasKey ? '已保存（如需更换请在此输入新 key）' : '粘贴你的 API Key...'"
          autocomplete="off"
        />
        <button type="button" class="toggle-btn" @click="showKey = !showKey" :title="showKey ? '隐藏' : '显示'">
          {{ showKey ? '🙈' : '👁' }}
        </button>
        <p v-if="hasKey && !form.api_key" data-test="key-status" class="hint">
          当前已保存：<code>{{ maskedKey }}</code>（留空保存即不改动）
        </p>
        <p v-else data-test="key-status" class="hint">尚未保存 Key</p>
      </div>

      <div class="field">
        <label for="base-url">API 链接（base_url）</label>
        <input id="base-url" data-test="base-url" v-model="form.base_url"
               placeholder="留空使用官方默认端点" />
      </div>

      <div class="field">
        <label for="model">模型</label>
        <input id="model" data-test="model" v-model="form.model" placeholder="如 deepseek-chat" />
      </div>

      <div class="actions">
        <button data-test="test" @click="onTest" :disabled="testing">
          {{ testing ? '测试中...' : '测试连接' }}
        </button>
        <button class="primary" data-test="save" @click="onSave" :disabled="saving">
          {{ saving ? '保存中...' : '保存' }}
        </button>
      </div>

      <p v-if="testResult" data-test="test-result"
         class="test-result" :class="testResult.ok ? 'ok' : 'fail'">
        {{ testResult.ok ? '✅' : '❌' }} {{ testResult.detail }}
      </p>
      <p v-if="saveMsg" class="test-result ok">{{ saveMsg }}</p>
      <p v-if="saveError" class="test-result fail">{{ saveError }}</p>
    </section>
  </div>
</template>

<script setup>
import { reactive, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getLlmConfig, saveLlmConfig, testLlmConfig } from '@/api'

const router = useRouter()

const loaded = ref(false)
const loadError = ref('')
const providers = ref({})
const hasKey = ref(false)
const maskedKey = ref('')

const form = reactive({ provider: 'deepseek', api_key: '', base_url: '', model: '' })
const showKey = ref(false)

const testing = ref(false)
const testResult = ref(null)
const saving = ref(false)
const saveMsg = ref('')
const saveError = ref('')

function goBack() {
  if (window.history.length > 1) router.back()
  else router.push('/')
}

function onProviderChange() {
  const p = providers.value[form.provider]
  if (!p) return
  // 切 provider：自动填该预设的默认 base_url / model（用户可再手改）
  form.base_url = p.default_base_url || ''
  form.model = p.default_model || ''
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
    form.api_key = ''  // 永不预填真实 key；留空 = 不改
    loaded.value = true
  } catch (e) {
    loadError.value = e.message || '加载配置失败'
    loaded.value = true
  }
}

/** 构造提交体：只包含有意义的字段。api_key 留空则不发（保留旧值）。 */
function buildPayload({ includeKeyIfAny }) {
  const body = {}
  if (form.provider) body.provider = form.provider
  if (form.base_url !== null && form.base_url !== undefined) body.base_url = form.base_url
  if (form.model) body.model = form.model
  if (includeKeyIfAny && form.api_key.trim()) body.api_key = form.api_key.trim()
  return body
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
    saveMsg.value = '已保存。下一次处理播客即生效（API 与 Worker 均立即生效）。'
    // 保存后刷新掩码状态
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

<style scoped>
.settings-view {
  max-width: 640px;
  margin: 0 auto;
  padding: 24px 20px 64px;
}
.settings-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
}
.settings-title {
  font-size: 20px;
  font-weight: 600;
  color: #1f2937;
}
.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px; height: 36px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
  color: #4b5563;
  cursor: pointer;
}
.icon-btn:hover { border-color: #d1d5db; }
.settings-form {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  position: relative;
}
.field label {
  font-size: 14px;
  font-weight: 500;
  color: #374151;
}
.field input, .field select {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  font-size: 14px;
  font-family: 'SF Mono', 'Fira Code', monospace;
  background: #fff;
}
.field input:focus, .field select:focus {
  outline: none;
  border-color: #4f8ef7;
  box-shadow: 0 0 0 3px rgba(79, 142, 247, 0.1);
}
.toggle-btn {
  position: absolute;
  right: 8px;
  bottom: 30px;
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 16px;
}
.hint {
  font-size: 12px;
  color: #6b7280;
}
.hint code {
  font-family: 'SF Mono', monospace;
  background: #f3f4f6;
  padding: 1px 5px;
  border-radius: 4px;
}
.actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
}
.actions button {
  padding: 9px 18px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  background: #fff;
  color: #374151;
}
.actions button:disabled { opacity: 0.5; cursor: not-allowed; }
.actions button.primary {
  background: #4f8ef7;
  border-color: #4f8ef7;
  color: #fff;
}
.test-result {
  font-size: 13px;
  padding: 8px 12px;
  border-radius: 8px;
}
.test-result.ok { background: #ecfdf5; color: #065f46; }
.test-result.fail { background: #fee2e2; color: #991b1b; }
.error-message {
  color: #991b1b;
  background: #fee2e2;
  padding: 10px 12px;
  border-radius: 8px;
  margin-bottom: 12px;
}
</style>
```

- [ ] **Step 4: Run the Vitest suite to verify it passes**

Run: `cd frontend && npx vitest run tests/views/SettingsView.spec.js`
Expected: PASS (3 tests).

- [ ] **Step 5: Add the gear entry in `LibraryView.vue`**

In `frontend/src/views/LibraryView.vue`, inside `<header class="brand-header">`, add a settings link after the `.brand-stats` div (still inside the header). Add to the `<template>`:

```html
      <router-link to="/settings" class="settings-gear" title="LLM API 设置" aria-label="LLM API 设置">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="3"/>
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
        </svg>
      </router-link>
```

And add the style to the `<style>` block in `LibraryView.vue`:

```css
.settings-gear {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px; height: 34px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  color: #6b7280;
  text-decoration: none;
  transition: color .15s, border-color .15s;
}
.settings-gear:hover { color: #4f8ef7; border-color: #4f8ef7; }
```

- [ ] **Step 6: Commit**

```bash
git -C /Users/alli/podcast-digester add frontend/src/views/SettingsView.vue frontend/src/views/LibraryView.vue frontend/tests/views/SettingsView.spec.js
git -C /Users/alli/podcast-digester commit -m "feat(frontend): add LLM API settings page + library gear entry"
```

---

### Task 9: Manual end-to-end verification

> No new code. Confirms the whole stack works against the real running services.

- [ ] **Step 1: Run the full backend test suite**

Run: `cd backend && source venv/bin/activate && pytest tests -q`
Expected: all green (previous 392 + new tests), no failures.

- [ ] **Step 2: Run the full frontend test suite**

Run: `cd frontend && npx vitest run`
Expected: all green.

- [ ] **Step 3: Restart the API + Worker (launchd) so the new code loads**

Run (only if services are launchd-managed):
```bash
launchctl kickstart -k gui/$(id -u)/com.podcast-digester.api 2>/dev/null || true
launchctl kickstart -k gui/$(id -u)/com.podcast-digester.worker 2>/dev/null || true
```
If not launchd-managed, restart `uvicorn` and `worker.py` manually. The new `app_setting` table is created by `init_db()` on API start.

- [ ] **Step 4: Verify the DB table exists**

Run: `sqlite3 /Users/alli/podcast-digester/data/podcast_digester.db ".tables" | tr ' ' '\n' | grep app_setting`
Expected: prints `app_setting`.

- [ ] **Step 5: UI smoke test**

1. Open `http://localhost:5173/`, click the gear icon → `/settings` loads with current config (key masked).
2. Switch provider to OpenAI → base_url/model clear to defaults.
3. Paste a real key + click **测试连接** → `✅ 连通`.
4. Click **保存** → `已保存…`.
5. Paste a real podcast/video link, process one episode, confirm it runs against the newly saved provider/key (check `data/podcast_digester.db` `cost_log` model column or backend logs).

- [ ] **Step 6: Commit any final touches (e.g., README mention)**

If desired, add a one-line note to `README.md` Quick Start pointing to the in-app settings page, then:
```bash
git -C /Users/alli/podcast-digester add README.md
git -C /Users/alli/podcast-digester commit -m "docs: mention in-app LLM settings page"
```

---

## Self-Review (run after writing — already applied)

- **Spec coverage:** DB table (T1), read/write override (T2), get_config overlay + hermetic tests (T3), ping (T4), GET/PUT/test endpoints + mount (T5), frontend api/router/view/entry (T6/T7/T8), e2e verify (T9). Masking (T5 `_mask` + T8 display), SSRF (T5 PUT/test), key-preserve-on-omit (T5 PUT + T8 `buildPayload`), cross-process immediacy (T3 per-call read). All spec sections covered.
- **Placeholders:** none — every step has real code/commands.
- **Type/name consistency:** `read_runtime_override`/`write_runtime_override`/`OVERRIDE_KEY` (T2→T3→T5), `_resolve_config`/`_assert_public_https_base_url`/`PROVIDERS`/`LLMConfig` (T3→T5), `ping_llm` (T4→T5), `getLlmConfig`/`saveLlmConfig`/`testLlmConfig` (T6→T8), `data-test` hooks (`api-key`/`base-url`/`key-status`/`save`/`test`/`test-result`) match between T8 template and T8 test. `api_key_masked` / `has_api_key` / `providers` field names match between GET response (T5) and test+view (T8).

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-15-llm-settings-page.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
