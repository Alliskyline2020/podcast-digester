<template>
  <div class="subtitle-pane">
    <div class="pane-header">字幕</div>
    <RecycleScroller
      v-if="segments.length > 0"
      class="scroller"
      :items="segments"
      :item-size="64"
      key-field="id"
      v-slot="{ item }"
    >
      <div
        class="subtitle-item"
        :class="{ active: isCurrentSegment(item) }"
        @click="seekTo(item.start_ms)"
      >
        <span class="subtitle-time">{{ formatTime(item.start_ms) }}</span>
        <span class="subtitle-text">
          {{ item.text_with_punct || item.text_translated || item.text_original }}
        </span>
      </div>
    </RecycleScroller>
    <div v-else class="pane-placeholder">
      暂无字幕
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { RecycleScroller } from 'vue-virtual-scroller'
import { usePlayer } from '../composables/player'

const { currentTime, transcriptSegments, seekTo, formatTime } = usePlayer()

// 判断当前段落
const isCurrentSegment = (segment) => {
  if (!currentTime.value) return false
  return segment.start_ms <= currentTime.value && segment.end_ms > currentTime.value
}
</script>

<style scoped>
.subtitle-pane {
  height: 100%;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.pane-header {
  padding: 12px 16px;
  font-weight: 600;
  font-size: 14px;
  border-bottom: 1px solid #e5e7eb;
  background: #f9fafb;
}

.scroller {
  flex: 1;
  overflow-y: auto;
}

.subtitle-item {
  display: flex;
  gap: 12px;
  padding: 10px 16px;
  cursor: pointer;
  transition: background-color 0.15s;
  border-bottom: 1px solid #f3f4f6;
}

.subtitle-item:hover {
  background-color: #f9fafb;
}

.subtitle-item.active {
  background-color: #fef3c7;
  border-left: 3px solid #f59e0b;
}

.subtitle-time {
  flex-shrink: 0;
  font-size: 12px;
  color: #6b7280;
  font-family: 'SF Mono', 'Fira Code', monospace;
  min-width: 80px;
}

.subtitle-text {
  flex: 1;
  font-size: 14px;
  line-height: 1.6;
  color: #374151;
}

.pane-placeholder {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #9ca3af;
  font-size: 14px;
}
</style>
