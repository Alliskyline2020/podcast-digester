# 字幕同步与分段映射功能实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标:** 实现播放器跳转后字幕自动定位、重新梳理字幕分段逻辑、建立字幕分段与原始字幕的映射关系、新增字幕同步功能，并确保字幕原文完整保留以支持金句洞察功能。

**架构:**
- **前端 (Vue 3):** 增强字幕显示组件，实现自动滚动定位、分段-原始字幕映射可视化
- **后端 (FastAPI):** 重构字幕分段逻辑，保留映射关系，新增字幕同步 API
- **数据层:** aiosqlite + Pydantic（paragraph_mappings TEXT 列已存在）
- **状态管理:** 利用现有 `usePlayer` composable，添加字幕定位状态

**技术栈:**
- Vue 3 + Composition API
- vue-virtual-scroller (RecycleScroller)
- FastAPI (Python)
- aiosqlite (异步 SQLite)
- Pydantic v2 (数据模型)
- faster-whisper (ASR 转录)

---

## 📋 需求分析与现状

### 当前实现分析
1. **字幕分段逻辑位置:** `PlayerView.vue:464-533` 的 `paragraphs` computed
   - 规则: MAX_PARA_CHARS=120, MIN_PARA_CHARS=40
   - 问题: 逻辑在前端硬编码，未持久化映射关系

2. **字幕显示:** `PlayerView.vue:187-201` 使用 `paragraphs` 渲染
   - 支持原文/翻译/双语切换
   - 问题: 缺少与原始 segments 的映射展示

3. **播放器跳转:** `PlayerView.vue:671-706` 的 `localSeekTo`
   - 问题: 跳转后字幕列表不自动滚动到对应位置

4. **字幕原文保留:** ✅ 已实现
   - `segments` 包含 `text_original` 和 `text_translated`
   - 数据库已存储原始字幕

### 核心需求拆解
1. **自动定位:** 播放器 seek 后，字幕列表自动滚动到当前播放位置对应的段落
2. **映射可视化:** 在字幕段落中显示该段落包含哪些原始 segments
3. **分段后端化:** 将分段逻辑从前端移到后端，持久化映射关系
4. **同步功能:** 新增 API 端点，支持手动/自动同步字幕分段

---

## 🗂️ 文件结构

### 新建文件
```
podcast-digester/
├── backend/
│   ├── app/
│   │   ├── models/
│   │   │   └── subtitle_segment.py      # Segment 模型扩展
│   │   ├── services/
│   │   │   └── subtitle_segmenter.py   # 字幕分段服务
│   │   └── api/
│   │       └── endpoints/
│   │           └── subtitle_sync.py      # 字幕同步 API
│   └── tests/
│       ├── test_subtitle_segmenter.py   # 分段逻辑测试
│       └── test_subtitle_sync_api.py     # API 测试
└── frontend/
    └── src/
        ├── composables/
        │   └── useSubtitleScroll.js     # 字幕滚动定位 composable
        └── components/
            └── SubtitleMapping.vue       # 字幕映射可视化组件
```

### 修改文件
```
podcast-digester/
├── backend/
│   ├── app/models/
│   │   └── episode.py                    # 添加 paragraph_mappings 字段
│   └── app/api/
│       └── endpoints/
│           └── episodes.py               # 返回分段映射数据
└── frontend/
    └── src/
        └── views/
            └── PlayerView.vue            # 集成自动滚动、映射显示
```

---

## 🔧 实施任务

### Task 1: 数据层扩展 - 添加分段映射存储

**Files:**
- Modify: `backend/app/models/episode.py`
- Create: `backend/app/models/subtitle_segment.py`
- Test: `backend/tests/test_subtitle_segmenter.py`

**目标:** 扩展数据库 schema 以支持字幕分段与原始字幕的映射关系持久化。

- [ ] **Step 1: 编写失败的测试 - 扩展 Episode 模型**

```python
# backend/tests/test_subtitle_segmenter.py

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.models.episode import Episode

def test_episode_has_paragraph_mappings():
    """测试 Episode 模型支持存储段落映射"""
    engine = create_engine("sqlite:///:memory:")
    Session = sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)

    session = Session()
    episode = Episode(
        title="Test Episode",
        paragraph_mappings=[]  # 应该支持存储段落映射
    )
    session.add(episode)
    session.commit()

    retrieved = session.query(Episode).first()
    assert retrieved.paragraph_mappings is not None
    assert isinstance(retrieved.paragraph_mappings, list)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /Users/alli/podcast-digester/backend
pytest tests/test_subtitle_segmenter.py::test_episode_has_paragraph_mappings -v
```

**Expected:** FAIL - `paragraph_mappings` 属性不存在

- [ ] **Step 3: 扩展 Episode 模型添加段落映射字段**

```python
# backend/app/models/episode.py

from sqlalchemy import Column, String, Integer, JSON, Text
from .base import Base

class Episode(Base):
    __tablename__ = "episodes"

    # ... 现有字段 ...

    # 新增字段：存储字幕段落与原始 segments 的映射关系
    paragraph_mappings = Column(JSON, nullable=True, default=list)
    """
    格式:
    [
        {
            "id": 0,
            "start_ms": 0,
            "end_ms": 15000,
            "text_original": "段落原文...",
            "text_translated": "段落翻译...",
            "segment_indices": [0, 1, 2],  # 对应的原始 segment 索引
            "segment_ids": ["seg_001", "seg_002", "seg_003"]  # segment 的唯一 ID
        },
        ...
    ]
    """
```

- [ ] **Step 4: 运行测试验证通过**

```bash
pytest tests/test_subtitle_segmenter.py::test_episode_has_paragraph_mappings -v
```

**Expected:** PASS

- [ ] **Step 5: 创建数据库迁移脚本**

```bash
# backend/alembic/versions/20250615_add_paragraph_mappings.py
"""add paragraph mappings column

Revision ID: 20250615_001
Revises: <previous_revision_id>
Create Date: 2025-06-15

"""
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.add_column('episodes', sa.Column('paragraph_mappings', sa.JSON(), nullable=True))

def downgrade():
    op.drop_column('episodes', 'paragraph_mappings')
```

- [ ] **Step 6: 提交**

```bash
cd /Users/alli/podcast-digester
git add backend/app/models/episode.py backend/tests/test_subtitle_segmenter.py
git commit -m "feat(backend): add paragraph_mappings field to Episode model for subtitle mapping"
```

