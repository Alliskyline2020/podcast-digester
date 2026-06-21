#!/bin/bash
# 项目启动脚本
# 快速启动前端和后端服务

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"

echo "🚀 启动 Podcast Digester..."
echo ""

# 检查后端环境
if [ ! -d "$BACKEND_DIR/venv" ]; then
    echo "❌ 后端虚拟环境不存在，请先创建："
    echo "   cd $BACKEND_DIR"
    echo "   python3 -m venv venv"
    echo "   source venv/bin/activate"
    echo "   pip install -r requirements.txt"
    exit 1
fi

if [ ! -f "$BACKEND_DIR/.env" ]; then
    echo "⚠️  后端.env不存在，正在从.env.example创建..."
    cp "$BACKEND_DIR/.env.example" "$BACKEND_DIR/.env"
    echo "   请编辑 $BACKEND_DIR/.env 并配置 DEEPSEEK_API_KEY"
fi

# 检查前端依赖
if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    echo "❌ 前端依赖未安装，请先安装："
    echo "   cd $FRONTEND_DIR"
    echo "   npm install"
    exit 1
fi

# 启动后端
echo "1️⃣ 启动后端服务..."
cd "$BACKEND_DIR"
source venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!
echo "   后端PID: $BACKEND_PID"
echo ""

# 等待后端启动
sleep 3

# 验证后端
if curl -s http://127.0.0.1:8000/ > /dev/null; then
    echo "   ✅ 后端启动成功 (http://127.0.0.1:8000)"
else
    echo "   ❌ 后端启动失败"
    exit 1
fi

# 启动前端
echo ""
echo "2️⃣ 启动前端服务..."
cd "$FRONTEND_DIR"
npm run dev &
FRONTEND_PID=$!
echo "   前端PID: $FRONTEND_PID"
echo ""

# 等待前端启动
sleep 3

# 验证前端
if curl -s http://localhost:5173/ > /dev/null; then
    echo "   ✅ 前端启动成功 (http://localhost:5173)"
else
    echo "   ❌ 前端启动失败"
    exit 1
fi

echo ""
echo "🎉 项目启动完成！"
echo ""
echo "📍 访问地址："
echo "   前端: http://localhost:5173"
echo "   后端: http://127.0.0.1:8000"
echo ""
echo "📋 可用命令："
echo "   查看后端日志: tail -f $BACKEND_DIR/uvicorn.log"
echo "   停止服务: kill $BACKEND_PID $FRONTEND_PID"
echo ""
echo "💡 提示："
echo "   - 按 Ctrl+C 停止当前窗口的服务"
echo "   - 使用 ./stop.sh 停止所有服务"
echo ""

# 保存PID
echo "$BACKEND_PID" > "$PROJECT_ROOT/.backend_pid"
echo "$FRONTEND_PID" > "$PROJECT_ROOT/.frontend_pid"

echo "✅ PID已保存到 .backend_pid 和 .frontend_pid"
