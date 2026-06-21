# Podcast Digester - 字幕同步与映射功能部署指南

> **版本:** v0.3.0  
> **发布日期:** 2025-06-15  
> **功能:** 字幕同步、分段映射、自动滚动

---

## 📋 目录

1. [功能概述](#功能概述)
2. [环境准备](#环境准备)
3. [数据库迁移](#数据库迁移)
4. [后端部署](#后端部署)
5. [前端部署](#前端部署)
6. [数据迁移](#数据迁移)
7. [回滚方案](#回滚方案)
8. [监控和验证](#监控和验证)

---

## 功能概述

### 新增功能

本版本新增以下字幕相关功能：

1. **字幕自动滚动**: 播放器跳转后，字幕列表自动滚动到当前播放位置对应的段落
2. **段落映射可视化**: 显示每个字幕段落包含的原始字幕数量和索引
3. **批量字幕同步**: 支持批量生成或更新字幕分段映射
4. **智能分段规则**: 可配置的字幕分段规则（最大/最小字符数、时间间隔阈值）
5. **降级兼容**: 对旧数据自动使用前端分段逻辑，确保功能可用

### 技术架构

```
Frontend (Vue 3)
    ├── useSubtitleScroll.js - 自动滚动 composable
    ├── SubtitleMapping.vue - 映射可视化组件
    └── PlayerView.vue - 播放器集成

Backend (FastAPI)
    ├── SubtitleSegmenter - 字幕分段服务
    ├── /api/episodes/{id}/sync-subtitles - 单个节目同步
    ├── /api/admin/batch-sync-subtitles - 批量同步
    └── paragraph_mappings JSON 字段 - 映射持久化

Database (SQLite)
    └── episodes.paragraph_mappings - 新增字段
```

---

## 环境准备

### 系统要求

- **操作系统**: Linux/macOS/Windows
- **Python**: 3.12+
- **Node.js**: 18+
- **数据库**: SQLite 3.38+

### 依赖检查

```bash
# 检查 Python 版本
python --version

# 检查 Node.js 版本
node --version

# 检查 SQLite 版本
sqlite3 --version
```

### 环境变量配置

创建 `backend/.env` 文件：

```bash
# 必需配置
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx

# 可选配置
DATABASE_URL=sqlite:///./data/podcast_digester.db
MEDIA_DIR=/path/to/data/media
LOG_LEVEL=INFO
```

---

## 数据库迁移

### 迁移文件位置

迁移文件位于: `/Users/alli/podcast-digester/backend/alembic/versions/`

### 执行迁移

```bash
# 1. 进入后端目录
cd /Users/alli/podcast-digester/backend

# 2. 激活虚拟环境
source venv/bin/activate  # Linux/macOS
# 或
venv\Scripts\activate  # Windows

# 3. 查看当前迁移状态
alembic current

# 4. 应用迁移
alembic upgrade head

# 5. 验证迁移
sqlite3 ../data/podcast_digester.db "PRAGMA table_info(episodes);"
```

### 预期输出

迁移成功后，`episodes` 表应包含以下新字段：

```sql
...
paragraph_mappings|JSON|YES||NULL
...
```

### 迁移回滚

如需回滚数据库迁移：

```bash
alembic downgrade -1
```

---

## 后端部署

### 1. 安装依赖

```bash
cd /Users/alli/podcast-digester/backend

# 安装 Python 依赖
pip install -r requirements.txt

# 验证安装
pip list | grep -E "fastapi|uvicorn|pydantic"
```

### 2. 数据库初始化

```bash
# 初始化数据库
python -c "from app.database import init_db; init_db()"

# 验证数据库
sqlite3 ../data/podcast_digester.db ".tables"
```

### 3. 启动后端服务

**开发模式:**

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

**生产模式:**

```bash
# 使用 gunicorn (推荐)
gunicorn app.main:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 0.0.0.0:8000 \
  --access-logfile - \
  --error-logfile -
```

**使用 Docker:**

```dockerfile
# Dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

```bash
# 构建镜像
docker build -t podcast-digester-backend .

# 运行容器
docker run -d \
  --name podcast-backend \
  -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  -e DEEPSEEK_API_KEY=your_key_here \
  podcast-digester-backend
```

### 4. 验证后端部署

```bash
# 健康检查
curl http://localhost:8000/

# 访问 API 文档
open http://localhost:8000/docs

# 测试字幕同步 API
curl -X POST http://localhost:8000/api/episodes/test-id/sync-subtitles
```

---

## 前端部署

### 1. 安装依赖

```bash
cd /Users/alli/podcast-digester/frontend

# 安装 Node.js 依赖
npm install

# 验证安装
npm list | grep -E "vue|vite"
```

### 2. 环境配置

创建 `frontend/.env.production` 文件：

```bash
VITE_API_BASE_URL=https://your-domain.com/api
VITE_APP_TITLE=Podcast Digester
```

### 3. 构建生产版本

```bash
# 构建生产版本
npm run build

# 验证构建
ls -la dist/
```

### 4. 部署静态文件

**使用 Nginx:**

```nginx
server {
    listen 80;
    server_name your-domain.com;
    root /var/www/podcast-digester/frontend/dist;
    index index.html;

    # 前端路由
    location / {
        try_files $uri $uri/ /index.html;
    }

    # API 代理
    location /api {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # 静态资源缓存
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
```

**使用 Docker:**

```dockerfile
# Dockerfile
FROM node:18-alpine as build

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
```

### 5. 启动前端服务

**开发模式:**

```bash
npm run dev
```

**生产模式:**

```bash
# 使用 serve
npm install -g serve
serve -s dist -l 3000

# 或直接使用 nginx
systemctl start nginx
```

### 6. 验证前端部署

```bash
# 访问前端
open http://localhost:3000

# 检查浏览器控制台是否有错误
# 验证 API 请求是否正常
```

---

## 数据迁移

### 批量同步现有字幕

对于已有字幕数据的节目，需要批量生成段落映射：

```bash
# 使用 curl
curl -X POST http://localhost:8000/api/admin/batch-sync-subtitles \
  -H "Content-Type: application/json" \
  -d '{
    "episode_ids": ["ep_001", "ep_002", "ep_003"]
  }'

# 使用 Python
python -c "
import requests

response = requests.post(
    'http://localhost:8000/api/admin/batch-sync-subtitles',
    json={'episode_ids': ['ep_001', 'ep_002', 'ep_003']}
)

print(f'Total: {response.json()[\"total\"]}')
print(f'Successful: {len(response.json()[\"successful\"])}')
print(f'Failed: {len(response.json()[\"failed\"])}')
"
```

### 验证数据迁移

```bash
# 查询节目详情
curl http://localhost:8000/api/episode/ep_001 | jq '.paragraph_mappings'

# 验证数据库
sqlite3 ../data/podcast_digester.db "
SELECT id, 
       json_array_length(paragraph_mappings) as paragraph_count 
FROM episodes 
WHERE paragraph_mappings IS NOT NULL;"
```

---

## 回滚方案

### 数据库回滚

```bash
# 回滚数据库迁移
cd /Users/alli/podcast-digester/backend
alembic downgrade -1
```

### 代码回滚

```bash
# 回滚到上一个版本
git tag  # 查看版本标签
git checkout v0.2.1-m2p  # 切换到旧版本
```

### 数据恢复

```bash
# 1. 停止服务
./stop.sh

# 2. 恢复数据库备份
cp ../data/podcast_digester.db.backup ../data/podcast_digester.db

# 3. 重启服务
./start.sh
```

### 前端回滚

```bash
# 重新构建旧版本
cd /Users/alli/podcast-digester/frontend
git checkout v0.2.1-m2p
npm run build

# 部署旧版本
rm -rf /var/www/podcast-digester/frontend/dist/*
cp -r dist/* /var/www/podcast-digester/frontend/dist/
```

---

## 监控和验证

### 健康检查

```bash
# 后端健康检查
curl http://localhost:8000/

# 预期输出
{
  "name": "Podcast Digester",
  "version": "0.3.0",
  "status": "healthy"
}
```

### 功能验证清单

#### 后端 API

- [ ] `GET /api/episodes/{id}` 返回 `paragraph_mappings` 字段
- [ ] `POST /api/episodes/{id}/sync-subtitles` 成功生成段落映射
- [ ] `POST /api/admin/batch-sync-subtitles` 批量同步成功
- [ ] 段落映射包含 `segment_indices` 和 `segment_ids`
- [ ] 时间戳正确（`start_ms`, `end_ms`）

#### 前端功能

- [ ] 播放器页面加载正常
- [ ] 字幕 tab 显示段落列表
- [ ] 每个段落显示"X 段原始字幕"标识
- [ ] 点击可展开查看原始字幕详情
- [ ] 播放器跳转后字幕自动滚动到对应位置
- [ ] 滚动行为流畅，无卡顿

#### 降级兼容

- [ ] 旧节目（无 `paragraph_mappings`）仍可正常显示
- [ ] 前端分段逻辑正确生成段落
- [ ] 控制台无错误日志

### 性能监控

```bash
# 后端性能测试
ab -n 1000 -c 10 http://localhost:8000/api/episodes

# 批量同步性能测试
time curl -X POST http://localhost:8000/api/admin/batch-sync-subtitles \
  -H "Content-Type: application/json" \
  -d '{"episode_ids": ["ep_001", "ep_002", "ep_003"]}'
```

### 日志监控

```bash
# 后端日志
tail -f /var/log/podcast-digester/backend.log

# 前端日志（浏览器控制台）
# 查找 [PlayerView]、[useSubtitleScroll] 标签
```

---

## 常见问题

### Q1: 迁移失败 "duplicate column name"

**原因:** 字段已存在

**解决:**
```bash
# 查看当前迁移版本
alembic current

# 标记迁移为完成（不实际执行 SQL）
alembic stamp head
```

### Q2: 批量同步后段落映射为空

**原因:** 字幕文件不存在或格式错误

**解决:**
```bash
# 检查字幕文件
ls -la ../data/media/*/transcript.json

# 验证字幕格式
cat ../data/media/ep_001/transcript.json | jq '.segments'
```

### Q3: 前端自动滚动不工作

**原因:** 容器 ref 或数据未正确加载

**解决:**
```javascript
// 在浏览器控制台调试
console.log('Container:', transcriptContainer.value)
console.log('Paragraphs:', paragraphs.value)
console.log('Current time:', currentTime.value)
```

### Q4: CORS 错误

**原因:** 跨域配置问题

**解决:**
```python
# backend/app/main.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://your-domain.com"],  # 修改为实际域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## 技术支持

如有问题，请参考以下资源：

- **项目文档:** `/Users/alli/podcast-digester/docs/`
- **API 文档:** http://localhost:8000/docs
- **测试报告:** `/Users/alli/podcast-digester/backend/htmlcov/index.html`

---

**部署完成后，请参考以下文档继续配置:**

- [安全加固指南](./security-hardening.md)
- [用户使用指南](./user-guide.md)
- [功能测试清单](./testing-checklist.md)
