<template>
  <div class="library-view">
    <!-- 品牌区：项目标题 + tagline + 统计 -->
    <header class="brand-header">
      <div class="brand-title-block">
        <h1 class="brand-title">Podcast Digester</h1>
        <span class="brand-tagline">本地播客摘要 · 5 分钟消化一期长播客</span>
      </div>
      <div class="brand-stats" v-if="episodes.length > 0">
        <span class="stat">{{ episodes.length }} 期</span>
        <span class="stat-sep">·</span>
        <span class="stat">{{ totalHours }} 小时</span>
        <span class="stat-sep">·</span>
        <span class="stat">{{ readyCount }} 期已消化</span>
      </div>
      <router-link to="/settings" class="settings-gear" title="LLM API 设置" aria-label="LLM API 设置">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="3"/>
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
        </svg>
      </router-link>
    </header>

    <!-- 粘贴输入区：常驻顶部，浅灰背景降权 -->
    <div class="paste-section">
      <div class="input-group">
        <label for="paste-input" class="sr-only">播客链接或本地文件路径</label>
        <input
          id="paste-input"
          v-model="inputText"
          @keyup.enter="handlePaste"
          placeholder="粘贴播客链接 (YouTube / Bilibili / 抖音 / 小宇宙) 或本地文件路径..."
          class="paste-input"
          :disabled="isPasting"
          :aria-invalid="!!error"
          :aria-describedby="error ? 'paste-error' : undefined"
        />
        <button @click="handlePaste" :disabled="!inputText.trim() || isPasting" class="paste-btn">
          {{ isPasting ? '处理中...' : '添加' }}
        </button>
      </div>
      <div v-if="error" id="paste-error" class="error-message" role="alert" aria-live="polite">{{ error }}</div>
    </div>

    <!-- 检索区：搜索框（按钮触发）+ 筛选 chips -->
    <div class="search-section">
      <div class="search-bar">
        <input
          v-model="searchQuery"
          @keyup.enter="handleSearch"
          placeholder="搜索节目标题或摘要..."
          class="search-input"
        />
        <button @click="handleSearch" class="search-btn" :disabled="!searchQuery.trim()">
          搜索
        </button>
        <div class="filter-chips" role="group" aria-label="按状态筛选节目">
          <button
            v-for="filter in filters"
            :key="filter.value"
            @click="setFilter(filter.value)"
            :class="{ active: currentFilter === filter.value }"
            :aria-current="currentFilter === filter.value ? 'true' : undefined"
            class="filter-chip"
          >
            {{ filter.label }}
          </button>
        </div>
      </div>
    </div>

    <!-- 节目状态转换通知（处理中 → 完成/失败）。
         避免用户在 'processing' 过滤下节目消失后误以为数据丢了。 -->
    <div
      v-if="recentTransitions.length > 0"
      class="transitions-toast"
      role="status"
      aria-live="polite"
    >
      <div
        v-for="t in recentTransitions"
        :key="t.id"
        class="transition-item"
        :class="`transition-${t.status}`"
      >
        <span class="transition-icon" aria-hidden="true">
          {{ t.status === 'ready' ? '✓' : '⚠️' }}
        </span>
        <span class="transition-text">
          节目「{{ (t.title || '').slice(0, 30) }}{{ (t.title || '').length > 30 ? '...' : '' }}」
          {{ t.status === 'ready' ? '处理完成' : '处理失败' }}
        </span>
        <button
          v-if="t.status === 'ready'"
          @click="openEpisode(t.id)"
          class="transition-action"
        >
          查看
        </button>
        <button
          @click="dismissTransition(t.id)"
          class="transition-dismiss"
          aria-label="关闭通知"
        >
          ✕
        </button>
      </div>
    </div>

    <!-- 节目列表（响应式网格）-->
    <div class="episodes-list">
      <article
        v-for="ep in filteredEpisodes"
        :key="ep.id"
        class="episode-card"
        :class="`card-status-${getStatusKey(ep.status)}`"
        @click="openEpisode(ep.id)"
      >
        <div class="card-body">
          <!-- 标题区：中文标题为主，英文原标题为副 -->
          <div class="title-block">
            <h3 class="title-zh">{{ ep.title_zh || ep.title }}</h3>
            <p v-if="ep.title_zh && ep.title_zh !== ep.title" class="title-original" :title="ep.title">
              {{ ep.title }}
            </p>
          </div>

          <!-- 元信息标签：语种/时长/来源/分类 -->
          <EpisodeTags
            :language="ep.language"
            :duration-min="ep.duration_min"
            :source-type="ep.source_type"
            :title="ep.title"
            class="card-tags"
          />

          <!-- 处理中状态 - 紧凑三行：进度条 / 当前阶段 / 全阶段状态条 -->
          <div v-if="isProcessing(ep.status)" class="processing-info">
            <template v-for="summary in [stageSummary(ep)]" :key="ep.id">
              <!-- 行1：总进度条 + % + N/M 步 -->
              <div class="progress-row">
                <div class="progress-bar">
                  <div class="progress-fill" :style="{ width: `${ep.overall_progress * 100}%` }"></div>
                </div>
                <span class="progress-percent">{{ Math.round(ep.overall_progress * 100) }}%</span>
                <span class="progress-step">{{ summary.step }}/{{ summary.total }} 步</span>
              </div>
              <!-- 行2：当前阶段名 + 计数（聚焦） -->
              <div v-if="summary.active" class="active-stage">
                <span class="active-stage__pulse"></span>
                <span class="active-stage__name">{{ summary.active.name }}中</span>
                <span
                  v-if="summary.active.current != null && summary.active.total != null"
                  class="active-stage__count"
                >{{ summary.active.current }}/{{ summary.active.total }}</span>
              </div>
              <!-- 行3：全阶段状态条（done/active/todo 三态着色） -->
              <div class="stage-chips">
                <template v-for="(r, i) in summary.rows" :key="r.id">
                  <span v-if="i > 0" class="stage-chips__sep">/</span>
                  <span class="stage-chip" :class="`stage-chip--${r.state}`">{{ r.name }}</span>
                </template>
              </div>
            </template>
          </div>

          <!-- 完成状态 -->
          <p v-else-if="ep.status === 'ready' && ep.tldr_zh" class="tldr">{{ ep.tldr_zh }}</p>

          <!-- 失败状态 -->
          <div v-else-if="ep.status === 'failed'" class="error-info">
            <span>⚠️ {{ getErrorMessage(ep) }}</span>
          </div>

          <!-- 底部元信息行 -->
          <div class="card-meta">
            <span class="meta-time">{{ formatTime(ep.created_at) }}</span>
            <template v-if="ep.status === 'ready' && ep.highlights_count > 0">
              <span class="meta-dot">·</span>
              <span class="meta-highlights">💡 {{ ep.highlights_count }} 条亮点</span>
            </template>
            <template v-if="ep.status === 'ready' && ep.worth_listening_verdict">
              <span class="meta-dot">·</span>
              <span class="meta-verdict" :class="`verdict-${ep.worth_listening_verdict}`">
                {{ verdictText(ep.worth_listening_verdict) }}
              </span>
            </template>
          </div>
        </div>

        <!-- 操作按钮（右下角悬浮）-->
        <div v-if="!ep.is_fixture" class="card-actions">
          <button v-if="isProcessing(ep.status)" @click.stop="confirmCancel(ep)" class="card-action-btn" title="取消处理">取消</button>
          <template v-else-if="ep.status === 'failed'">
            <button
              @click.stop="resumeEpisode(ep)"
              :disabled="resumingId === ep.id"
              class="card-action-btn"
              title="恢复处理"
            >{{ resumingId === ep.id ? '恢复中' : '恢复' }}</button>
            <button @click.stop="confirmDelete(ep)" class="card-action-btn card-action-danger" title="删除">删除</button>
          </template>
          <button v-else-if="ep.status === 'ready'" @click.stop="confirmDelete(ep)" class="card-action-btn card-action-danger" title="删除">删除</button>
        </div>
      </article>

      <!-- 加载中状态：初次加载时避免误显示"暂无节目" -->
      <div v-if="isLoading" class="empty-state" role="status" aria-live="polite">
        <div class="loading-spinner" aria-hidden="true"></div>
        <p>加载节目中...</p>
      </div>

      <!-- 空状态 -->
      <div v-else-if="filteredEpisodes.length === 0" class="empty-state">
        <div v-if="episodes.length > 0 && searchQuery" class="no-results">
          <div class="empty-icon">🔍</div>
          <p>没有找到匹配的节目</p>
          <p class="empty-hint">尝试其他关键词或清除筛选条件</p>
        </div>
        <div v-else>
        <div class="empty-icon">📻</div>
        <p>暂无节目</p>
        <p class="empty-hint">粘贴播客链接开始使用</p>
        <button v-if="hasFixtures" @click="loadFixture" class="try-demo-btn">
          试用演示数据
        </button>
      </div>
    </div>

    <!-- 删除确认对话框 -->
    <div v-if="showDeleteDialog" class="dialog-overlay" @click.self="cancelDelete">
      <div class="dialog-box" role="dialog" aria-modal="true" aria-labelledby="delete-dialog-title">
        <h3 id="delete-dialog-title" class="dialog-title">确认删除</h3>
        <p class="dialog-message">
          确定要删除节目「{{ episodeToDelete?.title }}」吗？
        </p>
        <div class="dialog-actions">
          <button @click="cancelDelete" class="dialog-btn dialog-btn-cancel">取消</button>
          <button @click="executeDelete" class="dialog-btn dialog-btn-confirm">删除</button>
        </div>
      </div>
    </div>

    <!-- 取消确认对话框 -->
    <div v-if="showCancelDialog" class="dialog-overlay" @click.self="cancelCancel">
      <div class="dialog-box" role="dialog" aria-modal="true" aria-labelledby="cancel-dialog-title">
        <h3 id="cancel-dialog-title" class="dialog-title">确认取消</h3>
        <p class="dialog-message">
          确定要取消节目「{{ episodeToCancel?.title }}」的处理吗？
        </p>
        <div class="dialog-actions">
          <button @click="cancelCancel" class="dialog-btn dialog-btn-cancel">继续处理</button>
          <button @click="executeCancel" class="dialog-btn dialog-btn-confirm">取消任务</button>
        </div>
      </div>
    </div>

    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import * as api from '@/api'
