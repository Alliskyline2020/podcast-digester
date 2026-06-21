<template>
  <div class="outline-pane">
    <div class="pane-header">章节大纲</div>
    <div v-if="chapters.length > 0" class="chapters-list">
      <div
        v-for="(chapter, idx) in chapters"
        :key="idx"
        class="chapter-item"
        :class="{ active: isCurrentChapter(idx) }"
        @click="seekToChapter(chapter)"
      >
        <div class="chapter-number">{{ idx + 1 }}</div>
        <div class="chapter-info">
          <div class="chapter-title">{{ chapter.title_zh }}</div>
          <div class="chapter-time">{{ formatTime(chapter.start_ms) }}</div>
        </div>
      </div>
    </div>
    <div v-else class="pane-placeholder">
      暂无章节大纲
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { usePlayer } from '../composables/player'

const { currentTime, bundle, seekTo, formatTime } = usePlayer()

const chapters = computed(() => {
  if (!bundle.value?.outline?.entries) return []
  return bundle.value.outline.entries
})

const isCurrentChapter = (index) => {
  if (!currentTime.value || !chapters.value[index]) return false
  const chapter = chapters.value[index]
  return currentTime.value >= chapter.start_ms && currentTime.value < chapter.end_ms
}

const seekToChapter = (chapter) => {
  seekTo(chapter.start_ms)
}
</script>

<style scoped>
.outline-pane {
  height: 100%;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  border-right: 1px solid #e5e7eb;
  background: #f9fafb;
}

.pane-header {
  padding: 12px 16px;
  font-weight: 600;
  font-size: 14px;
  border-bottom: 1px solid #e5e7eb;
}

.chapters-list {
  flex: 1;
  overflow-y: auto;
}

.chapter-item {
  display: flex;
  gap: 12px;
  padding: 12px 16px;
  cursor: pointer;
  transition: background-color 0.15s;
  border-bottom: 1px solid #f3f4f6;
}

.chapter-item:hover {
  background-color: #f3f4f6;
}

.chapter-item.active {
  background-color: #e0e7ff;
  border-left: 3px solid #6366f1;
}

.chapter-number {
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: #6366f1;
  color: white;
  font-size: 12px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
}

.chapter-info {
  flex: 1;
}

.chapter-title {
  font-size: 14px;
  font-weight: 500;
  color: #1f2937;
  margin-bottom: 4px;
}

.chapter-time {
  font-size: 12px;
  color: #6b7280;
  font-family: 'SF Mono', 'Fira Code', monospace;
}

.pane-placeholder {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #9ca3af;
  font-size: 14px;
  padding: 20px;
}
</style>
