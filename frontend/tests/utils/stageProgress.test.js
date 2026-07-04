import { describe, it, expect } from 'vitest'
import { stageRows, STAGE_ORDER } from '@/utils/stageProgress'

describe('stageRows', () => {
  it('marks the current stage active, prior stages done, later stages todo', () => {
    const ep = {
      current_stage: 'summarize',
      stages: [
        { id: 'download', name: '下载', progress: 1 },
        { id: 'transcribe', name: '转录', progress: 1 },
        { id: 'chapterize', name: '分章', progress: 1 },
        { id: 'summarize', name: '摘要', progress: 0.25, current: 1, total: 4 },
      ],
    }
    const rows = stageRows(ep)
    const byId = Object.fromEntries(rows.map((r) => [r.id, r]))
    expect(byId.download.state).toBe('done')
    expect(byId.transcribe.state).toBe('done')
    expect(byId.chapterize.state).toBe('done')
    expect(byId.summarize.state).toBe('active')
    expect(byId.summarize.current).toBe(1)
    expect(byId.summarize.total).toBe(4)
    expect(byId.summarize.progress).toBe(0.25)
    expect(byId.highlight.state).toBe('todo')
    expect(byId.product_insights.state).toBe('todo')
  })

  it('hides a skipped-never-started stage that is already past (zh source skips translate)', () => {
    // 中文源：translate 从不进入 ep.stages；当前已到 highlight
    const ep = {
      current_stage: 'highlight',
      stages: [
        { id: 'download', progress: 1 },
        { id: 'transcribe', progress: 1 },
        { id: 'chapterize', progress: 1 },
        { id: 'summarize', progress: 1 },
        { id: 'highlight', progress: 0.4 },
      ],
    }
    const ids = stageRows(ep).map((r) => r.id)
    expect(ids).not.toContain('translate')
    expect(ids).toEqual([
      'download', 'transcribe', 'chapterize', 'summarize', 'highlight', 'product_insights',
    ])
  })

  it('shows translate as done when it actually ran (en source)', () => {
    const ep = {
      current_stage: 'highlight',
      stages: [
        { id: 'download', progress: 1 },
        { id: 'transcribe', progress: 1 },
        { id: 'chapterize', progress: 1 },
        { id: 'summarize', progress: 1 },
        { id: 'translate', progress: 1 },
        { id: 'highlight', progress: 0.1 },
      ],
    }
    const row = stageRows(ep).find((r) => r.id === 'translate')
    expect(row.state).toBe('done')
  })

  it('renders upcoming stages as todo even when not yet in live stages', () => {
    const ep = {
      current_stage: 'download',
      stages: [{ id: 'download', progress: 0.1 }],
    }
    const rows = stageRows(ep)
    expect(rows[0].state).toBe('active')
    expect(rows.slice(1).every((r) => r.state === 'todo')).toBe(true)
    expect(rows.length).toBe(STAGE_ORDER.length)
  })

  it('falls back to all-todo when current_stage is unknown / missing', () => {
    const rows = stageRows({ current_stage: 'pending', stages: [] })
    expect(rows.length).toBe(STAGE_ORDER.length)
    expect(rows.every((r) => r.state === 'todo')).toBe(true)
    // 名称仍取自 STAGE_ORDER 兜底
    expect(rows[0].name).toBe('下载')
  })

  it('carries large counts like 440/4045 through verbatim', () => {
    const ep = {
      current_stage: 'transcribe',
      stages: [{ id: 'download', progress: 1 }, { id: 'transcribe', progress: 0.108, current: 440, total: 4045 }],
    }
    const row = stageRows(ep).find((r) => r.id === 'transcribe')
    expect(row.current).toBe(440)
    expect(row.total).toBe(4045)
  })
})
