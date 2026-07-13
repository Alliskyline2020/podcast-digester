# LLM Multi-Provider Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the DeepSeek-only LLM binding with a provider-agnostic adapter layer supporting both OpenAI-compatible and Anthropic-compatible protocols, funneled through a single `complete()` chokepoint — while removing the thinking-model tier and keeping all 369 existing tests green.

**Architecture:** `app/llm.py` (module) → `app/llm/` (package) with focused submodules: `config.py` (PROVIDERS registry + `get_config()` + SSRF guard + DEEPSEEK_* alias), `cost.py` (price table), `protocols.py` (`LLMResponse` + `OpenAIAdapter` + `AnthropicAdapter` wrapping the official SDKs), `client.py` (unified `complete()` + retry + error translation). The existing `chat_json`/`chat_structured` become thin wrappers over `complete()` so all current call sites and the conftest `monkeypatch.setattr(app.llm, "chat_json", …)` contract keep working unchanged.

**Tech Stack:** Python 3.11+, `openai==1.51.0` (already pinned), `anthropic` (new), pytest + pytest-asyncio + pytest-mock.

**Spec:** `docs/superpowers/specs/2026-07-13-llm-multi-provider-design.md` (approved). This plan is the bite-sized TDD decomposition of that spec.

## Global Constraints

Copied verbatim from the spec + project conventions; every task's requirements implicitly include these.

