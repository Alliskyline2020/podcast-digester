<template>
  <div v-if="highlight" class="highlight-card">
    <div class="card-header">
      <h3>💡 亮点卡</h3>
      <span v-if="highlight.worth_listening_verdict" class="verdict" :class="highlight.worth_listening_verdict">
        {{ verdictText(highlight.worth_listening_verdict) }}
      </span>
    </div>

    <div class="card-body">
      <p class="tldr">{{ highlight.tldr_zh }}</p>

      <div v-if="highlight.highlights && highlight.highlights.length > 0" class="highlights-list">
        <div
          v-for="(h, idx) in highlight.highlights"
          :key="idx"
          class="highlight-item"
          @click="seekToHighlight(h)"
        >
          <span class="highlight-kind">{{ kindEmoji(h.kind) }}</span>
          <span class="highlight-text">{{ h.text_zh }}</span>
          <span class="highlight-why">{{ h.why_zh }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { usePlayer } from '../composables/player'

const props = defineProps({
  highlight: {
    type: Object,
    required: true,
  },
})

const { seekTo } = usePlayer()

const verdictText = (verdict) => {
  const texts = {
    deep_listen: '🎧 深度聆听',
    skim_outline: '👄 略读大纲',
    skip: '⏭️ 可跳过',
  }
  return texts[verdict] || verdict
}

const kindEmoji = (kind) => {
  const emojis = {
    quote: '💬',
    insight: '💡',
    fact: '📊',
    contrarian: '🤔',
    story: '📖',
  }
  return emojis[kind] || '💡'
}

const seekToHighlight = (highlight) => {
  if (highlight.start_ms) {
    seekTo(highlight.start_ms)
  }
}
</script>

<style scoped>
.highlight-card {
  background: white;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  margin-bottom: 20px;
  overflow: hidden;
}

.card-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 20px;
  border-bottom: 1px solid #e5e7eb;
  background: #f9fafb;
}

.card-header h3 {
  font-size: 16px;
  font-weight: 600;
  color: #1f2937;
  flex: 1;
}

.verdict {
  padding: 4px 12px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
}

.verdict.deep_listen {
  background: #d1fae5;
  color: #065f46;
}

.verdict.skim_outline {
  background: #fef3c7;
  color: #d97706;
}

.verdict.skip {
  background: #fee2e2;
  color: #dc2626;
}

.card-body {
  padding: 16px 20px;
}

.tldr {
  font-size: 15px;
  line-height: 1.7;
  color: #374151;
  margin-bottom: 16px;
}

.highlights-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.highlight-item {
  display: flex;
  gap: 8px;
  padding: 10px 14px;
  background: #f9fafb;
  border-radius: 6px;
  cursor: pointer;
  transition: background-color 0.15s;
}

.highlight-item:hover {
  background: #f3f4f6;
}

.highlight-kind {
  font-size: 16px;
  flex-shrink: 0;
}

.highlight-text {
  flex: 1;
  font-size: 14px;
  font-weight: 500;
  color: #1f2937;
  line-height: 1.5;
}

.highlight-why {
  font-size: 12px;
  color: #6b7280;
  font-style: italic;
  flex-shrink: 0;
  max-width: 200px;
}
</style>
