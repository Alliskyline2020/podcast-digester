/**
 * 处理进度阶段的全阶段列表渲染助手。
 *
 * 与 backend pipeline 阶段顺序保持一致：download → transcribe → chapterize →
 * summarize → translate(仅非中文源) → highlight → product_insights。
 */

// 固定阶段顺序 + 中文名。translate 仅非中文源执行，可能不出现在 ep.stages。
export const STAGE_ORDER = [
  { id: 'download', name: '下载' },
  { id: 'transcribe', name: '转录' },
  { id: 'chapterize', name: '分章' },
  { id: 'summarize', name: '摘要' },
  { id: 'translate', name: '翻译' },
  { id: 'highlight', name: '亮点' },
  { id: 'product_insights', name: '洞察' },
]

/**
 * 合并 STAGE_ORDER（固定顺序）与 ep.stages（实时进度/计数），返回逐行渲染数据。
 *
 *   done:   已越过当前阶段且实际启动过
 *   active: 当前阶段（显示 % 与 计数 440/4045）
 *   todo:   未到的阶段（置灰）
 *
 * 未启动且已越过（如中文源跳过的 translate，不会出现在 ep.stages）→ 不返回，
 * 避免误显示为"完成"。
 *
 * @param {{current_stage?: string, stages?: Array<{id:string,name?:string,progress?:number,current?:number|null,total?:number|null}>}} ep
 * @returns {Array<{id:string,name:string,state:('done'|'active'|'todo'),progress:number,current:number|null,total:number|null}>}
 */
export function stageRows(ep) {
  const currentIdx = STAGE_ORDER.findIndex((m) => m.id === ep?.current_stage)
  const live = new Map((ep?.stages || []).map((s) => [s.id, s]))
  return STAGE_ORDER.map((meta, idx) => {
    const s = live.get(meta.id)
    // 未启动且已越过（中文源跳过 translate）→ 不渲染，避免误显示为"完成"
    if (!s && currentIdx !== -1 && idx < currentIdx) return null
    let state = 'todo'
    if (currentIdx !== -1 && idx < currentIdx) state = 'done'
    else if (idx === currentIdx) state = 'active'
    return {
      id: meta.id,
      name: s?.name || meta.name,
      state,
      progress: Number(s?.progress ?? 0),
      current: s?.current ?? null,
      total: s?.total ?? null,
    }
  }).filter(Boolean)
}

/**
 * 紧凑卡片视图的进度摘要：总阶段数、已完成数、当前步、活跃阶段、逐行数据。
 *
 * 用于把处理中卡片里"7 行纵向 stage 列表"压缩成三行
 *   行1: [████████░░] 43%   N/M 步
 *   行2: 转录中 · 440/4045
 *   行3: 下载 / 转录 / 分章 / 摘要 / 翻译 / 亮点 / 洞察   （按状态着色）
 *
 * - `total`/`done` 用 stageRows(ep).length 与 done 计数（动态）—— 中文源跳过
 *   translate 时为 6 而非 7，避免"6/7 但已全部完成"的歧义。
 * - `step` = done + (active?1:0)，reached 语义：用户已踏上第 N 步。
 *   比 done 更贴合"第 N 步 / 共 M 步"的 stepper 直觉（最后一步进行中即 M/M）。
 * - `rows` 透传 stageRows 结果，供行3 chip 渲染复用，避免模板里二次计算。
 *
 * @param {{current_stage?: string, stages?: Array}} ep
 * @returns {{total:number, done:number, step:number, active:({id:string,name:string,state:string,progress:number,current:number|null,total:number|null}|null), rows:Array<{id:string,name:string,state:string,progress:number,current:number|null,total:number|null}>}}
 */
export function stageSummary(ep) {
  const rows = stageRows(ep)
  const done = rows.filter((r) => r.state === 'done').length
  const active = rows.find((r) => r.state === 'active') || null
  const step = done + (active ? 1 : 0)
  return { total: rows.length, done, step, active, rows }
}
