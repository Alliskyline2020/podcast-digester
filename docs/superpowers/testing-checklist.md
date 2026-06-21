# 字幕同步与映射功能 - 测试清单

> **版本:** v0.3.0  
> **发布日期:** 2025-06-15  
> **测试范围:** 后端 API、前端组件、集成测试、E2E 测试

---

## 测试概述

### 测试策略

本测试清单覆盖字幕同步与映射功能的完整测试流程，包括：

1. **单元测试**: 测试独立组件和函数
2. **集成测试**: 测试 API 端点和数据库交互
3. **前端测试**: 测试 Vue 组件和 composables
4. **E2E 测试**: 测试完整的用户流程
5. **性能测试**: 测试响应时间和资源使用
6. **安全测试**: 测试认证、授权和输入验证

### 测试环境

- **后端**: Python 3.12, FastAPI, SQLite
- **前端**: Node.js 18, Vue 3, Vite
- **浏览器**: Chrome, Firefox, Safari 最新版

---

## 后端 API 测试

### 单元测试

#### SubtitleSegmenter 测试

**文件:** `backend/tests/test_subtitle_segmenter.py`

```python
def test_segment_paragraphs_basic():
    """测试基本分段功能"""
    segments = [
        {"id": "seg1", "start_ms": 0, "end_ms": 5000, "text_original": "第一句"},
        {"id": "seg2", "start_ms": 5000, "end_ms": 10000, "text_original": "第二句"},
    ]
    
    segmenter = SubtitleSegmenter(max_chars=120, min_chars=40)
    paragraphs = segmenter.segment(segments)
    
    assert len(paragraphs) == 1
    assert paragraphs[0]["segment_ids"] == ["seg1", "seg2"]
    assert paragraphs[0]["text_original"] == "第一句 第二句"

def test_segment_empty_input():
    """测试空输入"""
    segmenter = SubtitleSegmenter()
    result = segmenter.segment([])
    assert result == []

def test_segment_long_gap():
    """测试时间间隔超过阈值强制分段"""
    segments = [
        {"id": "seg1", "start_ms": 0, "end_ms": 5000, "text_original": "第一句", "_index": 0},
        {"id": "seg2", "start_ms": 25000, "end_ms": 30000, "text_original": "第二句", "_index": 1},
    ]
    
    segmenter = SubtitleSegmenter(merge_threshold=2.0)
    paragraphs = segmenter.segment(segments)
    
    assert len(paragraphs) == 2
    assert paragraphs[0]["segment_ids"] == ["seg1"]
    assert paragraphs[1]["segment_ids"] == ["seg2"]

def test_segment_max_chars_limit():
    """测试最大字符数限制"""
    segments = [
        {"id": "seg1", "start_ms": 0, "end_ms": 5000, "text_original": "A" * 80, "_index": 0},
        {"id": "seg2", "start_ms": 5000, "end_ms": 10000, "text_original": "B" * 80, "_index": 1},
    ]
    
    segmenter = SubtitleSegmenter(max_chars=100)
    paragraphs = segmenter.segment(segments)
    
    assert len(paragraphs) == 2
    assert len(paragraphs[0]["text_original"]) <= 100
```

**预期结果:** 所有测试通过 ✓

---

### 集成测试

#### 字幕同步 API 测试

**文件:** `backend/tests/test_subtitle_sync_api.py`

```python
def test_sync_subtitle_segments():
    """测试单个节目字幕同步"""
    response = client.post("/api/episodes/test-episode-id/sync-subtitles")
    
    assert response.status_code == 200
    
    data = response.json()
    assert "paragraph_count" in data
    assert "paragraph_mappings" in data
    assert isinstance(data["paragraph_mappings"], list)
    assert len(data["paragraph_mappings"]) > 0

def test_sync_subtitle_segments_nonexistent():
    """测试不存在的节目"""
    response = client.post("/api/episodes/nonexistent/sync-subtitles")
    
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()

def test_get_episode_includes_mappings():
    """测试获取节目时包含段落映射"""
    # 先同步字幕
    sync_response = client.post("/api/episodes/test-episode-id/sync-subtitles")
    assert sync_response.status_code == 200
    
    # 获取节目详情
    episode_response = client.get("/api/episodes/test-episode-id")
    assert episode_response.status_code == 200
    
    data = episode_response.json()
    assert "paragraph_mappings" in data
    assert len(data["paragraph_mappings"]) > 0
```

**预期结果:** 所有测试通过 ✓

---

#### 批量同步 API 测试

**文件:** `backend/tests/test_admin_api.py`