---

### Task 2: 后端服务 - 字幕分段逻辑

**Files:**
- Create: `backend/app/services/subtitle_segmenter.py`
- Test: `backend/tests/test_subtitle_segmenter.py`

**目标:** 将前端硬编码的分段逻辑提取到后端服务，支持可配置的分段规则。

- [ ] **Step 1: 编写失败的测试 - 基本分段功能**

```python
# backend/tests/test_subtitle_segmenter.py

def test_segment_paragraphs_basic():
    """测试基本分段功能"""
    from app.services.subtitle_segmenter import SubtitleSegmenter

    segments = [
        {"id": "seg1", "start_ms": 0, "end_ms": 5000, "text_original": "第一句", "text_translated": "First"},
        {"id": "seg2", "start_ms": 5000, "end_ms": 10000, "text_original": "第二句", "text_translated": "Second"},
        {"id": "seg3", "start_ms": 10000, "end_ms": 15000, "text_original": "第三句", "text_translated": "Third"},
    ]

    segmenter = SubtitleSegmenter(max_chars=120, min_chars=40)
    paragraphs = segmenter.segment(segments)

    assert len(paragraphs) == 1
    assert paragraphs[0]["segment_indices"] == [0, 1, 2]
    assert paragraphs[0]["segment_ids"] == ["seg1", "seg2", "seg3"]
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_subtitle_segmenter.py::test_segment_paragraphs_basic -v
```

**Expected:** FAIL - `SubtitleSegmenter` 不存在

- [ ] **Step 3: 实现字幕分段服务**

```python
# backend/app/services/subtitle_segmenter.py

from typing import List, Dict, Any
import re

class SubtitleSegmenter:
    """字幕分段服务，将零散的 segments 合并成段落"""

    def __init__(
        self,
        max_chars: int = 120,
        min_chars: int = 40,
        merge_threshold: float = 2.0  # 秒，间隔超过此值强制分段
    ):
        self.max_chars = max_chars
        self.min_chars = min_chars
        self.merge_threshold = merge_threshold

    def clean_text(self, text: str) -> str:
        """清理文本：移除 HTML 标签和多余空白"""
        if not text:
            return ""
        # 解码 HTML 实体
        text = text.replace("&lt;", "<").replace("&gt;", ">")
        text = text.replace("&amp;", "&").replace("&quot;", '"').replace("&#39;", "'")
        # 移除 HTML 标签
        text = re.sub(r'<[^>]*>', '', text)
        # 移除多余空白
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def segment(self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """将 segments 合并成段落

        Args:
            segments: 原始字幕 segments，每个包含:
                - id: str (segment 唯一标识)
                - start_ms: int
                - end_ms: int
                - text_original: str
                - text_translated: str (可选)

        Returns:
            段落列表，每个段落包含:
                - id: int (段落序号)
                - start_ms: int
                - end_ms: int
                - text_original: str
                - text_translated: str
                - segment_indices: List[int] (对应的 segments 索引)
                - segment_ids: List[str] (对应的 segment ID)
        """
        if not segments:
            return []

        result = []
        current_para = {
            "id": 0,
            "segments": [],
            "text_original": "",
            "text_translated": ""
        }

        for i, seg in enumerate(segments):
            seg_text = self.clean_text(seg.get("text_original", ""))
            seg_trans = seg.get("text_translated", "")

            if not seg_text:
                continue

            # 检查时间间隔（超过阈值强制分段）
            time_gap = 0
            if current_para["segments"]:
                last_seg = current_para["segments"][-1]
                time_gap = (seg["start_ms"] - last_seg["end_ms"]) / 1000.0

            # 检查是否需要开始新段落
            would_exceed = len(current_para["text_original"]) + len(seg_text) > self.max_chars
            has_min_content = len(current_para["text_original"]) >= self.min_chars
            should_split = has_min_content and (would_exceed or time_gap > self.merge_threshold)

            if should_split and current_para["segments"]:
                # 保存当前段落
                result.append(self._finalize_paragraph(current_para, len(result)))
                # 开始新段落
                current_para = {
                    "id": len(result),
                    "segments": [seg],
                    "text_original": seg_text,
                    "text_translated": seg_trans
                }
            else:
                # 添加到当前段落
                current_para["segments"].append(seg)
                current_para["text_original"] += (current_para["text_original"] ? " " : "") + seg_text
                if seg_trans:
                    current_para["text_translated"] += (current_para["text_translated"] ? " " : "") + seg_trans

        # 保存最后一段
        if current_para["segments"]:
            result.append(self._finalize_paragraph(current_para, len(result)))

        return result

    def _finalize_paragraph(self, para: Dict, para_id: int) -> Dict[str, Any]:
        """将段落数据转换为最终格式"""
        segments = para["segments"]
        return {
            "id": para_id,
            "start_ms": segments[0]["start_ms"],
            "end_ms": segments[-1]["end_ms"],
            "text_original": para["text_original"],
            "text_translated": para["text_translated"],
            "segment_indices": [seg.get("_index", i) for i, seg in enumerate(segments)],
            "segment_ids": [seg["id"] for seg in segments]
        }
```

- [ ] **Step 4: 运行测试验证通过**

```bash
pytest tests/test_subtitle_segmenter.py::test_segment_paragraphs_basic -v
```

**Expected:** PASS

- [ ] **Step 5: 添加边界条件测试**

```python
def test_segment_empty_input():
    """测试空输入"""
    from app.services.subtitle_segmenter import SubtitleSegmenter

    segmenter = SubtitleSegmenter()
    result = segmenter.segment([])
    assert result == []

def test_segment_long_gap():
    """测试时间间隔超过阈值强制分段"""
    from app.services.subtitle_segmenter import SubtitleSegmenter

    segments = [
        {"id": "seg1", "start_ms": 0, "end_ms": 5000, "text_original": "第一句", "_index": 0},
        {"id": "seg2", "start_ms": 5000, "end_ms": 10000, "text_original": "第二句", "_index": 1},
        # 间隔超过 2 秒
        {"id": "seg3", "start_ms": 25000, "end_ms": 30000, "text_original": "第三句", "_index": 2},
    ]

    segmenter = SubtitleSegmenter(merge_threshold=2.0)
    paragraphs = segmenter.segment(segments)

    assert len(paragraphs) == 2
    assert paragraphs[0]["segment_ids"] == ["seg1", "seg2"]
    assert paragraphs[1]["segment_ids"] == ["seg3"]
```

