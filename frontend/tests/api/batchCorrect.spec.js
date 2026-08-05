import { describe, it, expect, vi, beforeEach } from 'vitest'
import { batchCorrect } from '@/api'

// Mock fetch globally
global.fetch = vi.fn()

describe('batchCorrect', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('calls POST /api/episodes/{id}/batch-correct with correct body when apply=false', async () => {
    const mockResponse = { ok: true, json: async () => ({ preview: { transcript_matches: 5, modules: {} } }) }
    global.fetch.mockResolvedValue(mockResponse)

    await batchCorrect('ep123', '杨植麟', '杨志林', false)

    expect(global.fetch).toHaveBeenCalledWith(
      '/api/episodes/ep123/batch-correct',
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ correct: '杨植麟', wrong: '杨志林', apply: false })
      })
    )
  })

  it('calls POST with apply=true when applying', async () => {
    const mockResponse = { ok: true, json: async () => ({ preview: { transcript_matches: 5, modules: {} } }) }
    global.fetch.mockResolvedValue(mockResponse)

    await batchCorrect('ep123', '杨植麟', '杨志林', true)

    expect(global.fetch).toHaveBeenCalledWith(
      '/api/episodes/ep123/batch-correct',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ correct: '杨植麟', wrong: '杨志林', apply: true })
      })
    )
  })

  it('returns parsed JSON response', async () => {
    const mockData = { preview: { transcript_matches: 3, modules: { outline: 1, summaries: 2 } } }
    const mockResponse = { ok: true, json: async () => mockData }
    global.fetch.mockResolvedValue(mockResponse)

    const result = await batchCorrect('ep123', 'correct', 'wrong', false)

    expect(result).toEqual(mockData)
  })

  it('throws error when response is not ok', async () => {
    const mockResponse = { ok: false }
    global.fetch.mockResolvedValue(mockResponse)

    await expect(batchCorrect('ep123', 'correct', 'wrong', false)).rejects.toThrow('批量纠错失败')
  })
})
