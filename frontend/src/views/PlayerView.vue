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
        <EpisodeTags
          :language="bundle?.episode?.language"
          :source-type="bundle?.episode?.source_type"
          :title="bundle?.episode?.title"
          :show="['language', 'source', 'category']"
          class="header-tags"
        />
        <span class="episode-meta">
          {{ bundle?.outline?.entries?.length || 0 }} 章节 ·
          {{ formatDuration(bundle?.transcript?.segments) }}
        </span>
      </div>
      <div class="header-actions">
        <!-- 导出按钮 -->
        <button @click="showExportModal = true" class="icon-btn no-print" title="导出摘要">
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

    <!-- 加载中提示：bundle 还没拿到时，避免界面看起来像"未知节目"bug -->
    <div
      v-if="!bundle && !loadError"
      class="loading-banner"
      role="status"
      aria-live="polite"
    >
      <div class="loading-spinner-small" aria-hidden="true"></div>
      <span>加载节目中...</span>
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
    <main class="player-main" :style="{ '--left-width': leftPanelWidth + 'px' }">
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

      <!-- 左右栏拖拽分隔条 -->
      <div class="panel-resizer" @mousedown="startResize" title="拖动调整宽度"></div>

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
          <!-- 字幕编辑工具栏(只在 transcript tab 显示) -->
          <div class="subtitle-toolbar">
            <div class="toolbar-group">
              <button
                @click="editMode = !editMode"
                :class="{ active: editMode }"
                class="toolbar-btn"
                :title="editMode ? '退出编辑(回到段落视图)' : '进入单句编辑模式'"
              >
                {{ editMode ? '✏️ 编辑中 · 点击退出' : '✏️ 编辑模式' }}
              </button>
              <button
                v-if="editMode"
                @click="showOnlyErrors = !showOnlyErrors"
                :class="{ active: showOnlyErrors }"
                class="toolbar-btn"
              >
                🔍 {{ showOnlyErrors ? '显示全部' : '仅显示错误' }}
              </button>
            </div>
            <div class="toolbar-group">
              <span v-if="editMode" class="toolbar-hint">{{ editableSegments.length }} 条单句</span>
              <button
                @click="showGlossary = !showGlossary"
                :class="{ active: showGlossary }"
                class="toolbar-btn"
                title="管理词库"
              >
                📚 词库
              </button>
              <button
                @click="applyGlossaryAll"
                :disabled="applyingGlossary"
                class="toolbar-btn toolbar-btn-primary"
                title="LLM 全篇纠错(耗时几十秒)"
              >
                {{ applyingGlossary ? '⏳ 纠错中...' : '⚡ 批量纠错' }}
              </button>
            </div>
          </div>

          <!-- 反馈通知(保存/纠错结果) -->
          <div v-if="glossaryNotice" class="glossary-notice">{{ glossaryNotice }}</div>

          <!-- 词库面板(可折叠) -->
          <div v-if="showGlossary" class="glossary-panel">
            <div class="glossary-add-row">
              <input v-model="newGlossaryWrong" placeholder="错误词(如:姚顺雨)" class="glossary-input" />
              <span class="glossary-arrow">→</span>
              <input v-model="newGlossaryCorrect" placeholder="正确词(如:姚顺宇)" class="glossary-input" />
              <button
                @click="addGlossaryEntry"
                :disabled="!newGlossaryWrong.trim() || !newGlossaryCorrect.trim()"
                class="glossary-add-btn"
              >
                添加
              </button>
            </div>
            <div v-if="Object.keys(glossary).length > 0" class="glossary-list">
              <div v-for="(wrongs, correct) in glossary" :key="correct" class="glossary-entry">
                <span class="glossary-correct">{{ correct }}</span>
                <span class="glossary-arrow">←</span>
                <span class="glossary-wrongs">{{ Array.isArray(wrongs) ? wrongs.join(', ') : wrongs }}</span>
                <button @click="removeGlossary(correct)" class="glossary-del" title="删除">×</button>
              </div>
            </div>
            <p v-else class="glossary-empty">词库为空。添加条目后,字幕中匹配的错误词会自动标记 ⚠️</p>
          </div>

          <!-- 字幕头部(语言切换,只在只读模式显示) -->
          <div v-if="!editMode" class="transcript-header">
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
                英文
              </button>
              <button
                @click="subtitleLang = 'translated'"
                :class="{ active: subtitleLang === 'translated' }"
                :disabled="!hasTranslated"
                class="lang-btn"
              >
                中文
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
            v-if="paragraphs.length > 0 || segments.length > 0"
            @scroll="handleUserScroll"
          >
            <!-- 只读模式:段落视图(用户友好) -->
            <DynamicScroller
              v-if="!editMode"
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

            <!-- 编辑模式:单句 segment 视图(API 对齐,每条可编辑) -->
            <DynamicScroller
              v-else
              ref="transcriptScroller"
              :items="editableSegments"
              :min-item-size="50"
              key-field="id"
              class="transcript-scroller"
              v-slot="{ item, index, active }"
            >
              <DynamicScrollerItem
                :item="item"
                :active="active"
                :data-index="index"
              >
                <div
                  :key="item.id"
                  class="segment-row"
                  :class="{
                    active: isCurrentSegment(item),
                    editing: editingId === item.id,
                    'has-error': hasSegmentError(item)
                  }"
                >
                  <span class="segment-time" @click="localSeekTo(item.start_ms)" :title="`跳到 ${formatTime(item.start_ms)}`">{{ formatTime(item.start_ms) }}</span>
                  <div class="segment-body">
                    <textarea
                      v-if="editingId === item.id"
                      v-model="editingText"
                      class="segment-textarea"
                      rows="2"
                      @keyup.ctrl.enter="saveEdit(item)"
                      @keyup.esc="cancelEdit"
                    />
                    <span v-else class="segment-text" @click="startEdit(item)" :title="'点击编辑 (Ctrl+Enter 保存)'">
                      {{ editBuffer[item.id] ?? item.text_original }}
                    </span>
                  </div>
                  <div v-if="editingId === item.id" class="segment-edit-actions">
                    <button @click="saveEdit(item)" class="seg-btn seg-btn-save">保存</button>
                    <button @click="cancelEdit" class="seg-btn">取消</button>
                    <button @click="addCurrentToGlossary(item)" class="seg-btn" title="加入词库(在下方面板填)">📚</button>
                  </div>
                  <span
                    v-else-if="hasSegmentError(item)"
                    class="segment-error-mark"
                    title="包含词库错误词"
                  >⚠️</span>
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
            <div v-if="productInsightsProduct.length" class="insight-section">
              <h3 class="insight-section-title">
                <span class="section-icon">📦</span>
                产品洞察
              </h3>
              <ul class="insight-list">
                <li v-for="(item, idx) in productInsightsProduct" :key="'p-' + idx" class="insight-card">
                  <div class="insight-card-header">
                    <span class="insight-cat-icon">{{ getInsightCategoryIcon(item.category) }}</span>
                    <span class="insight-cat-label">{{ getInsightCategoryLabel(item.category) }}</span>
                    <span
                      v-if="firstSegmentMs(item.cited_segment_ids) !== null"
                      class="insight-time"
                      @click="localSeekTo(firstSegmentMs(item.cited_segment_ids))"
                    >⏱ {{ formatTime(firstSegmentMs(item.cited_segment_ids)) }}</span>
                  </div>
                  <p class="insight-text">{{ item.text_zh }}</p>
                  <p v-if="item.rationale_zh" class="insight-rationale">{{ item.rationale_zh }}</p>
                </li>
              </ul>
            </div>

            <!-- 技术洞察 -->
            <div v-if="productInsightsTechnical.length" class="insight-section">
              <h3 class="insight-section-title">
                <span class="section-icon">⚙️</span>
                技术洞察
              </h3>
              <ul class="insight-list">
                <li v-for="(item, idx) in productInsightsTechnical" :key="'t-' + idx" class="insight-card">
                  <div class="insight-card-header">
                    <span class="insight-cat-icon">{{ getInsightCategoryIcon(item.category) }}</span>
                    <span class="insight-cat-label">{{ getInsightCategoryLabel(item.category) }}</span>
                    <span
                      v-if="firstSegmentMs(item.cited_segment_ids) !== null"
                      class="insight-time"
                      @click="localSeekTo(firstSegmentMs(item.cited_segment_ids))"
                    >⏱ {{ formatTime(firstSegmentMs(item.cited_segment_ids)) }}</span>
                  </div>
                  <p class="insight-text">{{ item.text_zh }}</p>
                  <p v-if="item.rationale_zh" class="insight-rationale">{{ item.rationale_zh }}</p>
                </li>
              </ul>
            </div>

            <!-- 市场洞察 -->
            <div v-if="productInsightsMarket.length" class="insight-section">
              <h3 class="insight-section-title">
                <span class="section-icon">📊</span>
                市场/行业洞察
              </h3>
              <ul class="insight-list">
                <li v-for="(item, idx) in productInsightsMarket" :key="'m-' + idx" class="insight-card">
                  <div class="insight-card-header">
                    <span class="insight-cat-icon">{{ getInsightCategoryIcon(item.category) }}</span>
                    <span class="insight-cat-label">{{ getInsightCategoryLabel(item.category) }}</span>
                    <span
                      v-if="firstSegmentMs(item.cited_segment_ids) !== null"
                      class="insight-time"
                      @click="localSeekTo(firstSegmentMs(item.cited_segment_ids))"
                    >⏱ {{ formatTime(firstSegmentMs(item.cited_segment_ids)) }}</span>
                  </div>
                  <p class="insight-text">{{ item.text_zh }}</p>
                  <p v-if="item.rationale_zh" class="insight-rationale">{{ item.rationale_zh }}</p>
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

  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import ExportModal from '@/components/ExportModal.vue'
