# 设计:设置页 base_url 锁定下拉 + 模型自动拉取

- **日期**: 2026-07-15
- **状态**: 已批准(用户「通过,写吧」)
- **范围**: 前后端——在已有 `/settings` 页面上,把 base_url 变成「按 provider 锁定的下拉」,把 model 变成「填前三项后自动拉取的下拉」
- **承接**: [2026-07-15-llm-settings-page-design.md](./2026-07-15-llm-settings-page-design.md)(基础设置页已上线)

---

## 1. 背景与问题

上一版设置页的 base_url 与 model 都是**自由文本框**:
- base_url 用户容易填错(多一个斜杠、漏 `/v1`、写成文档地址而非 API 地址)。
- model 名要用户自己去查文档手敲,且会过时(如 DeepSeek `deepseek-reasoner` 官方公告 2026/07/24 下线)。
- 用户原话:「api url 链接可以根据 provider 锁定列表,让用户下拉选择,应该只有 coding plan 的 url 链接是特别的,但是常规 url 应该是固定的,模型可以用户填写前三项后,自动拉取,用户选择。」

**调研结论(已联网核对官方文档 + 本地代码)**:

| provider | 固定 base_url(下拉可选项) | 列模型 API |
|---|---|---|
| deepseek | `https://api.deepseek.com` | `GET /models`(OpenAI 兼容) |
| **glm** | `https://open.bigmodel.cn/api/paas/v4`(标准)<br>`https://open.bigmodel.cn/api/coding/paas/v4`(**编码套件/Coding**) | `GET /models`(OpenAI 兼容) |
| moonshot | `https://api.moonshot.cn/v1`(国内)<br>`https://api.moonshot.ai/v1`(海外) | `GET /v1/models`(OpenAI 兼容) |
| qwen | `https://dashscope.aliyuncs.com/compatible-mode/v1` | OpenAI 兼容 |
| doubao | `https://ark.cn-beijing.volces.com/api/v3` | ark `/models` 列的是基础模型,**可用模型实为控制台 endpoint id**,列表对不上 |
| openai | `https://api.openai.com/v1` | `GET /v1/models` |
| anthropic | `https://api.anthropic.com` | `GET /v1/models` |
| openai-compatible / anthropic-compatible | (无固定地址,自由输入) | 视端点而定,失败兜底自由输入 |

**关键发现**:
- 三家目标 provider(DeepSeek / GLM / Moonshot)全是 OpenAI 兼容、都支持列模型。
- **只有 GLM 有「标准 / 编码套件」两个端点**——这正是用户说的「特别的 coding plan 链接」。其余常规地址固定不变。
- 本地 `OpenAIAdapter` / `AnthropicAdapter` 是 SDK 包装(`openai.AsyncOpenAI` / `anthropic.AsyncAnthropic`),**自带 `.models.list()`**,命中 `{base_url}/models`,所以「服务端拉模型列表」几乎零成本。
- 已有基建可直接复用:`_get_adapter(cfg, timeout)`、`_humanize_llm_error()`、SSRF 守卫 `_assert_public_https_base_url`、admin 鉴权、`fetchWithTimeout`(自动带 X-Admin-Token)、后端错误信封统一包成 `{"message": ...}`(前端读 `err.message`)。

## 2. 目标 / 非目标

**目标**
1. base_url 按 provider 锁定为下拉:常规 provider 单一固定(只读锁定);GLM 可选标准 / 编码套件;Moonshot 可选国内 / 海外;两个 compatible 类型仍自由输入。
2. 填齐 provider + api_key + base_url 三项后,**自动拉取**模型列表填入下拉,用户选择;拉取失败可手动输入兜底。
3. key 不出服务端:模型拉取在后端完成(复用 adapter),前端只拿模型 id 列表。
4. 沿用现有视觉与代码风格,不改设计系统。

**非目标(YAGNI)**
- 不在前端直连 provider(会被 CORS 拦且暴露 key)——明确否决。
- 不把模型名写死进预设(会过时)——明确否决;`default_model` 仅作拉取前/失败时的回退默认。
- 不做模型搜索 / 收藏 / 别名。
- 不改运行时覆写与跨进程机制(上一版已就绪)。

## 3. 架构总览

```
SettingsView.vue
  ├─ provider 下拉  ──▶ 切换时刷新 base_url 下拉选项(来自 PROVIDERS.base_urls)
  ├─ base_url 下拉  ──▶ compatible 类型时退化为自由输入框
  └─ provider+key+base_url 齐全 ──(防抖 500ms / 手动「↻ 拉取」)──▶ POST /api/admin/llm-config/models
                                                                     │  routers/llm_config.py (verify_admin)
                                                                     │  SSRF 校验 base_url
                                                                     ▼
                                                       client.py::list_models(cfg)
                                                       └─ _get_adapter(cfg) → adapter.models.list()
                                                                     │
                                                          ◀── { models: ["deepseek-chat", ...] }
                                                          失败 → 内联提示 + 切「手动输入」兜底
```