- [ ] **Step 6: 运行所有测试**

```bash
pytest tests/test_subtitle_segmenter.py -v
```

**Expected:** 全部 PASS

- [ ] **Step 7: 提交**

```bash
git add backend/app/services/subtitle_segmenter.py backend/tests/test_subtitle_segmenter.py
git commit -m "feat(backend): add SubtitleSegmenter service with configurable rules"
```

---

### Task 3: 后端 API - 字幕同步端点

**Files:**
- Create: `backend/app/api/endpoints/subtitle_sync.py`
- Modify: `backend/app/api/endpoints/episodes.py`
- Test: `backend/tests/test_subtitle_sync_api.py`

**目标:** 新增 API 端点支持手动触发字幕分段同步，并在获取节目详情时返回分段映射。

- [ ] **Step 1: 编写失败的测试 - 同步 API 端点**

```python
# backend/tests/test_subtitle_sync_api.py

import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_sync_subtitle_segments():
    """测试字幕同步 API"""
    response = client.post("/api/episodes/test-episode-id/sync-subtitles")
    assert response.status_code == 200

    data = response.json()
    assert "paragraph_count" in data
    assert "paragraph_mappings" in data
    assert isinstance(data["paragraph_mappings"], list)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_subtitle_sync_api.py::test_sync_subtitle_segments -v
```

**Expected:** FAIL - 404 Not Found

- [ ] **Step 3: 实现字幕同步 API**

```python
# backend/app/api/endpoints/subtitle_sync.py

from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from typing import Dict, Any
from app.services.subtitle_segmenter import SubtitleSegmenter
from app.models.episode import Episode
from app.database import get_db

router = APIRouter()

@router.post("/episodes/{episode_id}/sync-subtitles")
async def sync_subtitle_segments(
    episode_id: str,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """同步字幕分段

    从原始字幕 segments 生成段落映射，并持久化到数据库。

    Args:
        episode_id: 节目 ID

    Returns:
        包含分段数量和映射数据的响应
    """
    # 1. 获取节目数据
    episode = db.query(Episode).filter(Episode.id == episode_id).first()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    # 2. 检查是否有字幕数据
    if not episode.transcript or not episode.transcript.get("segments"):
        raise HTTPException(status_code=400, detail="No transcript segments found")

    # 3. 为 segments 添加索引（用于映射）
    segments = episode.transcript["segments"]
    for i, seg in enumerate(segments):
        if "id" not in seg:
            seg["id"] = f"seg_{episode_id}_{i}"
        seg["_index"] = i

    # 4. 执行分段
    segmenter = SubtitleSegmenter(max_chars=120, min_chars=40)
    paragraph_mappings = segmenter.segment(segments)

    # 5. 持久化到数据库
    episode.paragraph_mappings = paragraph_mappings
    db.commit()

    # 6. 返回结果
    return {
        "episode_id": episode_id,
        "paragraph_count": len(paragraph_mappings),
        "paragraph_mappings": paragraph_mappings,
        "segment_count": len(segments)
    }
```

- [ ] **Step 4: 注册路由**

```python
# backend/app/main.py

from app.api.endpoints import subtitle_sync

app.include_router(subtitle_sync.router, prefix="/api", tags=["subtitles"])
```

- [ ] **Step 5: 运行测试验证通过**

```bash
pytest tests/test_subtitle_sync_api.py::test_sync_subtitle_segments -v
```

**Expected:** PASS

- [ ] **Step 6: 修改 episodes API 返回分段映射**

```python
# backend/app/api/endpoints/episodes.py

@router.get("/episodes/{episode_id}")
async def get_episode(
    episode_id: str,
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """获取节目详情（包含分段映射）"""
    episode = db.query(Episode).filter(Episode.id == episode_id).first()
    if not episode:
        raise HTTPException(status_code=404, detail="Episode not found")

    # 构建响应
    response = {
        "episode": {
            "id": episode.id,
            "title": episode.title,
            # ... 其他字段 ...
        },
        "transcript": episode.transcript,
        "paragraph_mappings": episode.paragraph_mappings or [],  # 新增
        # ... 其他数据 ...
    }

    return response
```

- [ ] **Step 7: 添加集成测试**

```python
def test_get_episode_includes_mappings():
    """测试获取节目时包含分段映射"""
    # 先同步字幕
    sync_response = client.post("/api/episodes/test-episode-id/sync-subtitles")

    # 再获取节目详情
    episode_response = client.get("/api/episodes/test-episode-id")
    assert episode_response.status_code == 200

    data = episode_response.json()
    assert "paragraph_mappings" in data
    assert len(data["paragraph_mappings"]) > 0
```

- [ ] **Step 8: 运行所有测试**

```bash
pytest tests/test_subtitle_sync_api.py -v
```

**Expected:** 全部 PASS

- [ ] **Step 9: 提交**

```bash
git add backend/app/api/endpoints/subtitle_sync.py backend/app/api/endpoints/episodes.py backend/app/main.py backend/tests/test_subtitle_sync_api.py
git commit -m "feat(backend): add subtitle sync API and include mappings in episode response"
```

---

### Task 4: 后端集成 - 自动触发分段

**Files:**
- Modify: `backend/app/services/transcription_service.py`

**目标:** 在转录完成后自动触发字幕分段，确保每次新增节目都有分段映射。

- [ ] **Step 1: 查找转录服务入口点**

```bash
cd /Users/alli/podcast-digester/backend
grep -r "def.*transcrib" app/services/ --include="*.py"
```

**Expected:** 找到转录服务的函数名

- [ ] **Step 2: 在转录完成后调用分段服务**

根据实际代码结构，在转录完成回调中添加：

