<template>
  <div class="library-view">
    <!-- 搜索和过滤栏 -->
    <div class="search-section">
      <div class="search-bar">
        <input
          v-model="searchQuery"
          @input="handleSearch"
          placeholder="搜索节目标题或摘要..."
          class="search-input"
        />
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
        <!-- Admin token 设置入口；后端配置了 ADMIN_TOKEN 时，写操作需要这个 -->
        <button
          @click="showTokenDialog = true"
          class="admin-token-btn"
          :class="{ 'admin-token-btn-active': hasAdminToken }"
          :aria-label="hasAdminToken ? '管理 admin token（已设置）' : '设置 admin token'"
          :title="hasAdminToken ? 'Admin token 已设置（点击修改/登出）' : '设置 admin token'"
        >
          <span aria-hidden="true">{{ hasAdminToken ? '🔓' : '🔒' }}</span>
        </button>
      </div>
    </div>

    <!-- 粘贴输入区 -->
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

    <!-- 节目列表 -->
    <div class="episodes-list">
      <div v-for="ep in filteredEpisodes" :key="ep.id" class="episode-card" @click="openEpisode(ep.id)">
        <div class="card-header">
          <span class="status-badge" :class="`status-${ep.status}`">
            {{ statusText(ep.status) }}
          </span>
          <span class="episode-time">{{ formatTime(ep.created_at) }}</span>
        </div>
        <div class="card-body">
          <h3 class="episode-title">{{ ep.title }}</h3>

          <!-- 处理中状态 - 详细进度显示 -->
          <div v-if="isProcessing(ep.status)" class="processing-info">
            <!-- 总体进度条 -->
            <div class="progress-container">
              <div class="progress-bar">
                <div class="progress-fill" :style="{ width: `${ep.overall_progress * 100}%` }"></div>
              </div>
              <span class="progress-percent">{{ Math.round(ep.overall_progress * 100) }}%</span>
            </div>

            <!-- 阶段流程显示 -->
            <div v-if="ep.stages && ep.stages.length > 0" class="stages-flow">
              <div
                v-for="(stage, idx) in displayStages(ep.stages)"
                :key="idx"
                class="stage-step"
                :class="{
                  'stage-active': stage.id === ep.current_stage,
                  'stage-completed': stage.progress >= 1,
                  'stage-pending': stage.progress === 0 && stage.id !== ep.current_stage
                }"
              >
                <div class="stage-dot"></div>
                <span class="stage-name">{{ stage.name }}</span>
              </div>
            </div>
            <span v-else class="progress-text">正在处理...</span>
          </div>

          <!-- 完成状态 -->
          <template v-else-if="ep.status === 'ready'">
            <p v-if="ep.tldr_zh" class="tldr">{{ ep.tldr_zh }}</p>
            <div v-if="ep.highlights_count > 0" class="highlights-preview">
              <span class="highlights-count">💡 {{ ep.highlights_count }} 条亮点</span>
              <span v-if="ep.worth_listening_verdict" class="verdict-badge" :class="ep.worth_listening_verdict">
                {{ verdictText(ep.worth_listening_verdict) }}
              </span>
            </div>
          </template>

          <!-- 失败状态 -->
          <div v-else-if="ep.status === 'failed'" class="error-info">
            <span>⚠️ {{ getErrorMessage(ep) }}</span>
          </div>
        </div>
        <div v-if="!ep.is_fixture" class="card-footer">
          <!-- 处理中状态显示取消按钮 -->
          <button v-if="isProcessing(ep.status)" @click.stop="confirmCancel(ep)" class="cancel-btn">取消</button>
          <!-- 失败状态显示恢复和删除按钮 -->
          <template v-else-if="ep.status === 'failed'">
            <button @click.stop="confirmResume(ep)" class="resume-btn">恢复</button>
            <button @click.stop="confirmDelete(ep)" class="delete-btn">删除</button>
          </template>
          <!-- 完成状态显示删除按钮 -->
          <button v-else-if="ep.status === 'ready'" @click.stop="confirmDelete(ep)" class="delete-btn">删除</button>
        </div>
      </div>

      <!-- 空状态 -->
      <div v-if="filteredEpisodes.length === 0" class="empty-state">
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

    <!-- 恢复确认对话框 -->
    <div v-if="showResumeDialog" class="dialog-overlay" @click.self="cancelResume">
      <div class="dialog-box" role="dialog" aria-modal="true" aria-labelledby="resume-dialog-title">
        <h3 id="resume-dialog-title" class="dialog-title">恢复任务</h3>
        <p class="dialog-message">
          恢复节目「{{ episodeToResume?.title }}」的处理
        </p>
        <div class="dialog-input-group">
          <label>请输入原始链接：</label>
          <input
            v-model="resumeInput"
            placeholder="粘贴原始播客链接或文件路径..."
            class="dialog-input"
            :class="{ 'dialog-input-error': resumeError }"
            :aria-invalid="!!resumeError"
            :aria-describedby="resumeError ? 'resume-error' : undefined"
            @keyup.enter="executeResume"
            @input="resumeError = ''"
          />
          <p v-if="resumeError" id="resume-error" class="dialog-error" role="alert">
            {{ resumeError }}
          </p>
        </div>
        <div class="dialog-actions">
          <button @click="cancelResume" class="dialog-btn dialog-btn-cancel">取消</button>
          <button
            @click="executeResume"
            :disabled="!resumeInput.trim() || resumeInProgress"
            class="dialog-btn dialog-btn-confirm"
          >
            {{ resumeInProgress ? '恢复中...' : '恢复' }}
          </button>
        </div>
      </div>
    </div>
    </div>
    <!-- Admin token 设置对话框 -->
    <TokenDialog
      :show="showTokenDialog"
      @cancel="showTokenDialog = false"
    />
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import * as api from '@/api'
import { validatePodcastInput } from '@/utils/validation'
import { useAdminAuth } from '@/composables/useAdminAuth'
import TokenDialog from '@/components/TokenDialog.vue'

