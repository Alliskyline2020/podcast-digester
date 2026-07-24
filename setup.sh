#!/usr/bin/env bash
# 一键安装脚本 —— 把所有"隐藏步骤"收敛成一条命令：
#   venv → pip 依赖 → Playwright 浏览器 → Apple AFM3 桥接 → 前端依赖 → .env
# 可重复运行（幂等）。适合新机器首次部署。
#
# 用法：  ./setup.sh
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

# 简易彩色输出
c_ok()   { printf '\033[0;32m%s\033[0m\n'   "$*"; }
c_warn() { printf '\033[0;33m%s\033[0m\n'   "$*"; }
c_step() { printf '\033[0;36m%s\033[0m\n'   "$*"; }

echo "🔧 Podcast Digester 一键安装"
echo

# ── 前置检查 ──
need() { command -v "$1" >/dev/null 2>&1 || { echo "❌ 缺少 $1，请先安装后重跑"; exit 1; }; }
need node

# Python：必须 3.11–3.13。3.14 目前缺部分依赖的预编译 wheel（faster-whisper→av、
# pydantic-core、greenlet），回退源码构建会失败。注意：脚本里 `python3` 不吃交互
# shell 的 alias，可能解析到系统默认的 3.14，所以这里主动挑一个兼容版本。
PYBIN=""
for cand in python3.13 python3.12 python3.11; do
  command -v "$cand" >/dev/null 2>&1 && { PYBIN="$cand"; break; }
done
# 兜底：若裸 python3 本身就在 3.11–3.13 区间，直接用它
if [ -z "$PYBIN" ] && python3 -c 'import sys;sys.exit(0 if (3,11)<=sys.version_info<(3,14) else 1)' 2>/dev/null; then
  PYBIN=python3
fi
if [ -z "$PYBIN" ]; then
  echo "❌ 需要 Python 3.11–3.13。当前 python3 = $(python3 --version 2>&1)。"
  echo "   Python 3.14 暂不兼容（faster-whisper / pydantic 等缺预编译 wheel）。"
  echo "   安装兼容版本：  brew install python@3.12    （或用 pyenv 装 3.13）"
  exit 1
fi
node -e "process.exit(Number(process.version.slice(1).split('.')[0])>=18?0:1)" \
  || { echo "❌ 需要 Node 18+，当前 $(node -v)"; exit 1; }
c_ok "✓ Python $("$PYBIN" --version 2>&1 | awk '{print $2}')  /  Node $(node -v)"

# ffmpeg：yt-dlp 后处理需要，缺失只警告不阻断
if command -v ffmpeg >/dev/null 2>&1; then
  c_ok "✓ ffmpeg 已安装"
else
  c_warn "⚠️  未检测到 ffmpeg（yt-dlp 后处理需要）。macOS: brew install ffmpeg  |  Linux: sudo apt install ffmpeg"
fi
# 代理提示：pip / playwright / npm 均遵从 HTTPS_PROXY 环境变量。
# 中国大陆网络下若依赖下载失败，先 export HTTPS_PROXY=http://127.0.0.1:7897 再重跑。
if [ -z "${HTTPS_PROXY:-}" ] && [ -z "${https_proxy:-}" ]; then
  c_warn "ⓘ  未检测到 HTTPS_PROXY：若 pip/playwright/npm 下载失败，请 export HTTPS_PROXY 后重跑"
fi
echo

# ── 1. 后端虚拟环境 + Python 依赖 ──
c_step "1/5  后端虚拟环境 + Python 依赖"
cd "$BACKEND_DIR"
[ -d venv ] || "$PYBIN" -m venv venv
# shellcheck disable=SC1091
source venv/bin/activate
python -m pip install -q --upgrade pip
pip install -q -r requirements.txt
c_ok "   ✓ Python 依赖已安装"

# ── 2. Playwright 浏览器（CDP 抓取 / 小宇宙等需要，pip 不会自动装浏览器二进制）──
c_step "2/5  Playwright 浏览器（chromium）"
python -m playwright install chromium
c_ok "   ✓ chromium 就绪"

# ── 3. Apple AFM3 语音识别桥接（macOS 转录"无字幕源"需要）──
c_step "3/5  Apple AFM3 语音识别桥接"
if [ "$(uname)" = "Darwin" ]; then
  if ./tools/build_apple_asr.sh; then
    c_ok "   ✓ 桥接编译成功"
  else
    c_warn "   ⚠️  AFM 编译失败（可能缺 Xcode/命令行工具，或未装 macOS 26 SDK）。"
    c_warn "      不影响「带平台字幕」的源（YouTube/B 站等有 CC 的内容）；"
    c_warn "      仅「无字幕源需 ASR 转录」时会用到，届时再解决。"
  fi
else
  echo "   ⊘ 非 macOS，跳过（Linux/WSL 仅支持自带平台字幕的源）"
fi

# ── 4. 前端依赖 ──
c_step "4/5  前端依赖"
cd "$FRONTEND_DIR"
# --include=dev 兜底：部分机器全局设了 NODE_ENV=production，导致 npm 跳过 devDependencies（vite 等）
npm install --include=dev
c_ok "   ✓ 前端依赖已安装"

# ── 5. 配置文件 ──
c_step "5/5  配置文件"
cd "$BACKEND_DIR"
if [ -f .env ]; then
  echo "   ✓ .env 已存在，保留（如需改 provider 见 README「可插拔 LLM」）"
else
  cp .env.example .env
  c_warn "   ✓ 已从模板创建 .env —— 记得填入 LLM_API_KEY"
fi

echo
c_ok "🎉 安装完成！"
echo
echo "下一步："
echo "  1. 编辑 $BACKEND_DIR/.env，至少填入 LLM_API_KEY（默认 provider=deepseek）"
echo "  2. 一键启动 API + 前端 + Worker：  ./start.sh"
echo "     （只想起 API+前端、Worker 单独控制：  ./start.sh --no-worker）"
echo "  3. 浏览器打开 http://localhost:5173 ，粘贴一个播客/视频链接即可"
echo "  4. 停止：  ./stop.sh     日志：  tail -f logs/uvicorn.log logs/frontend.log logs/worker.log"
echo
c_ok "提示：./start.sh 默认会一并后台启动 Worker（写 .worker_pid，日志在 logs/）；停止用 ./stop.sh。"