import { validatePodcastInput } from '@/utils/validation'
import { stageSummary } from '@/utils/stageProgress'
import EpisodeTags from '@/components/EpisodeTags.vue'

const router = useRouter()

const inputText = ref('')
const episodes = ref([])
// 首次加载标志：为 true 时显示加载态，避免在数据到达前误显示"暂无节目"
const isLoading = ref(true)
// 节目从 processing → ready/failed 的转换通知。
// 用于解决"在处理中过滤下节目完成后消失看起来像数据丢失"的 UX 问题。
const recentTransitions = ref([])
const isPasting = ref(false)
const error = ref('')
let pollInterval = null

// 搜索和过滤
const searchQuery = ref('')
const currentFilter = ref('all')
const filters = [
  { value: 'all', label: '全部' },
  { value: 'ready', label: '已完成' },
  { value: 'processing', label: '处理中' },
  { value: 'failed', label: '失败' },
]

const hasFixtures = ref(true) // 假设有演示数据

// 计算属性 - 过滤后的episodes
const filteredEpisodes = computed(() => {
  let filtered = episodes.value

  // 应用搜索过滤
  if (searchQuery.value.trim()) {
    const query = searchQuery.value.toLowerCase().trim()
    filtered = filtered.filter(ep =>
      ep.title?.toLowerCase().includes(query) ||
      ep.tldr_zh?.toLowerCase().includes(query)
    )
  }

  // 应用状态过滤
  if (currentFilter.value !== 'all') {
    filtered = filtered.filter(ep => {
      if (currentFilter.value === 'ready') return ep.status === 'ready'
      if (currentFilter.value === 'processing') return ['pending', 'downloading', 'asr_running', 'llm_running'].includes(ep.status)
      if (currentFilter.value === 'failed') return ep.status === 'failed'
      return true
    })
  }

  return filtered
})