import EpisodeTags from '@/components/EpisodeTags.vue'
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

// 音频播放状态机已迁移到 useAudioPlayback（composable）。
// 顶部 usePlayer 解构出 audioRef 后注入该 composable。

const bundle = bundleRef
const audioRef = ref(null)
const transcriptContainer = ref(null)
// DynamicScroller 实例引用，用于把它的 scrollToItem 注入到 useSubtitleScroll
const transcriptScroller = ref(null)

// 音频播放状态机：seek 排队、canplay/seeked 事件、pendingSeek 处理。
// 一并接管 audioReady / pendingSeek / isSeeking / seekQueue 状态。
import { useAudioPlayback } from '@/composables/useAudioPlayback'
const {
  audioReady,
  pendingSeek,
  isSeeking,
  seekQueue,
  executeSeek,
  localSeekTo,
  onCanPlay,
  onLoadedData,
  onCanPlayThrough,
  onAudioSeeking,
  onAudioSeeked,
} = useAudioPlayback({ seekTo, audioRef })
const subtitleLang = ref('original')
// 左栏宽度（可拖拽调整），通过 CSS 变量 --left-width 驱动 grid 第一列宽
const leftPanelWidth = ref(320)
const startResize = (e) => {
  e.preventDefault()
  const startX = e.clientX
  const startWidth = leftPanelWidth.value
  const mainEl = e.currentTarget.parentElement
  const mainRect = mainEl.getBoundingClientRect()
  const onMove = (ev) => {
    // 限制 240 ~ (mainWidth - 400)，避免左栏过窄或右栏被挤没
    const w = Math.max(240, Math.min(mainRect.width - 400, startWidth + ev.clientX - startX))
    leftPanelWidth.value = w
  }
  const onUp = () => {
    document.removeEventListener('mousemove', onMove)
    document.removeEventListener('mouseup', onUp)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }
  document.addEventListener('mousemove', onMove)
  document.addEventListener('mouseup', onUp)
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
}
const expandedChapter = ref(-1)
const showExportModal = ref(false)
// isMappingExpanded 已移除 - 不再需要映射展开状态