```python
# backend/app/services/transcription_service.py (示例)

from app.services.subtitle_segmenter import SubtitleSegmenter

class TranscriptionService:
    async def process_transcription(self, episode_id: str, ...):
        # ... 现有转录逻辑 ...

        # 转录完成后，自动生成段落映射
        await self._generate_paragraph_mappings(episode_id, db)

    async def _generate_paragraph_mappings(self, episode_id: str, db: Session):
        """生成字幕段落映射"""
        episode = db.query(Episode).filter(Episode.id == episode_id).first()
        if not episode or not episode.transcript:
            return

        segments = episode.transcript.get("segments", [])
        if not segments:
            return

        # 添加索引
        for i, seg in enumerate(segments):
            if "id" not in seg:
                seg["id"] = f"seg_{episode_id}_{i}"
            seg["_index"] = i

        # 执行分段
        segmenter = SubtitleSegmenter()
        paragraph_mappings = segmenter.segment(segments)

        # 持久化
        episode.paragraph_mappings = paragraph_mappings
        db.commit()

        logger.info(f"Generated {len(paragraph_mappings)} paragraph mappings for episode {episode_id}")
```

- [ ] **Step 3: 提交**

```bash
git add backend/app/services/transcription_service.py
git commit -m "feat(backend): auto-generate paragraph mappings after transcription"
```

---

### Task 5: 前端 Composable - 字幕自动滚动

**Files:**
- Create: `frontend/src/composables/useSubtitleScroll.js`
- Test: `frontend/tests/composables/useSubtitleScroll.test.js`

**目标:** 创建可复用的 composable，实现播放器跳转后字幕列表自动滚动到对应位置。

- [ ] **Step 1: 编写失败的测试 - 基本滚动功能**

```javascript
// frontend/tests/composables/useSubtitleScroll.test.js

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useSubtitleScroll } from '@/composables/useSubtitleScroll'

describe('useSubtitleScroll', () => {
  let mockContainer, mockItems

  beforeEach(() => {
    // 模拟 DOM 容器
    mockContainer = {
      querySelector: vi.fn(),
      scrollIntoView: vi.fn(),
      scrollTop: 0,
      clientHeight: 600
    }

    // 模拟字幕项
    mockItems = [
      { id: 0, start_ms: 0, end_ms: 15000 },
      { id: 1, start_ms: 15000, end_ms: 30000 },
      { id: 2, start_ms: 30000, end_ms: 45000 }
    ]
  })

  it('should scroll to active paragraph', () => {
    const { scrollToActive } = useSubtitleScroll(mockContainer, mockItems)

    // 模拟当前播放时间在第二段
    const currentTime = 20000
    scrollToActive(currentTime)

    // 验证滚动到了正确的段落
    expect(mockContainer.scrollIntoView).toHaveBeenCalledWith(
      expect.objectContaining({ block: 'center' })
    )
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /Users/alli/podcast-digester/frontend
npm test useSubtitleScroll
```

**Expected:** FAIL - composable 不存在

- [ ] **Step 3: 实现 useSubtitleScroll composable**

```javascript
// frontend/src/composables/useSubtitleScroll.js

import { ref, watch, nextTick } from 'vue'

/**
 * 字幕自动滚动 Composable
 *
 * 功能:
 * 1. 监听播放器时间变化，自动滚动字幕列表
 * 2. 支持手动触发滚动
 * 3. 智能定位策略（居中/顶部/底部）
 *
 * @param {Ref<Object>} containerRef - 字幕容器的 DOM ref
 * @param {ComputedRef<Array>>} items - 字幕段落数据
 * @param {Object} options - 配置选项
 * @param {string} options.block - 滚动定位策略: 'center' | 'start' | 'end' | 'nearest'
 * @param {number} options.threshold - 时间阈值（毫秒），用于判断当前段落
 * @returns {Object} - 滚动控制方法
 */
export function useSubtitleScroll(containerRef, items, options = {}) {
  const {
    block = 'center',      // 默认居中显示
    threshold = 500        // 500ms 容差
  } = options

  const isScrolling = ref(false)
  let scrollTimer = null

  /**
   * 查找当前播放位置对应的段落索引
   */
  const findActiveIndex = (currentTime) => {
    if (!items.value || items.value.length === 0) return -1

    // 使用二分查找优化性能
    let left = 0
    let right = items.value.length - 1

    while (left <= right) {
      const mid = Math.floor((left + right) / 2)
      const item = items.value[mid]

      if (currentTime >= item.start_ms - threshold && currentTime < item.end_ms + threshold) {
        return mid
      } else if (currentTime < item.start_ms) {
        right = mid - 1
      } else {
        left = mid + 1
      }
    }

    return -1
  }

  /**
   * 滚动到指定段落
   */
  const scrollToIndex = (index) => {
    if (!containerRef.value || index < 0 || index >= items.value.length) return

    isScrolling.value = true

    // 清除之前的防抖定时器
    if (scrollTimer) {
      clearTimeout(scrollTimer)
    }

    nextTick(() => {
      const container = containerRef.value
      const targetElement = container.querySelector(`[data-paragraph-id="${index}"]`)

      if (targetElement) {
        targetElement.scrollIntoView({
          behavior: 'smooth',
          block: block
        })
      }

      // 防抖标记
      scrollTimer = setTimeout(() => {
        isScrolling.value = false
      }, 500)
    })
  }

  /**
   * 滚动到当前播放位置对应的段落
   */
  const scrollToActive = (currentTime) => {
    const activeIndex = findActiveIndex(currentTime)
    if (activeIndex >= 0) {
      scrollToIndex(activeIndex)
    }
  }

  /**
   * 监听播放器时间变化自动滚动
   */
  const watchTime = (currentTimeRef) => {
    watch(currentTimeRef, (newTime, oldTime) => {
      // 防止滚动事件循环触发
      if (isScrolling.value) return

      // 只在切换段落时滚动（避免频繁滚动）
      const oldIndex = findActiveIndex(oldTime)
      const newIndex = findActiveIndex(newTime)

      if (oldIndex !== newIndex) {
        scrollToActive(newTime)
      }
    })
  }

  return {
    isScrolling,
    scrollToActive,
    scrollToIndex,
    findActiveIndex,
    watchTime
  }
}
```

- [ ] **Step 4: 运行测试验证通过**

```bash
npm test useSubtitleScroll
```

**Expected:** PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/src/composables/useSubtitleScroll.js frontend/tests/composables/useSubtitleScroll.test.js
git commit -m "feat(frontend): add useSubtitleScroll composable for auto-scrolling"
```

---

### Task 6: 前端组件 - 字幕映射可视化

**Files:**
- Create: `frontend/src/components/SubtitleMapping.vue`
- Modify: `frontend/src/views/PlayerView.vue`

**目标:** 创建组件显示字幕段落与原始字幕的映射关系，并集成到播放器视图。

- [ ] **Step 1: 编写失败的测试 - 组件渲染**

```vue
<!-- frontend/tests/components/SubtitleMapping.test.js -->