// 品牌区统计
const totalHours = computed(() => {
  const total = episodes.value.reduce((sum, ep) => sum + (ep.duration_min || 0), 0)
  return Math.round(total / 60)
})

const readyCount = computed(() =>
  episodes.value.filter(ep => ep.status === 'ready').length
)

// 把后端 status 映射成卡片左侧 strip 的 key（ready/processing/failed/pending）
const getStatusKey = (status) => {
  if (['pending', 'downloading', 'asr_running', 'llm_running'].includes(status)) return 'processing'
  return status || 'pending'
}

// 删除确认对话框状态
const showDeleteDialog = ref(false)
const episodeToDelete = ref(null)

// 取消确认对话框状态
const showCancelDialog = ref(false)
const episodeToCancel = ref(null)

// 正在恢复的 episode id（用于按钮 loading 态 + 防重复点击）
const resumingId = ref(null)

const verdictText = (verdict) => {
  const texts = {
    deep_listen: '🎧 深度聆听',
    skim_outline: '👄 略读大纲',
    skip: '⏭️ 可跳过',
  }
  return texts[verdict] || verdict
}

const isProcessing = (status) => {
  return ['pending', 'downloading', 'asr_running', 'llm_running'].includes(status)
}

const formatTime = (dateStr) => {
  const date = new Date(dateStr)
  const now = new Date()
  const diff = now - date
  const minutes = Math.floor(diff / 60000)
  const hours = Math.floor(diff / 3600000)
  const days = Math.floor(diff / 86400000)

  if (days > 0) return `${days}天前`
  if (hours > 0) return `${hours}小时前`
  if (minutes > 0) return `${minutes}分钟前`
  return '刚刚'
}

