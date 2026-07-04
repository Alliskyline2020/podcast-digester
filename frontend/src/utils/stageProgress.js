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
