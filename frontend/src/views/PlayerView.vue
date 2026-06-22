<template>
  <div class="player-view">
    <!-- 顶部导航栏 -->
    <header class="player-header">
      <button @click="goBack" class="icon-btn" title="返回">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M19 12H5M12 19l-7-7 7-7"/>
        </svg>
      </button>
      <div class="title-info">
        <h1 class="episode-title">{{ bundle?.episode?.title || '未知节目' }}</h1>
        <span class="episode-meta">
          {{ bundle?.outline?.entries?.length || 0 }} 章节 ·
          {{ formatDuration(bundle?.transcript?.segments) }}
        </span>
      </div>
      <div class="header-actions">
        <!-- 编辑字幕按钮 -->
        <button @click="showTranscriptEditor = true" class="icon-btn" title="编辑字幕">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
            <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
          </svg>
        </button>
        <!-- 导出按钮 -->
        <button @click="showExportModal = true" class="icon-btn" title="导出摘要">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
            <polyline points="7 10 12 15 17 10"/>
            <line x1="12" y1="15" x2="12" y2="3"/>
          </svg>
        </button>
      </div>
    </header>

    <!-- 音频播放器 - 全宽 -->
    <div class="audio-section">
      <audio
        ref="audioRef"
        :src="audioUrl"
        @timeupdate="onTimeUpdate"
        @loadedmetadata="onLoadedMetadata"
        @canplay="onCanPlay"
        @canplaythrough="onCanPlayThrough"
        @loadeddata="onLoadedData"
        @seeked="onAudioSeeked"
        @seeking="onAudioSeeking"
        preload="auto"
        controls
        class="audio-player"
      />
    </div>

    <!-- Error message display -->
    <transition name="fade">
      <div v-if="loadError" class="error-banner">
        <div class="error-content">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <line x1="12" y1="8" x2="12" y2="12"/>
            <line x1="12" y1="16" x2="12.01" y2="16"/>
          </svg>
          <span class="error-message">{{ loadErrorMessage }}</span>
          <button @click="loadEpisode" class="error-retry">重试</button>
          <button @click="loadError = null" class="error-dismiss">✕</button>
        </div>
      </div>
    </transition>

    <!-- 主内容区 - 两栏布局 -->
    <main class="player-main">
      <!-- 左栏：章节 + 摘要 -->
      <aside class="chapters-panel">
        <h2 class="panel-title">章节</h2>
        <div class="chapters-list">
          <div
            v-for="(chapter, idx) in chapters"
            :key="idx"
            class="chapter-item"
            :class="{ active: isCurrentChapter(idx) }"
          >
            <div class="chapter-header" @click="localSeekTo(chapter.start_ms)">
              <span class="chapter-num">{{ idx + 1 }}</span>
              <div class="chapter-info">
                <p class="chapter-title">{{ chapter.title_zh }}</p>
                <span class="chapter-time">{{ formatTime(chapter.start_ms) }}</span>
              </div>
              <button
                @click.stop="toggleChapter(idx)"
                class="expand-btn"
                :class="{ expanded: expandedChapter === idx }"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <polyline :points="expandedChapter === idx ? '6 9 12 15 18 9' : '18 15 12 9 6 15'"/>
                </svg>
              </button>
            </div>
            <transition name="expand">
              <div v-show="expandedChapter === idx" class="chapter-summary">
                <div v-if="getChapterSummary(idx)" class="summary-content">
                  <p class="summary-text">{{ getChapterSummary(idx)?.content_zh }}</p>
                  <ul v-if="getChapterSummary(idx)?.key_points_zh?.length" class="key-points">
                    <li v-for="(point, pidx) in getChapterSummary(idx).key_points_zh" :key="pidx">
                      {{ point }}
                    </li>
                  </ul>
                </div>
                <div v-else class="summary-empty">
                  <span class="empty-text">暂无摘要</span>
                </div>
              </div>
            </transition>
          </div>
        </div>
      </aside>

      <!-- 右栏：Tab 切换 -->
      <section class="content-tabs">
        <div class="tab-header" role="tablist" aria-label="节目内容视图">
          <button
            v-for="tab in tabs"
            :key="tab.id"
            @click="activeTab = tab.id"
            class="tab-btn"
            :class="{ active: activeTab === tab.id }"
            role="tab"
            :aria-selected="activeTab === tab.id"
            :id="`tab-${tab.id}`"
            :aria-controls="`tabpanel-${tab.id}`"
          >
            {{ tab.label }}
          </button>
        </div>

        <!-- Tab 1: 摘要 + 金句 -->
        <div v-show="activeTab === 'summary'" class="tab-content summary-tab" role="tabpanel" id="tabpanel-summary" aria-labelledby="tab-summary">
          <div v-if="highlight" class="verdict-card">
            <p class="tldr-text">{{ highlight.tldr_zh }}</p>
            <div class="verdict-row">
              <span class="verdict-badge" :class="`verdict-${highlight.worth_listening_verdict}`">
                {{ verdictText(highlight.worth_listening_verdict) }}
              </span>
              <span class="audience-text">{{ highlight.target_audience_zh }}</span>
            </div>
          </div>

          <div v-if="highlightsByKind.length" class="highlights-section">
            <h3 class="section-title">金句 · 洞察</h3>
            <div class="highlights-content">
              <div v-for="group in highlightsByKind" :key="group.kind" class="highlight-group">
                <div class="highlight-group-header">
                  <span class="group-icon">{{ group.icon }}</span>
                  <span class="group-label">{{ group.label }}</span>
                  <span class="group-count">{{ group.items.length }}</span>
                </div>
                <div class="highlight-group-items">
                  <div
                    v-for="(item, idx) in group.items"
                    :key="idx"
                    class="highlight-item"
                    @click.stop="localSeekTo(item.start_ms)"
                  >
                    <div class="h-main">
                      <p class="h-text">{{ item.text_zh }}</p>
                      <span v-if="item.start_ms" class="h-time" @click.stop="localSeekTo(item.start_ms)">
                        {{ formatTime(item.start_ms) }}
                      </span>
                    </div>
                    <span class="h-why">{{ item.why_zh }}</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- Tab 2: 转录字幕 -->
        <div v-show="activeTab === 'transcript'" class="tab-content transcript-tab" role="tabpanel" id="tabpanel-transcript" aria-labelledby="tab-transcript">
          <!-- 标点恢复失败的提示：避免用户以为"字幕没标点"是 bug -->
          <div
            v-if="bundle?.episode?.punctuation_status?.status === 'failed'"
            class="punct-warning"
            role="alert"
          >
            <span class="punct-warning-icon">⚠️</span>
            <span class="punct-warning-text">
              字幕标点自动恢复失败（{{ bundle.episode.punctuation_status.error_type }}），
              当前为原始 ASR 文本。可尝试使用"术语纠错"或"LLM 纠正"功能补救。
            </span>
          </div>
          <div class="transcript-header">
            <div class="subtitle-info">
              <span class="subtitle-count">{{ formatTime(segments[segments.length - 1]?.end_ms || 0) }}</span>
            </div>
            <div class="language-toggles">
              <button
                @click="subtitleLang = 'original'"
                :class="{ active: subtitleLang === 'original' }"
                :disabled="!hasOriginal"
                class="lang-btn"
              >
                原文
              </button>
              <button
                @click="subtitleLang = 'translated'"
                :class="{ active: subtitleLang === 'translated' }"
                :disabled="!hasTranslated"
                class="lang-btn"
              >
                翻译
              </button>
              <button
                @click="subtitleLang = 'both'"
                :class="{ active: subtitleLang === 'both' }"
                :disabled="!hasTranslated"
                class="lang-btn"
              >
                双语
              </button>
            </div>
          </div>
          <div
            ref="transcriptContainer"
            class="transcript-content"
            v-if="paragraphs.length > 0"
            @scroll="handleUserScroll"
          >
            <DynamicScroller
              ref="transcriptScroller"
              :items="paragraphs"
              :min-item-size="60"
              key-field="id"
              class="transcript-scroller"
              v-slot="{ item, index, active }"
            >
              <DynamicScrollerItem
                :item="item"
                :active="active"
                :data-index="index"
                :data-paragraph-id="index"
              >
                <div
                  :key="item.id"
                  class="subtitle-block"
                  :class="{ active: isCurrentParagraph(item) }"
                  @click="localSeekTo(item.start_ms)"
                >
                  <span class="block-time">{{ formatTimeRange(item.start_ms, item.end_ms) }}</span>
                  <div class="block-content">
                    <span v-if="subtitleLang === 'original' || subtitleLang === 'both'" class="block-text">{{ item.text_clean || item.text_original }}</span>
                    <span v-if="subtitleLang === 'translated' || subtitleLang === 'both'" class="block-translated">{{ item.text_translated || item.text_clean || item.text_original }}</span>
                  </div>
                </div>
              </DynamicScrollerItem>
            </DynamicScroller>
          </div>
          <div v-else class="empty-state">
            <svg width="40" height="40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <path d="M9 12h6M12 9v6"/>
            </svg>
            <p>暂无字幕</p>
          </div>
        </div>

        <!-- Tab 3: 产品和技术洞察 -->
        <div v-show="activeTab === 'insights'" class="tab-content insights-tab" role="tabpanel" id="tabpanel-insights" aria-labelledby="tab-insights">
          <div v-if="productInsights" class="insights-content">
            <!-- 产品洞察 -->
            <div v-if="productInsights.product_insights_zh?.length" class="insight-section">
              <h3 class="insight-section-title">
                <span class="section-icon">📦</span>
                产品洞察
              </h3>
              <ul class="insight-list">
                <li v-for="(item, idx) in productInsights.product_insights_zh" :key="'p-' + idx">
                  {{ item }}
                </li>
              </ul>
            </div>

            <!-- 技术洞察 -->
            <div v-if="productInsights.technical_insights_zh?.length" class="insight-section">
              <h3 class="insight-section-title">
                <span class="section-icon">⚙️</span>
                技术洞察
              </h3>
              <ul class="insight-list">
                <li v-for="(item, idx) in productInsights.technical_insights_zh" :key="'t-' + idx">
                  {{ item }}
                </li>
              </ul>
            </div>

            <!-- 市场洞察 -->
            <div v-if="productInsights.market_insights_zh?.length" class="insight-section">
              <h3 class="insight-section-title">
                <span class="section-icon">📊</span>
                市场/行业洞察
              </h3>
              <ul class="insight-list">
                <li v-for="(item, idx) in productInsights.market_insights_zh" :key="'m-' + idx">
                  {{ item }}
                </li>
              </ul>
            </div>

            <!-- 提到的公司/技术 -->
            <div v-if="productInsights.mentioned_companies?.length || productInsights.mentioned_technologies?.length" class="insight-tags">
              <div v-if="productInsights.mentioned_companies?.length" class="tag-group">
                <span class="tag-label">提到的公司/产品：</span>
                <div class="tags">
                  <span v-for="(tag, idx) in productInsights.mentioned_companies" :key="'c-' + idx" class="tag">
                    {{ tag }}
                  </span>
                </div>
              </div>
              <div v-if="productInsights.mentioned_technologies?.length" class="tag-group">
                <span class="tag-label">提到的技术：</span>
                <div class="tags">
                  <span v-for="(tag, idx) in productInsights.mentioned_technologies" :key="'tech-' + idx" class="tag">
                    {{ tag }}
                  </span>
                </div>
              </div>
            </div>
          </div>

          <!-- 占位符：没有洞察数据时显示 -->
          <div v-else class="insights-placeholder">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <path d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"/>
            </svg>
            <h3>暂无产品洞察</h3>
            <p>此节目尚未生成产品和技术洞察。</p>
            <button @click="generateInsights" class="generate-btn">
              生成洞察
            </button>
          </div>
        </div>
      </section>
    </main>

    <!-- 快捷键展示区域 - 固定在底部 -->
    <div class="shortcuts-bar">
      <div class="shortcuts-container">
        <div class="shortcuts-header">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <rect x="2" y="4" width="20" height="16" rx="2"/>
            <path d="M6 8h.01M10 8h.01M14 8h.01M18 8h.01M6 12h.01M10 12h.01M14 12h.01M18 12h.01M10 16h4"/>
          </svg>
          <span>快捷键</span>
        </div>
        <div class="shortcuts-list">
          <div class="shortcut-chip">
            <kbd>空格</kbd>
            <span>播放/暂停</span>
          </div>
          <div class="shortcut-chip">
            <kbd>←</kbd>
            <span>后退5s</span>
          </div>
          <div class="shortcut-chip">
            <kbd>→</kbd>
            <span>前进5s</span>
          </div>
          <div class="shortcut-chip">
            <kbd>J</kbd>
            <span>上一章</span>
          </div>
          <div class="shortcut-chip">
            <kbd>K</kbd>
            <span>下一章</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 导出模态框 -->
    <ExportModal
      :show="showExportModal"
      :episode-id="bundle?.episode?.id"
      :episode-title="bundle?.episode?.title"
      @close="showExportModal = false"
    />

    <!-- 字幕编辑器 -->
    <Teleport to="body">
      <Transition name="modal">
        <div v-if="showTranscriptEditor" class="transcript-modal-overlay" @click="handleTranscriptEditorClose">
          <div class="transcript-modal-content" @click.stop>
            <button @click="handleTranscriptEditorClose" class="modal-close-btn">✕</button>
            <TranscriptEditor
              v-if="bundle?.episode?.id"
              :episode-id="bundle?.episode?.id"
              @close="handleTranscriptEditorClose"
            />
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import ExportModal from '@/components/ExportModal.vue'
import TranscriptEditor from '@/components/TranscriptEditor.vue'
import * as api from '@/api'
import { usePlayer } from '@/composables/player'
import { useSubtitleScroll } from '@/composables/useSubtitleScroll'
import { DynamicScroller, DynamicScrollerItem } from 'vue-virtual-scroller'
// SubtitleMapping 组件已移除 - 改为直接显示时间范围

