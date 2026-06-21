<template>
  <div class="subtitle-mapping">
    <!-- 映射信息摘要 -->
    <div class="mapping-summary" @click="toggleExpand">
      <span class="mapping-icon">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline :points="expanded ? '6 9 12 15 18 9' : '18 15 12 9 6 15'"/>
        </svg>
      </span>
      <span class="mapping-text">
        {{ paragraph.segment_indices.length }} 段原始字幕
      </span>
      <span class="mapping-range">
        #{{ paragraph.segment_indices[0] + 1 }} - #{{ paragraph.segment_indices[paragraph.segment_indices.length - 1] + 1 }}
      </span>
    </div>

    <!-- 展开的原始字幕详情 -->
    <transition name="expand">
      <div v-show="expanded" class="segment-details">
        <div
          v-for="(segId, idx) in paragraph.segment_ids"
          :key="segId"
          class="segment-item"
        >
          <span class="segment-index">#{{ paragraph.segment_indices[idx] + 1 }}</span>
          <span class="segment-id">{{ segId }}</span>
        </div>
      </div>
    </transition>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  paragraph: {
    type: Object,
    required: true
  },
  expanded: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['toggle'])

const expanded = ref(props.expanded)

const toggleExpand = () => {
  expanded.value = !expanded.value
  emit('toggle', expanded.value)
}
</script>

<style scoped>
.subtitle-mapping {
  margin-top: 6px;
  padding: 6px 10px;
  background: #f9fafb;
  border-radius: 6px;
  font-size: 11px;
}

.mapping-summary {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  user-select: none;
}

.mapping-icon {
  color: #9ca3af;
  transition: transform 0.2s;
}

.mapping-summary:hover .mapping-icon {
  color: #6b7280;
}

.mapping-text {
  color: #6b7280;
}

.mapping-range {
  margin-left: auto;
  color: #9ca3af;
  font-family: 'SF Mono', monospace;
}

.segment-details {
  margin-top: 8px;
  padding-left: 20px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.segment-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 3px 0;
}

.segment-index {
  color: #3b82f6;
  font-family: 'SF Mono', monospace;
  min-width: 30px;
}

.segment-id {
  color: #9ca3af;
  font-family: 'SF Mono', monospace;
  font-size: 10px;
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
  max-height: 200px;
  opacity: 1;
}
</style>