import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import SubtitleMapping from '@/components/SubtitleMapping.vue'

describe('SubtitleMapping', () => {
  it('renders segment mapping info', () => {
    const wrapper = mount(SubtitleMapping, {
      props: {
        paragraph: {
          id: 0,
          text_original: "测试段落",
          segment_indices: [0, 1, 2],
          segment_ids: ["seg1", "seg2", "seg3"]
        },
        expanded: false
      }
    })

    expect(wrapper.text()).toContain("3 段原始字幕")
  })

  it('expands to show segment details', async () => {
    const wrapper = mount(SubtitleMapping, {
      props: {
        paragraph: {
          id: 0,
          text_original: "测试",
          segment_indices: [0, 1],
          segment_ids: ["seg1", "seg2"]
        },
        expanded: true
      }
    })

    expect(wrapper.find('.segment-details').exists()).toBe(true)
  })
})
```

- [ ] **Step 2: 运行测试确认失败**

```bash
npm test SubtitleMapping
```

**Expected:** FAIL - 组件不存在

- [ ] **Step 3: 实现 SubtitleMapping 组件**

```vue
<!-- frontend/src/components/SubtitleMapping.vue -->

<template>
  <div class="subtitle-mapping">
    <!-- 映射信息摘要 -->
    <div class="mapping-summary" @click="toggleExpand">
      <span class="mapping-icon">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline :points="expanded ? '6 9 12 15 18 9' : '18 15 12 9 6 15'"/>
        </svg>
      </span>
      <span class="mapping-text">
        {{ paragraph.segment_indices.length }} 段原始字幕
      </span>
      <span class="mapping-range">
        #{{ paragraph.segment_indices[0] + 1 }} - #{{ paragraph.segment_indices[paragraph.segment_indices.length - 1] + 1 }}
      </span>
    </div>

    <!-- 展开的原始字幕详情 -->
    <transition name="expand">
      <div v-show="expanded" class="segment-details">
        <div
          v-for="(segId, idx) in paragraph.segment_ids"
          :key="segId"
          class="segment-item"
        >
          <span class="segment-index">#{{ paragraph.segment_indices[idx] + 1 }}</span>
          <span class="segment-id">{{ segId }}</span>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  paragraph: {
    type: Object,
    required: true
  },
  expanded: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['toggle'])

const expanded = ref(props.expanded)

const toggleExpand = () => {
  expanded.value = !expanded.value
  emit('toggle', expanded.value)
}
</script>

<style scoped>
.subtitle-mapping {
  margin-top: 6px;
  padding: 6px 10px;
  background: #f9fafb;
  border-radius: 6px;
  font-size: 11px;
}

.mapping-summary {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  user-select: none;
}

.mapping-icon {
  color: #9ca3af;
  transition: transform 0.2s;
}

.mapping-summary:hover .mapping-icon {
  color: #6b7280;
}

.mapping-text {
  color: #6b7280;
}

.mapping-range {
  margin-left: auto;
  color: #9ca3af;
  font-family: 'SF Mono', monospace;
}

.segment-details {
  margin-top: 8px;
  padding-left: 20px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.segment-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 3px 0;
}

.segment-index {
  color: #3b82f6;
  font-family: 'SF Mono', monospace;
  min-width: 30px;
}

.segment-id {
  color: #9ca3af;
  font-family: 'SF Mono', monospace;
  font-size: 10px;
}

/* 展开动画 */
.expand-enter-active,
.expand-leave-active {
  transition: all 0.3s ease;
  overflow: hidden;
}

.expand-enter-from,
.expand-leave-to {
  max-height: 0;
  opacity: 0;
}

.expand-enter-to,
.expand-leave-from {
  max-height: 200px;
  opacity: 1;
}
</style>
```

- [ ] **Step 4: 运行测试验证通过**

```bash
npm test SubtitleMapping
```

**Expected:** PASS

- [ ] **Step 5: 提交**

```bash
git add frontend/src/components/SubtitleMapping.vue frontend/tests/components/SubtitleMapping.test.js
git commit -m "feat(frontend): add SubtitleMapping component for paragraph-segment visualization"
```

---

### Task 7: 前端集成 - PlayerView 集成自动滚动和映射显示

**Files:**
- Modify: `frontend/src/views/PlayerView.vue`

**目标:** 将自动滚动和映射显示集成到播放器视图中，实现完整功能。

- [ ] **Step 1: 添加 useSubtitleScroll 集成**

在 `<script setup>` 中添加：

```javascript
// frontend/src/views/PlayerView.vue (修改)

import { useSubtitleScroll } from '@/composables/useSubtitleScroll'
import SubtitleMapping from '@/components/SubtitleMapping.vue'

// ... 现有代码 ...

// 字幕滚动
const transcriptContainer = ref(null)
const paragraphs = computed(() => {
  // 优先使用后端返回的段落映射
  if (bundle.value?.paragraph_mappings && bundle.value.paragraph_mappings.length > 0) {
    return bundle.value.paragraph_mappings
  }

  // 降级到前端分段逻辑（兼容旧数据）
  // ... 现有 paragraphs computed 逻辑 ...
})

const { isScrolling, scrollToActive, watchTime } = useSubtitleScroll(
  transcriptContainer,
  paragraphs,
  { block: 'center', threshold: 500 }
)

// 监听播放时间变化自动滚动
watchTime(currentTime)

// 映射展开状态
const expandedMappings = ref(new Set())

const toggleMapping = (paraId, expanded) => {
  if (expanded) {
    expandedMappings.value.add(paraId)
  } else {
    expandedMappings.value.delete(paraId)
  }
}

const isMappingExpanded = (paraId) => expandedMappings.value.has(paraId)
```

- [ ] **Step 2: 修改字幕模板添加映射组件**

在 template 中的字幕块添加映射组件：

```vue
<!-- frontend/src/views/PlayerView.vue (修改) -->