const router = useRouter()
const route = useRoute()

const props = defineProps({
  id: { type: String, required: false }
})

const episodeId = computed(() => props.id || route.params.id)

const {
  bundle: bundleRef,
  setBundle,
  currentTime,
  seekTo,
  togglePlay,
  seekRelative,
  setAudioRef,
  onTimeUpdate,
  onLoadedMetadata
} = usePlayer()

// 音频加载状态
const audioReady = ref(false)
const pendingSeek = ref(null)

// 音频准备好后的处理
const onCanPlay = (event) => {
  // 防止重复触发（当 seek 时可能会触发 canplay）
  if (event && event.type === 'canplay' && audioReady.value && audioRef.value && audioRef.value.currentTime > 1) {
    console.log('[PlayerView] canplay event fired but audio already ready and has content, ignoring')
    return
  }

  console.log('[PlayerView] Audio canplay event fired')
  audioReady.value = true

  // 如果有待处理的跳转，执行它
  if (pendingSeek.value !== null) {
    console.log('[PlayerView] Executing pending seek to', pendingSeek.value)
    const ms = pendingSeek.value
    pendingSeek.value = null

    // 使用 setTimeout 确保在事件循环下一帧执行，避免事件冲突
    setTimeout(() => {
      if (audioRef.value && audioReady.value) {
        executeSeek(ms)
      }
    }, 0)
  }
}

