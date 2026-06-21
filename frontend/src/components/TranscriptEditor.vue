<template>
  <div class="transcript-editor">
    <header class="editor-header">
      <div class="header-left">
        <h2>字幕编辑器</h2>
        <p v-if="episode" class="episode-title">{{ episode.title }}</p>
      </div>
      <div class="header-actions">
        <button @click="toggleGuide" class="btn btn-guide" :class="{ active: showGuide }">
          <span>💡 使用指南</span>
        </button>
        <button @click="showOnlyErrors = !showOnlyErrors" class="btn btn-toggle" :class="{ active: showOnlyErrors }">
          <span v-if="showOnlyErrors">👁️ 显示全部</span>
          <span v-else>⚠️ 仅显示错误</span>
        </button>
        <button @click="applyGlossary" class="btn btn-glossary" :disabled="applying">
          <span v-if="!applying">📚 一键纠错全部</span>
          <span v-else>纠错中...</span>
        </button>
        <button @click="saveAll" class="btn btn-save" :disabled="!hasChanges || saving">
          <span v-if="!saving">💾 保存全部更改</span>
          <span v-else>保存中...</span>
        </button>
      </div>
    </header>

    <!-- 使用指南面板 -->
    <transition name="slide-down">
      <div v-if="showGuide" class="guide-panel">
        <h3>🎯 如何纠错字幕？</h3>
        <div class="guide-steps">
          <div class="guide-step">
            <div class="step-number">1</div>
            <div class="step-content">
              <h4>一键纠错（推荐）</h4>
              <p>点击右上角 <strong>📚 一键纠错全部</strong> 按钮，系统会自动使用词库替换所有错误词汇。</p>
            </div>
          </div>
          <div class="guide-step">
            <div class="step-number">2</div>
            <div class="step-content">
              <h4>手动编辑</h4>
              <p>直接在文本框中修改错误词汇，然后点击 <strong>保存</strong> 按钮保存该条字幕。</p>
            </div>
          </div>
          <div class="guide-step">
            <div class="step-number">3</div>
            <div class="step-content">
              <h4>添加到词库</h4>
              <p>修正错误后，点击 <strong>📚+</strong> 按钮，将该词汇添加到词库，未来自动纠错。</p>
            </div>
          </div>
        </div>
        <div class="guide-tips">
          <p>💡 <strong>提示：</strong>标有 <span class="highlight-badge">高亮</span> 的字幕包含词库中的错误词，点击该segment的 <strong>📚 快速纠错</strong> 可立即修复。</p>
        </div>
      </div>
    </transition>

    <!-- 词库管理面板 -->
    <div class="glossary-panel" v-if="showGlossary">
      <div class="glossary-header">
        <h3>📚 专业词库</h3>
        <button @click="showGlossary = false" class="close-btn">×</button>
      </div>
      <div class="glossary-content">
        <div class="glossary-add">
          <h4>添加新词</h4>
          <div class="add-form">
            <input
              v-model="newCorrect"
              placeholder="正确的词（如：张小珺）"
              class="input-correct"
            />
            <input
              v-model="newWrong"
              placeholder="错误的词（如：小军）"
              class="input-wrong"
            />
            <button @click="addToGlossary" class="btn-add">添加</button>
          </div>
        </div>
        <div class="glossary-list">
          <h4>现有词汇（{{ Object.keys(glossary).length }}条）</h4>
          <div class="glossary-entries">
            <div
              v-for="(wrong, correct) in Object.entries(glossary)"
              :key="correct"
              class="glossary-entry"
            >
              <span class="correct">{{ correct }}</span>
              <span class="arrow">←</span>
              <span class="wrong">{{ wrong.join(", ") }}</span>
              <button @click="removeFromGlossary(correct)" class="btn-remove">×</button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 字幕列表 -->
    <div class="transcript-list">
      <!-- 错误提示栏 -->
      <div v-if="errorCount > 0" class="error-banner">
        <span v-if="showOnlyErrors">⚠️ 仅显示 {{ filteredSegments.length }} 条包含错误的字幕（共 {{ segments.length }} 条）</span>
        <span v-else>⚠️ 发现 {{ errorCount }} 条字幕包含可能的错误，已用 <span class="highlight-mark">黄色</span> 标记</span>
      </div>
      <div v-else-if="showOnlyErrors" class="info-banner">
        <span>✅ 没有发现包含错误的字幕</span>
      </div>

      <div
        v-for="{ seg: segment, index } in filteredSegments"
        :key="index"
        class="segment-item"
        :class="{
          edited: segment.manually_edited,
          corrected: segment.text_corrected,
          hasChanges: localChanges[index] !== undefined,
          hasErrors: hasSegmentErrors(index)
        }"
      >
        <div class="segment-header">
          <span class="segment-index">{{ index + 1 }}</span>
          <span class="segment-time">{{ formatTime(segment.start_ms) }}</span>
          <div class="segment-badges">
            <span v-if="hasSegmentErrors(index)" class="badge badge-error">⚠️ 包含错误</span>
            <span v-if="segment.manually_edited" class="badge badge-manual">已编辑</span>
            <span v-if="segment.text_corrected" class="badge badge-auto">已纠错</span>
          </div>
        </div>
        <div class="segment-content">
          <textarea
            v-model="segment.text_original"
            @input="markChanged(index)"
            class="segment-text"
            rows="2"
          ></textarea>
          <!-- 错误提示 -->
          <div v-if="getSegmentErrors(index).length > 0" class="error-hint">
            <span class="error-label">发现错误：</span>
            <span
              v-for="(error, idx) in getSegmentErrors(index)"
              :key="idx"
              class="error-item"
            >
              "{{ error.wrong }}" → "{{ error.correct }}"
            </span>
          </div>
        </div>
        <div class="segment-actions">
          <!-- 快速纠错按钮 -->
          <button
            v-if="hasSegmentErrors(index)"
            @click="quickFixSegment(index)"
            class="btn-segment btn-quick-fix"
            title="使用词库快速纠错"
          >
            📚 快速纠错
          </button>
          <button
            @click="saveSegment(index)"
            class="btn-segment"
            :disabled="!localChanges[index]"
          >
            保存
          </button>
          <button
            @click="addToGlossaryFromSegment(index)"
            class="btn-segment btn-add-glossary"
            title="添加到词库"
          >
            📚+
          </button>
          <button
            @click="resetSegment(index)"
            class="btn-segment btn-reset"
            :disabled="!segment.manually_edited && originalSegments[index] === segment.text_original"
          >
            重置
          </button>
        </div>
      </div>
    </div>

    <!-- 统计信息 -->
    <div class="stats-bar">
      <span>总条数: {{ segments.length }}</span>
      <span>已编辑: {{ editedCount }}</span>
      <span>待保存: {{ pendingChangesCount }}</span>
      <button @click="showGlossary = !showGlossary" class="btn-toggle-glossary">
        {{ showGlossary ? "隐藏" : "显示" }}词库
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import * as api from '@/api'

