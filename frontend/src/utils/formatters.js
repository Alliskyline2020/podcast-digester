/**
 * 播客内容展示用的纯函数格式化工具。
 *
 * 从 PlayerView.vue 抽出，避免视图层堆积纯函数；其他视图/组件可复用。
 * 所有函数都是纯函数（无副作用、无响应式依赖），便于单元测试。
 */

/**
 * 把毫秒转成 `MM:SS` 格式。`null`/`undefined` 显示 `--:--`。
 * @param {number|null|undefined} ms
 * @returns {string}
 */
export function formatTime(ms) {
  if (!ms && ms !== 0) return '--:--'
  const s = Math.floor(ms / 1000)
  const m = Math.floor(s / 60)
  const sec = s % 60
  return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
}

/**
 * 格式化段落时间范围：显示开始 - 结束。
 * @param {number} startMs
 * @param {number|null|undefined} endMs
 * @returns {string}
 */
export function formatTimeRange(startMs, endMs) {
  if (!startMs && startMs !== 0) return '--:--'
  if (!endMs && endMs !== 0) return formatTime(startMs)
  return `${formatTime(startMs)} - ${formatTime(endMs)}`
}

/**
 * 估算 segments 总时长（取最后一段 end_ms），返回 `N min`。
 * @param {Array<{end_ms?: number}>|null|undefined} segments
 * @returns {string}
 */
export function formatDuration(segments) {
  if (!segments?.length) return '0 min'
  const totalMs = segments[segments.length - 1]?.end_ms || 0
  const min = Math.floor(totalMs / 60000)
  return `${min} min`
}

const VERDICT_TEXT = {
  deep_listen: '🎧 深度聆听',
  skim_outline: '👄 略读大纲',
  skip: '⏭️ 可跳过',
}

/**
 * 把 verdict 枚举转成中文+emoji 展示。
 * @param {string} verdict
 * @returns {string}
 */
export function verdictText(verdict) {
  return VERDICT_TEXT[verdict] || verdict
}

const HIGHLIGHT_KIND_ICON = {
  quote: '💬',
  insight: '💡',
  fact: '📊',
  contrarian: '🔥',
  story: '📖',
}

/**
 * 亮点类型 -> emoji 图标。
 */
export function getHighlightKind(kind) {
  return HIGHLIGHT_KIND_ICON[kind] || '💡'
}

const HIGHLIGHT_KIND_LABEL = {
  quote: '金句',
  insight: '洞察',
  fact: '数据',
  contrarian: '反常识',
  story: '故事',
}

/**
 * 亮点类型 -> 中文标签。
 */
export function getHighlightKindLabel(kind) {
  return HIGHLIGHT_KIND_LABEL[kind] || kind
}

const INSIGHT_CATEGORY_ICON = {
  product_strategy: '🎯',
  product_ux: '🎨',
  product_growth: '📈',
  product_positioning: '🧭',
  tech_architecture: '🏗️',
  tech_eng_practice: '🛠️',
  tech_trend: '🔮',
  tech_challenge: '⚠️',
  market_trend: '📊',
  market_competition: '⚔️',
  market_business_model: '💰',
  market_opportunity: '✨',
  other: '💡',
}

const INSIGHT_CATEGORY_LABEL = {
  product_strategy: '策略',
  product_ux: '体验',
  product_growth: '增长',
  product_positioning: '定位',
  tech_architecture: '架构',
  tech_eng_practice: '工程实践',
  tech_trend: '技术趋势',
  tech_challenge: '技术挑战',
  market_trend: '市场趋势',
  market_competition: '竞争格局',
  market_business_model: '商业模式',
  market_opportunity: '机会点',
  other: '其他',
}

/**
 * 洞察细分维度 -> emoji 图标。
 */
export function getInsightCategoryIcon(category) {
  return INSIGHT_CATEGORY_ICON[category] || '💡'
}

/**
 * 洞察细分维度 -> 中文标签。
 */
export function getInsightCategoryLabel(category) {
  return INSIGHT_CATEGORY_LABEL[category] || category
}