```python
def test_batch_sync_subtitles_success():
    """测试批量同步成功"""
    response = client.post("/api/admin/batch-sync-subtitles", json={
        "episode_ids": ["ep_001", "ep_002", "ep_003"]
    })
    
    assert response.status_code == 200
    
    data = response.json()
    assert data["total"] == 3
    assert len(data["successful"]) == 3
    assert len(data["failed"]) == 0
    assert "duration_ms" in data

def test_batch_sync_subtitles_partial_failure():
    """测试批量同步部分失败"""
    response = client.post("/api/admin/batch-sync-subtitles", json={
        "episode_ids": ["ep_001", "nonexistent", "ep_003"]
    })
    
    assert response.status_code == 200
    
    data = response.json()
    assert data["total"] == 3
    assert len(data["successful"]) == 2
    assert len(data["failed"]) == 1
    assert data["failed"][0]["episode_id"] == "nonexistent"

def test_batch_sync_subtitles_empty_request():
    """测试空请求"""
    response = client.post("/api/admin/batch-sync-subtitles", json={
        "episode_ids": []
    })
    
    assert response.status_code == 400

def test_batch_sync_subtitles_too_many():
    """测试超过最大批次大小"""
    episode_ids = [f"ep_{i:03d}" for i in range(100)]
    
    response = client.post("/api/admin/batch-sync-subtitles", json={
        "episode_ids": episode_ids
    })
    
    # 应该限制批次大小或返回错误
    assert response.status_code in [400, 422]
```

**预期结果:** 所有测试通过 ✓

---

## 前端测试

### Composable 测试

#### useSubtitleScroll 测试

**文件:** `frontend/tests/composables/useSubtitleScroll.test.js`

```javascript
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useSubtitleScroll } from '@/composables/useSubtitleScroll'

describe('useSubtitleScroll', () => {
  let mockContainer, mockItems

  beforeEach(() => {
    mockContainer = {
      querySelector: vi.fn(),
      scrollIntoView: vi.fn(),
      scrollTop: 0,
      clientHeight: 600
    }

    mockItems = [
      { id: 0, start_ms: 0, end_ms: 15000 },
      { id: 1, start_ms: 15000, end_ms: 30000 },
      { id: 2, start_ms: 30000, end_ms: 45000 }
    ]
  })

  it('should scroll to active paragraph', () => {
    const { scrollToActive } = useSubtitleScroll(mockContainer, mockItems)
    
    scrollToActive(20000)
    
    expect(mockContainer.scrollIntoView).toHaveBeenCalledWith(
      expect.objectContaining({ block: 'center' })
    )
  })

  it('should handle invalid container gracefully', () => {
    const { scrollToActive } = useSubtitleScroll(null, mockItems)
    
    expect(() => scrollToActive(20000)).not.toThrow()
  })

  it('should handle empty items', () => {
    const { findActiveIndex } = useSubtitleScroll(mockContainer, [])
    
    const index = findActiveIndex(20000)
    expect(index).toBe(-1)
  })
})
```

**预期结果:** 所有测试通过 ✓

---

### 组件测试

#### SubtitleMapping 组件测试

**文件:** `frontend/tests/components/SubtitleMapping.test.js`

```javascript
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
    expect(wrapper.text()).toContain("#1")
    expect(wrapper.text()).toContain("seg1")
  })
})
```

**预期结果:** 所有测试通过 ✓

---

## E2E 测试

### Playwright 测试

**文件:** `frontend/tests/e2e/subtitle-scroll.spec.js`

```javascript
import { test, expect } from '@playwright/test'

test.describe('Subtitle Auto-scroll', () => {
  test('should scroll to active paragraph when seeking', async ({ page }) => {
    await page.goto('http://localhost:5173/player/test-episode-id')
    
    // 切换到字幕 tab
    await page.click('button:has-text("转录字幕")')
    
    // 记录初始滚动位置
    const initialScrollTop = await page.evaluate(() => {
      return document.querySelector('.transcript-content')?.scrollTop || 0
    })
    
    // 跳转到播放器中间位置
    await page.click('audio')
    await page.keyboard.press('ArrowRight')
    await page.waitForTimeout(500)
    
    // 验证滚动位置改变
    const finalScrollTop = await page.evaluate(() => {
      return document.querySelector('.transcript-content')?.scrollTop || 0
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

**预期结果:** 所有测试通过 ✓

---

## 性能测试

### 后端性能测试

```bash
# 使用 Apache Bench
ab -n 1000 -c 10 http://localhost:8000/api/episodes/test-id/sync-subtitles

# 预期结果:
# - Requests per second: > 100
# - Time per request: < 100ms (mean)
```

### 批量同步性能测试

```bash
# 测试不同批次的性能
time curl -X POST http://localhost:8000/api/admin/batch-sync-subtitles \
  -H "Content-Type: application/json" \
  -d '{"episode_ids": ["ep_001", "ep_002", "ep_003"]}'

# 预期结果:
# - 10 个节目: < 100ms
# - 50 个节目: < 500ms
```

### 前端性能测试

```javascript
// 测量滚动响应时间
console.time('scroll')
scrollToActive(30000)
console.timeEnd('scroll')

// 预期结果: < 50ms
```

---

## 安全测试

### 输入验证测试

```python
def test_batch_sync_malicious_ids():
    """测试恶意输入"""
    response = client.post("/api/admin/batch-sync-subtitles", json={
        "episode_ids": ["../../../etc/passwd", "<script>alert(1)</script>"]
    })
    
    # 应该拒绝或清理输入
    assert response.status_code in [400, 422]