const { hasToken: hasAdminToken } = useAdminAuth()
const showTokenDialog = ref(false)

const router = useRouter()

const inputText = ref('')
const episodes = ref([])
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

// 删除确认对话框状态
const showDeleteDialog = ref(false)
const episodeToDelete = ref(null)

// 取消确认对话框状态
const showCancelDialog = ref(false)
const episodeToCancel = ref(null)

// 恢复确认对话框状态
const showResumeDialog = ref(false)
const episodeToResume = ref(null)
const resumeInput = ref('')
const resumeError = ref('')
const resumeInProgress = ref(false)

// 状态文本映射
const statusText = (status) => {
  const texts = {
    pending: '等待中',
    downloading: '下载中',
    asr_running: '转录中',
    llm_running: '分析中',
    ready: '完成',
    failed: '失败',
  }
  return texts[status] || status
}

const verdictText = (verdict) => {
  const texts = {
    deep_listen: '🎧 深度聆听',
    skim_outline: '👄 略读大纲',
    skip: '⏭️ 可跳过',
  }
  return texts[verdict] || verdict
}

// 阶段名称映射（保留用于兼容，但API已返回中文名称）
const stageName = (name) => {
  // API现在直接返回中文名称，原样返回即可
  return name || ''
}

// 显示主要阶段（API已按正确顺序返回）
const displayStages = (stages) => {
  if (!stages || stages.length === 0) return []
  // 过滤掉 null/undefined 和 done 阶段（done在进度条中不显示）
  return stages.filter(s => s && s.id !== 'done')
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

// 恢复确认
const confirmResume = (episode) => {
  episodeToResume.value = episode
  resumeInput.value = ''
  showResumeDialog.value = true
}

const cancelResume = () => {
  showResumeDialog.value = false
  episodeToResume.value = null
  resumeInput.value = ''
  resumeError.value = ''
}

const executeResume = async () => {
  if (!episodeToResume.value) return

  const { ok, error: validationError, normalized } = validatePodcastInput(resumeInput.value)
  if (!ok) {
    // 用 inline error 替代 alert()，避免阻塞 + 不可测
    resumeError.value = validationError
    return
  }

  resumeError.value = ''
  resumeInProgress.value = true
  try {
    await api.resumeEpisode(episodeToResume.value.id, normalized)
    await loadEpisodes()
    cancelResume()
  } catch (e) {
    resumeError.value = e.message || '恢复失败'
  } finally {
    resumeInProgress.value = false
  }
}

const loadEpisodes = async () => {
  try {
    const data = await api.listEpisodes()
    episodes.value = data.episodes || []
  } catch (e) {
    console.error('加载节目列表失败:', e)
  }
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

onMounted(() => {
  startPolling()
})

onUnmounted(() => {
  if (pollInterval) clearInterval(pollInterval)
})
</script>

<style scoped>
.library-view {
  max-width: 1200px;
  margin: 0 auto;
  padding: 20px;
}

/* 搜索栏样式 */
.search-section {
  margin-bottom: 20px;
}

.search-bar {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.search-input {
  width: 100%;
  padding: 12px 16px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  font-size: 14px;
}

.search-input:focus {
  outline: none;
  border-color: #4f8ef7;
  box-shadow: 0 0 0 3px rgba(79, 142, 247, 0.1);
}

.filter-chips {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.filter-chip {
  padding: 6px 12px;
  background: #f3f4f6;
  color: #6b7280;
  border: 1px solid transparent;
  border-radius: 16px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.filter-chip:hover {
  background: #e5e7eb;
}

.filter-chip.active {
  background: #4f8ef7;
  color: white;
  border-color: #4f8ef7;
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
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.episode-card {
  background: #ffffff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  padding: 16px 20px;
  cursor: pointer;
  transition: box-shadow 0.2s;
}

.episode-card:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
}

.status-badge {
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 600;
}

.status-ready { background: #dcfce7; color: #166534; }
.status-failed { background: #fee2e2; color: #991b1b; }
.status-pending, .status-downloading, .status-asr_running,
.status-llm_running { background: #dbeafe; color: #075985; }

.episode-time {
  font-size: 12px;
  color: #6b7280;
}

.card-body {
  margin-bottom: 12px;
}

.episode-title {
  font-size: 16px;
  font-weight: 600;
  color: #1f2937;
  margin-bottom: 8px;
}

/* 处理中信息 */
.processing-info {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.progress-container {
  display: flex;
  align-items: center;
  gap: 10px;
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
  min-width: 40px;
}

/* 阶段流程 */
.stages-flow {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 8px 0;
}

.stage-step {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #9ca3af;
  position: relative;
}

.stage-step:not(:last-child)::after {
  content: '';
  position: absolute;
  right: -8px;
  top: 50%;
  transform: translateY(-50%);
  width: 4px;
  height: 1px;
  background: #e5e7eb;
}

.stage-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #e5e7eb;
  transition: all 0.3s ease;
}

.stage-step.stage-active .stage-dot {
  background: #4f8ef7;
  box-shadow: 0 0 0 3px rgba(79, 142, 247, 0.2);
  animation: pulse 1.5s infinite;
}

.stage-step.stage-active .stage-name {
  color: #4f8ef7;
  font-weight: 600;
}

.stage-step.stage-completed .stage-dot {
  background: #22c55e;
}

.stage-step.stage-completed .stage-name {
  color: #22c55e;
}

@keyframes pulse {
  0%, 100% {
    box-shadow: 0 0 0 3px rgba(79, 142, 247, 0.2);
  }
  50% {
    box-shadow: 0 0 0 6px rgba(79, 142, 247, 0.1);
  }
}

.progress-text {
  font-size: 12px;
  color: #6b7280;
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

.dialog-input-group {
  margin-bottom: 20px;
}

.dialog-input-group label {
  display: block;
  font-size: 13px;
  font-weight: 500;
  color: #374151;
  margin-bottom: 8px;
}

.dialog-input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  font-size: 14px;
}

.dialog-input:focus {
  outline: none;
  border-color: #4f8ef7;
  box-shadow: 0 0 0 3px rgba(79, 142, 247, 0.1);
}

.dialog-input-error {
  border-color: #ef4444;
}

.dialog-input-error:focus {
  border-color: #ef4444;
  box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.1);
}

.dialog-error {
  margin: 6px 0 0;
  color: #dc2626;
  font-size: 13px;
  line-height: 1.4;
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

.admin-token-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  margin-left: 8px;
  background: transparent;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  cursor: pointer;
  font-size: 14px;
  color: #6b7280;
  transition: all 0.15s;
}

.admin-token-btn:hover {
  background: #f3f4f6;
  border-color: #d1d5db;
}

.admin-token-btn-active {
  background: #ecfdf5;
  border-color: #10b981;
  color: #047857;
}

.admin-token-btn-active:hover {
  background: #d1fae5;
}
</style>