const props = defineProps({
  episodeId: {
    type: String,
    required: true
  }
})

const emit = defineEmits(['close'])

// 数据
const segments = ref([])
const originalSegments = ref({})
const localChanges = ref({})
const episode = ref(null)
const glossary = ref({})
const showGlossary = ref(false)
const showGuide = ref(true)  // 默认显示指南
const applying = ref(false)
const saving = ref(false)
const showOnlyErrors = ref(true)  // 只显示错误条目

// 新词表单
const newCorrect = ref('')
const newWrong = ref('')

// 计算属性
const editedCount = computed(() =>
  segments.value.filter(s => s.manually_edited).length
)

const pendingChangesCount = computed(() =>
  Object.keys(localChanges.value).length
)

const hasChanges = computed(() =>
  pendingChangesCount.value > 0
)

// 错误统计
const errorCount = computed(() => {
  let count = 0
  segments.value.forEach((seg, index) => {
    if (hasSegmentErrors(index)) {
      count++
    }
  })
  return count
})

// 过滤后的 segments（根据显示模式）
const filteredSegments = computed(() => {
  if (!showOnlyErrors.value) {
    return segments.value.map((seg, index) => ({ seg, index }))
  }
  return segments.value
    .map((seg, index) => ({ seg, index }))
    .filter(({ index }) => {
      // 显示包含错误的segments
      if (hasSegmentErrors(index)) return true

      // 也显示已编辑或已纠正的segments（让用户看到修改结果）
      const segment = segments.value[index]
      return segment.manually_edited || segment.text_corrected
    })
})

