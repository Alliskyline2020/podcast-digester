# 音频链接解析任务状态系统详细说明

## 概述

本文档详细说明了播客音频处理任务的7阶段状态系统，包括后端处理流程、前端显示逻辑、以及前后端数据交互。

---

## 后端处理阶段

### 阶段定义

| 阶段ID | 中文名称 | 权重 | 说明 |
|--------|----------|------|------|
| `download` | 下载 | 25% | 从URL/路径下载音频文件 |
| `transcribe` | 转录 | 25% | Whisper ASR语音转文字 |
| `chapterize` | 分章 | 12% | LLM智能分段并生成章节标题 |
| `summarize` | 摘要 | 20% | 为每个章节生成摘要和要点 |
| `translate` | 翻译 | 0% | 可选：翻译字幕为中文 |
| `highlight` | 亮点 | 18% | 提取亮点并给出收听建议 |
| `done` | 完成 | 0% | 持久化所有数据 |

### 总进度计算公式

```
总体进度 = Σ(各阶段权重 × 该阶段进度)

例如：下载完成50%，其他阶段未开始
总体进度 = 25% × 0.5 = 12.5%
```

---

## 数据库结构

### ingest_job 表

```sql
CREATE TABLE ingest_job (
    episode_id TEXT PRIMARY KEY,
    current_stage TEXT NOT NULL DEFAULT 'pending',  -- 当前阶段ID
    stages_json TEXT NOT NULL DEFAULT '[]',        -- 阶段数据JSON
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

### stages_json 格式

```json
[
  {
    "name": "download",           // 阶段ID
    "status": "downloading",      // 对应的EpisodeStatus
    "progress": 0.5,              // 进度 0-1
    "started_at": "2024-01-01T12:00:00",
    "completed_at": null,
    "error": null
  }
]
```

---

## API接口

### 1. 获取节目列表 `/api/episodes`

返回每个节目的进度信息：

```json
{
  "episodes": [
    {
      "id": "ep_1234567890",
      "title": "播客标题",
      "status": "downloading",
      "current_stage": "download",      // 当前阶段ID
      "overall_progress": 0.125,         // 总体进度 0-1
      "stages": [
        {
          "id": "download",              // 阶段ID（用于比较）
          "name": "下载",                  // 中文名称（用于显示）
          "status": "downloading",
          "progress": 0.5
        },
        {
          "id": "transcribe",
          "name": "转录",
          "status": "pending",
          "progress": 0.0
        }
      ]
    }
  ]
}
```

### 2. 获取节目详情 `/api/episode/{episode_id}`

返回完整 EpisodeBundle，包含 IngestJob（如果还在处理中）：

```json
{
  "episode": { ... },
  "transcript": { ... },
  "outline": { ... },
  "chapter_summaries": [ ... ],
  "highlight": { ... },
  "ingest_job": {
    "episode_id": "ep_1234567890",
    "current_stage": "download",
    "stages": [
      {
        "name": "download",
        "status": "downloading",
        "progress": 0.5,
        "started_at": "2024-01-01T12:00:00",
        "completed_at": null
      }
    ],
    "created_at": "2024-01-01T12:00:00",
    "updated_at": "2024-01-01T12:00:30"
  }
}
```

---

## 前端显示逻辑

### LibraryView.vue - 列表页

**阶段流程显示逻辑：**
```javascript
// 判断当前阶段的条件
stage.id === ep.current_stage  // 使用ID比较

// 判断已完成阶段
stage.progress >= 1

// 判断待处理阶段
stage.progress === 0 && stage.id !== ep.current_stage
```

**样式状态：**
- `stage-active`: 蓝色点 + 脉冲动画 + 加粗文字
- `stage-completed`: 绿色点 + 绿色文字
- `stage-pending`: 灰色点 + 灰色文字

### PlayerView.vue - 播放器页

**进度计算逻辑：**
```javascript
const stageWeights = {
  download: 25,
  transcribe: 25,
  chapterize: 12,
  summarize: 20,
  highlight: 18,
  translate: 0,  // 可选阶段不计入总进度
  done: 0
}

