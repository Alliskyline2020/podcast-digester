# 🚀 Podcast Digester 项目启动指南

## ✅ 当前状态

### 后端服务
- **状态**: ✅ 运行中
- **地址**: http://localhost:8000
- **进程ID**: 2086
- **日志**: /tmp/backend.log

### 前端服务
- **状态**: ⏳ 待启动
- **技术栈**: Vite + Vue 3

---

## 🎯 快速启动

### 1. 后端服务（已启动）✅

**访问地址**: http://localhost:8000

**API文档**: http://localhost:8000/docs

**健康检查**:
```bash
curl http://localhost:8000/api/episodes
```

**查看日志**:
```bash
tail -f /tmp/backend.log
```

### 2. 前端服务（需要启动）

```bash
# 进入前端目录
cd /Users/alli/podcast-digester/frontend

# 启动开发服务器
npm run dev
```

**访问地址**: http://localhost:5173

---

## 🧪 验证步骤

### 后端API验证

#### 1. 测试基础API
```bash
# 获取所有节目
curl http://localhost:8000/api/episodes

# 获取单个节目详情
curl http://localhost:8000/api/episode/ep_1781109978390

# 获取字幕
curl http://localhost:8000/api/episodes/ep_1781109978390/transcript
```

#### 2. 测试词库功能
```bash
# 获取词库
curl http://localhost:8000/api/glossary/entries

# 字幕纠错
curl -X POST http://localhost:8000/api/glossary/correct \
  -H "Content-Type: application/json" \
  -d '{"episode_id": "ep_1781109978390"}'
```

#### 3. 测试批量同步
```bash
# 批量同步字幕分段
curl -X POST http://localhost:8000/api/admin/batch-sync-subtitles \
  -H "Content-Type: application/json" \
  -d '{"episode_ids": ["ep_1781109978390"]}'
```

### 前端验证

启动前端后，在浏览器中测试：

1. **基础功能**
   - [ ] 页面正常加载
   - [ ] 节目列表显示
   - [ ] 播放器能播放音频
   - [ ] 字幕正常显示

2. **字幕编辑**
   - [ ] 打开字幕编辑器
   - [ ] 修改segment并保存
   - [ ] 刷新后修改生效

3. **词库纠错**
   - [ ] 查看词库条目
   - [ ] 一键纠错功能
   - [ ] 添加新词库条目

4. **导出功能**
   - [ ] 导出摘要卡片
   - [ ] 数据使用最新版本

---

## 📊 系统状态

### 测试状态
```
✅ 88/88 测试通过 (100%)
   - test_text_cleaners.py: 41/41 ✅
   - test_subtitle_segmenter.py: 9/9 ✅
   - test_database.py: 10/10 ✅
   - test_admin_api.py: 8/8 ✅
```

### 数据库状态
```
✅ outline (1条记录)
✅ summaries (1条记录)
✅ highlight (1条记录)
✅ product_insights (1条记录)
✅ glossary (8条记录)
```

### 已完成的优化
```
✅ Phase 1: 数据一致性 - 派生数据统一存储在数据库
✅ Phase 2: 并发安全 - 词库使用SQLite，自带并发保护
✅ P0级别: N+1查询、事务处理、错误处理、输入验证
✅ P1级别: 代码去重、测试基础设施
✅ Bug修复: HTML清洗、segment拼接、episode_id格式
```

---

## 🔧 管理命令

### 后端服务

**重启后端**:
```bash
# 停止旧服务
pkill -f "uvicorn.*app.main:app"

# 启动新服务
cd /Users/alli/podcast-digester/backend
nohup python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload > /tmp/backend.log 2>&1 &
```

**查看日志**:
```bash
tail -f /tmp/backend.log
```

### 前端服务

**启动前端**:
```bash
cd /Users/alli/podcast-digester/frontend
npm run dev
```

**停止前端**: Ctrl+C

---

## 📝 重要文件

### 后端
- `/Users/alli/podcast-digester/backend/app/main.py` - 主应用
- `/Users/alli/podcast-digester/backend/app/utils/text_cleaners.py` - 文本清洗工具
- `/Users/alli/podcast-digester/backend/tests/` - 测试文件

### 前端
- `/Users/alli/podcast-digester/frontend/src/` - 源代码
- `/Users/alli/podcast-digester/frontend/package.json` - 依赖配置

---

## 🎨 下一步

1. **启动前端验证** - 在浏览器中测试所有功能
2. **检查数据一致性** - 确认派生数据正确加载
3. **测试词库纠错** - 验证纠错功能正常工作
4. **性能测试** - 检查页面加载和响应速度

---

**项目状态**: ✅ 后端已启动，所有测试通过，等待前端验证