// 方法
const loadTranscript = async () => {
  try {
    console.log('[TranscriptEditor] Loading episode data...')
    const data = await api.getEpisode(props.episodeId)
    episode.value = data.episode

    console.log('[TranscriptEditor] Episode loaded:', episode.value?.title)

    // 读取transcript
    const transcriptData = await api.getTranscript(props.episodeId)
    const rawSegments = transcriptData.segments || []

    // 自动清理HTML标签和实体
    segments.value = rawSegments.map(seg => ({
      ...seg,
      text_original: cleanHtml(seg.text_original),
      // 清除前端状态标志
      manually_edited: false,
      text_corrected: false
    }))

    console.log('[TranscriptEditor] Loaded', segments.value.length, 'segments')

    // 保存原始副本（已清理）
    segments.value.forEach((seg, index) => {
      originalSegments.value[index] = seg.text_original
    })

    console.log('[TranscriptEditor] Original segments saved')
  } catch (error) {
    console.error('[TranscriptEditor] Failed to load transcript:', error)
    showError('加载字幕失败: ' + error.message)
  }
}

const loadGlossary = async () => {
  try {
    console.log('[TranscriptEditor] Loading glossary...')
    const data = await api.getGlossary()
    glossary.value = data.entries
    console.log('[TranscriptEditor] Glossary loaded:', Object.keys(glossary.value).length, 'entries')
    console.log('[TranscriptEditor] Glossary data:', glossary.value)
  } catch (error) {
    console.error('[TranscriptEditor] Failed to load glossary:', error)
    showError('加载词库失败: ' + error.message)
  }
}

const formatTime = (ms) => {
  const minutes = Math.floor(ms / 60000)
  const seconds = Math.floor((ms % 60000) / 1000)
  return `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`
}

// 清理HTML标签和实体
const cleanHtml = (text) => {
  if (!text) return ''
  // 解码HTML实体
  let cleaned = text
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&nbsp;/g, ' ')
  // 移除HTML标签
  cleaned = cleaned.replace(/<[^>]*>/g, '')
  return cleaned
}

const markChanged = (index) => {
  const segment = segments.value[index]
  if (segment.text_original !== originalSegments.value[index]) {
    localChanges.value[index] = true
  } else {
    delete localChanges.value[index]
  }
}

const saveSegment = async (index) => {
  try {
    const segment = segments.value[index]

    await api.updateTranscriptSegment(props.episodeId, {
      segment_index: index,
      text_original: segment.text_original,
      note_to_glossary: false
    })

    // 更新本地状态
    segment.manually_edited = true
    originalSegments.value[index] = segment.text_original
    delete localChanges.value[index]

    // 显示成功提示
    showSuccess('字幕已保存')
  } catch (error) {
    console.error('Failed to save segment:', error)
    showError('保存失败: ' + error.message)
  }
}

const resetSegment = (index) => {
  const segment = segments.value[index]
  segment.text_original = originalSegments.value[index]
  delete localChanges.value[index]
}

// 检查segment是否包含错误
const hasSegmentErrors = (index) => {
  return getSegmentErrors(index).length > 0
}

// 获取segment中的错误
const getSegmentErrors = (index) => {
  const segment = segments.value[index]
  if (!segment || !segment.text_original) return []

  const errors = []
  const text = segment.text_original

  // 检查词库中的每个条目
  for (const [correct, wrongList] of Object.entries(glossary.value)) {
    for (const wrong of wrongList) {
      if (text.includes(wrong)) {
        errors.push({ wrong, correct })
      }
    }
  }

  return errors
}

// 快速纠错单个segment
const quickFixSegment = (index) => {
  const segment = segments.value[index]
  const errors = getSegmentErrors(index)

  if (errors.length === 0) return

  // 应用所有纠错
  let correctedText = segment.text_original
  for (const error of errors) {
    correctedText = correctedText.replace(new RegExp(error.wrong, 'g'), error.correct)
  }

  segment.text_original = correctedText
  segment.text_corrected = true

  // 标记为已更改
  localChanges.value[index] = true
  showSuccess(`已自动纠错: ${errors[0].wrong} → ${errors[0].correct}`)
}

// 切换指南显示
const toggleGuide = () => {
  showGuide.value = !showGuide.value
}

