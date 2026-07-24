#!/usr/bin/env bash
# 项目启动脚本：一键启动后端 API + 前端 + Worker（全部后台 nohup + 日志落盘）。
#
# 用法：
#   ./start.sh             # 启动 API + 前端 + Worker
#   ./start.sh --no-worker # 只启动 API + 前端（Worker 想单独手动控制时用）
#
# 日志：logs/{uvicorn,frontend,worker}.log
# PID： .backend_pid / .frontend_pid / .worker_pid（均已 gitignore）
# 停止：./stop.sh（会一并停 Worker）

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
LOG_DIR="$PROJECT_ROOT/logs"
PY="$BACKEND_DIR/venv/bin/python"
START_WORKER=1

if [ "${1:-}" = "--no-worker" ]; then
  START_WORKER=0
fi

mkdir -p "$LOG_DIR"

# 就绪轮询：每 0.5s 探一次 URL，最多 ~30s；期间进程退出则立即失败并 tail 日志。
wait_for_http() {
  local url="$1" name="$2" log="$3" pid="$4" tries=60 i
  for i in $(seq 1 "$tries"); do
    if ! kill -0 "$pid" 2>/dev/null; then
      echo "   ❌ $name 进程已退出，最近日志："
      tail -n 20 "$log" 2>/dev/null || true
      return 1
    fi
    if curl -fsS "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.5
  done
  echo "   ❌ $name 在 30s 内未就绪，最近日志："
  tail -n 20 "$log" 2>/dev/null || true
  return 1
}

echo "🚀 启动 Podcast Digester..."
echo ""

# 前置检查
if [ ! -d "$BACKEND_DIR/venv" ]; then
  echo "❌ backend/venv 不存在，请先运行：./setup.sh"
  exit 1
fi
if [ ! -f "$BACKEND_DIR/.env" ]; then
  echo "⚠️  backend/.env 不存在，从 .env.example 创建（记得填 LLM_API_KEY）"
  cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
fi
if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  echo "❌ frontend/node_modules 不存在，请先运行：./setup.sh（或 cd frontend && npm install）"
  exit 1
fi

# ---- 1. 后端 API ----
echo "1️⃣  启动后端 API..."
cd "$BACKEND_DIR"
nohup "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 \
  > "$LOG_DIR/uvicorn.log" 2>&1 &
BACKEND_PID=$!
echo "$BACKEND_PID" > "$PROJECT_ROOT/.backend_pid"
echo "   PID $BACKEND_PID → logs/uvicorn.log"
if wait_for_http http://127.0.0.1:8000/ "后端 API" "$LOG_DIR/uvicorn.log" "$BACKEND_PID"; then
  echo "   ✅ 后端就绪 (http://127.0.0.1:8000)"
else
  exit 1
fi

# ---- 2. 前端 ----
echo "2️⃣  启动前端..."
cd "$FRONTEND_DIR"
nohup npm run dev > "$LOG_DIR/frontend.log" 2>&1 &
FRONTEND_PID=$!
echo "$FRONTEND_PID" > "$PROJECT_ROOT/.frontend_pid"
echo "   PID $FRONTEND_PID → logs/frontend.log"
if wait_for_http http://localhost:5173/ "前端" "$LOG_DIR/frontend.log" "$FRONTEND_PID"; then
  echo "   ✅ 前端就绪 (http://localhost:5173)"
else
  exit 1
fi

# ---- 3. Worker ----
if [ "$START_WORKER" = "1" ]; then
  echo "3️⃣  启动 Worker..."
  cd "$BACKEND_DIR"
  EXISTING_WORKER_PID=""
  [ -f "$PROJECT_ROOT/.worker_pid" ] && EXISTING_WORKER_PID=$(cat "$PROJECT_ROOT/.worker_pid" 2>/dev/null || true)
  if [ -n "$EXISTING_WORKER_PID" ] && kill -0 "$EXISTING_WORKER_PID" 2>/dev/null; then
    echo "   ⊘ Worker 已在运行 (PID $EXISTING_WORKER_PID)，跳过"
  else
    nohup "$PY" worker.py > "$LOG_DIR/worker.log" 2>&1 &
    WORKER_PID=$!
    echo "$WORKER_PID" > "$PROJECT_ROOT/.worker_pid"
    # Worker 无 HTTP 端点；给它 1s，确认没因「锁被占」立即自退
    sleep 1
    if kill -0 "$WORKER_PID" 2>/dev/null; then
      echo "   ✅ Worker 就绪 (PID $WORKER_PID) → logs/worker.log"
    else
      echo "   ⚠️  Worker 未启动（可能已有实例持有锁），详见 logs/worker.log"
      tail -n 10 "$LOG_DIR/worker.log" 2>/dev/null || true
    fi
  fi
fi

echo ""
echo "🎉 启动完成！"
echo "   前端: http://localhost:5173"
echo "   后端: http://127.0.0.1:8000"
echo "   日志: tail -f logs/uvicorn.log | logs/frontend.log | logs/worker.log"
echo "   停止: ./stop.sh"