// Error states
const loadError = ref(null)
const loadErrorMessage = ref('')

// isSeeking / seekQueue 已迁移到 useAudioPlayback（composable），见上方解构。

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
const productInsightsProduct = computed(() => productInsights.value?.product?.items || [])
const productInsightsTechnical = computed(() => productInsights.value?.technical?.items || [])
const productInsightsMarket = computed(() => productInsights.value?.market?.items || [])

// 把 cited_segment_ids[0] 映射到 segment 的 start_ms（用于点击洞察跳转到原音）
const firstSegmentMs = (ids) => {
  if (!ids?.length) return null
  const seg = segments.value.find(s => s.id === ids[0])
  return seg?.start_ms ?? null
}

const hasOriginal = computed(() => segments.value.length > 0)
const hasTranslated = computed(() => segments.value.some(s => s.text_translated))

const isCurrentParagraph = (para) => {
  if (!currentTime.value) return false
  return currentTime.value >= para.start_ms && currentTime.value < para.end_ms
}

// ==================== 字幕 inline 编辑（取代原 TranscriptEditor modal）====================
// 设计原则:只读模式显示段落(用户友好),编辑模式切换到单句 segment(API 对齐)
const editMode = ref(false)              // 编辑模式开关
const editingId = ref(null)              // 当前正在编辑的 segment id
const editingText = ref('')              // 编辑中的临时文本
const editBuffer = ref({})               // 已保存的本地修改 {segment_id: newText}(在 bundle 刷新前兜底显示)
const showOnlyErrors = ref(false)        // 仅显示含错误 segment
const showGlossary = ref(false)          // 词库面板展开
const glossary = ref({})                 // 词库 {correct: [wrong, wrong, ...]}
const newGlossaryWrong = ref('')         // 新词库条目-错误词
const newGlossaryCorrect = ref('')       // 新词库条目-正确词
const applyingGlossary = ref(false)      // 批量纠错进行中
const glossaryNotice = ref('')           // 批量纠错结果反馈