const saveAll = async () => {
  saving.value = true

  try {
    // 批量保存所有更改的segments
    const promises = []
    for (const indexStr in localChanges.value) {
      const index = parseInt(indexStr)
      const segment = segments.value[index]

      promises.push(
        api.updateTranscriptSegment(props.episodeId, {
          segment_index: index,
          text_original: segment.text_original,
          note_to_glossary: false
        })
      )
    }

    await Promise.all(promises)

    // 更新本地状态
    for (const indexStr in localChanges.value) {
      const index = parseInt(indexStr)
      const segment = segments.value[index]
      segment.manually_edited = true
      originalSegments.value[index] = segment.text_original
    }

    localChanges.value = {}
    showSuccess(`已保存 ${promises.length} 条字幕\n\n关闭编辑器后将自动刷新页面显示更新后的内容`)

    // 自动关闭编辑器并触发父组件刷新
    emit('close')
  } catch (error) {
    console.error('Failed to save segments:', error)
    showError('批量保存失败: ' + error.message)
  } finally {
    saving.value = false
  }
}

const applyGlossary = async () => {
  applying.value = true

  try {
    console.log('[TranscriptEditor] Applying glossary to episode:', props.episodeId)

    const result = await api.applyGlossary(props.episodeId)

    console.log('[TranscriptEditor] Glossary applied:', result)
    console.log('[TranscriptEditor] Corrected segments:', result.corrected_segments)

    // 重新加载字幕
    await loadTranscript()

    showSuccess(`词库纠错完成，纠正了 ${result.corrected_segments} 条字幕\n\n关闭编辑器后将自动刷新页面显示更新后的内容`)

    // 自动关闭编辑器并触发父组件刷新
    emit('close')
  } catch (error) {
    console.error('[TranscriptEditor] Failed to apply glossary:', error)
    showError('词库纠错失败: ' + error.message)
  } finally {
    applying.value = false
  }
}

const addToGlossary = async () => {
  if (!newCorrect.value || !newWrong.value) {
    showError('请填写正确和错误的词汇')
    return
  }

  try {
    await api.addGlossaryEntry({
      correct: newCorrect.value,
      wrong: [newWrong.value]
    })

    // 重新加载词库
    await loadGlossary()

    newCorrect.value = ''
    newWrong.value = ''

    showSuccess('词库条目已添加')
  } catch (error) {
    console.error('Failed to add to glossary:', error)
    showError('添加失败: ' + error.message)
  }
}

const removeFromGlossary = async (correct) => {
  try {
    await api.deleteGlossaryEntry(correct)
    await loadGlossary()
    showSuccess('词库条目已删除')
  } catch (error) {
    console.error('Failed to remove from glossary:', error)
    showError('删除失败: ' + error.message)
  }
}

const addToGlossaryFromSegment = (index) => {
  const segment = segments.value[index]
  const currentText = segment.text_original
  const originalText = originalSegments.value[index]

  if (currentText !== originalText) {
    // 用户编辑过，推测原词是错误的
    newCorrect.value = currentText
    newWrong.value = originalText
    showGlossary.value = true
  }
}

const showSuccess = (message) => {
  // 简单的提示
  console.log('✅', message)
  // 使用alert作为临时提示
  alert(`✅ ${message}`)
}

const showError = (message) => {
  console.error('❌', message)
  // 使用alert作为临时提示
  alert(`❌ ${message}`)
}

onMounted(() => {
  loadTranscript()
  loadGlossary()
})
</script>

<style scoped>
.transcript-editor {
  max-width: 1200px;
  margin: 0 auto;
  padding: 20px;
}

.editor-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 30px;
  padding-bottom: 20px;
  border-bottom: 2px solid #e5e7eb;
}

.header-left h2 {
  margin: 0 0 8px 0;
  font-size: 24px;
  color: #1f2937;
}

.episode-title {
  margin: 0;
  font-size: 14px;
  color: #6b7280;
}

.header-actions {
  display: flex;
  gap: 12px;
}

.btn {
  padding: 10px 20px;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-glossary {
  background: linear-gradient(135deg, #f59e0b 0%, #d97706 100%);
  color: white;
}

.btn-glossary:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(245, 158, 11, 0.3);
}

.btn-save {
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
  color: white;
}

.btn-save:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3);
}