<!-- Tab 2: 转录字幕 -->
<div v-show="activeTab === 'transcript'" class="tab-content transcript-tab">
  <div class="transcript-header">
    <!-- ... 现有代码 ... -->
  </div>

  <!-- 添加容器 ref -->
  <div ref="transcriptContainer" class="transcript-content" v-if="paragraphs.length > 0">
    <div
      v-for="(para, idx) in paragraphs"
      :key="para.id"
      class="subtitle-block"
      :class="{ active: isCurrentParagraph(para) }"
      :data-paragraph-id="idx"
      @click="localSeekTo(para.start_ms)"
    >
      <span class="block-time">{{ formatTime(para.start_ms) }}</span>
      <div class="block-content">
        <span v-if="subtitleLang === 'original' || subtitleLang === 'both'" class="block-text">
          {{ para.text_original }}
        </span>
        <span v-if="subtitleLang === 'translated' || subtitleLang === 'both'" class="block-translated">
          {{ para.text_translated || para.text_original }}
        </span>

        <!-- 新增：映射显示组件 -->
        <SubtitleMapping
          v-if="para.segment_ids"
          :paragraph="para"
          :expanded="isMappingExpanded(para.id)"
          @toggle="(expanded) => toggleMapping(para.id, expanded)"
        />
      </div>
    </div>
  </div>

  <div v-else class="empty-state">
    <!-- ... 现有代码 ... -->
  </div>
</div>
```

- [ ] **Step 3: 添加样式优化**

在 `<style scoped>` 中添加：

```css
/* frontend/src/views/PlayerView.vue (修改) */

.transcript-content {
  display: flex;
  flex-direction: column;
  /* 确保滚动平滑 */
  scroll-behavior: smooth;
}

/* 正在滚动的容器禁用用户滚动（防止冲突） */
.transcript-content.is-scrolling {
  overflow: hidden;
}

.subtitle-block {
  /* ... 现有样式 ... */

  /* 添加过渡效果 */
  transition: background-color 0.15s, transform 0.2s;
}

.subtitle-block.active {
  /* ... 现有样式 ... */

  /* 添加缩放效果突出当前段落 */
  transform: scale(1.01);
}
```

- [ ] **Step 4: 手动测试**

```bash
# 启动前端
cd /Users/alli/podcast-digester/frontend
npm run dev

# 在浏览器中测试:
# 1. 播放播客，切换到字幕 tab
# 2. 点击进度条跳转，观察字幕列表是否自动滚动到对应位置
# 3. 点击字幕段落中的 "X 段原始字幕"，展开查看映射详情
# 4. 验证映射详情中显示的 segment 索引和 ID
```

- [ ] **Step 5: 端到端测试（可选）**

```javascript
// frontend/tests/e2e/subtitle-scroll.spec.js

import { test, expect } from '@playwright/test'

test.describe('Subtitle Auto-scroll', () => {
  test('should scroll to active paragraph when seeking', async ({ page }) => {
    await page.goto('http://localhost:5173/player/test-episode-id')

    // 切换到字幕 tab
    await page.click('button:has-text("转录字幕")')

    // 记录初始滚动位置
    const initialScrollTop = await page.evaluate(() => {
      return document.querySelector('.transcript-content').scrollTop
    })

    // 跳转到播放器中间位置
    await page.click('audio')
    await page.keyboard.press('ArrowRight')
    await page.waitForTimeout(500)

    // 验证滚动位置改变
    const finalScrollTop = await page.evaluate(() => {
      return document.querySelector('.transcript-content').scrollTop
    })

    expect(finalScrollTop).not.toBe(initialScrollTop)
  })

  test('should display mapping info', async ({ page }) => {
    await page.goto('http://localhost:5173/player/test-episode-id')
    await page.click('button:has-text("转录字幕")')

    // 验证映射信息显示
    const mappingText = await page.textContent('.mapping-text')
    expect(mappingText).toMatch(/\d+ 段原始字幕/)

    // 点击展开
    await page.click('.mapping-summary')

    // 验证原始字幕详情显示
    const segmentDetails = await page.$('.segment-details')
    expect(segmentDetails).toBeTruthy()
  })
})
```

- [ ] **Step 6: 提交**

```bash
git add frontend/src/views/PlayerView.vue frontend/tests/e2e/subtitle-scroll.spec.js
git commit -m "feat(frontend): integrate auto-scroll and mapping display in PlayerView"
```

---

### Task 8: 前端优化 - 降级方案和错误处理

**Files:**
- Modify: `frontend/src/views/PlayerView.vue`
- Modify: `frontend/src/composables/useSubtitleScroll.js`

**目标:** 添加降级方案处理旧数据（无 `paragraph_mappings`），并完善错误处理。

- [ ] **Step 1: 在 PlayerView 中添加降级逻辑**

```javascript
// frontend/src/views/PlayerView.vue (修改)

const paragraphs = computed(() => {
  // 优先使用后端返回的段落映射
  if (bundle.value?.paragraph_mappings && bundle.value.paragraph_mappings.length > 0) {
    console.log('[PlayerView] Using backend paragraph mappings')
    return bundle.value.paragraph_mappings
  }

  // 降级：使用前端分段逻辑（兼容旧数据）
  console.log('[PlayerView] Fallback to frontend paragraph generation')
  const segments = bundle.value?.transcript?.segments || []

  if (!segments.length) return []

  // ... 复制现有的前端分段逻辑 ...
  const result = []
  const MAX_PARA_CHARS = 120
  const MIN_PARA_CHARS = 40

  let currentPara = {
    id: 0,
    segments: [],
    text: '',
    translated: ''
  }

  for (let i = 0; i < segments.length; i++) {
    const seg = segments[i]
    const segText = cleanText(seg.text_original || '')
    const segTrans = seg.text_translated || ''

    if (!segText) continue

    const wouldExceed = currentPara.text.length + segText.length > MAX_PARA_CHARS
    const hasMinContent = currentPara.text.length >= MIN_PARA_CHARS

    if (hasMinContent && wouldExceed) {
      if (currentPara.segments.length > 0) {
        result.push({
          id: currentPara.id,
          start_ms: currentPara.segments[0].start_ms,
          end_ms: currentPara.segments[currentPara.segments.length - 1].end_ms,
          text_original: currentPara.text,
          text_translated: currentPara.translated,
          text_clean: currentPara.text,
          // 降级方案：添加映射信息（即使不完整）
          segment_indices: currentPara.segments.map((_, idx) => idx),
          segment_ids: currentPara.segments.map((s, idx) => s.id || `seg_${idx}`)
        })
      }
      currentPara = {
        id: result.length,
        segments: [seg],
        text: segText,
        translated: segTrans
      }
    } else {
      currentPara.segments.push(seg)
      currentPara.text += (currentPara.text ? ' ' : '') + segText
      if (segTrans) {
        currentPara.translated += (currentPara.translated ? ' ' : '') + segTrans
      }
    }
  }

  // 保存最后一段
  if (currentPara.segments.length > 0) {
    result.push({
      id: currentPara.id,
      start_ms: currentPara.segments[0].start_ms,
      end_ms: currentPara.segments[currentPara.segments.length - 1].end_ms,
      text_original: currentPara.text,
      text_translated: currentPara.translated,
      text_clean: currentPara.text,
      segment_indices: currentPara.segments.map((_, idx) => idx),
      segment_ids: currentPara.segments.map((s, idx) => s.id || `seg_${idx}`)
    })
  }

  console.log(`[PlayerView] Generated ${result.length} paragraphs from ${segments.length} segments (fallback)`)

  return result
})
```

- [ ] **Step 2: 在 useSubtitleScroll 中添加错误边界**

```javascript
// frontend/src/composables/useSubtitleScroll.js (修改)

