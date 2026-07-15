# 设计:LLM API 设置页

- **日期**: 2026-07-15
- **状态**: 已批准(用户授权「按推荐执行」)
- **范围**: 前后端——让用户在网页上填入并保存自己的 LLM API 配置,改完即时生效

---

## 1. 背景与问题

当前 LLM 配置只能通过编辑后端 `.env` 生效(`app/llm/config.py::get_config()` 读 `os.getenv()`),
前端没有任何读写入口。新用户要「用自己的 API」必须 SSH 进服务器改文件并重启服务,门槛高。

**关键发现(探索结论)**:
- `get_config()` 是**每次调用都重新解析**的(非启动时读死)→ 运行时覆写可即时生效。
- 配置优先级已存在:`LLM_*` > `DEEPSEEK_*` > `PROVIDERS` 预设默认。
- 已有 SSRF 防护(`_assert_public_https_base_url`)与 admin 鉴权(`verify_admin` / `X-Admin-Token` / `WriteAuthMiddleware`)。
- **缺**:配置读写端点、DB 配置表、连通性测试。

## 2. 目标 / 非目标

**目标**
1. 前端页面可填入 provider / API Key / base_url / model 并保存。
2. 改完**无需重启**即对 API 与 Worker 两进程同时生效。
3. 保存前可「测试连接」,提前发现错误 key / 链接。
4. 沿用现有视觉与代码风格(scoped CSS、`fetchWithTimeout`、admin 鉴权)。

**非目标(YAGNI)**
- 不做多套配置 profile / 环境切换(单用户工具,一套生效配置即可)。
- 不做配置历史 / 版本回滚。
- 不做 key 加密落盘(本地单用户,与 `.env` 存 key 同等敏感度,可接受)。
- 不引入 dark mode / 新设计系统。

## 3. 架构总览

```
SettingsView.vue  ──(X-Admin-Token)──▶  /api/admin/llm-config
                                              GET 读 / PUT 写 / POST test
                                              │  routers/llm_config.py  (verify_admin)
                                              ▼
                                   app_setting 表 (key='llm_config', value=JSON)
                                              ▲
                            get_config() 读取顺序:  DB 覆写  >  .env  >  预设默认
```

**跨进程正确性(关键决策)**:API 与 Worker 是两个进程,各自有自己的内存。
因此 `get_config()` 必须**每次直接同步读 DB**(1 行表,亚毫秒),
不能用进程内缓存(否则 Worker 看不到 API 进程刚写入的配置)。
SQLite 现为 **WAL 模式**,跨进程「写后读」可见、读读并发安全。
`.env` 仍是启动兜底(无 DB 记录时回退到现状)。

## 4. 后端改动

### 4.1 数据库 — `app/database.py`
建表处新增(沿用现有 aiosqlite + `CREATE TABLE IF NOT EXISTS`):

```sql
CREATE TABLE IF NOT EXISTS app_setting (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,          -- JSON
  updated_at TEXT NOT NULL
);
```

只用到一条记录:`key='llm_config'`。

### 4.2 配置覆写 — `app/llm/config.py`
`get_config()` 现有 env 解析**之后**,叠一层 DB 覆写:
- 用 `sqlite3`(同步标准库,非 aiosqlite)按 DB 路径(取自 `settings`)读 `app_setting` 中 `key='llm_config'` 的 JSON。
- DB 有对应字段就覆盖 env 解析出的 `LLMConfig` 字段;表/记录缺失或异常时**静默回退**到 env(绝不让配置读取抛错阻塞流水线)。
- base_url 覆写后仍过 `_assert_public_https_base_url`(复用现有 SSRF guard)。
- 1 行表的同步读开销亚毫秒,可接受;不引入缓存以保证跨进程即时一致。

新增小工具:
- `read_runtime_override() -> dict` — 同步读 DB 的 JSON,失败返回 `{}`。
- `merge_override(base: LLMConfig, override: dict) -> LLMConfig` — 生成最终 `LLMConfig`(只覆盖 override 里非空字段)。

### 4.3 连通性测试 — `app/llm/client.py`(或新建 `app/llm/test_conn.py`)
新增 `ping_llm(config: LLMConfig) -> tuple[bool, str]`:
- 用**传入的** `LLMConfig`(**不**走 `get_config()`,这样能测未保存的草稿值),
  复用 `protocols.py` 的 adapter 发一个极小请求(prompt 如 `"ping"`, `max_tokens≈5`, 短超时如 15s)。
- 返回 `(ok, detail)`:`ok=True` 给延迟;`ok=False` 给人类可读原因(401 无效 key / 超时 / 域名不通 / 非 2xx)。

### 4.4 新路由 — `app/routers/llm_config.py`
router 级 `Depends(verify_admin)`(沿用现有 admin 模式):

