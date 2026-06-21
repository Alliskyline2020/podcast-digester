<template>
  <transition name="fade">
    <div v-if="show" class="export-overlay" @click="close">
      <div class="export-modal" @click.stop>
        <header class="modal-header">
          <div class="header-content">
            <div class="header-icon">📤</div>
            <div class="header-text">
              <h2>导出摘要</h2>
              <p class="header-desc">选择导出格式和主题样式</p>
            </div>
          </div>
          <button @click="close" class="close-btn" aria-label="关闭">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M18 6L6 18M6 6l12 12"/>
            </svg>
          </button>
        </header>

        <div class="modal-body">
          <!-- 格式选择 -->
          <div class="section">
            <h3 class="section-title">导出格式</h3>
            <div class="format-options">
              <button
                v-for="fmt in formats"
                :key="fmt.id"
                @click="selectedFormat = fmt.id"
                :class="{ active: selectedFormat === fmt.id }"
                class="format-card"
              >
                <div class="format-icon">{{ fmt.icon }}</div>
                <div class="format-badge">{{ fmt.badge }}</div>
                <div class="format-info">
                  <div class="format-name">{{ fmt.name }}</div>
                  <div class="format-desc">{{ fmt.desc }}</div>
                  <div class="format-features">
                    <span v-for="feature in fmt.features" :key="feature" class="feature-tag">
                      {{ feature }}
                    </span>
                  </div>
                </div>
                <div class="format-check">
                  <svg v-if="selectedFormat === fmt.id" width="20" height="20" viewBox="0 0 20 20" fill="currentColor">
                    <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/>
                  </svg>
                </div>
              </button>
            </div>
          </div>

          <!-- 主题选择 -->
          <div class="section">
            <h3 class="section-title">主题样式</h3>
            <div class="theme-options">
              <button
                v-for="theme in themes"
                :key="theme.id"
                @click="selectedTheme = theme.id"
                :class="{ active: selectedTheme === theme.id }"
                class="theme-card"
              >
                <div class="theme-preview" :class="theme.id">
                  <div class="preview-header"></div>
                  <div class="preview-content">
                    <div class="preview-line"></div>
                    <div class="preview-line short"></div>
                  </div>
                </div>
                <div class="theme-name">{{ theme.name }}</div>
                <div class="theme-desc">{{ theme.desc }}</div>
                <div class="theme-check" v-if="selectedTheme === theme.id">
                  <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
                    <path d="M13.5 3L6 11L2.5 7.5L1 9L6 14L15 4L13.5 3Z"/>
                  </svg>
                </div>
              </button>
            </div>
          </div>

          <!-- 高级选项 -->
          <div class="section">
            <h3 class="section-title">高级选项</h3>
            <div class="options-list">
              <label class="option-item">
                <input type="checkbox" v-model="includeTranscript" class="option-checkbox" />
                <div class="option-content">
                  <div class="option-title">包含完整字幕</div>
                  <div class="option-desc">在导出中包含完整的节目字幕文本</div>
                </div>
              </label>
            </div>
          </div>
        </div>

        <footer class="modal-footer">
          <button @click="close" class="btn-cancel">取消</button>
          <button
            @click="handleExport"
            :disabled="exporting"
            class="btn-export"
          >
            <span v-if="!exporting" class="btn-content">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/>
                <polyline points="7 10 12 15 17 10"/>
                <line x1="12" y1="15" x2="12" y2="3"/>
              </svg>
              导出摘要
            </span>
            <span v-else class="btn-content loading">
              <svg class="spinner" width="18" height="18" viewBox="0 0 24 24">
                <circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="2" opacity="0.25"/>
                <path fill="none" stroke="currentColor" stroke-width="2" d="M12 2A10 10 0 0118 12" stroke-linecap="round"/>
              </svg>
              生成中...
            </span>
          </button>
        </footer>
      </div>
    </div>
  </transition>
</template>

<script setup>
import { ref } from 'vue'
import * as api from '@/api'

const props = defineProps({
  show: Boolean,
  episodeId: String,
  episodeTitle: String
})

const emit = defineEmits(['close'])

const formats = [
  {
    id: 'html',
    name: 'HTML 网页',
    icon: '🌐',
    badge: '推荐',
    desc: '交互式网页，支持文字选择和链接分享',
    features: ['可交互', '轻量级', '易分享']
  },
  {
    id: 'png',
    name: 'PNG 长图',
    icon: '🖼️',
    badge: '热门',
    desc: '精美长图，完美适配社交媒体分享',
    features: ['高分辨率', '社交媒体', '离线查看']
  }
]