- **Two protocols only:** `openai_compatible` and `anthropic_compatible`. NO Gemini native (use an OpenAI-compatible gateway if ever needed). This follows qmreader.
- **Official SDKs, not raw httpx:** `openai.AsyncOpenAI` and `anthropic.AsyncAnthropic`. Chosen for stability + compatibility (providers officially recommend their own SDKs).
- **Thinking mode removed entirely:** one model for all tasks. Delete every `deepseek-v4-flash` literal and the "需要 thinking" code-path rationale. No `reasoning_content` handling, no thinking/fast dual-tier routing.
- **No BYOK, no streaming.** Single-user self-hosted. Calls are non-streaming batch JSON.
- **Backward compatibility:** `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` remain as aliases mapping to `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL`. Existing `.env` files must keep working.
- **conftest mock contract preserved:** `monkeypatch.setattr(app.llm, "chat_json", …)` (see `backend/tests/conftest.py:181`) must still patch successfully after `app/llm.py` → `app/llm/` conversion. `chat_json` is re-exported from the package `__init__.py`.
- **Acceptance bar (spec criterion #3):** `grep -rn "deepseek-v4-flash\|deepseek-chat\|DEEPSEEK_API_KEY" backend/app --include="*.py"` may only return lines inside the DEEPSEEK_* alias-mapping code (in `app/config.py`) and the `PROVIDERS["deepseek"]` registry entry (in `app/llm/config.py`). Nowhere else.
- **Don't break existing behavior:** highlights / insights / translate / polish / segment / subtitle behavior is covered by the existing 369 tests — they are the regression net. Run the full suite after every wiring change.
- **Git convention:** branch `refactor/lang-naming` (already checked out), author `Al Li <alli@local>`, **no** Co-Authored-By trailer, conventional-commit messages. **Commits are gated on explicit user "提交"** — during execution, stage changes per task but only commit when the user says so (or batch commits at the user's direction). The `Commit` steps below describe the intended per-task checkpoint, not an instruction to auto-commit.

## File Structure

```
backend/app/llm/                 # NEW package (replaces app/llm.py)
├── __init__.py                  # public API: complete, chat_json, chat_structured,
│                                #   LLMParseError, LLMRateLimitError, get_config
├── config.py                    # PROVIDERS registry, LLMConfig, get_config(),
│                                #   infer_provider_type(), _assert_public_https_base_url()
├── cost.py                      # COST_PER_1M_TOKENS table + cost()
├── protocols.py                 # LLMResponse dataclass + OpenAIAdapter + AnthropicAdapter
└── client.py                    # _retry_with_backoff(), complete(), _get_adapter()

backend/app/llm.py               # DELETED (becomes the package above)
backend/app/config.py            # MODIFIED: DEEPSEEK_* → LLM_* alias plumbing;
                                #   drop deepseek-specific cost table + calculate_llm_cost
backend/app/models.py            # MODIFIED: neutralize one field description
backend/app/llm_pipeline/
  ├── llm_highlight.py           # MODIFIED: drop 2× model="deepseek-v4-flash"
  ├── llm_product_insights.py    # MODIFIED: drop 1× model="deepseek-v4-flash"
  └── legacy.py                  # MODIFIED: drop unused DEEPSEEK_MODEL import
backend/app/services/
  ├── subtitle_processor.py      # MODIFIED: drop POLISH_MODEL constant
  └── llm_subtitle_processor.py  # MODIFIED: route 5 sync calls through complete();
                                  #   drop __init__ api_key/base_url plumbing
backend/app/routers/
  ├── subtitles.py               # MODIFIED: drop 3× os.getenv("DEEPSEEK_API_KEY") + guards
  └── admin.py                   # MODIFIED: drop 1× os.getenv("DEEPSEEK_API_KEY") + guard
backend/.env.example             # MODIFIED: add LLM_* vars, mark DEEPSEEK_* as legacy aliases
backend/requirements.txt         # MODIFIED: + anthropic
backend/tests/
  ├── test_llm_config.py         # NEW
  ├── test_llm_cost.py           # NEW
  ├── test_llm_protocols.py      # NEW
  ├── test_llm_client.py         # NEW
  └── (existing suite stays green throughout)
```

---

## Task 1: Convert `app/llm.py` → `app/llm/` package (pure mechanical move)

**Why first:** Python cannot have both `app/llm.py` and `app/llm/` — Tasks 2–5 need sibling submodules. This task is a pure refactor move: zero logic change, the existing suite must stay green, and it unblocks everything else.

**Files:**
- Move: `backend/app/llm.py` → `backend/app/llm/__init__.py` (via `git mv`)
- Test: the existing 369-test suite is the test (no new test)

**Interfaces:**
- Produces: `app.llm` as a package whose `__init__.py` exposes the identical public names (`chat_json`, `chat_structured`, `_get_client`, `LLMParseError`, `LLMRateLimitError`) so every `from ..llm import chat_json` / `from app.llm import …` / `monkeypatch.setattr(app.llm, "chat_json", …)` keeps resolving.

- [ ] **Step 1: Confirm baseline is green**

Run: `cd backend && python -m pytest -q 2>&1 | tail -5`
Expected: all tests pass (record the count — it must stay ≥ this number after the move).

- [ ] **Step 2: Move the file into a package**

Run:
```bash
cd backend && \
mkdir -p app/llm && \
git mv app/llm.py app/llm/__init__.py
```
Expected: `app/llm.py` gone, `app/llm/__init__.py` present with the original content.

- [ ] **Step 3: Fix the single intra-package relative import**

The moved file's first import block references sibling modules with `.` (top-level package) semantics. Inside `app/llm/__init__.py`, `from .config import …` now means `app/llm/config.py` (which doesn't exist yet), not `app/config.py`. Change the config import to go up two levels.

In `backend/app/llm/__init__.py`, replace:

```python
from .config import (
    DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL,
    MAX_RETRIES, BASE_DELAY, MAX_DELAY, DEFAULT_TEMPERATURE,
    calculate_llm_cost,
)
```

with:

```python
from ..config import (
    DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL,
    MAX_RETRIES, BASE_DELAY, MAX_DELAY, DEFAULT_TEMPERATURE,
    calculate_llm_cost,
)
```

Leave everything else in `__init__.py` byte-identical.

- [ ] **Step 4: Run the full suite — must stay green**

Run: `cd backend && python -m pytest -q 2>&1 | tail -5`
Expected: same pass count as Step 1. If any test fails with an import error, the relative-import depth is wrong — recheck Step 3.

- [ ] **Step 5: Commit**

```bash
git add app/llm/__init__.py
git commit -m "refactor(llm): convert app/llm.py to app/llm/ package (no logic change)"
```
(Gated on user "提交" — see Global Constraints.)

---

## Task 2: Extract cost table into `app/llm/cost.py`

**Files:**
- Create: `backend/app/llm/cost.py`
- Create: `backend/tests/test_llm_cost.py`
- Modify: `backend/app/llm/__init__.py` (import `cost` from the new module instead of `app.config.calculate_llm_cost`)

**Interfaces:**
- Produces: `app.llm.cost.cost(model: str, prompt_tokens: int, completion_tokens: int) -> float` and the `COST_PER_1M_TOKENS` dict. Unknown model → `0.0` + a warning log (spec: "unknown → 0.0 + warn").
- Consumes: nothing (pure function over a module-level dict).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_llm_cost.py`:

```python
"""cost() 单元测试：价格查表 + 未知模型兜底。"""
import logging

from app.llm.cost import cost, COST_PER_1M_TOKENS


def test_known_model_input_plus_output():
    # deepseek-chat: input 0.14 / output 0.28 per 1M (USD)
    c = cost("deepseek-chat", 1_000_000, 1_000_000)
    assert c == 0.14 + 0.28


def test_zero_tokens_is_zero_cost():
    assert cost("deepseek-chat", 0, 0) == 0.0


def test_unknown_model_returns_zero_and_warns(caplog):
    with caplog.at_level(logging.WARNING, logger="app.llm.cost"):
        c = cost("some-unknown-model", 500, 500)
    assert c == 0.0
    assert any("some-unknown-model" in r.message for r in caplog.records)


def test_table_has_anthropic_entry():
    # 兼容性回归：价格表必须含至少一个 anthropic 模型条目
    assert any(k.startswith("claude") for k in COST_PER_1M_TOKENS)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_llm_cost.py -q 2>&1 | tail -8`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.llm.cost'`.

- [ ] **Step 3: Implement `app/llm/cost.py`**

Create `backend/app/llm/cost.py`:

```python
"""LLM 成本核算：按 (模型, 输入/输出 token) 查价格表。

未知模型返回 0.0 并打 warning（spec: unknown → 0.0 + warn），
让 per-episode 预算守护 `_meta.cost_usd` 始终有值、永不崩。
价格单位：USD per 1,000,000 tokens。来源：各厂商官网定价页（impl 时核对）。
"""
import logging

logger = logging.getLogger(__name__)

# 价格表：USD per 1M tokens。新增 provider 时按官方定价页补条目。
# 字段含义：{"input": 输入单价, "output": 输出单价}
COST_PER_1M_TOKENS: dict[str, dict[str, float]] = {
    # DeepSeek
    "deepseek-chat": {"input": 0.14, "output": 0.28},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19},
    # OpenAI
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    # Anthropic
    "claude-3-5-sonnet-latest": {"input": 3.00, "output": 15.00},
    "claude-3-5-haiku-latest": {"input": 0.80, "output": 4.00},
    # GLM (智谱)
    "glm-4-flash": {"input": 0.10, "output": 0.10},
    "glm-4": {"input": 3.50, "output": 3.50},
    # 通义千问
    "qwen-plus": {"input": 0.40, "output": 1.20},
    # 月之暗面
    "moonshot-v1-8k": {"input": 1.70, "output": 1.70},
}


def cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """计算单次 LLM 调用成本（美元）。

    未知模型返回 0.0 并 warning（不抛异常，保证预算守护逻辑不崩）。
    """
    rates = COST_PER_1M_TOKENS.get(model)
    if rates is None:
        logger.warning(
            "cost: 未知模型 %r，按 0.0 计费。请在 COST_PER_1M_TOKENS 补条目。", model
        )
        return 0.0
    return (prompt_tokens / 1_000_000) * rates["input"] + \
           (completion_tokens / 1_000_000) * rates["output"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_llm_cost.py -q 2>&1 | tail -8`
Expected: PASS (4 tests).

- [ ] **Step 5: Rewire `__init__.py` to use the new cost module**

In `backend/app/llm/__init__.py`, the `chat_json`/`chat_structured` bodies call `calculate_llm_cost(model, …)` (imported from `..config`). Replace that import and the two call sites.

Replace the import line (from Task 1 Step 3) so the block reads:

```python
from ..config import (
    DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL,
    MAX_RETRIES, BASE_DELAY, MAX_DELAY, DEFAULT_TEMPERATURE,
)
from .cost import cost as calculate_llm_cost
```

(The alias `as calculate_llm_cost` keeps the two existing call sites in `chat_json` and `chat_structured` working without editing their bodies. `calculate_llm_cost` is the local name they already use.)

- [ ] **Step 6: Run the full suite — must stay green**

Run: `cd backend && python -m pytest -q 2>&1 | tail -5`
Expected: pass count ≥ Task 1 baseline (now +4 new cost tests).

- [ ] **Step 7: Commit**

```bash
git add app/llm/cost.py tests/test_llm_cost.py app/llm/__init__.py
git commit -m "feat(llm): extract cost table into app/llm/cost.py with multi-provider rates"
```

---

## Task 3: `app/llm/config.py` — PROVIDERS, `get_config()`, SSRF guard, DEEPSEEK_* alias

**Files:**
- Create: `backend/app/llm/config.py`
- Create: `backend/tests/test_llm_config.py`

**Interfaces:**
- Produces:
  - `app.llm.config.LLMConfig` (frozen dataclass): `provider`, `provider_type`, `api_key`, `base_url`, `model`, `temperature`, `max_tokens`, `timeout`
  - `app.llm.config.get_config() -> LLMConfig` (reads env, applies DEEPSEEK_* alias, validates, SSRF-guards)
  - `app.llm.config.infer_provider_type(provider: str) -> str`
  - `app.llm.config.PROVIDERS` (registry dict)
  - `app.llm.config._assert_public_https_base_url(base_url: str) -> None`
- Consumes: nothing (reads `os.environ` directly).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_llm_config.py`:

```python
"""app/llm/config 单元测试：PROVIDERS、get_config 别名、provider_type 推断、SSRF 守卫。"""
import pytest

from app.llm.config import (
    PROVIDERS, get_config, infer_provider_type, LLMConfig,
)


@pytest.fixture
def clean_llm_env(monkeypatch):
    """清空所有 LLM/DEEPSEEK 环境变量，每个用例显式 set 需要的。"""
    for k in list(__import__("os").environ):
        if k.startswith(("LLM_", "DEEPSEEK_")):
            monkeypatch.delenv(k, raising=False)
    return monkeypatch


def test_providers_registry_has_required_entries():
    for name in ("deepseek", "openai", "anthropic", "glm", "qwen", "doubao", "moonshot"):
        assert name in PROVIDERS, f"缺少 provider: {name}"
        entry = PROVIDERS[name]
        assert "provider_type" in entry
        assert entry["provider_type"] in ("openai_compatible", "anthropic_compatible")
        assert "default_base_url" in entry
        assert "default_model" in entry


def test_infer_provider_type_from_registry():
    assert infer_provider_type("deepseek") == "openai_compatible"
    assert infer_provider_type("anthropic") == "anthropic_compatible"


def test_infer_unknown_provider_defaults_to_openai():
    assert infer_provider_type("totally-unknown") == "openai_compatible"


def test_deepseek_legacy_alias_works(clean_llm_env, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-legacy")
    monkeypatch.setenv("DEEPSEEK_MODEL", "deepseek-chat")
    cfg = get_config()
    assert cfg.api_key == "sk-legacy"
    assert cfg.model == "deepseek-chat"
    assert cfg.provider == "deepseek"
    assert cfg.provider_type == "openai_compatible"


def test_llm_vars_take_precedence_over_deepseek_alias(clean_llm_env, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-legacy")
    monkeypatch.setenv("LLM_API_KEY", "sk-new")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_MODEL", "claude-3-5-haiku-latest")
    cfg = get_config()
    assert cfg.api_key == "sk-new"
    assert cfg.provider == "anthropic"
    assert cfg.provider_type == "anthropic_compatible"
    assert cfg.model == "claude-3-5-haiku-latest"


def test_explicit_provider_type_overrides_inference(clean_llm_env, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-x")
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")  # 推断为 openai_compatible
    monkeypatch.setenv("LLM_PROVIDER_TYPE", "anthropic_compatible")  # 显式覆盖
    cfg = get_config()
    assert cfg.provider_type == "anthropic_compatible"


def test_missing_api_key_raises(clean_llm_env):
    with pytest.raises(ValueError, match="LLM_API_KEY"):
        get_config()


def test_ssrf_guard_blocks_localhost(clean_llm_env, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-x")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:8080")
    with pytest.raises(ValueError, match="base_url"):
        get_config()


def test_ssrf_guard_blocks_private_range(clean_llm_env, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-x")
    monkeypatch.setenv("LLM_BASE_URL", "http://192.168.1.5")
    with pytest.raises(ValueError, match="base_url"):
        get_config()


def test_ssrf_guard_allows_public_https(clean_llm_env, monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "sk-x")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.deepseek.com")
    cfg = get_config()  # 不抛
    assert cfg.base_url == "https://api.deepseek.com"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_llm_config.py -q 2>&1 | tail -8`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.llm.config'`.

- [ ] **Step 3: Implement `app/llm/config.py`**

Create `backend/app/llm/config.py`:

```python
"""LLM 提供方配置：PROVIDERS 预设表 + get_config() 统一读取 + SSRF 守卫。

设计（参考 qmreader）：
- provider  = 命名预设（用于填默认值 / UI 标题）
- provider_type = 实际协议（openai_compatible | anthropic_compatible），决定请求形状
- DEEPSEEK_* 环境变量作为向后兼容别名映射到 LLM_*。
"""
import ipaddress
import os
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

logger = __import__("logging").getLogger(__name__)


# ==================== PROVIDERS 预设表 ====================
# 每个条目：title(展示名) / provider_type(协议) / default_base_url / default_model
# base_url 留空 = 用 SDK 自带默认（OpenAI / Anthropic 官方端点）。
# URL 与模型名以厂商官方文档为准（impl 时已核对）。
PROVIDERS: dict[str, dict] = {
    "deepseek": {
        "title": "DeepSeek",
        "provider_type": "openai_compatible",
        "default_base_url": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
    },
    "openai": {
        "title": "OpenAI",
        "provider_type": "openai_compatible",
        "default_base_url": "",  # SDK 默认 https://api.openai.com/v1
        "default_model": "gpt-4o-mini",
    },
    "anthropic": {
        "title": "Anthropic (Claude)",
        "provider_type": "anthropic_compatible",
        "default_base_url": "",  # SDK 默认 https://api.anthropic.com
        "default_model": "claude-3-5-sonnet-latest",
    },
    "glm": {
        "title": "智谱 GLM",
        "provider_type": "openai_compatible",
        "default_base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4-flash",
    },
    "qwen": {
        "title": "通义千问",
        "provider_type": "openai_compatible",
        "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
    },
    "doubao": {
        "title": "字节豆包",
        "provider_type": "openai_compatible",
        "default_base_url": "https://ark.cn-beijing.volces.com/api/v3",
        # 豆包模型 id 实为 endpoint id，需用户在火山控制台创建后填入 LLM_MODEL
        "default_model": "",
    },
    "moonshot": {
        "title": "月之暗面 Kimi",
        "provider_type": "openai_compatible",
        "default_base_url": "https://api.moonshot.cn/v1",
        "default_model": "moonshot-v1-8k",
    },
    # 通用兜底：用户自填 base_url / model
    "openai-compatible": {
        "title": "OpenAI 兼容（自定义端点）",
        "provider_type": "openai_compatible",
        "default_base_url": "",
        "default_model": "",
    },
    "anthropic-compatible": {
        "title": "Anthropic 兼容（自定义端点）",
        "provider_type": "anthropic_compatible",
        "default_base_url": "",
        "default_model": "",
    },
}


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    provider_type: str            # openai_compatible | anthropic_compatible
    api_key: str
    base_url: str                 # 可为空（用 SDK 默认）
    model: str
    temperature: float
    max_tokens: Optional[int]     # None = 不传，用 provider 默认
    timeout: float


def infer_provider_type(provider: str) -> str:
    """从 PROVIDERS 表推断协议。未知 provider 默认 openai_compatible（最通用）。"""
    entry = PROVIDERS.get(provider)
    if entry is None:
        return "openai_compatible"
    return entry["provider_type"]


# ==================== SSRF 守卫 ====================
def _assert_public_https_base_url(base_url: str) -> None:
    """禁止把 LLM 请求打到内网/本机（参考 qmreader assertPublicHttpsBaseUrl）。

    空字符串放行（用 SDK 自带官方端点）。http 一律拒（LLM key 不可明文走 http）。
    """
    if not base_url:
        return
    parsed = urlparse(base_url)
    if parsed.scheme != "https":
        raise ValueError(f"base_url 必须是 https://：{base_url!r}")
    host = parsed.hostname or ""
    if host.endswith(".local"):
        raise ValueError(f"base_url 禁止指向 .local：{base_url!r}")
    try:
        # 解析所有 A/AAAA；任一落内网段即拒
        infos = __import__("socket").getaddrinfo(host, None)
    except OSError:
        raise ValueError(f"base_url 主机无法解析：{host!r}")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise ValueError(f"base_url 禁止指向内网/本机地址 {ip}：{base_url!r}")


# ==================== 统一配置读取 ====================
def get_config() -> LLMConfig:
    """从环境变量读取并校验 LLM 配置。

    优先级：LLM_* > DEEPSEEK_*（向后兼容别名）> PROVIDERS[provider] 默认值。
    """
    provider = os.getenv("LLM_PROVIDER", "deepseek")

    # 显式 LLM_PROVIDER_TYPE 胜出；否则从 provider 推断
    provider_type = os.getenv("LLM_PROVIDER_TYPE") or infer_provider_type(provider)

    # API key / base_url / model：LLM_* 优先，回退 DEEPSEEK_* 别名，再回退 registry 默认
    api_key = os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY", "")
    preset = PROVIDERS.get(provider, {})
    base_url = (
        os.getenv("LLM_BASE_URL")
        or os.getenv("DEEPSEEK_BASE_URL", "")
        or preset.get("default_base_url", "")
    )
    model = (
        os.getenv("LLM_MODEL")
        or os.getenv("DEEPSEEK_MODEL", "")
        or preset.get("default_model", "")
    )

    temperature = float(os.getenv("LLM_TEMPERATURE", "0.3"))
    max_tokens_raw = os.getenv("LLM_MAX_TOKENS")
    max_tokens = int(max_tokens_raw) if max_tokens_raw else None
    timeout = float(os.getenv("LLM_TIMEOUT", "60"))

    if not api_key:
        raise ValueError(
            "LLM_API_KEY 未配置（也可用旧名 DEEPSEEK_API_KEY）。请在环境变量中设置。"
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_llm_config.py -q 2>&1 | tail -8`
Expected: PASS (10 tests).

- [ ] **Step 5: Run the full suite — must stay green**

Run: `cd backend && python -m pytest -q 2>&1 | tail -5`
Expected: pass count ≥ Task 2 (now +10 new config tests). `app/llm/config.py` is not yet wired into `__init__.py`, so existing behavior is untouched.

- [ ] **Step 6: Commit**

```bash
git add app/llm/config.py tests/test_llm_config.py
git commit -m "feat(llm): add PROVIDERS registry, get_config() with DEEPSEEK alias + SSRF guard"
```

---

## Task 4: `app/llm/protocols.py` — `LLMResponse` + OpenAI/Anthropic adapters

**Files:**
- Create: `backend/app/llm/protocols.py`
- Create: `backend/tests/test_llm_protocols.py`

**Interfaces:**
- Produces:
  - `app.llm.protocols.LLMResponse` (frozen dataclass): `content`, `model`, `usage` (dict with `prompt_tokens`, `completion_tokens`, `total_tokens`), `finish_reason` (normalized), `cost_usd`
  - `app.llm.protocols.OpenAIAdapter(api_key, base_url, timeout)` with `async def complete(*, model, messages, temperature, max_tokens, response_format) -> LLMResponse`
  - `app.llm.protocols.AnthropicAdapter(api_key, base_url, timeout)` with the same `complete()` signature
- Consumes: `app.llm.cost.cost` for per-call cost.

**Design notes baked into the code:**
- OpenAI adapter passes `response_format` through unchanged.
- Anthropic adapter **ignores `response_format`** (no native JSON mode — JSON correctness comes from prompt instructions + the fenced-block extraction fallback in `chat_json`). This is the spec's explicit decision.
- Anthropic adapter extracts `system` messages to the top-level `system` param; maps all non-assistant roles to `user`. The pipeline is single-turn (`[system, user]`) so no alternating-message repair is needed.
- Anthropic `max_tokens` is required by the API; the adapter supplies `8192` when the caller passes `None`.
- Tests mock the SDK clients (no network).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_llm_protocols.py`:

```python
"""protocols 单元测试：两个 adapter 的请求塑形 + 响应归一化（mock SDK，无网络）。"""
import pytest

from app.llm.protocols import LLMResponse, OpenAIAdapter, AnthropicAdapter


# ---------- OpenAIAdapter ----------

class _FakeUsage:
    def __init__(self, p, c):
        self.prompt_tokens = p
        self.completion_tokens = c
        self.total_tokens = p + c


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content, finish_reason):
        self.message = _FakeMessage(content)
        self.finish_reason = finish_reason


class _FakeOpenAIResponse:
    def __init__(self, content, finish_reason="stop", model="deepseek-chat", p=10, c=20):
        self.choices = [_FakeChoice(content, finish_reason)]
        self.model = model
        self.usage = _FakeUsage(p, c)


class _FakeChatCompletions:
    def __init__(self, create_ret):
        self._ret = create_ret
        self.last_kwargs = None

    async def create(self, **kwargs):
        self.last_kwargs = kwargs
        return self._ret


class _FakeOpenAIClient:
    def __init__(self, create_ret):
        self.chat = type("C", (), {"completions": _FakeChatCompletions(create_ret)})()


@pytest.mark.asyncio
async def test_openai_adapter_passes_response_format_and_returns_llmresponse(monkeypatch):
    fake = _FakeOpenAIClient(_FakeOpenAIResponse('{"k": 1}', finish_reason="stop"))
    monkeypatch.setattr("openai.AsyncOpenAI", lambda **kw: fake)

    adapter = OpenAIAdapter(api_key="sk", base_url="https://api.deepseek.com", timeout=60)
    resp = await adapter.complete(
        model="deepseek-chat",
        messages=[{"role": "system", "content": "s"}, {"role": "user", "content": "u"}],
        temperature=0.3, max_tokens=8192,
        response_format={"type": "json_object"},
    )
    assert isinstance(resp, LLMResponse)
    assert resp.content == '{"k": 1}'
    assert resp.finish_reason == "stop"
    assert resp.usage == {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30}
    assert resp.cost_usd > 0
    # response_format 必须透传给 SDK
    assert fake.chat.completions.last_kwargs["response_format"] == {"type": "json_object"}
    assert fake.chat.completions.last_kwargs["max_tokens"] == 8192


@pytest.mark.asyncio
async def test_openai_adapter_omits_max_tokens_when_none(monkeypatch):
    fake = _FakeOpenAIClient(_FakeOpenAIResponse("ok"))
    monkeypatch.setattr("openai.AsyncOpenAI", lambda **kw: fake)
    adapter = OpenAIAdapter(api_key="sk", base_url="", timeout=60)
    await adapter.complete(
        model="m", messages=[{"role": "user", "content": "u"}],
        temperature=0.3, max_tokens=None, response_format=None,
    )
    assert "max_tokens" not in fake.chat.completions.last_kwargs


# ---------- AnthropicAdapter ----------

class _FakeTextBlock:
    def __init__(self, text):
        self.type = "text"
        self.text = text


class _FakeAnthropicUsage:
    def __init__(self, i, o):
        self.input_tokens = i
        self.output_tokens = o


class _FakeAnthropicResponse:
    def __init__(self, text, stop_reason="end_turn", model="claude-3-5-sonnet-latest"):
        self.content = [_FakeTextBlock(text)]
        self.stop_reason = stop_reason
        self.model = model
        self.usage = _FakeAnthropicUsage(12, 34)


class _FakeMessages:
    def __init__(self, create_ret):
        self._ret = create_ret
        self.last_kwargs = None

    async def create(self, **kwargs):
        self.last_kwargs = kwargs
        return self._ret


class _FakeAnthropicClient:
    def __init__(self, create_ret):
        self.messages = _FakeMessages(create_ret)


@pytest.mark.asyncio
async def test_anthropic_adapter_extracts_system_and_maps_roles(monkeypatch):
    fake = _FakeAnthropicClient(_FakeAnthropicResponse("hello", stop_reason="end_turn"))
    monkeypatch.setattr("anthropic.AsyncAnthropic", lambda **kw: fake)

    adapter = AnthropicAdapter(api_key="sk-ant", base_url="", timeout=60)
    resp = await adapter.complete(
        model="claude-3-5-sonnet-latest",
        messages=[{"role": "system", "content": "be brief"},
                  {"role": "user", "content": "hi"}],
        temperature=0.3, max_tokens=None,
        response_format={"type": "json_object"},  # 必须被忽略
    )
    assert resp.content == "hello"
    assert resp.finish_reason == "stop"          # end_turn → stop
    assert resp.usage["total_tokens"] == 12 + 34
    kw = fake.messages.last_kwargs
    # system 提到顶层；messages 只剩 user
    assert kw["system"] == "be brief"
    assert kw["messages"] == [{"role": "user", "content": "hi"}]
    # max_tokens 必填 → adapter 兜底 8192
    assert kw["max_tokens"] == 8192
    # response_format 不可透传（Anthropic 无原生 JSON 模式）
    assert "response_format" not in kw


@pytest.mark.asyncio
async def test_anthropic_adapter_normalizes_stop_reasons(monkeypatch):
    for raw, want in [("end_turn", "stop"), ("stop_sequence", "stop"),
                      ("max_tokens", "length")]:
        fake = _FakeAnthropicClient(_FakeAnthropicResponse("x", stop_reason=raw))
        monkeypatch.setattr("anthropic.AsyncAnthropic", lambda **kw: fake)
        adapter = AnthropicAdapter(api_key="sk", base_url="", timeout=60)
        resp = await adapter.complete(
            model="claude", messages=[{"role": "user", "content": "x"}],
            temperature=0.3, max_tokens=100, response_format=None,
        )
        assert resp.finish_reason == want
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_llm_protocols.py -q 2>&1 | tail -8`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.llm.protocols'`.

- [ ] **Step 3: Implement `app/llm/protocols.py`**

Create `backend/app/llm/protocols.py`:

```python
"""协议适配层：把统一的 complete() 请求塑形成各家 SDK 的形状，再归一化响应。

两个 adapter 共享同一签名 complete(*, model, messages, temperature, max_tokens,
response_format) -> LLMResponse，使 client.complete() 可按 provider_type 无脑分发。

- OpenAIAdapter：response_format 透传（OpenAI 兼容端点支持 json_object/json_schema）。
- AnthropicAdapter：response_format 忽略（无原生 JSON 模式，靠 prompt + 上层 fenced
  代码块抽取兜底）；system 抽到顶层；max_tokens 必填故兜底 8192。
"""
from dataclasses import dataclass
from typing import Optional

from .cost import cost


@dataclass(frozen=True)
class LLMResponse:
    content: str
    model: str
    usage: dict               # {prompt_tokens, completion_tokens, total_tokens}
    finish_reason: str        # 归一化：stop | length | content_filter | refusal | ...
    cost_usd: float


class OpenAIAdapter:
    """openai.AsyncOpenAI 包装。覆盖 DeepSeek/OpenAI/GLM/通义/豆包/月之暗面等。"""

    def __init__(self, api_key: str, base_url: str, timeout: float):
        from openai import AsyncOpenAI
        kwargs = {"api_key": api_key, "timeout": timeout}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = AsyncOpenAI(**kwargs)

    async def complete(self, *, model, messages, temperature, max_tokens,
                       response_format) -> LLMResponse:
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        if response_format is not None:
            kwargs["response_format"] = response_format
        resp = await self._client.chat.completions.create(**kwargs)
        usage = {
            "prompt_tokens": resp.usage.prompt_tokens,
            "completion_tokens": resp.usage.completion_tokens,
            "total_tokens": resp.usage.total_tokens,
        }
        return LLMResponse(
            content=resp.choices[0].message.content or "",
            model=resp.model or model,
            usage=usage,
            finish_reason=resp.choices[0].finish_reason or "stop",
            cost_usd=cost(model, usage["prompt_tokens"], usage["completion_tokens"]),
        )


def _split_system(messages):
    """把 OpenAI 风格 messages 拆成 (system_str, conversation[])。

    Anthropic 要求 system 在顶层、messages 只含 user/assistant。
    管线是单轮 [system, user]，无需处理多轮交替修复。
    """
    system_parts = [m["content"] for m in messages if m.get("role") == "system"]
    conv = []
    for m in messages:
        role = m.get("role")
        if role == "system":
            continue
        conv.append({"role": "assistant" if role == "assistant" else "user",
                     "content": m["content"]})
    system = "\n\n".join(system_parts) if system_parts else None
    return system, conv


def _normalize_stop_reason(stop_reason: Optional[str]) -> str:
    """Anthropic stop_reason → 统一 finish_reason。"""
    return {
        "end_turn": "stop",
        "stop_sequence": "stop",
        "max_tokens": "length",
    }.get(stop_reason or "", stop_reason or "stop")


class AnthropicAdapter:
    """anthropic.AsyncAnthropic 包装。"""

    def __init__(self, api_key: str, base_url: str, timeout: float):
        from anthropic import AsyncAnthropic
        kwargs = {"api_key": api_key, "timeout": timeout}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = AsyncAnthropic(**kwargs)

    async def complete(self, *, model, messages, temperature, max_tokens,
                       response_format) -> LLMResponse:
        # response_format 故意忽略：Anthropic 无原生 JSON 模式。
        system, conv = _split_system(messages)
        create_kwargs = {
            "model": model,
            "messages": conv,
            "temperature": temperature,
            "max_tokens": max_tokens if max_tokens is not None else 8192,
        }
        if system is not None:
            create_kwargs["system"] = system
        resp = await self._client.messages.create(**create_kwargs)
        content = "".join(
            block.text for block in resp.content
            if getattr(block, "type", None) == "text"
        )
        usage = {
            "prompt_tokens": resp.usage.input_tokens,
            "completion_tokens": resp.usage.output_tokens,
            "total_tokens": resp.usage.input_tokens + resp.usage.output_tokens,
        }
        return LLMResponse(
            content=content,
            model=resp.model or model,
            usage=usage,
            finish_reason=_normalize_stop_reason(resp.stop_reason),
            cost_usd=cost(model, usage["prompt_tokens"], usage["completion_tokens"]),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_llm_protocols.py -q 2>&1 | tail -8`
Expected: PASS (5 tests).

- [ ] **Step 5: Run the full suite — must stay green**

Run: `cd backend && python -m pytest -q 2>&1 | tail -5`
Expected: pass count ≥ Task 3 (now +5 protocol tests). `protocols.py` is not yet wired in.

- [ ] **Step 6: Commit**

```bash
git add app/llm/protocols.py tests/test_llm_protocols.py
git commit -m "feat(llm): add OpenAI/Anthropic protocol adapters + LLMResponse"
```

---

## Task 5: `app/llm/client.py` — unified `complete()` + retry; rewire `chat_json`/`chat_structured`

This is the keystone wiring task. After it, every model call funnels through `complete()`.

**Files:**
- Create: `backend/app/llm/client.py`
- Create: `backend/tests/test_llm_client.py`
- Modify: `backend/app/llm/__init__.py` (rewrite `chat_json`/`chat_structured` to call `complete()`; re-export `complete` + `get_config`)

**Interfaces:**
- Produces:
  - `app.llm.client.complete(messages, *, model=None, temperature=None, max_tokens=None, response_format=None, timeout=None) -> LLMResponse`
  - `app.llm.client._retry_with_backoff(func, *, retry_on_json=False)` (moved from `__init__.py`)
  - `app.llm.complete` and `app.llm.get_config` (re-exported from the package for direct callers)
- Consumes: `app.llm.config.get_config`, `app.llm.protocols.{OpenAIAdapter, AnthropicAdapter, LLMResponse}`.

**Behavior change (deliberate, documented):** the old `_retry_with_backoff` retried on `JSONDecodeError` because parsing lived inside the retried closure. After this task, `complete()` retries **transient API errors only** (429 / 5xx / network / timeout); JSON parsing lives in `chat_json`, which handles malformed JSON via the existing fenced-block extraction fallback rather than re-calling the API. This removes nested retry, matches the spec ("complete() + retry"), and is covered by the OpenAI-compatible `json_object` mode (the default) plus prompt-based JSON for Anthropic.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_llm_client.py`:

```python
"""client.complete 单元测试：provider_type 分发 + 重试 + 错误翻译（mock adapter）。"""
import pytest

import app.llm.client as client_module
from app.llm.protocols import LLMResponse


def _ok_response(content='{"a":1}'):
    return LLMResponse(content=content, model="deepseek-chat",
                       usage={"prompt_tokens": 5, "completion_tokens": 7, "total_tokens": 12},
                       finish_reason="stop", cost_usd=0.01)


@pytest.mark.asyncio
async def test_complete_dispatches_to_openai_adapter_for_deepseek(monkeypatch):
    calls = []

    class FakeAdapter:
        async def complete(self, **kw):
            calls.append(kw)
            return _ok_response()

    monkeypatch.setattr(client_module, "_get_adapter", lambda cfg, timeout: FakeAdapter())
    # 绕过真实 get_config：注入一个最小配置
    from app.llm.config import LLMConfig
    fake_cfg = LLMConfig("deepseek", "openai_compatible", "sk", "https://api.deepseek.com",
                         "deepseek-chat", 0.3, None, 60.0)
    monkeypatch.setattr(client_module, "get_config", lambda: fake_cfg)

    resp = await client_module.complete(
        messages=[{"role": "user", "content": "hi"}],
        response_format={"type": "json_object"},
    )
    assert resp.content == '{"a":1}'
    assert calls[0]["model"] == "deepseek-chat"
    assert calls[0]["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_complete_retries_on_rate_limit_then_succeeds(monkeypatch):
    attempts = {"n": 0}

    class FlakyAdapter:
        async def complete(self, **kw):
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise Exception("429 Too Many Requests")  # 可重试
            return _ok_response()

    monkeypatch.setattr(client_module, "_get_adapter", lambda cfg, timeout: FlakyAdapter())
    from app.llm.config import LLMConfig
    monkeypatch.setattr(client_module, "get_config", lambda: LLMConfig(
        "deepseek", "openai_compatible", "sk", "https://api.deepseek.com",
        "deepseek-chat", 0.3, None, 60.0))
    # 加速测试：把退避延迟压到 ~0
    monkeypatch.setattr(client_module, "BASE_DELAY", 0.0)
    monkeypatch.setattr(client_module, "MAX_DELAY", 0.0)

    resp = await client_module.complete(messages=[{"role": "user", "content": "x"}])
    assert attempts["n"] == 3
    assert resp.content == '{"a":1}'


@pytest.mark.asyncio
async def test_complete_does_not_retry_on_non_retryable(monkeypatch):
    attempts = {"n": 0}

    class BadAdapter:
        async def complete(self, **kw):
            attempts["n"] += 1
            raise Exception("Invalid API key")  # 不可重试

    monkeypatch.setattr(client_module, "_get_adapter", lambda cfg, timeout: BadAdapter())
    from app.llm.config import LLMConfig
    monkeypatch.setattr(client_module, "get_config", lambda: LLMConfig(
        "deepseek", "openai_compatible", "sk", "https://api.deepseek.com",
        "deepseek-chat", 0.3, None, 60.0))

    with pytest.raises(Exception, match="Invalid API key"):
        await client_module.complete(messages=[{"role": "user", "content": "x"}])
    assert attempts["n"] == 1  # 没重试
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_llm_client.py -q 2>&1 | tail -8`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.llm.client'`.

- [ ] **Step 3: Implement `app/llm/client.py`**

Create `backend/app/llm/client.py`:

```python
"""统一 LLM 调用入口 complete()：分发到对应协议 adapter + 指数退避重试 + 错误翻译。

所有模型调用（chat_json / chat_structured / 直接调用）都从这里过。
"""
import asyncio
import logging

from ..config import MAX_RETRIES, BASE_DELAY, MAX_DELAY
from .config import get_config, LLMConfig
from .protocols import LLMResponse, OpenAIAdapter, AnthropicAdapter

logger = logging.getLogger(__name__)


def _get_adapter(cfg: LLMConfig, timeout: float):
    """按 provider_type 选 adapter。客户端不缓存（配置可热更；成本可接受）。"""
    if cfg.provider_type == "anthropic_compatible":
        return AnthropicAdapter(cfg.api_key, cfg.base_url, timeout)
    return OpenAIAdapter(cfg.api_key, cfg.base_url, timeout)


def _is_retryable(err: Exception) -> bool:
    """429 / 5xx / 网络超时 可重试；其它（鉴权、参数错误）不重试。"""
    error_str = str(err).lower()
    return any(x in error_str for x in (
        "429", "rate limit", "too many requests",
        "500", "502", "503", "504", "server error",
        "connection", "timeout", "network", "temporarily",
    ))


async def _retry_with_backoff(func, *, retry_on_json: bool = False):
    """指数退避重试。仅重试可重试错误（_is_retryable）。

    retry_on_json=True 时也重试 json.JSONDecodeError（供 chat_json 包住 parse 用）。
    """
    import json  # 局部导入，避免非 JSON 路径强依赖
    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            return await func()
        except json.JSONDecodeError as e:
            last_error = e
            if not retry_on_json or attempt >= MAX_RETRIES:
                raise
            await asyncio.sleep(0.1 * (attempt + 1))
            continue
        except Exception as e:
            last_error = e
            if not _is_retryable(e) or attempt >= MAX_RETRIES:
                raise
            delay = min(BASE_DELAY * (2 ** attempt), MAX_DELAY)
            if "429" in str(e).lower():
                delay = min(delay * 2, MAX_DELAY)
            logger.warning(f"LLM 可重试错误 (第 {attempt + 1}/{MAX_RETRIES + 1} 次): {e}，{delay:.1f}s 后重试")
            await asyncio.sleep(delay)
    raise last_error


async def complete(
    messages: list[dict],
    *,
    model: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
    response_format: dict | None = None,
    timeout: float | None = None,
) -> LLMResponse:
    """统一 LLM 调用。参数留空则用 get_config() 的默认值。重试瞬态 API 错误。"""
    cfg = get_config()
    model = model or cfg.model
    temperature = cfg.temperature if temperature is None else temperature
    timeout = timeout or cfg.timeout
    adapter = _get_adapter(cfg, timeout)

    return await _retry_with_backoff(
        lambda: adapter.complete(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
    )
```

- [ ] **Step 4: Run client test to verify it passes**

Run: `cd backend && python -m pytest tests/test_llm_client.py -q 2>&1 | tail -8`
Expected: PASS (3 tests).

- [ ] **Step 5: Rewire `chat_json` / `chat_structured` in `__init__.py`**

Replace the **entire contents** of `backend/app/llm/__init__.py` with:

```python
"""
LLM 调用包。

公共入口：
- complete():            统一底层调用（分发 OpenAI/Anthropic adapter + 重试）
- chat_json():           调 LLM 并确保返回解析后的 JSON（向后兼容旧调用）
- chat_structured():     调 LLM 返回 Pydantic 结构化对象
- get_config():          读取 LLM 配置（provider/key/base_url/model/...）

所有模型调用都过 complete()。messages 永远是 OpenAI 形态；Anthropic adapter 内部转换。
"""
import json
import logging
import time
from typing import TypeVar, Type

from .client import complete, _retry_with_backoff
from .config import get_config
from .cost import cost as calculate_llm_cost  # 向后兼容：旧代码可能 from app.llm import calculate_llm_cost
from .protocols import LLMResponse

logger = logging.getLogger(__name__)

T = TypeVar("T")


class LLMParseError(Exception):
    """LLM 输出解析错误。"""
    pass


class LLMRateLimitError(Exception):
    """LLM API 速率限制错误。"""
    pass


async def chat_json(
    system: str,
    user: str,
    temperature: float | None = None,
    response_format: dict | None = None,
    max_retries: int | None = None,
    model: str | None = None,
    max_tokens: int = 8192,
) -> dict:
    """调用 LLM 并确保返回解析后的 JSON。

    通过 complete() 发起调用（complete 内部重试瞬态 API 错误），再做 JSON 解析。
    解析失败时尝试提取 ```json 代码块兜底；仍失败抛 LLMParseError。
    max_tokens 截断（finish_reason=length）直接抛 LLMParseError（重试也救不回）。
    """
    if response_format is None:
        response_format = {"type": "json_object"}

    async def _do_call() -> dict:
        start_time = time.time()
        resp = await complete(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )
        content = resp.content
        latency_ms = int((time.time() - start_time) * 1000)

        if resp.finish_reason == "length":
            raise LLMParseError(
                f"Response truncated by max_tokens={max_tokens} "
                f"(finish_reason=length). Output length so far: {len(content)} chars. "
                f"Increase max_tokens or split the workload."
            )

        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            # 提取 ```json / ``` 代码块兜底（Anthropic 无原生 JSON 模式时尤其重要）
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            data = json.loads(content)  # 仍失败则抛 JSONDecodeError → 由外层重试/抛出

        data["_meta"] = {
            "prompt_tokens": resp.usage["prompt_tokens"],
            "completion_tokens": resp.usage["completion_tokens"],
            "total_tokens": resp.usage["total_tokens"],
            "cost_usd": resp.cost_usd,
            "latency_ms": latency_ms,
        }
        return data

    try:
        # complete() 已重试 API 错误；这里 retry_on_json=True 让坏 JSON 也触发整体重试
        return await _retry_with_backoff(_do_call, retry_on_json=True)
    except LLMParseError:
        raise
    except Exception as e:
        raise LLMParseError(f"Failed to get valid JSON response: {e}")


async def chat_structured(
    system: str,
    user: str,
    response_model: Type[T],
    temperature: float | None = None,
    model: str | None = None,
    max_tokens: int = 8192,
) -> T:
    """调用 LLM 并返回 Pydantic 结构化对象（OpenAI json_schema 模式）。"""
    async def _do_call() -> T:
        start_time = time.time()
        resp = await complete(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": response_model.__name__,
                    "strict": True,
                    "schema": response_model.model_json_schema(),
                },
            },
        )
        latency_ms = int((time.time() - start_time) * 1000)
        data = json.loads(resp.content)
        obj = response_model.model_validate(data)
        obj._meta = {
            "prompt_tokens": resp.usage["prompt_tokens"],
            "completion_tokens": resp.usage["completion_tokens"],
            "total_tokens": resp.usage["total_tokens"],
            "cost_usd": resp.cost_usd,
            "latency_ms": latency_ms,
        }
        return obj

    try:
        return await _retry_with_backoff(_do_call, retry_on_json=True)
    except Exception as e:
        raise LLMParseError(f"Failed to get structured response: {e}")


__all__ = [
    "complete", "chat_json", "chat_structured", "get_config",
    "LLMResponse", "LLMParseError", "LLMRateLimitError", "calculate_llm_cost",
]
```

- [ ] **Step 6: Run the full suite — must stay green**

Run: `cd backend && python -m pytest -q 2>&1 | tail -8`
Expected: pass count ≥ Task 4 (+3 new client tests). The `conftest.py` `mock_llm_response` fixture patches `app.llm.chat_json` — still valid because `__init__.py` re-exports it. If any test fails here, the most likely cause is a call site relying on a default that moved (e.g. `DEFAULT_TEMPERATURE`) — grep for it and reconcile.

- [ ] **Step 7: Commit**

```bash
git add app/llm/client.py app/llm/__init__.py tests/test_llm_client.py
git commit -m "feat(llm): unified complete() chokepoint; rewire chat_json/chat_structured on top"
```

---

## Task 6: Migrate main-pipeline call sites — drop thinking-model overrides

After Task 5, every `chat_json`/`chat_structured` call already routes through `complete()` and uses the configured default model. This task removes the three `model="deepseek-v4-flash"` overrides (the thinking model being eliminated) and the `POLISH_MODEL` constant. These are the **only** `model=` overrides in the async path.

**Files:**
- Modify: `backend/app/llm_pipeline/llm_highlight.py:89-96` and `:281-287`
- Modify: `backend/app/llm_pipeline/llm_product_insights.py:66-73`
- Modify: `backend/app/services/subtitle_processor.py:21` and `:134-141`

**Interfaces:** unchanged (all these are internal `chat_json` call sites; removing `model=` makes them use the configured default).

- [ ] **Step 1: `llm_highlight.py` — first highlight-extraction call**

In `backend/app/llm_pipeline/llm_highlight.py`, replace:

```python
            result = await chat_json(
                system=HIGHLIGHT_SYSTEM,
                user=user_input,
                temperature=0.3,
                response_format={"type": "json_object"},
                model="deepseek-v4-flash",  # 金句提取需要 thinking(判断价值/洞察)
                max_tokens=16384,
            )
```

with:

```python
            result = await chat_json(
                system=HIGHLIGHT_SYSTEM,
                user=user_input,
                temperature=0.3,
                response_format={"type": "json_object"},
                max_tokens=16384,
            )
```

- [ ] **Step 2: `llm_highlight.py` — chapter-ranking call**

In the same file, replace:

```python
        result = await chat_json(
            system=RANK_CHAPTERS_SYSTEM,
            user=build_rank_chapters_user(title, duration_min, outline_block, summaries_block),
            temperature=0.2,
            model="deepseek-v4-flash",  # 章节价值排序需要 thinking(判断数据点/洞察)
            max_tokens=8000,  # 94 章排序列表长,4000 不够
        )
```

with:

```python
        result = await chat_json(
            system=RANK_CHAPTERS_SYSTEM,
            user=build_rank_chapters_user(title, duration_min, outline_block, summaries_block),
            temperature=0.2,
            max_tokens=8000,  # 94 章排序列表长,4000 不够
        )
```

- [ ] **Step 3: `llm_product_insights.py` — insight-extraction call**

In `backend/app/llm_pipeline/llm_product_insights.py`, replace:

```python
        result = await chat_json(
            system=PRODUCT_INSIGHTS_SYSTEM,
            user=user_input,
            temperature=0.3,
            response_format={"type": "json_object"},
            model="deepseek-v4-flash",  # 洞察提取需要 thinking(判断产品/技术/市场价值)
            max_tokens=8192,
        )
```

with:

```python
        result = await chat_json(
            system=PRODUCT_INSIGHTS_SYSTEM,
            user=user_input,
            temperature=0.3,
            response_format={"type": "json_object"},
            max_tokens=8192,
        )
```

- [ ] **Step 4: `subtitle_processor.py` — drop `POLISH_MODEL`**

In `backend/app/services/subtitle_processor.py`:

Delete the line:

```python
POLISH_MODEL = "deepseek-chat"
```

(keep `POLISH_BATCH_SIZE` and `POLISH_MAX_TOKENS`).

Then in the `polish()` method, replace:

```python
                    result = await chat_json(
                        system=POLISH_SYSTEM,
                        user=_build_polish_user(inputs),
                        temperature=0.2,
                        model=POLISH_MODEL,
                        max_tokens=POLISH_MAX_TOKENS,
                        response_format={"type": "json_object"},
                    )
```

with:

```python
                    result = await chat_json(
                        system=POLISH_SYSTEM,
                        user=_build_polish_user(inputs),
                        temperature=0.2,
                        max_tokens=POLISH_MAX_TOKENS,
                        response_format={"type": "json_object"},
                    )
```

- [ ] **Step 5: Verify the async path is clean of removed literals**

Run:
```bash
cd backend && grep -rn --include="*.py" -e "deepseek-v4-flash" -e "POLISH_MODEL" app || echo "CLEAN: no matches"
```
Expected: `CLEAN: no matches`.

- [ ] **Step 6: Run the targeted + full suite**

Run: `cd backend && python -m pytest tests/test_llm_highlight.py tests/test_llm_product_insights.py tests/test_subtitle_processor.py -q 2>&1 | tail -8`
Expected: PASS.

Run: `cd backend && python -m pytest -q 2>&1 | tail -5`
Expected: full suite green.

- [ ] **Step 7: Commit**

```bash
git add app/llm_pipeline/llm_highlight.py app/llm_pipeline/llm_product_insights.py app/services/subtitle_processor.py
git commit -m "refactor(llm): drop deepseek-v4-flash thinking-model overrides + POLISH_MODEL"
```

---

## Task 7: Migrate the sync `LLMSubtitleProcessor` + its router/admin callers to `complete()`

`app/services/llm_subtitle_processor.py` builds its own **sync** `OpenAI(api_key=…)` client and is instantiated in 4 places with `os.getenv("DEEPSEEK_API_KEY")`. Per the spec ("all modules calling API models funnel through"), route its 5 `self.client.chat.completions.create(model="deepseek-chat", …)` calls through the unified async `complete()`. The methods are already `async def`, so this also removes event-loop blocking (a latent improvement). The 4 callers stop reading `DEEPSEEK_API_KEY` / passing `api_key=`.

**Files:**
- Modify: `backend/app/services/llm_subtitle_processor.py` (drop sync client + `__init__` key plumbing; route 5 calls through `complete()`)
- Modify: `backend/app/routers/subtitles.py:231-238`, `:313-319`, `:371-378` (drop `api_key` read + guard; construct `LLMSubtitleProcessor()`)
- Modify: `backend/app/routers/admin.py:80-93` (same)
- Test: `backend/tests/test_subtitle_sync_api.py` and `tests/test_admin_api.py` (existing) — fix mocks if they break

**Interfaces:**
- Consumes: `app.llm.complete`
- Produces: `LLMSubtitleProcessor()` constructable with no args (backward-compatible: keep `api_key`/`base_url` params but ignore them, so callers don't all need changing in lockstep — though this task changes them anyway).

- [ ] **Step 1: Read the current 5 call sites to capture exact shapes**

Run:
```bash
cd backend && sed -n '40,70p;115,145p;265,285p;385,400p;455,475p;565,585p' app/services/llm_subtitle_processor.py
```
Confirm each of the 5 calls is `response = self.client.chat.completions.create(model="deepseek-chat", messages=<list>, temperature=<num>, [max_tokens=<num>,] [response_format=<dict>])` followed by `content = response.choices[0].message.content`. Record any site that reads extra fields (e.g. `response.usage`) — those become `resp.usage` from `LLMResponse`.

- [ ] **Step 2: Rewrite the class header + `__init__`**

In `backend/app/services/llm_subtitle_processor.py`, replace:

```python
from openai import OpenAI
from app.utils import clean_llm_text
```

with:

```python
from app.utils import clean_llm_text
from ..llm import complete
```

Then replace the `__init__`:

```python
    def __init__(self, api_key: str, base_url: str = "https://api.deepseek.com/v1"):
        """初始化 LLM 客户端

        Args:
            api_key: DeepSeek API key
            base_url: API 基础 URL
        """
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url,
        )
```

with:

```python
    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        """初始化。api_key/base_url 保留参数仅为向后兼容，实际配置走 app.llm.get_config()。"""
        # 不再自建客户端：所有调用经 app.llm.complete() 统一分发。
```

- [ ] **Step 3: Rewrite each of the 5 call sites**

For each `self.client.chat.completions.create(...)` block, replace the SDK call + content extraction with a `complete()` call. The generic transformation (apply to all 5 sites — adjust the kept kwargs to match each site):

**Before (shape):**
```python
            response = self.client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                temperature=0.3,
                # 可能有: max_tokens=..., response_format=...
            )
            content = response.choices[0].message.content
```

**After (shape):**
```python
            resp = await complete(
                messages=messages,
                temperature=0.3,
                # 保留原 max_tokens=... / response_format=...（若有）
                # model= 删除：用 get_config() 配置的默认模型
            )
            content = resp.content
```

Apply to all 5 sites (lines ~123-124, ~271-272, ~391-392, ~459-460, ~570-571). Remove the `model="deepseek-chat",` line in each. Keep every other kwarg (`messages`, `temperature`, `max_tokens`, `response_format`) exactly as-is. The enclosing methods are already `async def`, so `await complete(...)` is valid.

If any site reads `response.usage` afterward, replace `response.usage.prompt_tokens` → `resp.usage["prompt_tokens"]` (and likewise `completion_tokens`/`total_tokens`).

- [ ] **Step 4: Update the 3 router callers in `subtitles.py`**

In `backend/app/routers/subtitles.py`, at each of the three sites (around lines 233-238, 315-319, 374-378), replace:

```python
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise HTTPException(status_code=500, detail="DEEPSEEK_API_KEY 未配置")

        processor = LLMSubtitleProcessor(api_key=api_key)
```

with:

```python
        processor = LLMSubtitleProcessor()
```

- [ ] **Step 5: Update the `admin.py` caller**

In `backend/app/routers/admin.py`, replace:

```python
    api_key = os.getenv("DEEPSEEK_API_KEY")
    use_llm = api_key is not None
    llm_processor = None
    segmenter = None

    if use_llm:
        try:
            from ..services.llm_subtitle_processor import LLMSubtitleProcessor
            llm_processor = LLMSubtitleProcessor(api_key=api_key)
            logger.info(f"Batch sync: using LLM segmentation")
        except Exception as e:
            logger.warning(f"Batch sync: LLM initialization failed, using rule-based: {e}")
            use_llm = False
```

with:

```python
    llm_processor = None
    segmenter = None
    use_llm = True

    try:
        from ..services.llm_subtitle_processor import LLMSubtitleProcessor
        llm_processor = LLMSubtitleProcessor()
        logger.info("Batch sync: using LLM segmentation")
    except Exception as e:
        logger.warning(f"Batch sync: LLM initialization failed, using rule-based: {e}")
        use_llm = False
```

(The key presence is now validated inside `complete()`/`get_config()` at call time, not at construction. If no key is configured, the LLM call raises and the existing per-episode try/except degrades gracefully.)

- [ ] **Step 6: Verify the sync subsystem is clean**

Run:
```bash
cd backend && grep -rn --include="*.py" -e "DEEPSEEK_API_KEY" app/routers app/services/llm_subtitle_processor.py || echo "CLEAN: no DEEPSEEK_API_KEY in routers/llm_subtitle_processor"
```
Expected: `CLEAN`.

Run:
```bash
cd backend && grep -n 'from openai import\|self.client\|"deepseek-chat"' app/services/llm_subtitle_processor.py || echo "CLEAN: sync client + literal removed"
```
Expected: `CLEAN`.

- [ ] **Step 7: Run targeted tests, fix mocks if broken**

Run: `cd backend && python -m pytest tests/test_subtitle_sync_api.py tests/test_admin_api.py -q 2>&1 | tail -15`
Expected: PASS. If a test fails because it patched the old sync `OpenAI` client or `LLMSubtitleProcessor.client`, update that test to patch `app.llm.complete` (or `app.services.llm_subtitle_processor.complete`) instead. Keep the assertion intent (the test should still verify the endpoint returns the expected shape); only change the mock target.

- [ ] **Step 8: Run the full suite**

Run: `cd backend && python -m pytest -q 2>&1 | tail -5`
Expected: full suite green.

- [ ] **Step 9: Commit**

```bash
git add app/services/llm_subtitle_processor.py app/routers/subtitles.py app/routers/admin.py tests/
git commit -m "refactor(llm): route sync LLMSubtitleProcessor + routers through complete()"
```

---

## Task 8: Cleanup + config/env/requirements + acceptance verification

**Files:**
- Modify: `backend/app/config.py` (DEEPSEEK_* → LLM_* alias plumbing; drop the deepseek cost table + `calculate_llm_cost`)
- Modify: `backend/app/llm_pipeline/legacy.py:18` (drop unused `DEEPSEEK_MODEL` import)
- Modify: `backend/app/models.py:436` (neutralize field description)
- Modify: `backend/.env.example` (add `LLM_*`; mark `DEEPSEEK_*` legacy)
- Modify: `backend/requirements.txt` (+ `anthropic`)
- Test: the acceptance grep + full suite

- [ ] **Step 1: `legacy.py` — drop unused import**

In `backend/app/llm_pipeline/legacy.py`, delete the line:

```python
from ..config import DEEPSEEK_MODEL
```

(`DEEPSEEK_MODEL` is imported but never referenced in this file's body — verify with `grep DEEPSEEK_MODEL app/llm_pipeline/legacy.py` returning only the import line before deleting.)

- [ ] **Step 2: `models.py` — neutralize field description**

In `backend/app/models.py` around line 436, the field:

```python
    model: str = Field(..., description="deepseek-chat")
```

change to:

```python
    model: str = Field(..., description="configured LLM model id")
```

- [ ] **Step 3: `config.py` — DEEPSEEK_* alias plumbing + drop deepseek cost table**

This is the largest edit. In `backend/app/config.py`:

**(a)** Replace the DeepSeek API section (the block starting `# ==================== DeepSeek API ====================` through `self.deepseek_model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")`) with LLM_* alias plumbing:

```python
        # ==================== LLM API ====================
        # 统一多 provider 配置。LLM_* 为正式变量；DEEPSEEK_* 为向后兼容别名
        # （单用户自托管，不复用 key）。实际读取/校验/SSRF 守卫在 app/llm/config.py:get_config()。
        # 这里仅保留旧 Settings 字段供历史代码引用 + 别名映射。
        self.llm_provider = os.getenv("LLM_PROVIDER", "deepseek")
        self.llm_provider_type = os.getenv("LLM_PROVIDER_TYPE", "")
        # API key / base_url / model：LLM_* 优先，回退 DEEPSEEK_* 别名
        self.deepseek_api_key = os.getenv("LLM_API_KEY") or os.getenv("DEEPSEEK_API_KEY", "")
        self.deepseek_base_url = (
            os.getenv("LLM_BASE_URL") or os.getenv("DEEPSEEK_BASE_URL", "")
        )
        self.deepseek_model = os.getenv("LLM_MODEL") or os.getenv("DEEPSEEK_MODEL", "")
```

**(b)** Delete the deepseek cost table block:

```python
        # ==================== 成本配置（元 per 1M tokens） ====================
        self.llm_cost_per_token = {
            "deepseek-chat": {"input": 0.00014, "output": 0.00028},
            "deepseek-reasoner": {"input": 0.00055, "output": 0.00219},
        }
```

(Pricing now lives in `app/llm/cost.py::COST_PER_1M_TOKENS`.)

**(c)** Delete the `calculate_llm_cost` function (lines ~194-208) entirely — it's superseded by `app.llm.cost.cost`. Before deleting, confirm no live importer remains:

```bash
cd backend && grep -rn --include="*.py" "calculate_llm_cost" app tests
```
Expected: only matches inside `app/llm/__init__.py` (the `from .cost import cost as calculate_llm_cost` alias) and possibly its own definition. If anything in `app/config.py`'s callers still imports it from `..config`, that import was already re-routed in Task 2 Step 5. Delete the function body in `config.py`.

**(d)** Update `validate_config()` — replace the deepseek-key check:

```python
    if not settings.deepseek_api_key or settings.deepseek_api_key == "sk-your-api-key-here":
        errors.append("DEEPSEEK_API_KEY must be set")
```

with a provider-agnostic check that calls the unified validator:

```python
    from .llm.config import get_config
    try:
        get_config()
    except ValueError as e:
        errors.append(f"LLM config invalid: {e}")
```

- [ ] **Step 4: Confirm `config.py` only references DEEPSEEK_* in alias reads**

Run:
```bash
cd backend && grep -n --include="*.py" -e "deepseek-chat" -e "deepseek-v4-flash" app/config.py
```
Expected: no matches (the literal default `"deepseek-chat"` moved to `app/llm/config.py::PROVIDERS` in Task 3).

Run:
```bash
cd backend && grep -n "DEEPSEEK_API_KEY\|DEEPSEEK_MODEL\|DEEPSEEK_BASE_URL" app/config.py
```
Expected: only lines inside the alias-plumbing block from Step 3(a) (the `os.getenv("DEEPSEEK_…")` reads) and the backward-compat exports at the bottom (`DEEPSEEK_API_KEY = settings.deepseek_api_key` etc.). These ARE the allowed "config alias" lines per acceptance criterion #3.

- [ ] **Step 5: `.env.example` — add LLM_*, mark DEEPSEEK_* legacy**

In `backend/.env.example`, replace the LLM block (lines 13-19) with:

```bash
# ---- LLM（必填）----
# 支持多 provider，仅 2 种协议：openai_compatible / anthropic_compatible
# provider 预设见 app/llm/config.py:PROVIDERS（deepseek/openai/anthropic/glm/qwen/doubao/moonshot）
# 正式变量用 LLM_*；DEEPSEEK_* 为向后兼容别名（二选一即可，LLM_* 优先）

# provider 预设名（决定默认 base_url / model / 协议推断）
LLM_PROVIDER=deepseek
# 显式覆盖协议（留空则按 LLM_PROVIDER 推断）：openai_compatible | anthropic_compatible
# LLM_PROVIDER_TYPE=

# API Key（必填）
LLM_API_KEY=
# 端点；留空则用 provider 预设或 SDK 官方默认
# LLM_BASE_URL=https://api.deepseek.com
# 模型名
LLM_MODEL=deepseek-chat

# ---- DEEPSEEK_* 旧变量（向后兼容别名，可继续用；与 LLM_* 同时存在时 LLM_* 优先）----
# DEEPSEEK_API_KEY=
# DEEPSEEK_BASE_URL=https://api.deepseek.com
# DEEPSEEK_MODEL=deepseek-chat
```

- [ ] **Step 6: `requirements.txt` — add anthropic**

In `backend/requirements.txt`, replace:

```text
# LLM
openai==1.51.0
```

with:

```text
# LLM
openai==1.51.0
anthropic==0.39.0
```

Then install it:

```bash
cd backend && pip install "anthropic==0.39.0"
```

(Pin rationale: a stable recent release of the `anthropic` SDK with `AsyncAnthropic` + `messages.create`. If `pip` resolves to a different compatible version, pin whatever installs and note it.)

- [ ] **Step 7: Run the full suite**

Run: `cd backend && python -m pytest -q 2>&1 | tail -8`
Expected: all tests green, count ≥ the original 369 + new tests from Tasks 2–5 (≈ +22).

- [ ] **Step 8: Acceptance grep — the hard bar**

Run:
```bash
cd backend && grep -rn --include="*.py" -e "deepseek-v4-flash" -e "deepseek-chat" -e "DEEPSEEK_API_KEY" app
```
Expected output (and ONLY this):
- `app/config.py` — the alias-plumbing lines (`os.getenv("DEEPSEEK_API_KEY")`, `DEEPSEEK_API_KEY = settings.deepseek_api_key`) — **allowed** (config alias).
- `app/llm/config.py` — the `PROVIDERS["deepseek"]` entry (`"default_model": "deepseek-chat"`, `"default_base_url": "https://api.deepseek.com"`) — **allowed** (provider registry).

If any OTHER file appears, return to the matching task and remove the literal. Do not "allow-list" further files.

- [ ] **Step 9: Smoke import check (catches wiring breakage the grep can't)**

Run:
```bash
cd backend && python -c "from app.llm import complete, chat_json, chat_structured, get_config, LLMParseError; from app.llm.cost import cost; from app.llm.protocols import OpenAIAdapter, AnthropicAdapter; print('imports OK')"
```
Expected: `imports OK`.

- [ ] **Step 10: Commit**

```bash
git add app/config.py app/llm_pipeline/legacy.py app/models.py .env.example requirements.txt
git commit -m "refactor(llm): DEEPSEEK_* alias plumbing in config; add anthropic dep; neutralize literals"
```

---

## Acceptance Criteria (from spec §12)

- [ ] **(1) Anthropic end-to-end:** with `LLM_PROVIDER=anthropic`, `LLM_API_KEY=<claude key>`, `LLM_MODEL=claude-3-5-sonnet-latest`, a full episode processes and `highlight.json` / `product_insights.json` contain valid JSON. *(Manual smoke — requires a real key + an episode; run after the suite is green.)*
- [ ] **(2) DEEPSEEK_* backward compat:** with only `DEEPSEEK_API_KEY`/`DEEPSEEK_MODEL` set (no `LLM_*`), the full suite passes and `get_config()` resolves to the deepseek provider. *(Covered by Task 3 test `test_deepseek_legacy_alias_works` + full suite.)*
- [ ] **(3) Grep clean:** Task 8 Step 8 passes.
- [ ] **(4) Tests:** full suite green (≥ 369 + new).
- [ ] **(5) Anthropic JSON validity:** Anthropic-adapter responses parse as JSON via the fenced-block fallback. *(Covered by Task 4 `test_anthropic_adapter_*` + Task 5 `chat_json` extraction logic.)*
