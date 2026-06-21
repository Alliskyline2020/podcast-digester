#!/bin/bash
# 停止项目服务

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "🛑 停止 Podcast Digester 服务..."
echo ""

# 读取PID
if [ -f "$PROJECT_ROOT/.backend_pid" ]; then
    BACKEND_PID=$(cat "$PROJECT_ROOT/.backend_pid")
    echo "停止后端 (PID: $BACKEND_PID)..."
    kill $BACKEND_PID 2>/dev/null || echo "   ⚠️  后端进程已停止"
    rm "$PROJECT_ROOT/.backend_pid"
fi

if [ -f "$PROJECT_ROOT/.frontend_pid" ]; then
    FRONTEND_PID=$(cat "$PROJECT_ROOT/.frontend_pid")
    echo "停止前端 (PID: $FRONTEND_PID)..."
    kill $FRONTEND_PID 2>/dev/null || echo "   ⚠️  前端进程已停止"
    rm "$PROJECT_ROOT/.frontend_pid"
fi

# 额外清理：确保端口8000和5173的进程被终止
echo ""
echo "清理端口进程..."

# 查找并终止uvicorn进程
UVICORN_PIDS=$(ps aux | grep uvicorn | grep -v grep | awk '{print $2}')
if [ -n "$UVICORN_PIDS" ]; then
    echo "  停止 uvicorn 进程: $UVICORN_PIDS"
    echo "$UVICORN_PIDS" | xargs kill 2>/dev/null
fi

# 查找并终止vite/node进程
VITE_PIDS=$(lsof -ti:5173 2>/dev/null)
if [ -n "$VITE_PIDS" ]; then
    echo "  停止 vite 进程 (端口5173)"
    kill $VITE_PIDS 2>/dev/null || echo "   ⚠️  vite进程已停止"
fi

echo ""
echo "✅ 服务已停止"