| 方法 | 路径 | 行为 |
|---|---|---|
| GET | `/api/admin/llm-config` | 返回当前生效配置(provider/model/base_url 是否自定义)+ `PROVIDERS` 预设列表(供下拉)。**api_key 一律掩码**(`sk-xxxx****`)。 |
| PUT | `/api/admin/llm-config` | body 含 provider/api_key/base_url/model(均可选,空字段=不改)。SSRF 校验 base_url → 写 `app_setting`。**未提供 api_key 时保留旧值**。 |
| POST | `/api/admin/llm-config/test` | body 同 PUT,据此构造 `LLMConfig` 调 `ping_llm()`,返回 `{ok, detail}`。不落库。 |

挂进 `app/main.py`(`app.include_router(llm_config_router.router)`)。

## 5. 前端改动

### 5.1 路由 — `src/router.js`
新增 `/settings → SettingsView.vue`(lazy import,沿用现有写法)。

### 5.2 入口 — `src/views/LibraryView.vue`
右上角加齿轮按钮(`router.push('/settings')`)。

### 5.3 页面 — `src/views/SettingsView.vue`
scoped CSS,主色 `#4f8ef7`,沿用 `TokenDialog.vue` 的 input/button 样式与 token。布局:

```
┌──────────────────────────────────────────┐
│ ← 返回                  LLM API 设置       │  header(同 PlayerView)
├──────────────────────────────────────────┤
│  Provider  [ deepseek            ▼ ]      │  下拉;选中自动填默认 base_url/model
│  API Key   [ sk-••••••••      ] 👁         │  type=password;保存后掩码 + 眼睛切换
│  API 链接  [ https://api.deepseek.com   ] │  base_url
│  模型      [ deepseek-chat                ]│
│                                           │
│            [ 测试连接 ]    [ 保存 ]        │
│   ✅ 连通(120ms)  /  ❌ 401: 无效的 API Key │
└──────────────────────────────────────────┘
```

行为:
- 进入页 `getLlmConfig()` 拉当前配置 + 预设,回填(key 掩码)。
- 切 provider → base_url/model 填该预设默认(用户可手改)。
- 「测试连接」→ `testLlmConfig(当前表单值)` → 显示 ✅/❌ + 原因。
- 「保存」→ 前端非空校验(api_key 若仍是掩码占位则不发该字段)→ `saveLlmConfig()` → toast「已保存」。
- 顶部「← 返回」沿用 PlayerView header 样式。

### 5.4 API 层 — `src/api.js`
新增(沿用 `fetchWithTimeout`,自动带 `X-Admin-Token`):
- `getLlmConfig()`
- `saveLlmConfig(cfg)`
- `testLlmConfig(cfg)`

### 5.5 状态
`SettingsView.vue` 组件内 local state(ref/computed)即可,无跨页共享需求,**不**新增 composable。

## 6. 数据流(保存一次)

填表 → 前端非空校验 → `PUT /api/admin/llm-config` → 后端 SSRF 校验 + 写 `app_setting` → 200 → 前端 toast「已保存」 → 下一次 `get_config()`(API 或 Worker 进程)同步读 DB 自动命中新值。

## 7. 错误处理

- **base_url 非法 / 内网 / 非 https** → 后端 400 + 中文提示(复用 SSRF guard 报错文案)。
- **测试连接失败** → 展示 `ping_llm` 返回的具体原因(401 key 错 / 超时 / 域名不通 / 非 2xx)。
- **网络 / 超时** → 沿用 `fetchWithTimeout` 的「请求超时」中文报错。
- **未带 admin token** → 沿用现有 `WriteAuthMiddleware` 行为(401)。
- **get_config() 读 DB 失败** → 静默回退 env,绝不抛错阻塞流水线。

## 8. 安全

- 写端点强制 `verify_admin`(admin token 或 loopback)。
- **api_key 不完整回传**:GET 只给掩码;PUT 不带 key 时保留旧值。
- base_url 过 SSRF guard(禁止 http / 内网 / loopback)。
- key 落本地 SQLite(单用户,与 `.env` 同等敏感度,可接受)。

## 9. 测试

**后端 `backend/tests/test_llm_config.py`**(pytest,沿用现有 markers/结构):
- GET 返回的 `api_key` 为掩码。
- PUT 写入后 `get_config()` 读到覆写值。
- PUT 不带 api_key 时保留旧 key。
- SSRF:PUT 内网 / http base_url → 400。
- `/test`:`monkeypatch` `ping_llm` 返回成功 / 失败分支,断言响应。
- DB 缺失 / 损坏时 `get_config()` 回退 env 不抛错。

**前端 `frontend/tests/SettingsView.spec.js`**(Vitest,沿用现有结构):
- 渲染、`getLlmConfig` 回填、掩码显示。
- 切 provider 自动填默认 base_url/model。
- 「保存」调 `saveLlmConfig`(正确 body)。
- 「测试连接」调 `testLlmConfig` 并展示 ✅/❌。

## 10. 实现顺序(供 writing-plans 参考)

1. 后端 DB 表 + `get_config()` 覆写 + 单测(让「读写即生效」先成立)。
2. 后端 `llm_config` 路由(3 端点)+ `ping_llm` + 单测。
3. 前端 `api.js` 三个方法。
4. 前端 `SettingsView.vue` + 路由 + 齿轮入口 + Vitest。
5. 手测:保存配置 → 用真链接处理一集 → 确认走的是新 provider/key。