const onLoadedData = () => {
  console.log('[PlayerView] Audio loadeddata event fired')
  audioReady.value = true
}

const onCanPlayThrough = () => {
  console.log('[PlayerView] Audio canplaythrough event fired')
  audioReady.value = true
}

const onAudioSeeking = () => {
  console.log('[PlayerView] Audio seeking event fired')
}

const onAudioSeeked = () => {
  console.log('[PlayerView] Audio seeked event fired, currentTime is now', audioRef.value?.currentTime)

  // Reset seeking flag and process queue
  isSeeking.value = false

  // Process queued seeks if any
  if (seekQueue.value.length > 0) {
    const nextSeek = seekQueue.value.shift()
    console.log('[PlayerView] Processing queued seek:', nextSeek)
    setTimeout(() => {
      if (audioRef.value && audioReady.value) {
        executeSeek(nextSeek)
      }
    }, 50)
  }
}

// 实际执行跳转的函数
const executeSeek = (ms) => {
  if (!audioRef.value) return

  const audio = audioRef.value
  const targetTime = ms / 1000
  console.log('[executeSeek] Setting currentTime to', targetTime, 'current is', audio.currentTime)

  // 先暂停
  audio.pause()

  // 直接设置播放位置
  audio.currentTime = targetTime

  // 等待 seeked 事件确认跳转完成
  setTimeout(() => {
    console.log('[executeSeek] Checking currentTime after seek:', audio.currentTime, 'expected:', targetTime)

    if (Math.abs(audio.currentTime - targetTime) < 1) {
      // Seek 成功
      audio.play().then(() => {
        console.log('[executeSeek] Play succeeded, currentTime is', audio.currentTime)
      }).catch(err => {
        console.warn('[executeSeek] Play failed:', err)
      })
    } else {
      console.warn('[executeSeek] Seek did not work, currentTime is', audio.currentTime, 'expected', targetTime)
      audio.currentTime = targetTime
      setTimeout(() => audio.play().catch(console.warn), 100)
    }
  }, 100)
}