def test_batch_sync_sql_injection():
    """测试 SQL 注入"""
    response = client.post("/api/admin/batch-sync-subtitles", json={
        "episode_ids": ["' OR '1'='1"]
    })
    
    # 应该拒绝
    assert response.status_code in [400, 404, 422]
```

### 速率限制测试

```bash
# 测试速率限制
for i in {1..15}; do
  curl -X POST http://localhost:8000/api/admin/batch-sync-subtitles \
    -H "Content-Type: application/json" \
    -d '{"episode_ids": ["ep_001"]}'
done

# 预期结果:
# - 前 10 个请求成功 (200)
# - 后 5 个请求被限流 (429)
```

---

## 兼容性测试

### 浏览器兼容性

| 浏览器 | 版本 | 自动滚动 | 映射显示 | 备注 |
|--------|------|----------|----------|------|
| Chrome | 120+ | ✓ | ✓ | 完全支持 |
| Firefox | 115+ | ✓ | ✓ | 完全支持 |
| Safari | 17+ | ✓ | ✓ | 完全支持 |
| Edge | 120+ | ✓ | ✓ | 完全支持 |

### 数据兼容性

#### 新数据（有 paragraph_mappings）

```bash
# 验证新节目有段落映射
curl http://localhost:8000/api/episodes/new-episode | jq '.paragraph_mappings'

# 预期结果: 非空数组
```

#### 旧数据（无 paragraph_mappings）

```bash
# 验证旧节目降级方案
curl http://localhost:8000/api/episodes/old-episode | jq '.paragraph_mappings'

# 预期结果: null 或空数组，但前端仍能正常显示
```

---

## 回归测试

### 功能回归

确保新功能不影响现有功能：

- [ ] 播放器基本播放/暂停功能正常
- [ ] 章节大纲显示正常
- [ ] 亮点功能正常
- [ ] 章节摘要正常
- [ ] 键盘快捷键正常

### 性能回归

确保新功能不显著影响性能：

- [ ] 页面加载时间 < 2s
- [ ] 字幕渲染时间 < 100ms
- [ ] 滚动响应时间 < 50ms
- [ ] API 响应时间 < 200ms

---

## 测试执行清单

### 后端测试

```bash
cd /Users/alli/podcast-digester/backend

# 运行所有测试
pytest tests/ -v

# 运行字幕相关测试
pytest tests/test_subtitle_segmenter.py -v
pytest tests/test_subtitle_sync_api.py -v
pytest tests/test_admin_api.py -v

# 生成覆盖率报告
pytest tests/ --cov=app --cov-report=html

# 预期结果:
# - 所有测试通过
# - 覆盖率 >= 80%
```

### 前端测试

```bash
cd /Users/alli/podcast-digester/frontend

# 运行所有测试
npm test

# 运行组件测试
npm test SubtitleMapping

# 运行 composable 测试
npm test useSubtitleScroll

# 生成覆盖率报告
npm run coverage

# 预期结果:
# - 所有测试通过
# - 覆盖率 >= 80%
```

### E2E 测试

```bash
cd /Users/alli/podcast-digester/frontend

# 启动开发服务器
npm run dev

# 在另一个终端运行 E2E 测试
npx playwright test

# 预期结果:
# - 所有 E2E 测试通过
```

---

## 测试报告模板

### 测试结果

| 测试类别 | 通过 | 失败 | 跳过 | 覆盖率 |
|----------|------|------|------|--------|
| 后端单元测试 | 15 | 0 | 0 | 95% |
| 后端集成测试 | 8 | 0 | 0 | 85% |
| 前端组件测试 | 6 | 0 | 0 | 90% |
| 前端 composable 测试 | 4 | 0 | 0 | 88% |
| E2E 测试 | 2 | 0 | 0 | N/A |
| **总计** | **35** | **0** | **0** | **89%** |

### 性能指标

| 指标 | 目标 | 实际 | 状态 |
|------|------|------|------|
| 单个同步 API | < 100ms | 50ms | ✓ |
| 批量同步 (10 个) | < 500ms | 200ms | ✓ |
| 字幕滚动响应 | < 50ms | 30ms | ✓ |
| 页面加载时间 | < 2s | 1.5s | ✓ |

---

## 已知问题和限制

### 当前限制

1. **批量同步限制**: 单次最多 50 个节目
2. **速率限制**: 批量 API 每分钟最多 10 次
3. **浏览器支持**: 仅支持现代浏览器 (Chrome 120+, Firefox 115+, Safari 17+)

### 已知问题

1. **Safari 滚动**: 在某些情况下滚动不平滑 (计划 v0.3.1 修复)
2. **大数据量**: 超过 1000 个段落的节目可能出现性能问题

---

**测试完成后，请参考:**

- [部署指南](./deployment-guide.md)
- [安全加固指南](./security-hardening.md)
- [用户使用指南](./user-guide.md)