const themes = [
  {
    id: 'light',
    name: '明亮模式',
    desc: '清爽简洁，适合日间阅读'
  },
  {
    id: 'dark',
    name: '深色模式',
    desc: '护眼舒适，适合夜间阅读'
  }
]

const selectedFormat = ref('html')
const selectedTheme = ref('light')
const includeTranscript = ref(false)
const exporting = ref(false)

const close = () => emit('close')

const handleExport = async () => {
  exporting.value = true

  try {
    const result = await api.exportEpisode(
      props.episodeId,
      selectedFormat.value,
      {
        includeTranscript: includeTranscript.value,
        theme: selectedTheme.value,
        width: 1080
      }
    )

    const ext = selectedFormat.value
    const filename = `${props.episodeTitle || props.episodeId}_summary.${ext}`
    await api.downloadExport(result.download_url, filename)

    close()
  } catch (error) {
    console.error('Export failed:', error)
    alert(`导出失败: ${error.message}`)
  } finally {
    exporting.value = false
  }
}
</script>

<style scoped>
/* ===== 与主页一致的设计系统 ===== */
.export-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 20px;
  animation: fadeIn 0.2s ease-out;
}

@keyframes fadeIn {
  from { opacity: 0; }
  to { opacity: 1; }
}

.export-modal {
  background: white;
  border-radius: 16px;
  width: 100%;
  max-width: 520px;
  max-height: 90vh;
  overflow: hidden;
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

/* ===== 头部区域 ===== */
.modal-header {
  padding: 24px;
  border-bottom: 1px solid #e5e7eb;
  background: linear-gradient(135deg, #f5f7fa 0%, #e8ecf1 100%);
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
}

.header-content {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.header-icon {
  font-size: 32px;
  line-height: 1;
  flex-shrink: 0;
}

.header-text h2 {
  font-size: 20px;
  font-weight: 600;
  margin: 0 0 4px 0;
  color: #1f2937;
}

.header-desc {
  font-size: 13px;
  color: #6b7280;
  margin: 0;
}

.close-btn {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f3f4f6;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  color: #4b5563;
  transition: all 0.2s;
  flex-shrink: 0;
}

.close-btn:hover {
  background: #e5e7eb;
  color: #1f2937;
  transform: rotate(90deg);
}

/* ===== 主体内容 ===== */
.modal-body {
  padding: 24px;
  overflow-y: auto;
  flex: 1;
}

.modal-body::-webkit-scrollbar {
  width: 6px;
}

.modal-body::-webkit-scrollbar-track {
  background: transparent;
}

.modal-body::-webkit-scrollbar-thumb {
  background: #d1d5db;
  border-radius: 3px;
}

.modal-body::-webkit-scrollbar-thumb:hover {
  background: #9ca3af;
}

.section {
  margin-bottom: 28px;
}

.section:last-child {
  margin-bottom: 0;
}

.section-title {
  font-size: 15px;
  font-weight: 600;
  margin: 0 0 16px 0;
  color: #1f2937;
}

/* ===== 格式选择 ===== */
.format-options {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.format-card {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 16px;
  background: white;
  border: 2px solid #e5e7eb;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.2s;
  text-align: left;
  position: relative;
}

.format-card:hover {
  border-color: #3b82f6;
  background: #f9fafb;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.1);
}

.format-card.active {
  border-color: #3b82f6;
  background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%);
  box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.1), 0 4px 12px rgba(59, 130, 246, 0.15);
}

.format-icon {
  font-size: 40px;
  line-height: 1;
  flex-shrink: 0;
  position: relative;
}

.format-badge {
  position: absolute;
  top: -8px;
  left: -8px;
  background: #3b82f6;
  color: white;
  font-size: 10px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 12px;
  box-shadow: 0 2px 4px rgba(59, 130, 246, 0.3);
  text-transform: uppercase;
}

.format-info {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.format-name {
  font-size: 16px;
  font-weight: 600;
  color: #1f2937;
}

.format-desc {
  font-size: 13px;
  color: #6b7280;
  line-height: 1.5;
}

.format-features {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 4px;
}

.feature-tag {
  font-size: 11px;
  padding: 3px 8px;
  background: #f3f4f6;
  color: #4b5563;
  border-radius: 6px;
  font-weight: 500;
}

.format-card:hover .feature-tag {
  background: #dbeafe;
  color: #1d4ed8;
}

.format-check {
  width: 24px;
  height: 24px;
  background: #3b82f6;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  flex-shrink: 0;
  animation: checkPop 0.2s cubic-bezier(0.68, -0.55, 0.265, 1.55);
}

@keyframes checkPop {
  0% { transform: scale(0); }
  50% { transform: scale(1.2); }
  100% { transform: scale(1); }
}

/* ===== 主题选择 ===== */
.theme-options {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.theme-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
  background: white;
  border: 2px solid #e5e7eb;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.2s;
  text-align: left;
  position: relative;
}

.theme-card:hover {
  border-color: #3b82f6;
  background: #f9fafb;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.1);
}

.theme-card.active {
  border-color: #3b82f6;
  background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%);
  box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.1), 0 4px 12px rgba(59, 130, 246, 0.15);
}

.theme-preview {
  width: 100%;
  aspect-ratio: 16/10;
  background: #ffffff;
  border: 2px solid #e5e7eb;
  border-radius: 8px;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.theme-preview.dark {
  background: #1a1a1a;
  border-color: #333;
}

.preview-header {
  height: 8px;
  background: #e5e7eb;
  border-radius: 4px;
}

.theme-preview.dark .preview-header {
  background: #333;
}

.preview-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.preview-line {
  height: 6px;
  background: #e5e7eb;
  border-radius: 3px;
  flex: 1;
}

.theme-preview.dark .preview-line {
  background: #333;
}

.preview-line.short {
  width: 60%;
}

.theme-name {
  font-size: 14px;
  font-weight: 600;
  color: #1f2937;
  text-align: center;
}

.theme-desc {
  font-size: 12px;
  color: #6b7280;
  text-align: center;
  line-height: 1.5;
}

.theme-check {
  position: absolute;
  top: 12px;
  right: 12px;
  width: 20px;
  height: 20px;
  background: #3b82f6;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: white;
  box-shadow: 0 2px 4px rgba(59, 130, 246, 0.3);
  animation: checkPop 0.2s cubic-bezier(0.68, -0.55, 0.265, 1.55);
}

/* ===== 高级选项 ===== */
.options-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.option-item {
  display: flex;
  gap: 12px;
  padding: 12px;
  background: #f9fafb;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.2s;
}

.option-item:hover {
  background: #f3f4f6;
  border-color: #d1d5db;
}

.option-checkbox {
  width: 18px;
  height: 18px;
  accent-color: #3b82f6;
  cursor: pointer;
  flex-shrink: 0;
}

.option-content {
  flex: 1;
}

.option-title {
  font-size: 14px;
  font-weight: 500;
  color: #1f2937;
  margin-bottom: 2px;
}

.option-desc {
  font-size: 12px;
  color: #6b7280;
  line-height: 1.5;
}

/* ===== 底部按钮 ===== */
.modal-footer {
  padding: 20px 24px;
  border-top: 1px solid #e5e7eb;
  display: flex;
  gap: 12px;
  justify-content: flex-end;
  background: #f9fafb;
}

.btn-cancel,
.btn-export {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px 20px;
  border-radius: 10px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s;
  border: none;
}

.btn-cancel {
  background: #f3f4f6;
  color: #4b5563;
}

.btn-cancel:hover {
  background: #e5e7eb;
  color: #1f2937;
}

.btn-export {
  background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
  color: white;
  box-shadow: 0 2px 4px rgba(59, 130, 246, 0.2);
}

.btn-export:hover:not(:disabled) {
  background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
  box-shadow: 0 4px 8px rgba(37, 99, 235, 0.3);
  transform: translateY(-1px);
}

.btn-export:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.btn-content {
  display: flex;
  align-items: center;
  gap: 8px;
}

.spinner {
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* ===== 过渡动画 ===== */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

/* ===== 响应式 ===== */
@media (max-width: 640px) {
  .export-modal {
    max-width: 100%;
    border-radius: 16px 16px 0 0;
    margin: auto 0 0;
  }

  .format-card {
    flex-direction: column;
    gap: 12px;
  }

  .format-icon {
    width: 100%;
    text-align: center;
  }

  .format-badge {
    top: -6px;
    left: 50%;
    transform: translateX(-50%);
  }

  .theme-options {
    grid-template-columns: 1fr;
  }
}
</style>