// 计算总体进度
for (const stage of stages) {
  if (stage.progress >= 1) {
    progress += stageWeights[stage.id]
  } else if (stage.id === currentStageId) {
    progress += stageWeights[stage.id] * stage.progress
  }
}
```

---

## 实时更新机制

### 后端进度更新

1. **阶段开始时**：调用 `_add_stage()` → 同步到数据库
2. **进行中更新**：调用 `_update_stage_progress_sync()` → 实时同步到数据库
3. **阶段完成时**：调用 `_complete_stage()` → 同步到数据库

### 前端轮询

- **轮询间隔**：1.5秒
- **轮询条件**：存在处理中的任务时
- **轮询停止**：所有任务都完成或失败时

```javascript
// LibraryView.vue
const startPolling = () => {
  loadEpisodes()
  pollInterval = setInterval(() => {
    const hasProcessing = episodes.value.some(ep =>
      isProcessing(ep.status)
    )
    if (hasProcessing) {
      loadEpisodes()
    }
  }, 1500)
}
```

---

## EpisodeStatus 状态映射

| EpisodeStatus | 显示文本 | 对应阶段 |
|---------------|----------|----------|
| `pending` | 等待中 | 任务刚创建，等待Worker处理 |
| `downloading` | 下载中 | download阶段 |
| `asr_running` | 转录中 | transcribe阶段 |
| `llm_running` | 分析中 | chapterize/summarize/highlight阶段 |
| `ready` | 完成 | done阶段 |
| `failed` | 失败 | 任意阶段出错 |

---

## 错误处理

### 阶段失败时的状态更新

```python
# 在 pipeline.py 的 _process_internal 中
try:
    await self._process_internal(...)
except Exception as e:
    # 通过 atomic write 处理
    # storage.py 会更新 episode.status = 'failed'
    logger.error(f"Processing failed: {e}")
```

### 前端错误显示

```html
<!-- 失败状态显示 -->
<div v-else-if="ep.status === 'failed'" class="error-info">
  <span>⚠️ 处理失败，请重试</span>
</div>
```

---

## 任务取消

### 取消流程

1. **pending状态**：直接标记为failed（任务还没开始）
2. **running状态**：调用 `pipeline.cancel()` 取消异步任务

### API接口

```
POST /api/episode/{episode_id}/cancel
```

### 前端确认对话框

```vue
<!-- 取消确认对话框 -->
<div v-if="showCancelDialog" class="dialog-overlay">
  <div class="dialog-box">
    <h3>确认取消</h3>
    <p>确定要取消节目「{{ episodeToCancel?.title }}」的处理吗？</p>
    <div class="dialog-actions">
      <button @click="cancelCancel">继续处理</button>
      <button @click="executeCancel">取消任务</button>
    </div>
  </div>
</div>
```

---

## 文件结构

```
backend/app/
├── pipeline.py          # 主处理管道
├── database.py          # IngestJobRepository
├── main.py              # API接口 + _load_progress_fast
├── storage.py           # EpisodeManager
└── models.py            # IngestStage, IngestJob, EpisodeStatus

frontend/src/
├── views/
│   ├── LibraryView.vue  # 列表页 + 进度显示
│   └── PlayerView.vue   # 播放器页 + 进度显示
└── api/
    └── index.js         # API调用封装
```

---

## 测试要点

1. **新建任务**：粘贴URL后立即显示"等待中"状态
2. **下载阶段**：进度条从0%增长到25%
3. **转录阶段**：进度从25%增长到50%
4. **分章阶段**：进度从50%增长到62%
5. **摘要阶段**：进度从62%增长到82%
6. **亮点阶段**：进度从82%增长到100%
7. **完成状态**：显示完成，停止轮询
8. **失败状态**：显示错误信息，停止轮询
9. **取消操作**：可以取消进行中的任务
10. **并发处理**：多个任务可以同时处理

---

## 注意事项

1. **阶段ID一致性**：前后端使用相同的阶段ID（download, transcribe等）
2. **进度更新频率**：避免过于频繁的数据库写入，当前每个阶段完成时才同步
3. **轮询优化**：只在有处理中任务时才轮询，节省资源
4. **错误恢复**：启动时恢复pending状态的任务（task_recovery.py）
5. **原子性写入**：使用.tmp文件 + os.rename确保数据一致性