const bundle = bundleRef
const audioRef = ref(null)
const transcriptContainer = ref(null)
// DynamicScroller 实例引用，用于把它的 scrollToItem 注入到 useSubtitleScroll
const transcriptScroller = ref(null)
const subtitleLang = ref('original')
const expandedChapter = ref(-1)
const showExportModal = ref(false)
const showTranscriptEditor = ref(false)
// isMappingExpanded 已移除 - 不再需要映射展开状态

// Error states
const loadError = ref(null)
const loadErrorMessage = ref('')

// Seek queue to prevent race conditions
const isSeeking = ref(false)
const seekQueue = ref([])

// Tab 状态
const activeTab = ref('summary')

const tabs = [
  { id: 'summary', label: '摘要 + 金句' },
  { id: 'transcript', label: '转录字幕' },
  { id: 'insights', label: '产品和技术洞察' }
]

// 音频 URL
const audioUrl = computed(() => {
  if (!bundle.value?.episode?.id) return ''
  return `/media/${bundle.value.episode.id}/audio.m4a`
})

// HTML 实体解码
const decodeHtml = (text) => {
  const doc = new DOMParser()
  doc.documentElement.innerHTML = text
  return doc.documentElement.textContent
}

// 清理文本：移除多余空白和符号
const cleanText = (text) => {
  if (!text) return ''
  let cleaned = text
    // 解码 HTML 实体
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&')
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    // 移除 HTML 标签
    .replace(/<[^>]*>/g, '')
    // 移除多余空白
    .replace(/\s+/g, ' ')
    .trim()
  return cleaned
}

// 将零散的字幕段落合并成段落
const segments = computed(() => bundle.value?.transcript?.segments || [])

const paragraphs = computed(() => {
  // Prioritize backend paragraph_mappings if available
  if (bundle.value?.episode?.paragraph_mappings && bundle.value.episode.paragraph_mappings.length > 0) {
    console.log('[PlayerView] Using backend paragraph_mappings')
    return bundle.value.episode.paragraph_mappings
  }

  // Fallback to frontend paragraph generation
  if (!segments.value.length) return []

  const result = []
  const MAX_PARA_CHARS = 120 // 每段最多120字符
  const MIN_PARA_CHARS = 40   // 每段最少40字符

  let currentPara = {
    id: 0,
    segments: [],
    text: '',
    translated: ''
  }

  for (let i = 0; i < segments.value.length; i++) {
    const seg = segments.value[i]
    const segText = cleanText(seg.text_original || '')
    const segTrans = seg.text_translated || ''

    if (!segText) continue

    // 检查是否需要开始新段落
    const wouldExceed = currentPara.text.length + segText.length > MAX_PARA_CHARS
    const hasMinContent = currentPara.text.length >= MIN_PARA_CHARS

    if (hasMinContent && wouldExceed) {
      // 保存当前段落
      if (currentPara.segments.length > 0) {
        result.push({
          id: currentPara.id,
          start_ms: currentPara.segments[0].start_ms,
          end_ms: currentPara.segments[currentPara.segments.length - 1].end_ms,
          text_original: currentPara.text,
          text_translated: currentPara.translated,
          text_clean: currentPara.text
        })
      }
      // 开始新段落
      currentPara = {
        id: result.length,
        segments: [seg],
        text: segText,
        translated: segTrans
      }
    } else {
      // 添加到当前段落
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
      text_clean: currentPara.text
    })
  }

  console.log(`[PlayerView] Generated ${result.length} paragraphs from ${segments.value.length} segments`)

  return result
})

const chapters = computed(() => bundle.value?.outline?.entries || [])
const highlight = computed(() => bundle.value?.highlight)
const productInsights = computed(() => bundle.value?.product_insights)

const hasOriginal = computed(() => segments.value.length > 0)
const hasTranslated = computed(() => segments.value.some(s => s.text_translated))

const isCurrentParagraph = (para) => {
  if (!currentTime.value) return false
  return currentTime.value >= para.start_ms && currentTime.value < para.end_ms
}

const isCurrentChapter = (index) => {
  if (!currentTime.value || !chapters.value[index]) return false
  const ch = chapters.value[index]
  return currentTime.value >= ch.start_ms && currentTime.value < ch.end_ms
}

const getChapterSummary = (index) => {
  const summaries = bundle.value?.chapter_summaries
  if (!summaries || !Array.isArray(summaries)) return null
  return summaries.find(s => s.chapter_id === `ch${index}`)
}

const toggleChapter = (index) => {
  expandedChapter.value = expandedChapter.value === index ? -1 : index
}

// 格式化 / 亮点展示助手：从 utils/formatters 引入，避免在视图层堆纯函数。
import {
  formatTime,
  formatTimeRange,
  formatDuration,
  verdictText,
  getHighlightKind,
  getHighlightKindLabel,
} from '@/utils/formatters'

// 按类型分组亮点
const highlightsByKind = computed(() => {
  if (!highlight.value?.highlights) return []

  const groups = {
    quote: { label: '金句', icon: '💬', items: [] },
    insight: { label: '洞察', icon: '💡', items: [] },
    fact: { label: '数据', icon: '📊', items: [] },
    contrarian: { label: '反常识', icon: '🔥', items: [] },
    story: { label: '故事', icon: '📖', items: [] }
  }

  highlight.value.highlights.forEach(h => {
    if (groups[h.kind]) {
      groups[h.kind].items.push(h)
    }
  })

  return Object.entries(groups)
    .filter(([_, g]) => g.items.length > 0)
    .map(([kind, g]) => ({ kind, ...g }))
})

const navigateChapter = (direction) => {
  const currentIdx = chapters.value.findIndex((ch, idx) => isCurrentChapter(idx))
  if (direction < 0 && currentIdx > 0) {
    localSeekTo(chapters.value[currentIdx - 1].start_ms)
  } else if (direction > 0 && currentIdx < chapters.value.length - 1) {
    localSeekTo(chapters.value[currentIdx + 1].start_ms)
  }
}