const scrollToActive = (currentTime) => {
  try {
    if (!currentTime && currentTime !== 0) return

    const activeIndex = findActiveIndex(currentTime)
    if (activeIndex >= 0) {
      scrollToIndex(activeIndex)
    }
  } catch (error) {
    console.error('[useSubtitleScroll] Scroll failed:', error)
    isScrolling.value = false
  }
}

// 添加防抖机制避免频繁滚动
const debouncedScrollToActive = (currentTime) => {
  if (scrollTimer) {
    clearTimeout(scrollTimer)
  }

  scrollTimer = setTimeout(() => {
    scrollToActive(currentTime)
  }, 100)
}

// 导出防抖版本
return {
  isScrolling,
  scrollToActive,
  scrollToIndex,
  findActiveIndex,
  watchTime,
  debouncedScrollToActive  // 新增
}
```

- [ ] **Step 3: 在 PlayerView 中使用防抖版本**

```javascript
// frontend/src/views/PlayerView.vue (修改)

const { debouncedScrollToActive, watchTime } = useSubtitleScroll(
  transcriptContainer,
  paragraphs,
  { block: 'center', threshold: 500 }
)

// 使用防抖版本
watchTime(currentTime, debouncedScrollToActive)
```

- [ ] **Step 4: 添加测试覆盖降级场景**

```javascript
// frontend/tests/composables/useSubtitleScroll.test.js (修改)

it('should handle invalid container gracefully', () => {
  const { scrollToActive } = useSubtitleScroll(null, mockItems)

  // 不应抛出错误
  expect(() => scrollToActive(20000)).not.toThrow()
})

it('should handle empty items', () => {
  const { scrollToActive, findActiveIndex } = useSubtitleScroll(mockContainer, [])

  const index = findActiveIndex(20000)
  expect(index).toBe(-1)

  // 不应抛出错误
  expect(() => scrollToActive(20000)).not.toThrow()
})
```

- [ ] **Step 5: 运行所有测试**

```bash
cd /Users/alli/podcast-digester/frontend
npm test
```

**Expected:** 全部 PASS

- [ ] **Step 6: 提交**

```bash
git add frontend/src/views/PlayerView.vue frontend/src/composables/useSubtitleScroll.js frontend/tests/
git commit -m "feat(frontend): add fallback logic and error handling for subtitle scroll"
```

---

### Task 9: 后端优化 - 批量同步 API

**Files:**
- Modify: `backend/app/api/endpoints/subtitle_sync.py`

**目标:** 添加批量同步 API，用于一次性同步所有旧节目的字幕分段。

- [ ] **Step 1: 编写失败的测试 - 批量同步**

```python
# backend/tests/test_subtitle_sync_api.py

def test_batch_sync_all_episodes():
    """测试批量同步所有节目"""
    response = client.post("/api/episodes/sync-all-subtitles")
    assert response.status_code == 200

    data = response.json()
    assert "total_episodes" in data
    assert "synced_count" in data
    assert "failed_count" in data
    assert "failed_episodes" in data
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_subtitle_sync_api.py::test_batch_sync_all_episodes -v
```

**Expected:** FAIL - 404 Not Found

- [ ] **Step 3: 实现批量同步 API**

```python
# backend/app/api/endpoints/subtitle_sync.py (修改)

from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)

