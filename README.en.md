<div align="center">

# 🎙️ Podcast Digester

**Turn any podcast / video link into structured knowledge you can act on in 5 minutes.**

Paste a link → auto-download, transcribe, chapter, summarize, extract highlights → bilingual subtitles with click-to-seek.

A local-first, single-user tool built for high-density information consumers — PMs, researchers, investors.

![Python](https://img.shields.io/badge/Python-3.11--3.13-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![Vue](https://img.shields.io/badge/Vue-3-42b883?logo=vuedotjs&logoColor=white)
![LLM](https://img.shields.io/badge/LLM-Multi--Provider-8A2BE2)
![Tests](https://img.shields.io/badge/Tests-392%20passed-brightgreen)
![License](https://img.shields.io/badge/License-MIT-blue)
![Status](https://img.shields.io/badge/Status-Personal%20·%20Active-orange)

</div>

🌐 [简体中文](./README.md) | **English**

---

## ✨ The Problem It Solves

When you face a 2-hour podcast, the real cost isn't *understanding* it — it's **not knowing whether it's worth your time.** Podcast Digester distills an episode into:

- A one-line **TL;DR** + a **worth-listening verdict** (`Deep Listen` / `Skim` / `Skip` — defaults to `Skim` when unsure)
- A **chapter outline** with per-chapter Chinese summaries
- Five kinds of **highlights** (legend below), each with the original subtitle citation and a timestamp
- **Product / technical / market** insights, plus a list of companies mentioned
- **Bilingual subtitles** precisely aligned to the player timeline — click a chapter or highlight to seek

> Decide in 5 minutes; when you choose to deep-listen, the subtitles and highlights help you skim-listen.

### Highlight legend

| Tag | Meaning | Example |
|------|---------|---------|
| `fact` | A verifiable key data point / fact | "Revenue grew 40% in 2025" |
| `insight` | An opinion / judgment / conclusion | "The real moat is distribution, not the model" |
| `quote` | A quotable line | "We didn't invent the wheel; we paved the road" |
| `contrarian` | A view against consensus | "Everyone's bullish, but supply is already oversupplied" |
| `story` | A concrete case / narrative | "Their first three months served only 7 users…" |

## 🖼️ Screenshots

<div align="center">
<table>
<tr><td align="center"><b>Library</b> — paste a link, see processing status, click to open</td></tr>
<tr><td><img src="./docs/images/library.png" alt="Library 节目库"/></td></tr>
<tr><td align="center"><b>Player</b> — bilingual subtitles / chapters / summary / highlights / insights, click to seek</td></tr>
<tr><td><img src="./docs/images/player.png" alt="Player 播放器"/></td></tr>
</table>
</div>

**What to look for in the player view:**
- A one-line **TL;DR** at the top + a **verdict** badge (`Deep Listen` / `Skim` / `Skip`)
- **Chapter ticks** on the timeline; click a chapter title to jump
- Five kinds of **highlights** in the right pane, each with the source citation + timestamp; click to seek to the clip
- **Bilingual subtitles** (zh / en) under the player, precisely aligned to the timeline

## 🧠 Pipeline

Each episode flows through these stages in order, with **resumable checkpoints** (per-stage JSON + SQLite state):

<div align="center">

![Podcast Digester pipeline](./docs/images/pipeline.svg)

</div>

Chinese sources auto-skip `translate`; platform subtitles that already have proper punctuation auto-skip `polish` — avoiding needless LLM cost.

| Stage | Output |
|-------|--------|
| `download` | audio file (`data/media/ep_*/`) |
| `transcribe` | timestamped subtitle segments (`transcript.json`) |
| `polish` / `translate` | normalized punctuation + bilingual fields (`text_zh` / `text_en`) |
| `chapterize` | chapter titles and time ranges |
| `summarize` | per-chapter Chinese summaries |
| `highlight` | TL;DR + verdict + five highlight kinds (with citation / timestamp) |
| `product_insights` | product / tech / market insights + mentioned companies |

## 🏗️ Architecture

<div align="center">

![System architecture](./docs/images/architecture.svg)

</div>

**Fully local-first:** media files and all distilled artifacts live on your own disk; only LLM calls, platform fetches, and (subtitle-less) speech recognition go over the network.

## 🔌 Pluggable LLM (multi-provider)

All distill stages (polish / translate / chapterize / summarize / highlight / insights) share **one unified entry point**, `app/llm/client.py::complete()`, which dispatches between two adapters by protocol:

- `openai_compatible` — wraps `openai.AsyncOpenAI`; covers DeepSeek / OpenAI / GLM / Qwen / Doubao / Kimi and other OpenAI-compatible endpoints
- `anthropic_compatible` — wraps `anthropic.AsyncAnthropic`; covers the Claude family

Switching providers is just an env-var change — **no code changes.**

### Supported provider presets

| `LLM_PROVIDER` | Protocol (`provider_type`) | Default endpoint | Default model | Notes |
|----------------|----------------------------|------------------|---------------|-------|
| `deepseek` | `openai_compatible` | `api.deepseek.com` | `deepseek-chat` | Recommended, great value |
| `openai` | `openai_compatible` | SDK default | `gpt-4o-mini` | OpenAI official |
| `anthropic` | `anthropic_compatible` | SDK default | `claude-3-5-sonnet-latest` | Claude family |
| `glm` | `openai_compatible` | `open.bigmodel.cn/api/paas/v4` | `glm-4-flash` | Zhipu |
| `qwen` | `openai_compatible` | `dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` | Tongyi Qianwen |
| `doubao` | `openai_compatible` | `ark.cn-beijing.volces.com/api/v3` | *（fill in）* | ByteDance Doubao; the model id is an endpoint id |
| `moonshot` | `openai_compatible` | `api.moonshot.cn/v1` | `moonshot-v1-8k` | Moonshot Kimi |
| `openai-compatible` | `openai_compatible` | custom | custom | any OpenAI-compatible endpoint |
| `anthropic-compatible` | `anthropic_compatible` | custom | custom | any Anthropic-compatible endpoint |

### Switching examples (`.env`)

```bash
# —— DeepSeek (default) ——
LLM_PROVIDER=deepseek
LLM_API_KEY=sk-xxxxxxxx
LLM_MODEL=deepseek-chat          # optional; empty uses the preset default

# —— Anthropic Claude ——
LLM_PROVIDER=anthropic
LLM_API_KEY=sk-ant-xxxxxxxx
LLM_MODEL=claude-3-5-sonnet-latest

# —— Zhipu GLM ——
LLM_PROVIDER=glm
LLM_API_KEY=xxxxxxxx
LLM_MODEL=glm-4-flash

# —— Any self-hosted / third-party OpenAI-compatible endpoint ——
LLM_PROVIDER=openai-compatible
LLM_PROVIDER_TYPE=openai_compatible   # generic presets need an explicit protocol
LLM_BASE_URL=https://your-endpoint.com/v1
LLM_API_KEY=xxxxxxxx
LLM_MODEL=your-model
```

> **Config priority:** `LLM_*` > `DEEPSEEK_*` (backward-compat aliases) > `PROVIDERS[provider]` preset defaults.
>
> **SSRF guard:** `LLM_BASE_URL` must be `https://`, and may not point at `.local` / private / loopback addresses (LLM keys must never travel over plain http or to an internal host). See `app/llm/config.py`.

## 📥 Multi-source Support

| Source | Notes |
|------|------|
| **YouTube** | Prefers platform subtitles (manual / auto CC); fail-fast probe falls back to ASR when none exist |
| **Bilibili** | Anti-bot requires cookies: auto-uses your browser (Chrome, etc.) login session |
| **Xiaoyuzhou** | Chinese podcast platform |
| **Douyin** | Includes anti-bot bypass (curl-cffi / Playwright CDP, optional) |
| **Local files** | Feed in an already-downloaded audio/video file |

Cookie parsing for auth-required platforms is **unified** across the download and title-fetch paths (browser first, `cookies.txt` fallback) — no more "downloaded audio but couldn't fetch the title" mismatches.

### 🔑 Getting cookies (for auth-required platforms)

After cloning, platforms like Bilibili — or parts of YouTube (age / region locks) — need a login session. **Browser first, `cookies.txt` fallback** — pick either:

**Option A · Auto-read from browser (recommended, zero config)**

Just **log in** to the platform once in a local browser — the app auto-reads the login session from Chrome / Edge / Firefox / Safari. **No file to export.** Log in once in that browser before downloading.

**Option B · `cookies.txt` (fallback, for servers / headless machines)**

1. Install the browser extension **"Get cookies.txt LOCALLY"** (search the Chrome / Edge store)
2. Open the target platform page and confirm you're logged in → export from the extension
3. Drop the file at one of these (auto-detected in this order):
   - project root `podcast-digester/cookies.txt` (travels with the project, recommended)
   - `~/.config/yt-dlp/cookies.txt` (shared globally)

> Neither option needs code changes or env vars — `app/utils/cookie_helper.py` probes "browser → `cookies.txt`" automatically.

## 🚀 Quick Start

### Prerequisites

- **Python 3.11–3.13** (⚠️ **3.14 not yet supported**: faster-whisper / pydantic and other deps lack prebuilt wheels and fail to build from source), **Node.js 18+**
- **ffmpeg** (yt-dlp post-processing needs it): macOS `brew install ffmpeg` / Linux `sudo apt install ffmpeg`
- An **LLM API key** for any supported provider (default DeepSeek — [get one here](https://platform.deepseek.com/))
- **macOS 13+** (recommended): full feature set; **subtitle-less sources** transcribed locally via Apple AFM 3 (first run builds the bridge — `setup.sh` does this automatically)
- **Linux / WSL**: supports only sources **with platform subtitles** (YouTube / Bilibili CC); subtitle-less sources need ASR, which is Apple-only and won't run on Linux
- Windows: untested

### 1. Clone

```bash
git clone https://github.com/Alliskyline2020/podcast-digester.git
cd podcast-digester
```

### 2. Install (one command, recommended)

```bash
./setup.sh
```

`setup.sh` does it all: Python version check (picks 3.11–3.13) → backend venv + deps → Playwright browser → (macOS) AFM 3 bridge build → frontend deps → creates `.env` from the template. Re-runnable (idempotent).

<details><summary>Prefer step-by-step (or customize)?</summary>

```bash
# Backend
cd backend
python3.12 -m venv venv            # use 3.11–3.13, not 3.14
source venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium   # pip only installs the Python binding; the browser is separate
# macOS also needs the ASR bridge:
cd tools && ./build_apple_asr.sh && cd ..

# Frontend
cd ../frontend && npm install
```

</details>

### 3. Configure your LLM

Edit `backend/.env` and fill in at least the key (default `provider=deepseek`):

```bash
LLM_API_KEY=sk-xxxxxxxx        # your DeepSeek / OpenAI / Claude / GLM … key
# to switch providers, see "Switching examples" above
```

### 4. Run

```bash
./start.sh        # terminal 1: starts API + frontend
```

> ⚠️ `start.sh` starts **only the API + frontend**, **not the Worker**. The pipeline runs in the Worker, which you must start in a separate terminal — otherwise pasting a link won't trigger processing:

```bash
cd backend && source venv/bin/activate && python worker.py   # terminal 2: Worker
```

Open **http://localhost:5173/** and paste a podcast / video link.

**Verify the install:** paste any YouTube link (most have auto CC, easiest), and within 1–2 minutes you should see a summary + highlights — that means the deployment succeeded.

### Common issues

- **Nothing happens after pasting a link** → the Worker isn't running; `start.sh` doesn't include it, so start `python worker.py` in a separate terminal.
- **`pip install` fails with `Failed building wheel for av` / `pydantic-core`** → likely **Python 3.14** (missing prebuilt wheels). Switch to 3.11–3.13: `brew install python@3.12`, then re-run `./setup.sh`.
- **`vite: command not found` after `npm install`** → the machine has `NODE_ENV=production` set globally, so npm skipped devDependencies. Use `npm install --include=dev`, or `unset NODE_ENV` and reinstall (`setup.sh` already has this fallback).
- **Worker says `Another Worker is already running`** → a Worker is already running, or a stale lock was left after a crash. Remove the lock and retry: `rm /tmp/podcast_worker.pid`.
- **YouTube fetch fails / times out** → usually the network; set a proxy `HTTPS_PROXY=http://127.0.0.1:7897` (adjust to your proxy).
- **Bilibili download fails** → anti-bot; you need a browser login session (cookie), see "🔑 Getting cookies" above.
- **A subtitle-less source stalls at transcribe (macOS)** → the AFM 3 bridge wasn't built; re-run `cd backend/tools && ./build_apple_asr.sh` (or `./setup.sh`).

> On macOS, consider running API + Worker under launchd for persistence (see `start.sh` / `stop.sh`, or write your own `~/Library/LaunchAgents/*.plist`) so long jobs survive terminal closes.

## ⚙️ Configuration

Core config is via environment variables (see `backend/.env.example`):

| Variable | Required | Default | Description |
|------|:---:|------|------|
| `LLM_PROVIDER` | | `deepseek` | provider preset name (see the table above) |
| `LLM_API_KEY` | ✅ | — | LLM key (legacy name `DEEPSEEK_API_KEY` is equivalent) |
| `LLM_MODEL` | | per preset | model name (legacy `DEEPSEEK_MODEL`) |
| `LLM_PROVIDER_TYPE` | | inferred from provider | explicit protocol: `openai_compatible` / `anthropic_compatible` |
| `LLM_BASE_URL` | | per preset | endpoint; empty uses the SDK default (legacy `DEEPSEEK_BASE_URL`) |
| `LLM_TEMPERATURE` | | `0.3` | sampling temperature |
| `LLM_MAX_TOKENS` | | empty | per-call generation cap; empty uses the provider default |
| `LLM_TIMEOUT` | | `60` | per-call timeout (seconds) |
| `PODCAST_DIGESTER_HOST` / `_PORT` | | `127.0.0.1` / `8000` | bind address / port |
| `PODCAST_DIGESTER_ADMIN_TOKEN` | | empty | Admin-endpoint auth (leave empty for local single-user) |
| `PODCAST_DIGESTER_MAX_LLM_COST` | | `5.0` | per-episode LLM cost cap (USD); aborts if exceeded |
| `PODCAST_DIGESTER_MAX_EPISODE_HOURS` | | `5.0` | per-episode length cap (hours) |
| `HTTPS_PROXY` / `HTTP_PROXY` | | empty | proxy for reaching YouTube etc. |

Subtitle quality, chapter window, highlight counts, ASR polling, and more are tunable in `backend/app/config.py`.

## 📁 Project Structure

```
podcast-digester/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entry + route aggregation
│   │   ├── config.py            # env-driven config
│   │   ├── pipeline.py          # 8-stage pipeline orchestration (resumable)
│   │   ├── database.py          # SQLite async repository + state machine
│   │   ├── asr_afm3.py          # Apple AFM 3 ASR wrapper
│   │   ├── llm/                 # multi-provider adapter layer (complete() entry)
│   │   │   ├── client.py        #   unified dispatch by provider_type
│   │   │   ├── protocols.py     #   OpenAI / Anthropic adapter
│   │   │   ├── config.py        #   PROVIDERS presets + get_config + SSRF guard
│   │   │   └── cost.py          #   per-provider/model price table (cost estimate)
│   │   ├── sources/             # per-platform handlers (youtube/bilibili/douyin/xiaoyuzhou/local)
│   │   ├── services/            # subtitle alignment / polish / paragraph mapping
│   │   ├── llm_pipeline/        # LLM distill tasks: chapter / summary / translate / highlight / insight
│   │   └── utils/               # cookie / video-title / validation helpers
│   ├── tests/                   # pytest (unit + integration, 392 cases)
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── views/               # LibraryView / PlayerView
│   │   ├── components/          # UI components
│   │   └── utils/               # stage progress / formatting
│   └── tests/                   # Vitest
├── data/                        # SQLite + media/ep_* (gitignored)
├── docs/                        # transcript-correction guide
└── start.sh / stop.sh           # one-click start/stop
```

## 🧪 Tests

```bash
# Backend (392 cases; markers: unit / integration / api / database / llm)
cd backend && source venv/bin/activate && pytest tests

# Unit tests only (fast, no network)
pytest tests -m unit

# Frontend
cd frontend && npm test
```

## 🔒 Privacy & Cost

- **Local-first:** audio and all distilled artifacts stay on your own disk; only LLM calls, platform fetches, and (subtitle-less) speech recognition go over the network.
- **Cost-bounded:** a per-episode LLM spend above `PODCAST_DIGESTER_MAX_LLM_COST` (default $5) auto-aborts; `app/llm/cost.py` estimates each call's cost by provider / model.
- **Key safety:** the LLM key is read only from environment variables, and `base_url` passes an SSRF guard that rejects http / private / loopback endpoints.

## 🛣️ Roadmap

- [x] Multi-source (YouTube / Bilibili / Douyin / Xiaoyuzhou / local)
- [x] Resumable pipeline + per-stage progress
- [x] Bilingual subtitles (`text_zh` / `text_en`) with click-to-seek
- [x] Anti-bot auth (Bilibili cookies, subtitle-less fail-fast)
- [x] Pluggable multi-provider LLM (DeepSeek / OpenAI / Claude / GLM / Qwen / Doubao / Kimi)
- [ ] More platforms (Twitter/X, TikTok)
- [ ] Full-text search / cross-episode knowledge graph
- [ ] Mobile-responsive UI

## 📚 Docs

- [`docs/transcript-correction-guide.md`](./docs/transcript-correction-guide.md) — Transcript-correction guide (Chinese)
- [`CONTRIBUTING.md`](./CONTRIBUTING.md) — Contribution guide

## 🙏 Acknowledgements

- [**yt-dlp**](https://github.com/yt-dlp/yt-dlp) — multi-platform media download
- [**DeepSeek**](https://www.deepseek.com/) / [**OpenAI**](https://openai.com/) / [**Anthropic**](https://www.anthropic.com/) — reasoning / summary / highlight LLM (pick any one)
- **Apple AFM 3** — speech recognition when no subtitles are available
- [**feiskyer/video-skills**](https://github.com/feiskyer/video-skills) — reference for multi-platform download & transcription workflows
- [**FastAPI**](https://fastapi.tiangolo.com/) · [**Vue.js**](https://vuejs.org/) · [**Vite**](https://vitejs.dev/)

## 📄 License

[MIT License](./LICENSE) © 2026 Al Li

This project is for personal learning and research only. Please respect the terms of service of each content platform and your local copyright law; downloaded / transcribed content remains the property of its original author.