const handlePaste = async () => {
  // 客户端校验：避免把明显错误的输入打到后端
  const { ok, error: validationError, normalized } = validatePodcastInput(inputText.value)
  if (!ok) {
    error.value = validationError
    return
  }

  // 防止用户在请求 in-flight 时再次点 "添加"
  if (isPasting.value) return

  isPasting.value = true
  error.value = ''

  try {
    const episode = await api.pasteEpisode(normalized)
    episodes.value.unshift(episode)
    inputText.value = ''
  } catch (e) {
    error.value = e.message || '添加失败'
  } finally {
    isPasting.value = false
  }
}

const openEpisode = (id) => {
  router.push({ name: 'player', params: { id } })
}

// 删除确认
const confirmDelete = (episode) => {
  episodeToDelete.value = episode
  showDeleteDialog.value = true
}

const cancelDelete = () => {
  showDeleteDialog.value = false
  episodeToDelete.value = null
}

const executeDelete = async () => {
  if (!episodeToDelete.value) return

  try {
    await api.deleteEpisode(episodeToDelete.value.id)
    episodes.value = episodes.value.filter(ep => ep.id !== episodeToDelete.value.id)
    cancelDelete()
  } catch (e) {
    alert('删除失败: ' + e.message)
  }
}

// 取消确认
const confirmCancel = (episode) => {
  episodeToCancel.value = episode
  showCancelDialog.value = true
}

const cancelCancel = () => {
  showCancelDialog.value = false
  episodeToCancel.value = null
}

const executeCancel = async () => {
  if (!episodeToCancel.value) return

  try {
    await api.cancelEpisode(episodeToCancel.value.id)
    // 取消成功后刷新列表
    await loadEpisodes()
    cancelCancel()
  } catch (e) {
    alert('取消失败: ' + e.message)
  }
}

// 恢复：直接调用后端，raw_input 留空 → 后端从 source 表读原始 URL
const resumeEpisode = async (episode) => {
  if (resumingId.value) return
  resumingId.value = episode.id
  try {
    await api.resumeEpisode(episode.id)
    await loadEpisodes()
  } catch (e) {
    alert('恢复失败: ' + (e.message || '未知错误'))
  } finally {
    resumingId.value = null
  }
}