.btn-toggle {
  background: #e5e7eb;
  color: #374151;
}

.btn-toggle.active {
  background: linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%);
  color: white;
}

.btn-toggle:hover:not(:disabled) {
  transform: translateY(-1px);
}

.btn-toggle.active:hover {
  box-shadow: 0 4px 12px rgba(139, 92, 246, 0.3);
}

/* 词库面板 */
.glossary-panel {
  background: white;
  border: 2px solid #e5e7eb;
  border-radius: 12px;
  margin-bottom: 30px;
  overflow: hidden;
}

.glossary-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px;
  background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
  border-bottom: 1px solid #e5e7eb;
}

.glossary-header h3 {
  margin: 0;
  font-size: 18px;
  color: #92400e;
}

.close-btn {
  width: 32px;
  height: 32px;
  border: none;
  background: rgba(0,0,0,0.1);
  border-radius: 50%;
  cursor: pointer;
  font-size: 20px;
  color: #92400e;
}

.close-btn:hover {
  background: rgba(0,0,0,0.2);
}

.glossary-content {
  padding: 20px;
}

.glossary-add {
  margin-bottom: 24px;
  padding-bottom: 24px;
  border-bottom: 1px solid #e5e7eb;
}

.glossary-add h4 {
  margin: 0 0 12px 0;
  font-size: 14px;
  color: #6b7280;
}

.add-form {
  display: flex;
  gap: 12px;
}

.input-correct,
.input-wrong {
  flex: 1;
  padding: 10px 14px;
  border: 2px solid #e5e7eb;
  border-radius: 8px;
  font-size: 14px;
}

.input-correct:focus,
.input-wrong:focus {
  outline: none;
  border-color: #f59e0b;
}

.btn-add {
  padding: 10px 20px;
  background: #f59e0b;
  color: white;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  font-weight: 600;
}

.btn-add:hover {
  background: #d97706;
}

.glossary-list h4 {
  margin: 0 0 12px 0;
  font-size: 14px;
  color: #6b7280;
}

.glossary-entries {
  max-height: 300px;
  overflow-y: auto;
}

.glossary-entry {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  background: #f9fafb;
  border-radius: 8px;
  margin-bottom: 8px;
}

.correct {
  font-weight: 600;
  color: #059669;
}

.arrow {
  color: #9ca3af;
}

.wrong {
  color: #dc2626;
  flex: 1;
}

.btn-remove {
  width: 24px;
  height: 24px;
  border: none;
  background: #fee2e2;
  color: #dc2626;
  border-radius: 4px;
  cursor: pointer;
  font-size: 16px;
}

.btn-remove:hover {
  background: #fecaca;
}

/* 字幕列表 */
.transcript-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.segment-item {
  background: white;
  border: 2px solid #e5e7eb;
  border-radius: 12px;
  padding: 16px;
  transition: all 0.2s;
}

.segment-item:hover {
  border-color: #d1d5db;
  box-shadow: 0 2px 8px rgba(0,0,0,0.05);
}

.segment-item.edited {
  border-color: #3b82f6;
  background: #eff6ff;
}

.segment-item.corrected {
  border-color: #10b981;
  background: #ecfdf5;
}

.segment-item.hasChanges {
  border-color: #f59e0b;
  background: #fffbeb;
}

.segment-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.segment-index {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f3f4f6;
  border-radius: 8px;
  font-size: 12px;
  font-weight: 600;
  color: #6b7280;
}

.segment-time {
  font-family: 'SF Mono', Monaco, monospace;
  font-size: 13px;
  color: #6b7280;
}

.segment-badges {
  display: flex;
  gap: 6px;
  margin-left: auto;
}

.badge {
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 600;
}

.badge-manual {
  background: #dbeafe;
  color: #1d4ed8;
}

.badge-auto {
  background: #d1fae5;
  color: #059669;
}

.segment-text {
  width: 100%;
  padding: 12px;
  border: 2px solid #e5e7eb;
  border-radius: 8px;
  font-size: 14px;
  line-height: 1.6;
  resize: vertical;
  font-family: inherit;
}

.segment-text:focus {
  outline: none;
  border-color: #3b82f6;
}

.segment-actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}

.btn-segment {
  padding: 6px 14px;
  background: #f3f4f6;
  color: #4b5563;
  border: none;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
}

