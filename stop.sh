#!/usr/bin/env bash
# 停止项目服务（后端 API + 前端 + Worker）。
# 优先 SIGTERM 优雅退出（Worker 收到 SIGTERM 会跑完当前轮再退）；~5s 未退则 SIGKILL。

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "🛑 停止 Podcast Digester 服务..."
echo ""

# 优雅停一个 PID：SIGTERM → 轮询 ~5s → SIGKILL 兜底
stop_pid() {
  local pid="$1" name="$2" i
  [ -z "$pid" ] && return 0
  if kill -0 "$pid" 2>/dev/null; then
    echo "停止 $name (PID $pid)..."
    kill -TERM "$pid" 2>/dev/null || true
    for i in $(seq 1 20); do
      kill -0 "$pid" 2>/dev/null || return 0
      sleep 0.25
    done
    echo "   $name 未在 ~5s 内退出，SIGKILL"
    kill -KILL "$pid" 2>/dev/null || true
  fi
}

# 1. 按 PID 文件停（三个 PID 文件均由 start.sh 写入）
for pair in ".backend_pid:后端 API" ".frontend_pid:前端" ".worker_pid:Worker"; do
  file="${pair%%:*}"
  name="${pair##*:}"
  if [ -f "$PROJECT_ROOT/$file" ]; then
    stop_pid "$(cat "$PROJECT_ROOT/$file" 2>/dev/null)" "$name"
    rm -f "$PROJECT_ROOT/$file"
  fi
done

# 2. 兜底：按进程名/端口清理漏网进程（手动起的、或 PID 文件丢失的）
echo ""
echo "兜底清理..."
# 按端口清理后端（不按进程名 grep —— 同机其他项目若也用 app.main:app 入口
# 会被误伤，例如 stock-dashboard:8765；按本项目端口 8000 才精准）
BACKEND_PIDS=$(lsof -ti:8000 2>/dev/null || true)
if [ -n "$BACKEND_PIDS" ]; then
  echo "  停止端口 8000: $BACKEND_PIDS"
  echo "$BACKEND_PIDS" | xargs kill -TERM 2>/dev/null || true
fi
VITE_PIDS=$(lsof -ti:5173 2>/dev/null || true)
if [ -n "$VITE_PIDS" ]; then
  echo "  停止端口 5173: $VITE_PIDS"
  echo "$VITE_PIDS" | xargs kill -TERM 2>/dev/null || true
fi
# worker 兜底（.worker_pid 丢失/手动起时）：-f 搜全命令行，可匹配 macOS framework
# python 显示的 "MacOS/Python worker.py"（旧的小写 [p]ython grep 会漏匹配）
WORKER_PIDS=$(pgrep -f "worker\.py" 2>/dev/null || true)
if [ -n "$WORKER_PIDS" ]; then
  echo "  停止 worker: $WORKER_PIDS"
  echo "$WORKER_PIDS" | xargs kill -TERM 2>/dev/null || true
fi

echo ""
echo "✅ 服务已停止"