// 键盘快捷键：注册/卸载由 useKeyboardShortcuts 在 onMounted/onUnmounted 自动管理。
// 历史上这里有一段 25 行的 handleKeyboard 函数和两处 add/removeEventListener。
import { useKeyboardShortcuts } from '@/composables/useKeyboardShortcuts'
useKeyboardShortcuts({
  onSpace: () => togglePlay(),
  onSeek: (deltaSec) => seekRelative(deltaSec),
  onChapter: (direction) => navigateChapter(direction),
})

const localSeekTo = (ms) => {
  console.log('[localSeekTo] Called with ms:', ms)

  if (!ms && ms !== 0) {
    console.warn('[localSeekTo] Invalid timestamp:', ms)
    return
  }

  // Add to seek queue if currently seeking
  if (isSeeking.value) {
    console.log('[localSeekTo] Already seeking, adding to queue:', ms)
    seekQueue.value.push(ms)
    // Keep only the most recent seek (replace entire queue)
    if (seekQueue.value.length > 1) {
      seekQueue.value = [ms]
    }
    return
  }

  const targetTime = ms / 1000
  console.log(`[localSeekTo] Seeking to ${ms}ms (${targetTime.toFixed(2)}s)`)

  // 检查 audioRef
  console.log('[localSeekTo] audioRef.value:', audioRef.value)
  console.log('[localSeekTo] audioReady.value:', audioReady.value)

  if (!audioRef.value) {
    console.warn('[localSeekTo] audioRef is null')
    seekTo(ms)
    return
  }

  const audio = audioRef.value
  console.log('[localSeekTo] audio.readyState:', audio.readyState)
  console.log('[localSeekTo] audio.duration:', audio.duration)

  // 如果音频还没准备好，保存待处理的跳转
  if (!audioReady.value || audio.readyState < 2 || audio.duration === 0) {
    console.warn('[localSeekTo] Audio not ready, saving pending seek')
    pendingSeek.value = ms
    return
  }

  // 音频已准备好，直接跳转
  console.log('[localSeekTo] Audio ready, executing seek')
  isSeeking.value = true
  executeSeek(ms)
}

const loadEpisode = async () => {
  try {
    // Clear previous error state
    loadError.value = null
    loadErrorMessage.value = ''

    const data = await api.fetchEpisode(episodeId.value)
    console.log('[PlayerView] API returned data keys:', Object.keys(data))
    console.log('[PlayerView] Transcript check:', {
      hasTranscript: !!data.transcript,
      transcriptKeys: data.transcript ? Object.keys(data.transcript) : 'N/A',
      segmentCount: data.transcript?.segments?.length || 0
    })
    setBundle(data)
    console.log('[PlayerView] Bundle set successfully')
  } catch (e) {
    console.error('[PlayerView] 加载失败:', e)
    loadError.value = e
    loadErrorMessage.value = e.message || '加载失败，请稍后重试'
  }
}

const handleTranscriptEditorClose = async () => {
  showTranscriptEditor.value = false
  // 重新加载节目数据以获取更新后的字幕
  await loadEpisode()
}

const goBack = () => router.push({ name: 'library' })

const generateInsights = async () => {
  try {
    const response = await fetch(`/api/episode/${episodeId.value}/insights`, {
      method: 'POST',
    })
    if (response.ok) {
      const data = await response.json()
      console.log('[PlayerView] Insights generation started:', data)
      // 重新加载数据
      setTimeout(() => loadEpisode(), 2000)
    } else {
      const error = await response.json()
      console.error('[PlayerView] Insights generation failed:', error)
      alert(error.detail || '生成洞察失败')
    }
  } catch (e) {
    console.error('[PlayerView] Insights generation error:', e)
  }
}

// Initialize subtitle scroll functionality
const {
  scrollToActive,
  enableAutoScroll,
  disableAutoScroll,
  watchTime,
  cleanup: cleanupScroll
} = useSubtitleScroll(transcriptContainer, paragraphs, {
  block: 'center',
  threshold: 500,
  // 虚拟滚动模式下，远距离 index 的 DOM 节点会被回收；
  // 用 DynamicScroller 自带的 scrollToItem 跳转，绕开 querySelector。
  scrollToItemFn: (index) => {
    if (transcriptScroller.value && typeof transcriptScroller.value.scrollToItem === 'function') {
      transcriptScroller.value.scrollToItem(index)
    }
  },
})

// Watch activeTab changes to enable auto-scroll when switching to transcript tab
watch(activeTab, (newTab, oldTab) => {
  if (newTab === 'transcript' && oldTab !== 'transcript') {
    // 用户切换到字幕tab，启用自动滚动并滚动到当前播放位置
    nextTick(() => {
      enableAutoScroll()
      scrollToActive(currentTime.value)
    })
  }
})

// 监听用户手动滚动，禁用自动滚动
let userScrollTimeout = null
const handleUserScroll = () => {
  // 用户手动滚动，禁用自动滚动
  disableAutoScroll()

  // 防抖：如果用户停止滚动3秒后，可以重新启用自动滚动
  if (userScrollTimeout) clearTimeout(userScrollTimeout)
  userScrollTimeout = setTimeout(() => {
    // 可选：停止滚动3秒后重新启用自动滚动
    // enableAutoScroll()
  }, 3000)
}

// Watch currentTime changes and scroll to active paragraph
const timeWatcher = watchTime(currentTime, (newIndex, didScroll) => {
  // 只在字幕tab可见时更新当前段落索引
  if (activeTab.value === 'transcript') {
    // 更新当前段落索引（用于高亮显示）
    // 如果didScroll为false，说明用户手动滚动，只更新不滚动
    // 如果didScroll为true，说明已经自动滚动了
  }
})