// 单句 segment 是否对应当前播放位置
const isCurrentSegment = (seg) => {
  if (!currentTime.value || !seg) return false
  return currentTime.value >= seg.start_ms && currentTime.value < seg.end_ms
}

// 检测 segment 是否包含词库错误
const hasSegmentError = (seg) => {
  if (!seg?.text_original) return false
  const text = seg.text_original
  for (const correct in glossary.value) {
    for (const wrong of glossary.value[correct] || []) {
      if (wrong && text.includes(wrong)) return true
    }
  }
  return false
}

// 编辑模式实际渲染的 segments(支持"仅显示错误"过滤)
const editableSegments = computed(() => {
  if (!showOnlyErrors.value) return segments.value
  return segments.value.filter(hasSegmentError)
})

// 进入编辑
const startEdit = (seg) => {
  editingId.value = seg.id
  // 优先显示已保存的本地修改
  editingText.value = editBuffer.value[seg.id] ?? seg.text_original ?? ''
}

// 取消编辑
const cancelEdit = () => {
  editingId.value = null
  editingText.value = ''
}

// 保存编辑(调 API + 本地兜底)
const saveEdit = async (seg) => {
  const newText = editingText.value.trim()
  if (!newText || newText === seg.text_original) {
    cancelEdit()
    return
  }
  try {
    await api.updateTranscriptSegment(episodeId.value, {
      segment_index: seg.id,    // 后端用 segment.id(数字索引)
      text_original: newText,
      note_to_glossary: false,
    })
    // 本地兜底:即使 bundle 还没刷新,编辑区也显示新内容
    editBuffer.value[seg.id] = newText
    seg.text_original = newText   // 直接改引用,即时生效
    cancelEdit()
  } catch (e) {
    glossaryNotice.value = '❌ 保存失败:' + (e.message || '未知错误')
    setTimeout(() => { glossaryNotice.value = '' }, 3000)
  }
}

// 把当前编辑句的"错误词→正确词"加入词库
const addCurrentToGlossary = async (seg) => {
  // 简化:提示用户在词库面板手动添加(因为自动识别错误词不可靠)
  showGlossary.value = true
  newGlossaryWrong.value = ''     // 让用户填
  newGlossaryCorrect.value = ''
  glossaryNotice.value = '👇 在下方词库面板填写"错误词→正确词"后添加'
  setTimeout(() => { glossaryNotice.value = '' }, 3000)
}

// 加载词库
const loadGlossary = async () => {
  try {
    const data = await api.getGlossary()
    glossary.value = data?.entries || {}
  } catch (e) {
    console.warn('[glossary] 加载失败', e)
  }
}

// 添加词库条目
const addGlossaryEntry = async () => {
  const wrong = newGlossaryWrong.value.trim()
  const correct = newGlossaryCorrect.value.trim()
  if (!wrong || !correct) return
  try {
    await api.addGlossaryEntry({ correct, wrong })
    await loadGlossary()
    newGlossaryWrong.value = ''
    newGlossaryCorrect.value = ''
  } catch (e) {
    glossaryNotice.value = '❌ 添加失败:' + (e.message || '')
    setTimeout(() => { glossaryNotice.value = '' }, 3000)
  }
}

// 删除词库条目
const removeGlossary = async (correct) => {
  try {
    await api.deleteGlossaryEntry(correct)
    await loadGlossary()
  } catch (e) {
    glossaryNotice.value = '❌ 删除失败:' + (e.message || '')
    setTimeout(() => { glossaryNotice.value = '' }, 3000)
  }
}