**安全模型不变**:写端点与模型拉取端点都 `verify_admin`;key 不落响应、不打日志;base_url 过 SSRF 守卫。

## 4. 后端改动

### 4.1 锁定列表 — `app/llm/config.py` PROVIDERS

给每个 PROVIDERS 条目新增 `base_urls: list[str]`(固定下拉列表),保留 `default_base_url`(取 `base_urls[0]`,向后兼容现有 `_resolve_config` / 路由)。

```python
"deepseek": {
    "title": "DeepSeek",
    "provider_type": "openai_compatible",
    "default_base_url": "https://api.deepseek.com",
    "base_urls": ["https://api.deepseek.com"],
    "default_model": "deepseek-chat",
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
# openai / anthropic:把原 SDK 默认值显式写进 base_urls(单一固定)
"openai":    {..., "base_urls": ["https://api.openai.com/v1"]},
"anthropic": {..., "base_urls": ["https://api.anthropic.com"]},
# qwen / doubao:各自单一固定
"qwen":   {..., "base_urls": ["https://dashscope.aliyuncs.com/compatible-mode/v1"]},
"doubao": {..., "base_urls": ["https://ark.cn-beijing.volces.com/api/v3"]},
# 兼容兜底:base_urls 为空 → 前端走自由输入
"openai-compatible":    {..., "base_urls": []},
"anthropic-compatible": {..., "base_urls": []},
```

新增小工具(供路由判断是否锁定):
- `provider_base_urls(provider: str) -> list[str]` — 返回该 provider 的 `base_urls`(缺失则 `[]`)。`base_urls` 非空即「锁定下拉」,为空即「自由输入」。

### 4.2 列模型 — `app/llm/client.py`

新增 `list_models(cfg: LLMConfig) -> tuple[bool, list[str] | str]`,紧邻 `ping_llm`:
- 复用 `_get_adapter(cfg, timeout=20.0)`。
- `openai_compatible`: `adapter._client.models.list()` → 取每个 `.id`。
- `anthropic_compatible`: `adapter._client.models.list()` → 取每个 `.id`(Anthropic SDK 同名方法,命中 `/v1/models`)。
- 去重 + 保序,返回 `(True, [ids...])`。
- 任何异常走 `_humanize_llm_error()`(401/超时/域名不通/非 2xx 都给中文原因),返回 `(False, message)`。**不**抛错。

### 4.3 新路由 — `app/routers/llm_config.py`

`_public_providers()` 增加 `base_urls` 与 `base_url_editable` 字段(`base_urls` 非空→`editable=False`):

```python
def _public_providers() -> dict:
    return {
        name: {
            "title": p["title"],
            "provider_type": p["provider_type"],
            "default_base_url": p["default_base_url"],
            "base_urls": p.get("base_urls", []),           # 新
            "base_url_editable": not p.get("base_urls"),   # 新:空列表=可自由输入
            "default_model": p["default_model"],
        }
        for name, p in PROVIDERS.items()
    }
```

新增端点(沿用 `LLMConfigUpdate` 作为入参 schema,字段均 Optional,与 `/test` 一致):

| 方法 | 路径 | 行为 |
|---|---|---|
| POST | `/api/admin/llm-config/models` | 据 `{provider, provider_type?, api_key?, base_url}` 构造 `LLMConfig`(key 留空用已保存值,base_url 取表单),SSRF 校验 base_url,调 `list_models(cfg)`,返回 `{ok, models?: [...], detail?: "..."}`。**不落库、不打日志 key。** |

逻辑与现有 `/test` 完全同构(provider_type 推断、key 兜底、SSRF、构造 `LLMConfig`),只是把 `ping_llm` 换成 `list_models`,返回体多一个 `models`。

`GET /api/admin/llm-config` 的返回体随之多带 `base_urls` / `base_url_editable`(经 `_public_providers()`)。

## 5. 前端改动

### 5.1 API 层 — `src/api.js`
新增(沿用 `fetchWithTimeout`,20s 超时,读 `err.message`):

```js
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
  return await res.json()   // { ok, models?, detail? }
}
```

### 5.2 页面 — `src/views/SettingsView.vue`

**base_url 字段**:改为「锁定 provider 时渲染 `<select>`、compatible 时渲染 `<input>`」:

```html
<select v-if="!baseUrlEditable" id="base-url" v-model="form.base_url">
  <option v-for="u in baseUrlOptions" :key="u" :value="u">{{ u }}</option>
</select>
<input v-else id="base-url" v-model="form.base_url" placeholder="https://your-endpoint/v1" />
```

- `baseUrlOptions` = 当前 provider 的 `base_urls`;`baseUrlEditable` = 该 provider `base_url_editable`。
- 切 provider(`onProviderChange`):锁定型→`form.base_url = base_urls[0]`;compatible→保留原值或清空。触发 model 自动拉取条件重算。

