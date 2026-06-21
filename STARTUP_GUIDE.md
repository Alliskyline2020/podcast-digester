# 🚀 Podcast Digester 项目启动指南

## ✅ 服务状态

**当前服务状态：**
- ✅ 后端: http://127.0.0.1:8000 (healthy)
- ✅ 前端: http://localhost:5173 (running)
- ✅ API: 所有端点正常响应
- ✅ 测试: 25个测试全部通过，覆盖率38%

## 📋 快速启动

### 方法1：使用启动脚本（推荐）

```bash
# 启动所有服务
./start.sh

# 停止所有服务
./stop.sh

# 健康检查
python3 health_check.py
```

### 方法2：手动启动

```bash
# 终端1 - 启动后端
cd backend
source venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000

# 终端2 - 启动前端
cd frontend
npm run dev
```

## 🎯 访问地址

- **前端界面**: http://localhost:5173
- **后端API**: http://127.0.0.1:8000
- **API文档**: http://127.0.0.1:8000/docs
- **健康检查**: http://127.0.0.1:8000/

## 📊 当前状态

### 数据库
- 28个节目记录（大部分是测试数据，状态为failed）

### 配置要求
后端需要`.env`文件配置（`backend/.env`）：
```bash
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
```

### 功能验证
✅ 后端健康检查正常
✅ 前端页面加载正常
✅ API端点响应正常
✅ 粘贴功能可以创建新节目
⚠️ 现有节目处理失败（需要配置DEEPSEEK_API_KEY）

## 🧪 测试

```bash
# 运行所有测试
cd backend
pytest tests/ -v

# 运行测试并生成覆盖率报告
pytest tests/ --cov=app --cov-report=html

# 查看覆盖率报告
open htmlcov/index.html
```

## 🔧 故障排查

### 后端启动失败
```bash
# 检查端口占用
lsof -i:8000

# 检查虚拟环境
cd backend
source venv/bin/activate
pip list
```

### 前端启动失败
```bash
# 检查端口占用
lsof -i:5173

# 重新安装依赖
cd frontend
rm -rf node_modules
npm install
```

### API请求失败
```bash
# 检查后端日志
tail -f backend/uvicorn.log

# 测试API连接
curl http://127.0.0.1:8000/
```

### 节目处理失败
```bash
# 检查配置
cat backend/.env | grep DEEPSEEK

# 测试API密钥
curl https://api.deepseek.com/v1/models \
  -H "Authorization: Bearer $DEEPSEEK_API_KEY"
```

## 📁 项目结构

```
podcast-digester/
├── backend/              # 后端（FastAPI）
│   ├── app/
│   ├── venv/           # Python虚拟环境
│   ├── .env             # 配置文件
│   └── tests/           # 测试文件
├── frontend/             # 前端（Vue 3）
│   ├── src/
│   │   ├── composables/  # 全局状态管理
│   │   ├── components/   # Vue组件
│   │   └── views/        # 页面视图
│   └── node_modules/    # 前端依赖
├── data/                 # 数据目录
│   ├── podcast_digester.db
│   └── media/            # 节目媒体文件
├── fixtures/            # Fixture示例节目（待创建）
├── start.sh             # 启动脚本
├── stop.sh              # 停止脚本
└── health_check.py     # 健康检查脚本
```

## 🎯 下一步操作

1. **配置API密钥**
   ```bash
   # 编辑 backend/.env
   nano backend/.env
   # 添加: DEEPSEEK_API_KEY=sk-...
   ```

2. **访问前端界面**
   打开浏览器访问 http://localhost:5173

3. **测试完整流程**
   - 粘贴播客URL（支持YouTube/Bilibili/小宇宙）
   - 等待处理完成
   - 在播放器中查看章节大纲、字幕、亮点

4. **查看测试覆盖率**
   - 运行 `pytest tests/ --cov=app --cov-report=html`
   - 浏览器打开 `htmlcov/index.html`

## 📝 功能清单

### 已实现 ✅
- [x] 多源支持（YouTube、Bilibili、抖音、小宇宙、本地文件）
- [x] ASR转录（faster-whisper）
- [x] LLM分析（DeepSeek）
- [x] 虚拟滚动字幕
- [x] 章节大纲
- [x] 亮点提炼
- [x] 章节摘要
- [x] 键盘快捷键（空格、方向键、j/k）
- [x] 全局状态管理
- [x] 统一错误处理
- [x] 并发控制
- [x] 测试框架

### 已修复 ⚠️
- [x] VTT解析时间戳
- [x] Repository数据库访问
- [x] 组件化架构
- [x] 配置管理集中化

### 待优化 📋
- [ ] Fixture示例节目数据创建
- [ ] LLM成本控制
- [ ] 结构化日志
- [ ] API限流
- [ ] 测试覆盖率提升至60%+

---

*项目版本: v0.2.1-m2p*
*最后更新: 2025-01-10*