// 批量词库纠错(LLM,带 loading)
const applyGlossaryAll = async () => {
  if (applyingGlossary.value) return
  applyingGlossary.value = true
  glossaryNotice.value = '⏳ LLM 正在全篇纠错,这需要几十秒...'
  try {
    const result = await api.applyGlossary(episodeId.value)
    const n = result?.corrected_segments ?? 0
    glossaryNotice.value = n > 0
      ? `✅ 纠错完成,修复了 ${n} 条字幕`
      : '✅ 没有发现需要纠错的内容'
    await loadEpisode()   // 刷新字幕数据
  } catch (e) {
    glossaryNotice.value = '❌ 纠错失败:' + (e.message || '')
  } finally {
    applyingGlossary.value = false
    setTimeout(() => { glossaryNotice.value = '' }, 4000)
  }
}

// 编辑模式开启时确保词库已加载(用于错误检测)
watch(editMode, (newVal) => {
  if (newVal && Object.keys(glossary.value).length === 0) {
    loadGlossary()
  }
})

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
  getInsightCategoryIcon,
  getInsightCategoryLabel,
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

.header-tags {
  margin: 4px 0;
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

/* Loading banner: 初次加载时给用户视觉反馈 */
.loading-banner {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 24px;
  color: #6b7280;
  font-size: 14px;
}

.loading-spinner-small {
  width: 18px;
  height: 18px;
  border: 2px solid #e5e7eb;
  border-top-color: #4f8ef7;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
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
  grid-template-columns: var(--left-width, 320px) 6px minmax(0, 1fr);
  gap: 20px;
  padding: 20px;
  max-width: 1600px;
  margin: 0 auto;
  width: 100%;
  overflow: hidden;
}

/* 左右栏拖拽分隔条 */
.panel-resizer {
  width: 6px;
  cursor: col-resize;
  background: transparent;
  z-index: 10;
  transition: background 0.15s;
}

.panel-resizer:hover,
.panel-resizer:active {
  background: rgba(59, 130, 246, 0.3);
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

/* === 字幕编辑工具栏 === */
.subtitle-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.toolbar-group {
  display: flex;
  align-items: center;
  gap: 6px;
}

.toolbar-btn {
  padding: 5px 10px;
  background: white;
  color: #4b5563;
  border: 1px solid #e5e7eb;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}

.toolbar-btn:hover:not(:disabled) {
  background: #f3f4f6;
  border-color: #d1d5db;
}

.toolbar-btn.active {
  background: #1f2937;
  color: white;
  border-color: #1f2937;
}

.toolbar-btn-primary {
  background: #f59e0b;
  color: white;
  border-color: #f59e0b;
}

.toolbar-btn-primary:hover:not(:disabled) {
  background: #d97706;
  border-color: #d97706;
}

.toolbar-btn-primary:disabled,
.toolbar-btn:disabled {
  background: #e5e7eb;
  color: #9ca3af;
  cursor: not-allowed;
  border-color: #e5e7eb;
}

.toolbar-hint {
  font-size: 11px;
  color: #9ca3af;
  margin-right: 4px;
}

/* === 反馈通知 === */
.glossary-notice {
  padding: 6px 12px;
  margin-bottom: 8px;
  background: #fef3c7;
  border: 1px solid #fde68a;
  border-radius: 4px;
  font-size: 12px;
  color: #92400e;
}

/* === 词库面板 === */
.glossary-panel {
  padding: 10px 12px;
  background: #fafafa;
  border: 1px solid #ececec;
  border-radius: 6px;
  margin-bottom: 8px;
}

.glossary-add-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
}

.glossary-input {
  flex: 1;
  padding: 4px 8px;
  border: 1px solid #e5e7eb;
  border-radius: 4px;
  font-size: 12px;
  min-width: 0;
}

.glossary-input:focus {
  outline: none;
  border-color: #6b7280;
}

.glossary-arrow {
  color: #9ca3af;
  font-size: 12px;
  flex-shrink: 0;
}

.glossary-add-btn {
  padding: 4px 12px;
  background: #1f2937;
  color: white;
  border: none;
  border-radius: 4px;
  font-size: 12px;
  cursor: pointer;
  flex-shrink: 0;
}

.glossary-add-btn:disabled {
  background: #e5e7eb;
  cursor: not-allowed;
}

.glossary-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 160px;
  overflow-y: auto;
}

.glossary-entry {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  background: white;
  border: 1px solid #f0f0f0;
  border-radius: 4px;
  font-size: 12px;
}

.glossary-correct {
  color: #047857;
  font-weight: 600;
}

.glossary-wrongs {
  color: #b45309;
  flex: 1;
}

.glossary-del {
  background: transparent;
  border: none;
  color: #9ca3af;
  cursor: pointer;
  font-size: 14px;
  padding: 0 4px;
  line-height: 1;
}

.glossary-del:hover {
  color: #ef4444;
}

.glossary-empty {
  font-size: 11px;
  color: #9ca3af;
  margin: 0;
  font-style: italic;
}

/* === 单句 segment 编辑行 === */
.segment-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 10px;
  border-bottom: 1px solid #f3f4f6;
  transition: background 0.15s;
  position: relative;
}