// toggleMapping 函数已移除 - 不再需要映射展开功能
// formatTimeRange 函数已添加到 formatTime 函数附近

onMounted(() => {
  loadEpisode()
  // keydown 监听由 useKeyboardShortcuts 在自己的 onMounted 里注册

  // 确保音频元素准备就绪后再设置全局引用
  nextTick(() => {
    if (audioRef.value) {
      console.log('[PlayerView] Setting audioRef to global state')
      setAudioRef(audioRef.value)
    } else {
      console.error('[PlayerView] audioRef is null on mount')
    }
  })
})

onUnmounted(() => {
  // keydown 监听由 useKeyboardShortcuts 在自己的 onUnmounted 里卸载

  // Cleanup scroll composable to prevent memory leaks
  if (cleanupScroll) {
    cleanupScroll()
  }

  // Clear user scroll timeout
  if (userScrollTimeout) clearTimeout(userScrollTimeout)

  // Clear any pending seeks
  isSeeking.value = false
  seekQueue.value = []
  pendingSeek.value = null
})
</script>

<style scoped>
.player-view {
  min-height: 100vh;
  background: linear-gradient(135deg, #f5f7fa 0%, #e8ecf1 100%);
  display: flex;
  flex-direction: column;
}

/* 顶部导航 */
.player-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 20px;
  background: white;
  border-bottom: 1px solid #e5e7eb;
  position: sticky;
  top: 0;
  z-index: 10;
}

.icon-btn {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: #f3f4f6;
  border-radius: 10px;
  cursor: pointer;
  color: #4b5563;
  transition: all 0.2s;
}

.icon-btn:hover {
  background: #e5e7eb;
  color: #1f2937;
}

.title-info {
  flex: 1;
  min-width: 0;
}

