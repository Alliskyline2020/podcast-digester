<template>
  <div class="summary-pane">
    <div class="pane-header">章节摘要</div>
    <div v-if="currentChapterSummary" class="chapter-summary">
      <p class="summary-content">{{ currentChapterSummary.content_zh }}</p>
      <ul v-if="currentChapterSummary.key_points_zh && currentChapterSummary.key_points_zh.length > 0" class="key-points">
        <li v-for="(point, idx) in currentChapterSummary.key_points_zh" :key="idx">
          {{ point }}
        </li>
      </ul>
    </div>
    <div v-else class="pane-placeholder">
      <p>播放到章节时显示摘要</p>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { usePlayer } from '../composables/player'

const { currentTime, bundle } = usePlayer()

const currentChapterIndex = computed(() => {
  if (!currentTime.value || !bundle.value?.outline?.entries) return -1
  return bundle.value.outline.entries.findIndex(
    chapter => currentTime.value >= chapter.start_ms && currentTime.value < chapter.end_ms
  )
})

const currentChapterSummary = computed(() => {
  if (currentChapterIndex.value < 0 || !bundle.value?.chapter_summaries) return null
  return bundle.value.chapter_summaries[currentChapterIndex.value]
})
</script>

<style scoped>
.summary-pane {
  height: 100%;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  border-left: 1px solid #e5e7eb;
  background: #f9fafb;
}

.pane-header {
  padding: 12px 16px;
  font-weight: 600;
  font-size: 14px;
  border-bottom: 1px solid #e5e7eb;
}

.chapter-summary {
  padding: 16px;
}

.summary-content {
  font-size: 14px;
  line-height: 1.7;
  color: #374151;
  margin-bottom: 16px;
}

.key-points {
  list-style: none;
  padding: 0;
  margin: 0;
}

.key-points li {
  padding: 6px 0;
  font-size: 13px;
  color: #374151;
  line-height: 1.6;
  position: relative;
  padding-left: 20px;
}

.key-points li::before {
  content: "•";
  position: absolute;
  left: 8px;
  color: #6366f1;
  font-weight: bold;
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