.segment-row:hover {
  background: #fafafa;
}

.segment-row.active {
  background: linear-gradient(90deg, #fef3c7 0%, #fef9e7 40%, transparent 100%);
  border-left: 3px solid #f59e0b;
  padding-left: 7px;
}

.segment-row.has-error {
  background: #fef2f2;
}

.segment-row.has-error:hover {
  background: #fee2e2;
}

.segment-row.editing {
  background: #eff6ff;
  border-left: 3px solid #3b82f6;
  padding-left: 7px;
}

.segment-time {
  flex-shrink: 0;
  font-family: 'SF Mono', Monaco, Consolas, monospace;
  font-size: 11px;
  color: #6b7280;
  cursor: pointer;
  padding: 2px 4px;
  border-radius: 3px;
  min-width: 42px;
}

.segment-time:hover {
  background: #e5e7eb;
  color: #1f2937;
}

.segment-body {
  flex: 1;
  min-width: 0;
}

.segment-text {
  display: block;
  font-size: 13px;
  line-height: 1.5;
  color: #1f2937;
  cursor: text;
  word-break: break-word;
}

.segment-textarea {
  width: 100%;
  padding: 6px 8px;
  border: 1px solid #3b82f6;
  border-radius: 4px;
  font-size: 13px;
  line-height: 1.5;
  font-family: inherit;
  resize: vertical;
  min-height: 40px;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}

.segment-textarea:focus {
  outline: none;
}

.segment-edit-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}

.seg-btn {
  padding: 3px 8px;
  background: white;
  color: #4b5563;
  border: 1px solid #e5e7eb;
  border-radius: 3px;
  font-size: 11px;
  cursor: pointer;
}

.seg-btn:hover {
  background: #f3f4f6;
}

.seg-btn-save {
  background: #1f2937;
  color: white;
  border-color: #1f2937;
}

.seg-btn-save:hover {
  background: #374151;
}

.segment-error-mark {
  flex-shrink: 0;
  font-size: 12px;
  cursor: help;
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

.insight-list li.insight-card {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 12px 14px;
  font-size: 14px;
  line-height: 1.6;
  color: #374151;
}

.insight-card-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}

.insight-cat-icon {
  font-size: 15px;
}

.insight-cat-label {
  font-size: 12px;
  font-weight: 600;
  color: #6b7280;
  background: #f3f4f6;
  padding: 2px 8px;
  border-radius: 10px;
}

.insight-time {
  margin-left: auto;
  font-size: 12px;
  color: #3b82f6;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 4px;
  transition: background 0.15s;
}

.insight-time:hover {
  background: #eff6ff;
}

.insight-text {
  margin: 0 0 4px 0;
  color: #1f2937;
}

.insight-rationale {
  margin: 0;
  font-size: 12px;
  color: #6b7280;
  font-style: italic;
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
  padding: 6px 16px;
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
  padding: 3px 10px;
  background: #f3f4f6;
  border-radius: 8px;
  color: #6b7280;
  font-size: 11px;
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
  gap: 5px;
  padding: 3px 8px;
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
  min-width: 20px;
  height: 16px;
  padding: 0 5px;
  background: linear-gradient(135deg, #f9fafb 0%, #f3f4f6 100%);
  border: 1px solid #d1d5db;
  border-radius: 6px;
  font-family: 'SF Mono', 'Monaco', 'Consolas', monospace;
  font-size: 11px;
  font-weight: 600;
  color: #1f2937;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05), inset 0 1px 0 rgba(255, 255, 255, 0.5);
}

.shortcut-chip span {
  font-size: 11px;
  font-weight: 500;
  color: #4b5563;
  white-space: nowrap;
}

/* 响应式 */
@media (max-width: 1024px) {
  .player-main {
    grid-template-columns: var(--left-width, 280px) 6px minmax(0, 1fr);
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

  .panel-resizer {
    display: none;
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