.btn-segment:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-segment:hover:not(:disabled) {
  background: #e5e7eb;
}

.btn-add-glossary {
  background: #fef3c7;
  color: #92400e;
}

.btn-add-glossary:hover:not(:disabled) {
  background: #fde68a;
}

.btn-reset {
  background: #fee2e2;
  color: #dc2626;
}

.btn-reset:hover:not(:disabled) {
  background: #fecaca;
}

/* 统计栏 */
.stats-bar {
  position: sticky;
  bottom: 0;
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 16px 20px;
  background: white;
  border-top: 2px solid #e5e7eb;
  margin-top: 30px;
  font-size: 14px;
  color: #6b7280;
}

.btn-toggle-glossary {
  margin-left: auto;
  padding: 8px 16px;
  background: #f59e0b;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.btn-toggle-glossary:hover {
  background: #d97706;
}

/* 使用指南面板 */
.btn-guide {
  background: linear-gradient(135deg, #8b5cf6 0%, #7c3aed 100%);
  color: white;
}

.btn-guide:hover:not(:disabled) {
  background: linear-gradient(135deg, #7c3aed 0%, #6d28d9 100%);
}

.guide-panel {
  background: linear-gradient(135deg, #ede9fe 0%, #ddd6fe 100%);
  border: 2px solid #a78bfa;
  border-radius: 12px;
  padding: 24px;
  margin-bottom: 30px;
}

.guide-panel h3 {
  margin: 0 0 20px 0;
  font-size: 18px;
  color: #5b21b6;
}

.guide-steps {
  display: flex;
  flex-direction: column;
  gap: 20px;
  margin-bottom: 20px;
}

.guide-step {
  display: flex;
  gap: 16px;
}

.step-number {
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #7c3aed;
  color: white;
  border-radius: 50%;
  font-size: 16px;
  font-weight: 700;
}

.step-content h4 {
  margin: 0 0 8px 0;
  font-size: 15px;
  color: #5b21b6;
}

.step-content p {
  margin: 0;
  font-size: 14px;
  color: #7c3aed;
  line-height: 1.6;
}

.step-content strong {
  color: #5b21b6;
  font-weight: 600;
}

.guide-tips {
  padding: 16px;
  background: rgba(139, 92, 246, 0.1);
  border-radius: 8px;
  border: 1px solid #a78bfa;
}

.guide-tips p {
  margin: 0;
  font-size: 13px;
  color: #6b7280;
}

.highlight-badge {
  padding: 2px 8px;
  background: #f59e0b;
  color: white;
  border-radius: 4px;
  font-weight: 600;
}

/* 错误提示栏 */
.error-banner {
  padding: 12px 20px;
  background: #fef3c7;
  border: 2px solid #f59e0b;
  border-radius: 8px;
  margin-bottom: 20px;
  font-size: 14px;
  color: #92400e;
}

.highlight-mark {
  padding: 2px 6px;
  background: #f59e0b;
  color: white;
  border-radius: 4px;
  font-weight: 600;
}

.info-banner {
  padding: 12px 20px;
  background: #d1fae5;
  border: 2px solid #10b981;
  border-radius: 8px;
  margin-bottom: 20px;
  font-size: 14px;
  color: #065f46;
}

/* segment错误状态 */
.segment-item.hasErrors {
  border-color: #f59e0b;
  background: #fffbeb;
  border-width: 3px;
}

.badge-error {
  background: #fef3c7;
  color: #92400e;
}

.error-hint {
  padding: 8px 12px;
  background: #fef3c7;
  border-radius: 6px;
  margin-top: 8px;
  font-size: 13px;
}

.error-label {
  font-weight: 600;
  color: #92400e;
  margin-right: 4px;
}

.error-item {
  color: #dc2626;
  margin-right: 12px;
}

.btn-quick-fix {
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  color: white;
  border: none;
}

.btn-quick-fix:hover:not(:disabled) {
  background: linear-gradient(135deg, #059669 0%, #047857 100%);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
}

/* slide-down动画 */
.slide-down-enter-active,
.slide-down-leave-active {
  transition: all 0.3s ease;
  max-height: 500px;
  overflow: hidden;
}

.slide-down-enter-from,
.slide-down-leave-to {
  max-height: 0;
  opacity: 0;
}
</style>