.episode-title {
  font-size: 16px;
  font-weight: 600;
  color: #1f2937;
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.episode-meta {
  font-size: 12px;
  color: #6b7280;
}

.header-actions {
  display: flex;
  gap: 8px;
}

/* 音频播放器 - 全宽 */
.audio-section {
  padding: 12px 20px;
  background: white;
  border-bottom: 1px solid #e5e7eb;
}

/* Error banner */
.error-banner {
  padding: 12px 20px;
  background: #fee2e2;
  border-bottom: 1px solid #fecaca;
}

.error-content {
  display: flex;
  align-items: center;
  gap: 12px;
  color: #dc2626;
}

.error-message {
  flex: 1;
  font-size: 14px;
  font-weight: 500;
}

.error-retry {
  padding: 6px 16px;
  background: #dc2626;
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.error-retry:hover {
  background: #b91c1c;
}

.error-dismiss {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  border-radius: 6px;
  cursor: pointer;
  color: #dc2626;
  font-size: 16px;
  transition: all 0.2s;
}

.error-dismiss:hover {
  background: rgba(220, 38, 38, 0.1);
}

.audio-player {
  width: 100%;
  height: 48px;
  border-radius: 8px;
}

/* 主内容区 - 两栏布局 */
.player-main {
  flex: 1;
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 20px;
  padding: 20px;
  max-width: 1600px;
  margin: 0 auto;
  width: 100%;
  overflow: hidden;
}

/* 左栏：章节面板 */
.chapters-panel {
  background: white;
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  display: flex;
  flex-direction: column;
  max-height: calc(100vh - 140px);
}

.panel-title {
  font-size: 14px;
  font-weight: 600;
  color: #1f2937;
  margin: 0;
  padding: 14px 16px;
  border-bottom: 1px solid #f3f4f6;
}

.chapters-list {
  flex: 1;
  overflow-y: auto;
}

.chapters-list::-webkit-scrollbar {
  width: 4px;
}

.chapters-list::-webkit-scrollbar-thumb {
  background: #e5e7eb;
  border-radius: 2px;
}

.chapter-item {
  border-bottom: 1px solid #f8f9fa;
}

.chapter-item:last-child {
  border-bottom: none;
}

.chapter-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  cursor: pointer;
  transition: background 0.15s;
}

.chapter-header:hover {
  background: #fafbfc;
}

.chapter-item.active .chapter-header {
  background: linear-gradient(90deg, #eff6ff 0%, #fafbff 100%);
}

.chapter-item.active .chapter-num {
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
}

.chapter-num {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f3f4f6;
  color: #6b7280;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
  flex-shrink: 0;
  transition: all 0.2s;
}

.chapter-info {
  flex: 1;
  min-width: 0;
}

.chapter-title {
  font-size: 13px;
  font-weight: 500;
  color: #1f2937;
  margin: 0 0 2px 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  line-height: 1.4;
}

.chapter-time {
  font-size: 11px;
  color: #9ca3af;
  font-family: 'SF Mono', monospace;
}

.expand-btn {
  width: 28px;
  height: 28px;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  border-radius: 6px;
  cursor: pointer;
  color: #9ca3af;
  transition: all 0.2s;
}

.expand-btn:hover {
  background: #f3f4f6;
  color: #4b5563;
}

.expand-btn.expanded {
  color: #3b82f6;
}

.chapter-summary {
  padding: 0 14px 12px 14px;
  margin-left: 34px;
  border-left: 2px solid #f3f4f6;
}

.summary-content .summary-text {
  font-size: 13px;
  line-height: 1.7;
  color: #374151;
  margin: 0 0 10px 0;
}

.key-points {
  list-style: none;
  padding: 0;
  margin: 0;
}

.key-points li {
  font-size: 12px;
  line-height: 1.6;
  color: #4b5563;
  padding-left: 14px;
  position: relative;
  margin-bottom: 4px;
}

.key-points li:before {
  content: '•';
  position: absolute;
  left: 0;
  color: #3b82f6;
}

.summary-empty {
  padding: 12px 0;
}

.empty-text {
  font-size: 12px;
  color: #9ca3af;
  font-style: italic;
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
  max-height: 500px;
  opacity: 1;
}

/* 右栏：Tab 内容 */
.content-tabs {
  background: white;
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  display: flex;
  flex-direction: column;
  max-height: calc(100vh - 140px);
}

.tab-header {
  display: flex;
  gap: 2px;
  padding: 8px 12px;
  background: #f9fafb;
  border-bottom: 1px solid #f3f4f6;
}

.tab-btn {
  padding: 8px 16px;
  border: none;
  background: transparent;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  color: #6b7280;
  cursor: pointer;
  transition: all 0.2s;
}

.tab-btn:hover {
  color: #1f2937;
}

.tab-btn.active {
  background: white;
  color: #3b82f6;
  box-shadow: 0 1px 2px rgba(0,0,0,0.05);
}

.tab-content {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.tab-content::-webkit-scrollbar {
  width: 4px;
}

.tab-content::-webkit-scrollbar-thumb {
  background: #e5e7eb;
  border-radius: 2px;
}

/* 摘要 + 金句 Tab */
.verdict-card {
  background: #f9fafb;
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 20px;
}

.tldr-text {
  font-size: 14px;
  line-height: 1.7;
  color: #374151;
  margin: 0 0 12px 0;
}

.verdict-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.verdict-badge {
  padding: 4px 10px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
}

.verdict-deep_listen { background: #d1fae5; color: #065f46; }
.verdict-skim_outline { background: #fef3c7; color: #92400e; }
.verdict-skip { background: #fee2e2; color: #dc2626; }

.audience-text {
  font-size: 12px;
  color: #6b7280;
  background: #f3f4f6;
  padding: 4px 10px;
  border-radius: 6px;
}

.highlights-section {
  margin-top: 20px;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
  color: #1f2937;
  margin: 0 0 12px 0;
}

.highlights-content {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.highlight-group {
  background: #f9fafb;
  border-radius: 12px;
  overflow: hidden;
}

.highlight-group-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: #f3f4f6;
}

.group-icon {
  font-size: 14px;
}

.group-label {
  font-size: 13px;
  font-weight: 600;
  color: #374151;
}

.group-count {
  margin-left: auto;
  font-size: 11px;
  color: #9ca3af;
  background: white;
  padding: 2px 8px;
  border-radius: 10px;
}

.highlight-group-items {
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.highlight-item {
  padding: 10px 12px;
  background: white;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
  border: 1px solid transparent;
}

.highlight-item:hover {
  background: #fafbfc;
  border-color: #e5e7eb;
}

.h-main {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
}

.h-text {
  font-size: 13px;
  line-height: 1.5;
  color: #1f2937;
  margin: 0;
  flex: 1;
}

.h-time {
  flex-shrink: 0;
  font-size: 11px;
  color: #3b82f6;
  font-family: 'SF Mono', 'Monaco', monospace;
  background: #eff6ff;
  padding: 2px 6px;
  border-radius: 4px;
  line-height: 1.4;
}

.h-why {
  display: block;
  margin-top: 4px;
  font-size: 11px;
  color: #9ca3af;
  font-style: italic;
}

/* 转录字幕 Tab */
.punct-warning {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  margin-bottom: 12px;
  padding: 10px 12px;
  border: 1px solid #fbbf24;
  background: rgba(251, 191, 36, 0.08);
  border-radius: 8px;
  color: #92400e;
  font-size: 13px;
  line-height: 1.5;
}

.punct-warning-icon {
  flex-shrink: 0;
}

.punct-warning-text {
  flex: 1;
}

.transcript-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid #f3f4f6;
}

.subtitle-info {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #6b7280;
}

.subtitle-count {
  font-weight: 600;
  color: #1f2937;
  font-family: 'SF Mono', monospace;
}

.subtitle-dot {
  color: #d1d5db;
}

.subtitle-segments {
  color: #9ca3af;
}

.language-toggles {
  display: flex;
  gap: 3px;
  background: #f3f4f6;
  padding: 2px;
  border-radius: 6px;
}

.lang-btn {
  padding: 4px 10px;
  border: none;
  background: transparent;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
  color: #6b7280;
  cursor: pointer;
  transition: all 0.15s;
}

.lang-btn:hover:not(:disabled) {
  background: white;
  color: #1f2937;
}

.lang-btn.active {
  background: white;
  color: #3b82f6;
  box-shadow: 0 1px 2px rgba(0,0,0,0.05);
}

.lang-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.transcript-content {
  display: flex;
  flex-direction: column;
}

/* DynamicScroller 需要明确的可滚动高度才能虚拟化生效；
   高度来自父布局（transcript-tab 是 flex 子项）。 */
.transcript-scroller {
  flex: 1;
  height: 100%;
  overflow-y: auto;
}

.subtitle-block {
  display: flex;
  gap: 10px;
  padding: 10px 12px;
  cursor: pointer;
  transition: all 0.15s;
  border-left: 2px solid transparent;
  border-radius: 8px;
}

.subtitle-block:hover {
  background: #fafbfc;
}

.subtitle-block.active {
  background: linear-gradient(90deg, #fef3c7 0%, #fef9e7 40%, transparent 100%);
  border-left-color: #f59e0b;
}

.block-time {
  flex-shrink: 0;
  font-size: 11px;
  color: #9ca3af;
  font-family: 'SF Mono', 'Monaco', monospace;
  min-width: 45px;
  line-height: 1.5;
  padding-top: 1px;
}

.block-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}

.block-text {
  font-size: 14px;
  line-height: 1.6;
  color: #1f2937;
  word-break: break-word;
}

.block-translated {
  font-size: 13px;
  line-height: 1.5;
  color: #6b7280;
  word-break: break-word;
}

.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: #9ca3af;
  padding: 40px 20px;
}

.empty-state svg {
  opacity: 0.4;
}

.empty-state p {
  margin: 0;
  font-size: 13px;
}

/* 产品和技术洞察 Tab */
.insights-content {
  display: flex;
  flex-direction: column;
  gap: 24px;
}

.insight-section {
  background: #f9fafb;
  border-radius: 12px;
  padding: 16px;
}

.insight-section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  color: #1f2937;
  margin: 0 0 12px 0;
}

.section-icon {
  font-size: 18px;
}

.insight-list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.insight-list li {
  font-size: 14px;
  line-height: 1.6;
  color: #374151;
  padding-left: 20px;
  position: relative;
}

.insight-list li:before {
  content: "•";
  position: absolute;
  left: 0;
  color: #3b82f6;
  font-weight: bold;
}

.insight-tags {
  background: #f9fafb;
  border-radius: 12px;
  padding: 16px;
}

.tag-group {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.tag-group:last-child {
  margin-bottom: 0;
}

.tag-label {
  font-size: 13px;
  font-weight: 500;
  color: #6b7280;
  white-space: nowrap;
}

.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tag {
  font-size: 12px;
  color: #3b82f6;
  background: #eff6ff;
  padding: 4px 10px;
  border-radius: 12px;
}

/* 洞察占位符 */
.insights-placeholder {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  padding: 60px 40px;
  text-align: center;
}

.insights-placeholder svg {
  opacity: 0.3;
  color: #9ca3af;
}

.insights-placeholder h3 {
  font-size: 16px;
  font-weight: 600;
  color: #374151;
  margin: 0;
}

.insights-placeholder p {
  font-size: 14px;
  color: #6b7280;
  line-height: 1.6;
  max-width: 400px;
  margin: 0;
}

.generate-btn {
  margin-top: 8px;
  padding: 10px 20px;
  background: #3b82f6;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.generate-btn:hover {
  background: #2563eb;
}

/* 快捷键栏 - 底部固定 */
.shortcuts-bar {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  background: linear-gradient(to top, rgba(255, 255, 255, 0.98), rgba(255, 255, 255, 0.95));
  backdrop-filter: blur(10px);
  border-top: 1px solid #e5e7eb;
  padding: 12px 20px;
  z-index: 50;
  box-shadow: 0 -4px 20px rgba(0, 0, 0, 0.05);
}

.shortcuts-container {
  max-width: 1400px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 24px;
}

.shortcuts-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  background: #f3f4f6;
  border-radius: 10px;
  color: #6b7280;
  font-size: 13px;
  font-weight: 600;
  border: 1px solid #e5e7eb;
}

.shortcuts-header svg {
  flex-shrink: 0;
}

.shortcuts-list {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  justify-content: center;
}

.shortcut-chip {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  background: white;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  transition: all 0.15s ease;
}

.shortcut-chip:hover {
  background: #f9fafb;
  border-color: #d1d5db;
  transform: translateY(-1px);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}

.shortcut-chip kbd {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 28px;
  height: 24px;
  padding: 0 8px;
  background: linear-gradient(135deg, #f9fafb 0%, #f3f4f6 100%);
  border: 1px solid #d1d5db;
  border-radius: 6px;
  font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
  font-size: 13px;
  font-weight: 600;
  color: #1f2937;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05), inset 0 1px 0 rgba(255, 255, 255, 0.5);
}

.shortcut-chip span {
  font-size: 13px;
  font-weight: 500;
  color: #4b5563;
  white-space: nowrap;
}

/* 响应式 */
@media (max-width: 1024px) {
  .player-main {
    grid-template-columns: 280px minmax(0, 1fr);
    gap: 16px;
    padding: 16px;
  }

  .chapters-panel,
  .content-tabs {
    max-height: calc(100vh - 120px);
  }
}

@media (max-width: 768px) {
  .player-main {
    grid-template-columns: 1fr;
    padding: 12px;
    padding-bottom: 80px;
  }

  .chapters-panel {
    max-height: 400px;
  }

  .content-tabs {
    max-height: 500px;
  }

  .audio-section {
    padding: 10px 12px;
  }

  .shortcuts-bar {
    padding: 10px 16px;
  }

  .shortcuts-container {
    flex-direction: column;
    gap: 12px;
  }

  .shortcuts-list {
    gap: 6px;
  }

  .shortcut-chip {
    padding: 6px 10px;
  }

  .shortcut-chip kbd {
    min-width: 24px;
    height: 20px;
    font-size: 11px;
    padding: 0 6px;
  }

  .shortcut-chip span {
    font-size: 11px;
  }
}
</style>

<style scoped>
/* 字幕编辑器模态框 */
.transcript-modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.75);
  backdrop-filter: blur(4px);
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  animation: fadeIn 0.2s ease-out;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.transcript-modal-content {
  width: 100%;
  max-width: 1200px;
  max-height: 90vh;
  background: white;
  border-radius: 16px;
  overflow-y: auto;
  overflow-x: hidden;
  display: flex;
  flex-direction: column;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04);
  animation: slideUp 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

@keyframes slideUp {
  from {
    opacity: 0;
    transform: translateY(20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.modal-close-btn {
  position: absolute;
  top: 16px;
  right: 16px;
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.05);
  border: none;
  border-radius: 50%;
  cursor: pointer;
  font-size: 20px;
  color: #6b7280;
  transition: all 0.2s;
  z-index: 1;
}

.modal-close-btn:hover {
  background: rgba(0, 0, 0, 0.1);
  color: #1f2937;
}

.modal-enter-active,
.modal-leave-active {
  transition: opacity 0.2s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}

.modal-enter-active .transcript-modal-content,
.modal-leave-active .transcript-modal-content {
  transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

.modal-enter-from .transcript-modal-content,
.modal-leave-to .transcript-modal-content {
  opacity: 0;
  transform: translateY(20px);
}
</style>

