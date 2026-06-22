# Podcast Digester — Operations & Security Guide

> **状态**: 反映 2026-06-22 安全/稳定性 sweep 后的状态。
> 本文件记录这一轮重构新增的运维配置、安全控制、代码组织和测试入口。
> 老的 `deployment-guide.md` / `security-hardening.md` 描述 v0.3.0 字幕功能，
> 两者并存，本文档优先。

---

## TL;DR

- **本地开发**：`./start.sh`，无需任何环境变量，所有功能可用。
- **公网部署**：必须设置 `PODCAST_DIGESTER_ADMIN_TOKEN`，并通过 UI 输入 token；否则写操作被拒。
- **测试**：`cd backend && python -m pytest tests/` → 109 tests；`cd frontend && npx vitest run` → 88 tests。
- **构建**：`cd frontend && npx vite build` 产出 `dist/`，主 bundle ~52.7 KB gzip。

---

## 环境变量

### 必填（仅生产部署）

| 变量 | 说明 |
|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek LLM API key。启动时 `validate_config()` 检查存在性。 |
| `PODCAST_DIGESTER_ADMIN_TOKEN` | 共享密钥，保护所有写操作。强烈建议 `openssl rand -hex 32` 生成。 |

### 可选（有合理默认）

| 变量 | 默认 | 说明 |
|---|---|---|
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` | DeepSeek API 端点 |
| `DEEPSEEK_MODEL` | `deepseek-chat` | 使用的模型 |
| `PODCAST_DIGESTER_CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173` | 逗号分隔的允许 origin 白名单。公网部署必填实际域名。 |
| `PODCAST_DIGESTER_HOST` | `127.0.0.1` | uvicorn 绑定 host |
| `PODCAST_DIGESTER_PORT` | `8000` | uvicorn 端口 |
| `PODCAST_DIGESTER_MAX_LLM_COST` | `5.0` | 单集 LLM 成本上限（美元） |
| `PODCAST_DIGESTER_MAX_EPISODE_HOURS` | `5.0` | 单集时长上限 |
| `PODCAST_DIGESTER_WORKER_POLL_INTERVAL` | `5` | worker 拉取 pending 任务间隔（秒） |
| `PODCAST_DIGESTER_DATA_DIR` | `../data` | 数据目录（media/exports/db） |
| `PODCAST_DIGESTER_WHISPER_MODEL` | `small` | Whisper 模型（`tiny`/`small`/`medium`/`large`） |

完整列表见 `backend/app/config.py` 顶部注释。

---

## 安全模型

### 认证：分层防御

```
请求 ─┬─→ WriteAuthMiddleware（全局）
      │     ↓
      │   ADMIN_TOKEN 未配置 → 放行（开发模式）
      │   ADMIN_TOKEN 已配置：
      │     - GET / HEAD / OPTIONS → 放行
      │     - /media/, /fixtures/, /api/exports/ → 放行（只读资源）
      │     - 其他 /api/* + 写方法 → 要求 X-Admin-Token
      │
      └─→ verify_admin 依赖（仅 /api/admin/* 双层防御）
```

**重要：开发 vs 生产**
- 没设 `PODCAST_DIGESTER_ADMIN_TOKEN`：所有写操作开放（假定只 loopback 暴露）。
- 设了 `PODCAST_DIGESTER_ADMIN_TOKEN`：所有 POST/PUT/DELETE/PATCH 必须带正确 token。

### 前端 Login 流程（H2 followup）

1. 用户访问 Library 页，看到右上角 🔒 图标（灰）
2. 点击图标 → 弹出 TokenDialog
3. 粘贴 admin token → 保存
4. token 存入 `localStorage[PODCAST_DIGESTER_ADMIN_TOKEN]`，所有未来请求自动注入 `X-Admin-Token` 头
5. 图标变绿色 🔓，点击可登出/换 token

**实现位置**：
- 前端：`frontend/src/composables/useAdminAuth.js`（reactive 状态）+ `frontend/src/components/TokenDialog.vue`
- 底层：`frontend/src/api.js` 的 `fetchWithTimeout` 自动注入 header

### CORS

`backend/app/main.py` 的 CORSMiddleware 配置：
- `allow_origins` = `settings.cors_origins`（白名单，非 `*`）
- `allow_credentials=False`（无 cookie session，符合纯 token 模型）

非法 origin 的请求不会拿到 `Access-Control-Allow-Origin` 响应头，浏览器拒绝读取。

### 速率限制（C5）

| 端点 | 限制 | 说明 |
|---|---|---|
| `POST /api/paste` | 5/min | 创建新节目 |
| `POST /api/episode/{id}/insights` | 10/min | LLM 触发 |
| `POST /api/episodes/{id}/sync-subtitles-llm` | 10/min | LLM 智能分段 |
| `POST /api/episodes/{id}/extract-insights` | 10/min | 金句提取 |
| `POST /api/episodes/{id}/correct-transcript` | 10/min | ASR 纠错 |
| `POST /api/episodes/{id}/export` | 3/min | PNG 渲染（playwright） |
| 其他 | 无 |  |

实现：`backend/app/rate_limit.py` 的 `SlidingWindowLimiter`，按 `client_host:path` 维度滑动窗口，asyncio.Lock 保护内部 dict。超限返回 `429` + `Retry-After` 头。

### 内容安全策略（CSP）

`frontend/index.html` 顶部 meta：

```
default-src 'self';
script-src 'self';                      ← 不再需要 unsafe-eval/unsafe-inline
style-src 'self' 'unsafe-inline';       ← Vue scoped styles 需要
img-src 'self' data: blob:;
font-src 'self' data:;
media-src 'self' data: blob:;            ← 音频播放
connect-src 'self';
object-src 'none';
base-uri 'self';
frame-ancestors 'none';                  ← 防点击劫持
form-action 'self';
```

---

## 代码组织（H5/H7 refactor 后）

### Backend

```
backend/app/
├── main.py                  ~300 行 — FastAPI 创建、middleware、startup、health、include_router
├── deps.py                  共享：data_dir / is_loopback / verify_admin / WriteAuthMiddleware
├── rate_limit.py            SlidingWindowLimiter + rate_limit dep factory
├── config.py                Settings + validate_config()
├── routers/
│   ├── episodes.py          paste / list / get / delete / play / cancel / resume / insights
│   ├── subtitles.py         transcript / sync-subtitles / sync-subtitles-llm / extract / correct / segments-update / apply-glossary
│   ├── export.py            export + download
│   ├── admin.py             batch-sync（router-level verify_admin）
│   ├── media.py             音频 Range serving
│   └── glossary.py          entries / add / delete
├── services/
│   ├── episode_loader.py    load_episode_bundle + 各 _load_*_fast 助手
│   ├── background_tasks.py  create_background_task + sync_episode_modules
│   └── ... (glossary / segmenter / llm_* 等业务服务)
└── ...
```

**关键约定**：所有 router 使用属性访问 `deps.data_dir`（而非 `from ..deps import data_dir`），否则 `conftest.py` 的 `temp_data_dir` fixture 在测试期 patch `app.deps.data_dir` 不生效。

### Frontend

```
frontend/src/
├── views/
│   ├── LibraryView.vue      节目列表（含 admin token 入口）
│   └── PlayerView.vue       音频播放 + 三 tab（摘要/字幕/洞察）
├── components/
│   ├── TokenDialog.vue      admin token 输入/管理
│   ├── ExportModal.vue      导出 HTML/PNG
│   ├── TranscriptEditor.vue 字幕编辑 + 术语表
│   └── ...
├── composables/
│   ├── useAdminAuth.js      reactive admin token state（单例）
│   ├── useAudioPlayback.js  音频事件 + seek 排队（H7 phase 3）
│   ├── useKeyboardShortcuts.js  全局快捷键（H7 phase 2）
│   ├── useSubtitleScroll.js 字幕自动滚动（含虚拟滚动支持）
│   └── player.js            全局播放器 reactive state
├── utils/
│   ├── validation.js        validatePodcastInput（M5）
│   └── formatters.js        纯函数格式化（H7 phase 1）
├── api.js                   所有 API 调用 + fetchWithTimeout + admin token 注入
└── ...
```

**PlayerView.vue 仍 1904 行**，剩余的可拆分项是 sub-component（ChaptersPanel/PlayerControls 等），属于下一轮工作。

---

## 测试

### Backend

```bash
cd backend
source venv/bin/activate
python -m pytest tests/                  # 全部 109 个测试
python -m pytest tests/test_rate_limit.py        # 仅限流器
python -m pytest tests/test_write_auth_middleware.py  # 仅认证中间件
python -m pytest tests/test_admin_api.py         # 批量同步 API
```

测试覆盖矩阵：

| 文件 | 覆盖 |
|---|---|
| `test_rate_limit.py` | SlidingWindowLimiter 行为 + rate_limit dep + client_key |
| `test_write_auth_middleware.py` | WriteAuthMiddleware 5 个分支（token 配置/方法/路径/豁免） |
| `test_admin_api.py` | 批量字幕同步端到端 |
| `test_subtitle_sync_api.py` | 字幕同步 |
| `test_subtitle_segmenter.py` | 字幕分段逻辑 |
| `test_database.py` | DB repository |
| `test_errors.py` | 异常体系 |
| `test_apple_afm3.py` | Apple AFM ASR |
| `test_text_cleaners.py` | 文本清洗 |

`conftest.py` 有个 autouse fixture 默认绕过认证和限流（用于业务测试），测安全相关逻辑时通过 `monkeypatch` 替换为真实实例。

### Frontend

```bash
cd frontend
npx vitest run                  # 全部 88 个测试
npx vitest run tests/utils/validation.spec.js
npx vitest run tests/composables/
```

| 文件 | 覆盖 |
|---|---|
| `tests/utils/validation.spec.js` | validatePodcastInput 29 cases（所有 URL/path/边界） |
| `tests/composables/useAudioPlayback.spec.js` | 音频 seek 排队 + canplay 触发 12 cases |
| `tests/composables/useKeyboardShortcuts.spec.js` | 快捷键绑定 + 表单豁免 11 cases |
| `tests/views/PlayerView.integration.spec.js` | PlayerView 集成 15 cases |

### 构建

```bash
cd frontend
npx vite build                  # ~400ms，产出 dist/，主 bundle 52.70 KB gzip
```

生产构建会自动 drop 所有 `console.log`/`console.debug`/`console.info`（保留 `error`/`warn`），见 `vite.config.js` 的 `esbuild.pure`。

---

## 部署 checklist

### 本地开发

```bash
git clone <repo> && cd podcast-digester
cd backend && python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # 编辑填 DEEPSEEK_API_KEY
cd ../frontend && npm install
cd .. && ./start.sh
```

无需 admin token，全部功能可用（loopback）。

### 公网部署

1. **后端**：
   - 反向代理（nginx/caddy）做 TLS 终止
   - 设置 `PODCAST_DIGESTER_ADMIN_TOKEN=<openssl rand -hex 32>`
   - 设置 `PODCAST_DIGESTER_CORS_ORIGINS=https://your-domain.com`
   - 设置 `PODCAST_DIGESTER_HOST=127.0.0.1`（不直接暴露，由反代转发）
2. **前端**：
   - `npx vite build` → 静态文件部署到 CDN 或反代 serve
   - 用户首次访问点 🔒 → 输入 admin token → 保存
3. **HTTP 头**（反代层建议）：
   - `Strict-Transport-Security: max-age=31536000; includeSubDomains; preload`
   - `X-Content-Type-Options: nosniff`
   - `Referrer-Policy: strict-origin-when-cross-origin`

### 资源监控点

- `data/media/{episode_id}/sync_status.json`：字幕段落同步失败时写入，前端轮询可见
- `data/media/{episode_id}/punctuation_status.json`：标点恢复失败时写入，前端字幕 tab 顶部 banner 显示
- `data/*.log`：worker / uvicorn 日志
- `data/cost_log`（DB 表）：LLM token 消耗和成本

---

## 常见问题

**Q: 后端启动报 "DEEPSEEK_API_KEY must be set" 但我设置了？**
A: 检查 key 是否仍为 `.env.example` 里的占位符 `sk-your-api-key-here`。`validate_config()` 会拒绝这个特定值（不再像旧代码那样拒绝所有 `sk-` 开头的 key）。

**Q: 公网部署后所有 POST 都 401？**
A: 没设 `PODCAST_DIGESTER_ADMIN_TOKEN` 或前端没输 token。点 Library 页右上 🔒 输入即可。

**Q: 前端 vite build 报错 "Cannot resolve entry module index.html"？**
A: cwd 不对。必须在 `frontend/` 目录下跑 `npx vite build`。

**Q: 长节目字幕卡顿？**
A: 已经在 M7 用 DynamicScroller 虚拟化了。如果仍卡，检查浏览器 DevTools Performance 看是否其他原因。

**Q: 跨域请求被浏览器拒？**
A: 前端域名没加进 `PODCAST_DIGESTER_CORS_ORIGINS`。逗号分隔，无空格。

---

## 相关文档

- `deployment-guide.md`（v0.3.0 字幕功能部署，部分内容已过时）
- `security-hardening.md`（v0.3.0 安全 hardening 计划，本文档反映其实际落地状态）
- `user-guide.md`（字幕同步功能用户视角说明）
- `testing-checklist.md`（v0.3.0 测试 checklist）

冲突时**以本文档为准**。
