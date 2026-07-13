# LLM 多 Provider 适配层设计

- **日期**: 2026-07-13
- **状态**: 已批准（待实施）
- **参考项目**: [joeseesun/qmreader](https://github.com/joeseesun/qmreader)（`lib/deepseek.js`）
- **分支**: `refactor/lang-naming`

## 1. 背景与动机

当前后端的 LLM 调用层**硬绑定 DeepSeek**：

- `app/llm.py:_get_client()` 返回 `openai.OpenAI` 客户端，base_url/key 写死 DeepSeek。
- 模型字面量散落各处：`deepseek-v4-flash`（推理层）在 `llm_pipeline/llm_highlight.py`、`llm_pipeline/llm_product_insights.py`；`deepseek-chat`（快层）在 `services/subtitle_processor.py`（5 处）及 `llm.py` 默认值。
- `config.py` 只认 `DEEPSEEK_*` 环境变量；`validate_config()` 强制要求 `DEEPSEEK_API_KEY`。
- 成本表只识别两个 DeepSeek 模型。

结果：要换 provider（OpenAI / Claude / GLM / 通义 / 豆包 / 月之暗面）必须改代码。本设计把这层抽象成**协议无关、配置驱动**的统一适配层。

## 2. 目标 / 非目标

**目标**

1. 通过 `.env` 切换 provider，零代码改动。
2. 支持 2 种 API 协议：**OpenAI 兼容**（覆盖 DeepSeek / OpenAI / GLM / 通义 / 豆包 / 月之暗面 / OpenRouter / Ollama 等）与 **Anthropic 兼容**（Claude）。
3. 所有 LLM 调用收敛到**单一统一入口**，删除散落的模型字面量与直连 SDK 的代码。
4. 成本追踪泛化，未知模型不静默失败。
5. 平滑迁移：保留 `DEEPSEEK_*` 旧环境变量名作为兼容别名。

**非目标（明确不做）**

- **Gemini 原生协议** —— 跟随 qmreader 只做 2 种协议；Gemini 用户走 OpenAI 兼容网关。
- **thinking / 推理模型双层路由** —— 整体移除，一个模型走全部任务（见 §6）。
- **BYOK（按请求注入客户端 key）** —— 单用户自托管，provider 在 `.env` 一次性配；qmreader 的 `request-ai-config.js` 那层不移植。
- **流式输出** —— 现有调用全是非流式批量 JSON，不引入。

## 3. 架构

镜像 qmreader 的精髓：**`provider`（具名预设）与 `providerType`（协议）分离**，所有调用收敛到一个统一入口。

```
app/llm/
├── __init__.py     # 公开 API: complete(), get_config()
├── config.py       # get_config() + PROVIDERS 注册表 + infer_provider_type() + 基础 SSRF 防护
├── client.py       # 统一 complete() 分发 + 重试 + 错误翻译
├── protocols.py    # OpenAIAdapter(openai SDK) + AnthropicAdapter(anthropic SDK)
└── cost.py         # 价格表 + 成本计算
```

`app/llm.py`（旧单文件）→ `app/llm/`（新包）。所有调用点改为 `from app.llm import complete`。

### 统一入口契约

```python
# app/llm/__init__.py
from .client import complete
from .config import get_config

@dataclass
class LLMResponse:
    content: str
    model: str
    usage: dict            # {"prompt_tokens": int, "completion_tokens": int}（若返回则含 reasoning_tokens）
    finish_reason: str     # 归一化: "stop" | "length" | "content_filter" | "refusal" | ...
    cost_usd: float        # 由价格表算出；未知模型为 0.0 并告警

def complete(
    messages: list[dict[str, str]],   # OpenAI 形状: [{"role": "system|user|assistant", "content": "..."}]
    *,
    model: str | None = None,         # 覆盖；默认取 config.LLM_MODEL
    temperature: float | None = None,
    max_tokens: int | None = None,
    response_format: dict | None = None,   # {"type": "json_object"}
    timeout: float | None = None,
) -> LLMResponse: ...
```

调用方永远感知不到下面是哪个协议 / 哪个 SDK。`messages` 始终是 OpenAI 形状，Anthropic 适配器在内部转换。

## 4. 协议适配器（官方 SDK）

**选型理由（稳定 + 兼容优先）**：DeepSeek / GLM / 通义 / 豆包 / 月之暗面 / OpenRouter 官方文档均明确推荐"用 openai SDK + base_url"；Anthropic 官方推荐 anthropic SDK。官方 SDK 处理 base_url+path、超时、重试、类型与边界情况，比手写 HTTP 维护成本低。

### OpenAIAdapter（openai SDK）

```python
client = openai.OpenAI(api_key=cfg.api_key, base_url=cfg.base_url)
resp = client.chat.completions.create(
    model=cfg.model, messages=messages, temperature=..., max_tokens=...,
    response_format=...,   # 透传
)
# content = resp.choices[0].message.content
# finish_reason = resp.choices[0].finish_reason
# usage = {"prompt_tokens": resp.usage.prompt_tokens, "completion_tokens": resp.usage.completion_tokens}
```

覆盖全部 OpenAI 兼容 provider —— 只换 `base_url` / `api_key` / `model`。

### AnthropicAdapter（anthropic SDK）

镜像 qmreader 的 `anthropicPayload()` 转换逻辑：

```python
client = anthropic.Anthropic(api_key=cfg.api_key, base_url=cfg.base_url)
# 1. 抽取 system: 把 messages 里 role=="system" 的 content 合并成顶层 system 参数
# 2. role 映射: 其余消息 role 限定为 "user" | "assistant"
resp = client.messages.create(
    model=cfg.model, system=system_text or OMIT,
    messages=chat_messages, max_tokens=..., temperature=...,  # max_tokens 必填
)
# content = "".join(block.text for block in resp.content if block.type == "text")
# finish_reason: resp.stop_reason 归一化 ("end_turn"/"stop_sequence" → "stop")
# usage: {"prompt_tokens": resp.usage.input_tokens, "completion_tokens": resp.usage.output_tokens}
```

> Anthropic 的 `max_tokens` 是必填项，适配器从 config 默认值兜底。

**`response_format` 跨协议处理**：OpenAI 适配器原样透传 `response_format={"type":"json_object"}`（DeepSeek / GLM 等兼容）；Anthropic 无原生 JSON 模式，**忽略 `response_format`**，JSON 输出靠 prompt 指令 + 现有的 JSON 兜底解析（`parseJsonResponse` 逻辑已存在，不依赖模式）。

## 5. 配置

### 环境变量（新）

```env
LLM_PROVIDER=deepseek                       # 具名预设: 只为默认值 + UI 标题
LLM_PROVIDER_TYPE=openai_compatible         # 协议: openai_compatible | anthropic_compatible
LLM_API_KEY=sk-...
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
LLM_TEMPERATURE=0.7                         # 可选
LLM_MAX_TOKENS=4096                         # 可选
LLM_TIMEOUT=60                              # 可选，秒
```

### 兼容别名（旧名映射，平滑迁移）

`DEEPSEEK_*` 仍可用，当 `LLM_*` 未设置时映射：

| 旧名 | 映射 |
|---|---|
| `DEEPSEEK_API_KEY` | `LLM_API_KEY`（且 provider=deepseek, provider_type=openai_compatible） |
| `DEEPSEEK_BASE_URL` | `LLM_BASE_URL` |
| `DEEPSEEK_MODEL` | `LLM_MODEL` |

`validate_config()` 接受 `LLM_API_KEY` **或** `DEEPSEEK_API_KEY`（二选一即可）。

### PROVIDERS 注册表

```python
PROVIDERS = {
    "deepseek":            {"title": "DeepSeek",         "provider_type": "openai_compatible",    "default_base_url": "https://api.deepseek.com/v1",          "default_model": "deepseek-chat"},
    "openai":              {"title": "OpenAI",           "provider_type": "openai_compatible",    "default_base_url": "https://api.openai.com/v1",            "default_model": "gpt-4o-mini"},
    "anthropic":           {"title": "Anthropic Claude", "provider_type": "anthropic_compatible", "default_base_url": "https://api.anthropic.com",            "default_model": "claude-sonnet-4-6"},
    "glm":                 {"title": "智谱 GLM",         "provider_type": "openai_compatible",    "default_base_url": "https://open.bigmodel.cn/api/paas/v4", "default_model": "glm-4-flash"},
    "qwen":                {"title": "通义千问",         "provider_type": "openai_compatible",    "default_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "default_model": "qwen-plus"},
    "doubao":              {"title": "豆包",             "provider_type": "openai_compatible",    "default_base_url": "https://ark.cn-beijing.volces.com/api/v3", "default_model": "doubao-pro-32k"},
    "moonshot":            {"title": "月之暗面 Kimi",    "provider_type": "openai_compatible",    "default_base_url": "https://api.moonshot.cn/v1",            "default_model": "moonshot-v1-8k"},
    "openai-compatible":   {"title": "OpenAI 兼容",      "provider_type": "openai_compatible",    "default_base_url": "", "default_model": ""},
    "anthropic-compatible":{"title": "Claude 兼容",      "provider_type": "anthropic_compatible", "default_base_url": "", "default_model": ""},
}
```

> 各 provider 的 `default_base_url` / `default_model` 在实施时按厂商当前文档核对；用户可随时用 `LLM_BASE_URL` / `LLM_MODEL` 覆盖。

### 协议自动推断

`infer_provider_type()`：若显式 `LLM_PROVIDER_TYPE` 未设，依据 `provider` + `model` 名推断（model 含 `claude` 且 provider 是 anthropic 系列 → `anthropic_compatible`，否则 `openai_compatible`）。

### SSRF 防护

`assert_public_https_base_url()`：base_url 必须 https，拒绝 localhost / `127.*` / `10.*` / `192.168.*` / `172.16-31.*` / `169.254.*` / `::1` / `.local`。单用户自托管下风险低，但 10 行的基础防护避免误配。

## 6. thinking 模式：整体移除

- 删除 `LLM_THINKING_MODEL`、`reasoning_content` 解析、思考模型的 `max_tokens` 预算特殊处理、`deepseek-v4-flash` 字面量。
- **一个 `LLM_MODEL` 走全部任务**（highlights / insights / translate / polish / segment / summary 一视同仁），与 qmreader 哲学一致。
- 已知代价：highlights / insights 少一层推理深度（用户已确认可接受）。未来若要加回，属纯增量改动。

## 7. 成本追踪

- `complete()` 返回的 `LLMResponse.cost_usd` 由 `cost.py` 按 model 查价格表算出。
- 价格表结构：`COST_PER_1M_TOKENS = {model: {"input": float, "output": float}}`（USD / 百万 token）。可扩展。
- **未知模型 → cost = 0.0 + 告警日志**（不静默失败）。
- 沿用现有 `_meta.cost_usd` → episode 预算闸（`cost_log` 求和 vs `max_llm_cost_usd`）。

## 8. 错误处理

移植 qmreader 的类型化错误语义：

- **finish_reason 翻译**：`length` / `max_tokens` / `content_filter` / `refusal` / `tool_calls` / `model_context_window_exceeded` → 可读中文消息 + `retryable` 标志（`insufficient_system_resource` / `pause_turn` 可重试）。
- **重试**：2 次，指数退避 + `retry-after`；仅对 `retryable=True`（超时 / 429 / 5xx / 资源不足）重试。
- **错误类型**：`LLMRateLimitError` / `LLMAuthError` / `LLMContextLengthError` / `LLMProviderError`，向上抛出可读消息。

## 9. 迁移

| 文件 | 改动 |
|---|---|
| `app/llm.py` | 拆成 `app/llm/` 包；删除 `_get_client()` 直连用法 |
| `app/llm_pipeline/llm_highlight.py` | 调用 `complete()`，删 `deepseek-v4-flash` 字面量、删 `reasoning_content` 处理 |
| `app/llm_pipeline/llm_product_insights.py` | 同上 |
| `app/llm_pipeline/llm_translate.py` | 调用 `complete()` |
| `app/llm_pipeline/llm_split.py` | 调用 `complete()` |
| `app/llm_pipeline/llm_summary.py` | 调用 `complete()` |
| `app/services/subtitle_processor.py` | `LLMSubtitleProcessor` 改用 `complete()`，删 5 处 `deepseek-chat` 字面量 |
| `app/config.py` | 加 `LLM_*`；保留 `DEEPSEEK_*` 别名映射；`validate_config()` 放宽 |
| `backend/.env.example` | 文档化 `LLM_*` + 多 provider 示例 |
| `backend/requirements.txt` | 加 `anthropic` |

实施时先全量 grep 确认所有 LLM 调用点，确保无遗漏。

## 10. 测试策略

TDD 推进。新增（mock SDK，不触网）：

- `tests/llm/test_config.py` —— 配置解析、`DEEPSEEK_*` 别名映射、provider_type 推断、SSRF 防护、缺 key 报错。
- `tests/llm/test_protocols.py` —— OpenAI 适配器 response 映射；Anthropic 适配器 system 抽取 + role 映射 + `stop_reason` 归一化（均 mock SDK）。
- `tests/llm/test_client.py` —— `complete()` 分发、限流重试、finish_reason 错误翻译、cost 附加。
- `tests/llm/test_cost.py` —— 成本计算、未知模型告警。

现有 **369 个测试**是回归安全网（重点验证 highlights / translate / subtitle_processor 改调用后行为不变）。

## 11. 验收标准

1. `.env` 仅设 `LLM_PROVIDER=openai`（或 anthropic）+ key，全流程跑通一集（至少到 highlights）。
2. `.env` 仍用 `DEEPSEEK_*` 旧名，行为与重构前一致（向后兼容）。
3. `grep -rn "deepseek-v4-flash\|deepseek-chat\|DEEPSEEK_API_KEY" backend/app --include=*.py` 仅剩 config 别名映射处。
4. 全量测试 ≥ 369 通过，新增 llm 测试全绿。
5. 切换到 Anthropic 时，highlights 返回有效 JSON（验证 system 抽取 + role 映射正确）。

## 12. 未决问题

无。所有范围决策已确认：2 种协议 / 官方 SDK / 移除 thinking / 不做 BYOK / 不做 Gemini。