**model 字段**:改为 `<select>` + 拉取态 + 手动输入兜底:

```
模型  [ deepseek-chat          ▼ ]  [ ↻ 拉取 ]      ← 三项齐全才可点
       ↑ 下拉来自 listLlmModels();loading 时显示「拉取中…」
       拉取失败:内联「❌ 拉取失败:<原因>,可手动输入」+ 切 input  [ 手动输入 ]
```

行为:
- 计算属性 `canFetchModels = provider && base_url && (api_key 或 hasKey)`。
- **自动拉取**:`watch` provider / base_url / api_key 变化(防抖 500ms),`canFetchModels` 为真且列表为空时自动调 `listLlmModels(buildModelsPayload())`。对应「填写前三项后,自动拉取」。
- **手动「↻ 拉取」按钮**:随时可点重新拉取(如换了 key)。
- 成功:`modelOptions = result.models`;若当前 `form.model` 仍在列表中则保留,否则置为首项;列表为空回退到手动输入。
- 失败:内联中文原因(读 `e.message` / `result.detail`),切到 `<input>` 自由输入,用户不被卡住(doubao endpoint-id、个别不支持的兼容端点都能继续)。
- buildModelsPayload:与现有 `buildPayload` 同构(只含 provider/provider_type/base_url + api_key(若有));**不发空 key**(留空后端用已保存值)。

`load()` 回填后,若三项齐全,触发一次自动拉取以填充下拉(当前 model 若在列表内则选中)。

### 5.3 状态
全部组件内 local `ref`/`computed`,无跨页共享,**不**新增 composable(沿用上一版决策)。

## 6. 数据流

**切 provider / 填 key → 自动拉模型**:
切/填 → 前端防抖 500ms → `POST /api/admin/llm-config/models`(带 provider/base_url/api_key)→ 后端 SSRF 校验 + `list_models` → 返回 ids → 前端填下拉、保留已选 → 用户选模型 → (后续)「保存」走原 `PUT /api/admin/llm-config`。

## 7. 错误处理

- **base_url 非法/内网/http** → `/models` 端点返回 `{ok:false, detail:<SSRF 中文原因>}`,前端内联展示并切手动输入。
- **拉取失败(401 key 错 / 超时 / 域名不通 / 非兼容端点)** → `list_models` 经 `_humanize_llm_error` 给中文原因 → 同上。
- **列表为空** → 切手动输入兜底。
- **网络/超时** → `fetchWithTimeout` 的「请求超时」中文报错。
- **未带 admin token** → 沿用 `WriteAuthMiddleware`(401)。

## 8. 安全

- `/models` 端点 `verify_admin`;key 不入响应、不入日志。
- base_url 过 SSRF 守卫(禁止 http / 内网 / loopback)。锁定型 provider 的 base_url 来自硬编码可信列表,SSRF 风险为零;compatible 型走守卫。
- 不改 key 落盘策略(本地单用户,沿用上一版)。

## 9. 测试

**后端 `backend/tests/test_llm_config.py`**(pytest,沿用现有 markers):
- `provider_base_urls()` 返回正确列表;GLM 含 coding 端点、moonshot 含海外端点;compatible 为空。
- `_public_providers()` 带 `base_urls` / `base_url_editable`;compatible `editable=True`。
- `POST /models`:`monkeypatch` `list_models` 返回 `(True, ["a","b"])` → 响应 `{ok:true, models:["a","b"]}`;返回 `(False, "无效 key")` → `{ok:false, detail:"无效 key"}`。
- `/models` SSRF:内网 base_url → `{ok:false, detail: <SSRF 文案>}`。
- `/models` 不带 api_key 时用已保存 key(同 `/test` 的既有测试模式)。
- `list_models` 单元测试:mock adapter `_client.models.list()` 返回对象列表,断言去重保序取 `.id`;异常分支返回 `(False, msg)`。

**前端 `frontend/tests/SettingsView.spec.js`**(Vitest):
- 锁定型 provider 渲染 base_url `<select>`(选项=base_urls);compatible 渲染 `<input>`。
- 三项齐全后自动调 `listLlmModels`(用 fake timers 推进防抖);成功填下拉并保留已选。
- 拉取失败:展示内联原因、切到 `<input>`。
- 「↻ 拉取」按钮点击触发拉取。

## 10. 实现顺序(供 writing-plans 参考)

1. 后端 PROVIDERS 加 `base_urls` + `provider_base_urls()` + 单测(锁定数据源先立)。
2. 后端 `client.py::list_models()` + 单测(mock adapter)。
3. 后端 `/models` 端点 + `_public_providers` 扩字段 + 单测。
4. 前端 `api.js::listLlmModels()`。
5. 前端 `SettingsView.vue` base_url 下拉 + model 自动拉取/手动兜底 + Vitest。
6. 手测:切 provider 看 base_url 锁定;GLM 选 coding 端点;填 key 后模型自动拉取并可选;doubao/compatible 走手动输入;保存后处理一集确认生效。