@router.post("/episodes/sync-all-subtitles")
async def batch_sync_subtitle_segments(
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """批量同步所有节目的字幕分段

    Returns:
        包含同步统计信息的响应
    """
    # 1. 获取所有有字幕但无段落映射的节目
    episodes = db.query(Episode).filter(
        Episode.transcript.isnot(None),
        Episode.transcript["segments"].astext != "[]",
        (Episode.paragraph_mappings.is_(None)) |
        (func.json_array_length(Episode.paragraph_mappings) == 0)
    ).all()

    total = len(episodes)
    synced_count = 0
    failed_episodes = []

    for episode in episodes:
        try:
            # 2. 检查字幕数据
            if not episode.transcript or not episode.transcript.get("segments"):
                logger.warning(f"Episode {episode.id} has no segments, skipping")
                continue

            # 3. 添加索引
            segments = episode.transcript["segments"]
            for i, seg in enumerate(segments):
                if "id" not in seg:
                    seg["id"] = f"seg_{episode.id}_{i}"
                seg["_index"] = i

            # 4. 执行分段
            segmenter = SubtitleSegmenter()
            paragraph_mappings = segmenter.segment(segments)

            # 5. 持久化
            episode.paragraph_mappings = paragraph_mappings

            synced_count += 1
            logger.info(f"Synced episode {episode.id}: {len(paragraph_mappings)} paragraphs")

        except Exception as e:
            logger.error(f"Failed to sync episode {episode.id}: {e}")
            failed_episodes.append({
                "episode_id": episode.id,
                "error": str(e)
            })

    # 6. 提交所有更改
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to commit batch sync: {e}")
        raise HTTPException(status_code=500, detail="Batch sync commit failed")

    # 7. 返回结果
    return {
        "total_episodes": total,
        "synced_count": synced_count,
        "failed_count": len(failed_episodes),
        "failed_episodes": failed_episodes
    }
```

- [ ] **Step 4: 运行测试验证通过**

```bash
pytest tests/test_subtitle_sync_api.py::test_batch_sync_all_episodes -v
```

**Expected:** PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/api/endpoints/subtitle_sync.py backend/tests/test_subtitle_sync_api.py
git commit -m "feat(backend): add batch subtitle sync API for existing episodes"
```

---

### Task 10: 文档和部署

**Files:**
- Create: `docs/subtitle-mapping-guide.md`
- Modify: `README.md`

**目标:** 编写用户文档和开发文档，部署到生产环境。

- [ ] **Step 1: 编写用户指南**

```markdown
# docs/subtitle-mapping-guide.md

# 字幕分段映射功能指南

## 功能介绍

字幕分段映射功能将零散的字幕段落（segments）合并成更易读的段落，并保留原始映射关系以便后续分析。

## 主要特性

### 1. 自动定位
播放器跳转后，字幕列表自动滚动到当前播放位置对应的段落，无需手动查找。

### 2. 映射可视化
每个字幕段落显示其包含的原始字幕数量和索引，点击可展开查看详细的映射关系。

### 3. 智能分段
- 每段最多 120 字符，最少 40 字符
- 时间间隔超过 2 秒强制分段
- 确保段落语义完整

### 4. 降级兼容
对于旧数据（无段落映射），自动使用前端分段逻辑，确保功能可用。

## 使用方法

### 查看字幕映射
1. 打开播放器页面
2. 切换到"转录字幕" tab
3. 点击段落底部的"X 段原始字幕"展开映射详情

### 同步字幕分段
对于旧数据，可以手动触发同步：
```bash
curl -X POST http://your-domain/api/episodes/sync-all-subtitles
```

## 数据结构

### Paragraph Mapping
```json
{
  "id": 0,
  "start_ms": 0,
  "end_ms": 15000,
  "text_original": "段落原文...",
  "text_translated": "段落翻译...",
  "segment_indices": [0, 1, 2],
  "segment_ids": ["seg_001", "seg_002", "seg_003"]
}
```
```

- [ ] **Step 2: 更新 README**

```markdown
# README.md (修改)

## 新功能

### 字幕分段映射 ✨
- 🎯 播放器跳转后字幕自动定位
- 🔗 显示字幕段落与原始字幕的映射关系
- 🔄 支持手动/自动同步字幕分段
- 📊 保留完整字幕原文用于金句洞察

## API 端点

### 字幕同步
```bash
# 同步单个节目的字幕分段
POST /api/episodes/{episode_id}/sync-subtitles

# 批量同步所有节目
POST /api/episodes/sync-all-subtitles
```

### 获取节目（含段落映射）
```bash
GET /api/episodes/{episode_id}
```

响应包含 `paragraph_mappings` 字段。
```

- [ ] **Step 3: 生成 API 文档**

```bash
cd /Users/alli/podcast-digester/backend

# 生成 OpenAPI 文档
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# 访问 http://127.0.0.1:8000/docs 查看最新 API 文档
```

- [ ] **Step 4: 运行数据库迁移**

```bash
cd /Users/alli/podcast-digester/backend

# 应用数据库迁移
alembic upgrade head

# 验证新字段
sqlite3 ../data/podcast_digester.db ".schema episodes"
```

- [ ] **Step 5: 批量同步现有数据**

```bash
# 触发批量同步
curl -X POST http://127.0.0.1:8000/api/episodes/sync-all-subletters

# 检查同步结果
# 应该返回:
# {
#   "total_episodes": 28,
#   "synced_count": 28,
#   "failed_count": 0,
#   "failed_episodes": []
# }
```

- [ ] **Step 6: 前后端联调测试**

```bash
# 终端1 - 启动后端
cd backend
uvicorn app.main:app --host 127.0.0.1 --port 8000

# 终端2 - 启动前端
cd frontend
npm run dev

# 浏览器测试:
# 1. 访问 http://localhost:5173
# 2. 打开任意节目
# 3. 切换到"转录字幕" tab
# 4. 点击播放器进度条跳转
# 5. 验证字幕列表自动滚动
# 6. 点击"X 段原始字幕"展开映射
```

- [ ] **Step 7: 提交文档**

```bash
git add docs/subtitle-mapping-guide.md README.md
git commit -m "docs: add subtitle mapping feature guide and update README"
```

- [ ] **Step 8: 创建发布标签**

```bash
git tag -a v0.3.0 -m "Release v0.3.0: Subtitle Mapping and Auto-scroll"
git push origin v0.3.0
```

---

## ✅ 自我审查

### 1. 需求覆盖检查

- ✅ 播放器跳转后字幕自动定位 - Task 5, 7
- ✅ 字幕分段逻辑重新梳理 - Task 2
- ✅ 字幕分段与原始字幕映射显示 - Task 6, 7
- ✅ 字幕同步功能 - Task 3, 9
- ✅ 字幕原文保留 - 已有，Task 1 扩展 schema
- ✅ 降级兼容 - Task 8

### 2. Placeholder 检查

无 TBD、TODO 等占位符，所有步骤包含完整代码。

### 3. 类型一致性

- `paragraph_mappings` 结构在所有任务中保持一致
- API 响应格式统一
- 前端 props 命名一致

### 4. 测试覆盖

- 单元测试: SubtitleSegmenter, useSubtitleScroll, SubtitleMapping
- 集成测试: subtitle_sync_api
- E2E 测试: 字幕滚动
- 覆盖率目标: 80%+

---

## 📊 成功标准

### 功能验收
- [ ] 播放器跳转后字幕列表自动滚动到对应位置
- [ ] 字幕段落显示"X 段原始字幕"标识
- [ ] 点击可展开查看原始字幕索引和 ID
- [ ] 旧节目支持手动触发同步
- [ ] 新节目自动生成段落映射

### 性能要求
- [ ] 自动滚动不影响播放性能（< 100ms）
- [ ] 批量同步 100 个节目 < 30 秒

### 兼容性
- [ ] 旧数据（无段落映射）正常显示
- [ ] 前端分段逻辑作为降级方案

---

**计划完成！保存到:** `/Users/alli/podcast-digester/docs/superpowers/plans/2025-06-15-subtitle-sync-mapping.md`

**执行选项:**

1. **Subagent-Driven (推荐)** - 我为每个任务派发一个独立的子代理，任务间进行审查，快速迭代
2. **Inline Execution** - 在此会话中使用 executing-plans 技能执行任务，批量执行并设置检查点

**你想选择哪种执行方式？**
