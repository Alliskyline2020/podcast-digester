<template>
  <div class="episode-tags" v-if="tags.length">
    <span
      v-for="tag in tags"
      :key="tag.key"
      class="tag"
      :class="`tag-${tag.kind}`"
      :title="tag.title"
    >
      <span v-if="tag.icon" class="tag-icon" aria-hidden="true">{{ tag.icon }}</span>
      <span class="tag-label">{{ tag.label }}</span>
    </span>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  language: { type: String, default: null },
  durationMin: { type: [Number, String], default: null },
  sourceType: { type: String, default: null },
  title: { type: String, default: '' },
  // 可选：控制渲染哪些标签，默认全部
  show: {
    type: Array,
    default: () => ['language', 'duration', 'source', 'category'],
  },
})

// 语种映射
const LANGUAGE_LABELS = {
  zh: '中文',
  en: '英文',
  'zh-CN': '中文',
  'en-US': '英文',
}

// 分类推断：从标题关键词推断内容形式
// 后端 episode_type 字段当前 DB 里没数据（全是 other），所以前端用标题启发式。
// 关键词覆盖访谈/历史/科普/发布四种形式，其余归为播客。
function inferCategory(title) {
  const t = (title || '').toLowerCase()
  if (/\binterview\b|访谈|采访|对谈|conversation/.test(t)) return { label: '访谈', title: '访谈类内容' }
  if (/oral history|历史|documentary|纪事/.test(t)) return { label: '历史', title: '历史/纪实' }
  if (/physics|quantum|科学|mystery|mysteries|量子|物理/.test(t)) return { label: '科普', title: '科学/科普' }
  if (/\blaunch\b|发布|上线|launching|unveil/.test(t)) return { label: '发布', title: '产品发布' }
  return { label: '播客', title: '常规播客' }
}

// 时长格式化：<60min 显示 "45 分钟"，>=60min 显示 "3 小时 02 分"
function formatDuration(min) {
  const n = Number(min)
  if (!n || n <= 0) return null
  if (n < 60) return `${n} 分钟`
  const h = Math.floor(n / 60)
  const m = n % 60
  return m > 0 ? `${h} 小时 ${String(m).padStart(2, '0')} 分` : `${h} 小时`
}

const tags = computed(() => {
  const out = []
  if (props.show.includes('language') && props.language) {
    const label = LANGUAGE_LABELS[props.language] || props.language.toUpperCase()
    out.push({ key: 'language', kind: 'language', icon: '🌐', label, title: `语种：${label}` })
  }
  if (props.show.includes('duration')) {
    const label = formatDuration(props.durationMin)
    if (label) {
      out.push({ key: 'duration', kind: 'duration', icon: '⏱', label, title: `时长：${label}` })
    }
  }
  if (props.show.includes('source') && props.sourceType) {
    out.push({ key: 'source', kind: 'source', icon: '🔗', label: props.sourceType, title: `来源：${props.sourceType}` })
  }
  if (props.show.includes('category')) {
    const cat = inferCategory(props.title)
    out.push({ key: 'category', kind: 'category', icon: '🏷', label: cat.label, title: cat.title })
  }
  return out
})
</script>

<style scoped>
.episode-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

.tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 9px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
  line-height: 1.4;
  white-space: nowrap;
  /* 抑制触屏长按选中 */
  -webkit-touch-callout: none;
  user-select: none;
}

.tag-icon {
  font-size: 10px;
  /* emoji 默认有 line-height 偏移，微调对齐 */
  line-height: 1;
}

/* 语种：indigo */
.tag-language {
  background: #e0e7ff;
  color: #3730a3;
}

/* 时长：slate（最克制，作为辅助信息） */
.tag-duration {
  background: #f1f5f9;
  color: #475569;
}

/* 来源：violet */
.tag-source {
  background: #ede9fe;
  color: #6d28d9;
}

/* 分类：emerald */
.tag-category {
  background: #d1fae5;
  color: #047857;
}

/* 暗色模式预留：parent 容器带 dark class 时切换 */
:deep(.dark) .tag-language,
.dark .tag-language {
  background: rgba(99, 102, 241, 0.18);
  color: #c7d2fe;
}
</style>