const loadEpisodes = async () => {
  try {
    // 注意：api.listEpisodes() 返回的已经是 episodes 数组本身（不是 {episodes: []}）
    const incoming = await api.listEpisodes()

    // 检测状态转换：之前是 processing，现在是 ready/failed。
    // 用户可能在 'processing' 过滤下，节目一变 ready 就从列表消失，
    // 看起来像数据丢了。这里捕获转换并弹出可点击提示，引导用户切换过滤。
    const prevById = new Map(episodes.value.map((e) => [e.id, e.status]))
    const PROCESSING_STATES = ['pending', 'downloading', 'asr_running', 'llm_running']
    for (const ep of incoming) {
      const prev = prevById.get(ep.id)
      if (prev && PROCESSING_STATES.includes(prev) && ep.status !== prev) {
        // 状态发生转换：processing → ready/failed
        recentTransitions.value.unshift({
          id: ep.id,
          title: ep.title,
          status: ep.status,
          at: Date.now(),
        })
        // 只保留最近 5 条，避免无限增长
        recentTransitions.value = recentTransitions.value.slice(0, 5)
      }
    }

    episodes.value = incoming
  } catch (e) {
    console.error('加载节目列表失败:', e)
  } finally {
    // 首次加载完成后才允许展示空状态，避免误闪
    isLoading.value = false
  }
}

// 清掉超过 60s 的 transition toast
function pruneRecentTransitions() {
  const cutoff = Date.now() - 60_000
  recentTransitions.value = recentTransitions.value.filter((t) => t.at > cutoff)
}

function dismissTransition(id) {
  recentTransitions.value = recentTransitions.value.filter((t) => t.id !== id)
}

// 搜索处理（防抖）
let searchTimeout = null
const handleSearch = () => {
  // 搜索在 computed 属性中实时处理，无需额外逻辑
}

// 设置过滤
const setFilter = (filter) => {
  currentFilter.value = filter
}

// 获取错误消息
const getErrorMessage = (episode) => {
  // 根据错误类型提供具体的修复建议
  if (episode.error_msg) {
    const error = episode.error_msg.toLowerCase()
    if (error.includes('invalid') || error.includes('validation')) {
      return '链接无效，请检查后重试'
    } else if (error.includes('download') || error.includes('fetch')) {
      return '下载失败，请尝试其他链接或稍后重试'
    } else if (error.includes('asr') || error.includes('transcribe')) {
      return '音频处理失败，文件可能损坏'
    } else if (error.includes('llm') || error.includes('api')) {
      return '分析失败，请检查API配置或稍后重试'
    }
  }
  return '处理失败，点击恢复按钮重试'
}

// 加载演示数据
const loadFixture = async () => {
  try {
    await api.loadFixtureEpisode()
    await loadEpisodes()
    hasFixtures.value = false
  } catch (e) {
    alert('加载演示数据失败: ' + e.message)
  }
}

// 轮询检查状态
const startPolling = () => {
  loadEpisodes()
  pollInterval = setInterval(() => {
    const hasProcessing = episodes.value.some(ep => isProcessing(ep.status))
    if (hasProcessing) {
      loadEpisodes()
    }
  }, 1500) // 提高轮询频率到 1.5 秒
}

// 定期清理过期的 transition toast
let transitionPruneInterval = null

onMounted(() => {
  startPolling()
  transitionPruneInterval = setInterval(pruneRecentTransitions, 10_000)
})

onUnmounted(() => {
  if (pollInterval) clearInterval(pollInterval)
  if (transitionPruneInterval) clearInterval(transitionPruneInterval)
})
</script>

<style scoped>
.library-view {
  max-width: 1280px;
  margin: 0 auto;
  padding: 24px 20px 48px;
}

/* === 品牌区 === */
.brand-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid #e5e7eb;
}

