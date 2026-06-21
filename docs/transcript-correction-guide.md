# 字幕纠错系统使用指南

## 📚 系统概述

字幕纠错系统包含三个核心功能：

1. **专业词库** - 维护常见转录错误的映射表
2. **字幕编辑器** - 手动编辑字幕segment
3. **自动同步** - 字幕修改后同步到所有模块

---

## 🔧 后端API

### 1. 词库管理

#### 获取词库
```bash
curl -X POST http://localhost:8000/api/glossary/entries
```

#### 添加词库条目
```bash
curl -X POST http://localhost:8000/api/glossary/add \
  -H "Content-Type: application/json" \
  -d '{
    "correct": "张小珺",
    "wrong": ["小军", "张小君", "小珺"]
  }'
```

#### 删除词库条目
```bash
curl -X DELETE http://localhost:8000/api/glossary/entries/张小珺
```

### 2. 字幕编辑

#### 更新单个字幕segment
```bash
curl -X POST http://localhost:8000/api/episodes/ep_1781109978390/segments/update \
  -H "Content-Type: application/json" \
  -d '{
    "segment_index": 1,
    "text_original": "我是张小珺。",
    "note_to_glossary": true
  }'
```

参数说明：
- `segment_index`: segment索引（从0开始）
- `text_original`: 修改后的文本
- `note_to_glossary`: 是否添加到词库（自动推断正确词和错误词）

#### 应用词库到整个节目
```bash
curl -X POST http://localhost:8000/api/episodes/ep_1781109978390/apply-glossary
```

---

## 🎨 前端使用

### 在PlayerView中添加编辑按钮

在 `PlayerView.vue` 中添加：

```vue
<template>
  <div class="player-view">
    <!-- 现有内容 -->

    <!-- 添加字幕编辑按钮 -->
    <button @click="showTranscriptEditor = true" class="btn-edit-transcript">
      📝 编辑字幕
    </button>

    <!-- 字幕编辑器模态框 -->
    <TranscriptEditor
      v-if="showTranscriptEditor"
      :episodeId="episodeId"
      @close="showTranscriptEditor = false"
    />
  </div>
</template>

<script setup>
import { ref } from 'vue'
import TranscriptEditor from '@/components/TranscriptEditor.vue'

const showTranscriptEditor = ref(false)
</script>
```

### 字幕编辑器功能

#### 1. 查看字幕列表
- 显示所有字幕segments
- 显示时间戳和编辑状态

#### 2. 编辑字幕
- 点击textarea直接编辑
- 点击"保存"按钮保存单个segment
- 点击"保存全部更改"批量保存

#### 3. 应用词库纠错
- 点击"📚 应用词库纠错"按钮
- 自动使用词库替换所有错误词汇
- 显示纠正统计

#### 4. 管理词库
- 点击"显示词库"展开词库面板
- 添加新的词库条目
- 删除现有条目

#### 5. 快速添加到词库
- 编辑segment后，点击"📚+"按钮
- 自动填充词库表单
- 确认后添加到词库

---

## 💡 使用场景

### 场景1: 快速纠正常见错误

1. 发现"小军"应该改为"张小珺"
2. 在字幕编辑器中找到该segment
3. 修改文本为"我是张小珺。"
4. 保存时选择"添加到词库"
5. 下次自动纠正所有相同错误

### 场景2: 批量应用词库

1. 点击"应用词库纠错"按钮
2. 系统自动扫描所有segments
3. 替换词库中的所有错误词汇
4. 显示纠正数量（如"纠正了5条字幕"）

### 场景3: 手动编辑专业术语

1. 找到包含专业术语的segment
2. 手动更正专业术语
3. 点击"📚+"添加到词库
4. 未来相同错误自动纠正

---

## 📊 词库格式

词库存储在 `backend/data/glossary.json`:

```json
{
  "entries": {
    "张小珺": ["小军", "张小君", "小珺"],
    "谢赛宁": ["赛宁", "谢赛林"],
    "人工智能": ["人工只能", "人之智能"]
  }
}
```

- **Key**: 正确的词汇
- **Value**: 错误的词汇列表（可以有多个）

---

## 🔄 同步机制

字幕修改后，系统会自动：

1. ✅ 更新 `transcript.json` - 字幕文件
2. 📋 标记需要重新生成 `outline.json` - 章节概要
3. 📝 标记需要重新生成 `summaries.json` - 章节摘要
4. 💡 标记需要重新生成 `highlight.json` - 洞察金句

**注意**: 当前版本仅标记需要重新生成，不会自动重新生成LLM内容（避免频繁调用API）。

---

## 🧪 测试

### 测试词库纠错

```bash
cd backend
python test_transcript_correction.py
```

### 测试字幕编辑API

```bash
# 更新segment
curl -X POST http://localhost:8000/api/episodes/ep_1781109978390/segments/update \
  -H "Content-Type: application/json" \
  -d '{
    "segment_index": 1,
    "text_original": "我是张小珺。",
    "note_to_glossary": true
  }'
```

---

## 🚀 扩展建议

### 1. 自动学习
- 统计常见的手动编辑
- 自动建议添加到词库

### 2. 模糊匹配
- 支持拼音相似度匹配
- 支持同音字识别

### 3. 导出词库
- 导出为CSV/Excel
- 批量导入

### 4. 版本控制
- 保存字幕编辑历史
- 支持撤销/恢复

---

## 📝 注意事项

1. **词库持久化**: 词库保存在 `backend/data/glossary.json`，重启后仍保留
2. **备份机制**: 修改字幕前建议先备份 `transcript.json`
3. **性能优化**: 大文件（>1000 segments）建议分批编辑
4. **LLM成本**: 词库纠错不消耗API调用，手动编辑也不消耗

---

## 🎯 最佳实践

1. **先应用词库** - 使用词库快速处理常见错误
2. **手动精修** - 处理词库无法覆盖的特殊情况
3. **及时更新词库** - 发现新模式后立即添加到词库
4. **定期导出** - 备份词库到其他地方

---

有任何问题或建议，欢迎反馈！