.brand-title-block {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.brand-title {
  font-size: 24px;
  font-weight: 700;
  color: #1f2937;
  margin: 0;
  letter-spacing: -0.01em;
}

.brand-tagline {
  font-size: 13px;
  color: #6b7280;
}

.brand-stats {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #6b7280;
}

.stat { font-weight: 500; }
.stat-sep { color: #d1d5db; }

.settings-gear {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px; height: 34px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  color: #6b7280;
  text-decoration: none;
  transition: color .15s, border-color .15s;
}
.settings-gear:hover { color: #4f8ef7; border-color: #4f8ef7; }

/* === 粘贴区（视觉降权，浅灰背景）=== */
.paste-section {
  background: #fafafa;
  border: 1px solid #f0f0f0;
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 16px;
}

/* === 检索区 === */
.search-section {
  margin-bottom: 20px;
}

.search-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.search-input {
  flex: 1;
  min-width: 200px;
  padding: 8px 12px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  font-size: 13px;
  background: white;
}

.search-input:focus {
  outline: none;
  border-color: #4f8ef7;
  box-shadow: 0 0 0 3px rgba(79, 142, 247, 0.1);
}

.search-btn {
  padding: 8px 16px;
  background: #1f2937;
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s;
}

.search-btn:hover:not(:disabled) {
  background: #374151;
}

.search-btn:disabled {
  background: #d1d5db;
  cursor: not-allowed;
}

.filter-chips {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  margin-left: auto;
}

.filter-chip {
  padding: 6px 12px;
  background: transparent;
  color: #6b7280;
  border: 1px solid #e5e7eb;
  border-radius: 16px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}

.filter-chip:hover {
  background: #f3f4f6;
  border-color: #d1d5db;
}

.filter-chip.active {
  background: #1f2937;
  color: white;
  border-color: #1f2937;
}

.try-demo-btn {
  margin-top: 16px;
  padding: 10px 20px;
  background: #4f8ef7;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s;
}

.try-demo-btn:hover {
  background: #447eff;
}

.no-results {
  text-align: center;
  padding: 40px 20px;
}

/* 节目状态转换 toast */
.transitions-toast {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 16px;
}

.transition-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  font-size: 13px;
  border: 1px solid;
  animation: transition-slide-in 0.25s ease-out;
}

.transition-ready {
  background: #ecfdf5;
  border-color: #6ee7b7;
  color: #065f46;
}

.transition-failed {
  background: #fef2f2;
  border-color: #fca5a5;
  color: #991b1b;
}

.transition-icon {
  flex-shrink: 0;
  font-weight: 700;
}

.transition-text {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.transition-action {
  flex-shrink: 0;
  padding: 4px 10px;
  border: none;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.6);
  color: inherit;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
}

.transition-action:hover {
  background: rgba(255, 255, 255, 0.9);
}

.transition-dismiss {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  padding: 0;
  border: none;
  background: transparent;
  color: inherit;
  opacity: 0.6;
  cursor: pointer;
  font-size: 12px;
  line-height: 1;
}

.transition-dismiss:hover {
  opacity: 1;
}

@keyframes transition-slide-in {
  from {
    opacity: 0;
    transform: translateY(-4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.paste-section {
  margin-bottom: 30px;
}

.input-group {
  display: flex;
  gap: 10px;
}

.paste-input {
  flex: 1;
  padding: 12px 16px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  font-size: 14px;
}

.paste-input:disabled {
  background: #f3f4f6;
}

.paste-btn {
  padding: 12px 24px;
  background: #4f8ef7;
  color: white;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
}

.paste-btn:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}

.error-message {
  margin-top: 8px;
  color: #ef4444;
  font-size: 13px;
}

.episodes-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
  gap: 12px;
  align-items: start;
}

/* B 方案卡片：左侧彩色 strip + 浅灰底，按状态变色 */
.episode-card {
  position: relative;
  background: #fafafa;
  border: 1px solid #ececec;
  border-left: 3px solid #d1d5db;
  border-radius: 8px;
  padding: 14px 16px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s, transform 0.15s;
  overflow: hidden;
}

.episode-card:hover {
  background: #f4f4f5;
  transform: translateY(-1px);
}

/* 状态对应的左侧 strip 配色 */
.card-status-ready { border-left-color: #10b981; }
.card-status-processing { border-left-color: #f59e0b; }
.card-status-failed { border-left-color: #ef4444; }
.card-status-pending { border-left-color: #d1d5db; }

.card-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* 标题区：中文主标题 + 英文原标题副 */
.title-block {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.title-zh {
  font-size: 15px;
  font-weight: 600;
  color: #1f2937;
  line-height: 1.4;
  margin: 0;
  /* 放宽到 3 行（原来 nowrap 单行截断）*/
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  word-break: break-word;
}

.title-original {
  font-size: 12px;
  color: #9ca3af;
  line-height: 1.4;
  margin: 0;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  word-break: break-word;
  font-style: italic;
}

.card-tags {
  margin: 0;
}

/* 底部元信息行 */
.card-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 11px;
  color: #9ca3af;
  margin-top: auto;
  padding-top: 4px;
}

.meta-time { color: #9ca3af; }
.meta-dot { color: #d1d5db; }
.meta-highlights { color: #6b7280; }
.meta-verdict { font-weight: 600; }

/* 裁定标签配色 */
.verdict-deep_listen { color: #047857; }
.verdict-skim_outline { color: #b45309; }
.verdict-skip { color: #6b7280; }

/* 操作按钮：右下角，hover 才显示 */
.card-actions {
  position: absolute;
  bottom: 8px;
  right: 8px;
  display: flex;
  gap: 4px;
  opacity: 0;
  transition: opacity 0.15s;
}

.episode-card:hover .card-actions {
  opacity: 1;
}

.card-action-btn {
  padding: 4px 10px;
  background: rgba(255, 255, 255, 0.9);
  color: #4b5563;
  border: 1px solid #e5e7eb;
  border-radius: 4px;
  font-size: 11px;
  cursor: pointer;
  backdrop-filter: blur(4px);
  transition: all 0.15s;
}

.card-action-btn:hover {
  background: white;
  border-color: #d1d5db;
}

.card-action-danger:hover {
  color: #ef4444;
  border-color: #fecaca;
}

/* 处理中信息：紧凑三行（进度条 / 当前阶段 / 全阶段状态条）。
   全阶段状态条用 done/active/todo 三态着色，让用户一眼看到进度位置。 */
.processing-info {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* 行1：总进度条 + % + N/M 步 */
.progress-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.progress-bar {
  flex: 1;
  height: 6px;
  background: #e5e7eb;
  border-radius: 3px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #4f8ef7, #6366f1);
  transition: width 0.5s ease;
}

.progress-percent {
  font-size: 12px;
  font-weight: 600;
  color: #4f8ef7;
  font-variant-numeric: tabular-nums;
}

/* 步数计数推到最右，弱化为次要信息 */
.progress-step {
  margin-left: auto;
  font-size: 11px;
  color: #9ca3af;
  font-variant-numeric: tabular-nums;
}

/* 行2：当前阶段名 + 计数（聚焦） */
.active-stage {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  line-height: 1.4;
}

.active-stage__pulse {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #4f8ef7;
  animation: indeterminate-blink 1.2s infinite;
}

.active-stage__name {
  color: #4f8ef7;
  font-weight: 600;
}

.active-stage__count {
  color: #6366f1;
  font-variant-numeric: tabular-nums;
  font-size: 11px;
}

/* 行3：全阶段状态条。固定顺序列出所有阶段，按 done/active/todo 三态着色，
   斜杠分隔符弱化到最浅，让阶段名本身的状态色成为视觉主角。
   纯色彩 + 字重区分（不加 ✓ 等额外字形），保持紧凑、契合用户的"只列名字"意图。 */
.stage-chips {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  font-size: 11px;
  line-height: 1.6;
}

.stage-chips__sep {
  margin: 0 3px;
  color: #e2e8eb;
  font-weight: 400;
}

.stage-chip {
  font-variant-numeric: tabular-nums;
}

/* 已完成：active 主色蓝的弱化版（退色 slate-blue），同色相弱化，
   既表达"已落地"又不引入第二种语义色，保持调色盘只一种 accent hue。
   比 active 暗/灰一档，比 todo 的浅灰更"在场"，三态层次：active > done > todo。 */
.stage-chip--done {
  color: #7c93b8;
  font-weight: 500;
}

/* 当前进行：主色蓝（饱和）+ 加粗，与进度条/脉冲点同色，承接视觉焦点。 */
.stage-chip--active {
  color: #4f8ef7;
  font-weight: 600;
}

/* 未开始：浅灰退后，但保留可读，提示"还在后面"。 */
.stage-chip--todo {
  color: #cbd1d9;
  font-weight: 400;
}

@keyframes indeterminate-blink {
  0%, 100% { opacity: 0.3; }
  50% { opacity: 1; }
}

.tldr {
  font-size: 13px;
  color: #374151;
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.highlights-preview {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-top: 8px;
}

.highlights-count {
  font-size: 12px;
  color: #059669;
}

.verdict-badge {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
}

.verdict-deep_listen { background: #fef3c7; color: #92400e; }
.verdict-skim_outline { background: #e0e7ff; color: #4338ca; }
.verdict-skip { background: #fee2e2; color: #991b1b; }

.error-info {
  color: #ef4444;
  font-size: 13px;
}

.card-footer {
  display: flex;
  justify-content: flex-end;
}

.delete-btn {
  padding: 6px 12px;
  background: transparent;
  color: #ef4444;
  border: 1px solid #ef4444;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
}

.delete-btn:hover {
  background: #ef4444;
  color: white;
}

.cancel-btn {
  padding: 6px 12px;
  background: transparent;
  color: #f59e0b;
  border: 1px solid #f59e0b;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
}

.cancel-btn:hover {
  background: #f59e0b;
  color: white;
}

.resume-btn {
  padding: 6px 12px;
  background: transparent;
  color: #22c55e;
  border: 1px solid #22c55e;
  border-radius: 6px;
  font-size: 12px;
  cursor: pointer;
  margin-right: 8px;
}

.resume-btn:hover {
  background: #22c55e;
  color: white;
}

.empty-state {
  text-align: center;
  padding: 60px 20px;
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 16px;
}

.empty-state p {
  color: #6b7280;
  margin-bottom: 8px;
}

.empty-hint {
  font-size: 13px;
  color: #9ca3af;
}

/* 删除确认对话框 */
.dialog-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  animation: fadeIn 0.2s ease;
}

@keyframes fadeIn {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

.dialog-box {
  background: white;
  border-radius: 12px;
  padding: 24px;
  min-width: 320px;
  max-width: 400px;
  box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.1);
  animation: slideUp 0.2s ease;
}

@keyframes slideUp {
  from {
    transform: translateY(20px);
    opacity: 0;
  }
  to {
    transform: translateY(0);
    opacity: 1;
  }
}

.dialog-title {
  font-size: 18px;
  font-weight: 600;
  color: #1f2937;
  margin-bottom: 12px;
}

.dialog-message {
  font-size: 14px;
  color: #6b7280;
  line-height: 1.5;
  margin-bottom: 24px;
}

.dialog-actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
}

.dialog-btn {
  padding: 10px 20px;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  border: none;
  transition: all 0.2s ease;
}

.dialog-btn-cancel {
  background: #f3f4f6;
  color: #374151;
}

.dialog-btn-cancel:hover {
  background: #e5e7eb;
}

.dialog-btn-confirm {
  background: #ef4444;
  color: white;
}

.dialog-btn-confirm:hover {
  background: #dc2626;
}

.dialog-btn-confirm:disabled {
  background: #cbd5e1;
  cursor: not-allowed;
}

/* 仅给屏幕阅读器可见的标签，视觉隐藏但对辅助技术可见 */
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

/* 加载态 spinner */
.loading-spinner {
  width: 32px;
  height: 32px;
  border: 3px solid #e5e7eb;
  border-top-color: #4f8ef7;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin: 0 auto 12px;
}

@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
