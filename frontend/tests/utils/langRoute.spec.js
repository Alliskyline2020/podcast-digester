import { describe, it, expect } from 'vitest'
import { cjkRatio, routeText } from '@/utils/langRoute'

describe('cjkRatio', () => {
  it('returns 1 for pure CJK ideographs', () => {
    expect(cjkRatio('大家好我是小军')).toBe(1)
  })

  it('does not count CJK punctuation as ideographs', () => {
    // 7 ideographs + 1 fullwidth comma -> 7/8, not 1.
    expect(cjkRatio('大家好，我是小军')).toBeCloseTo(7 / 8, 7)
  })

  it('returns 0 for pure ASCII text', () => {
    expect(cjkRatio("Hello everyone, I'm Xiaojun")).toBe(0)
  })

  it('ignores whitespace when computing the denominator', () => {
    // Same characters, different spacing -> same ratio.
    expect(cjkRatio('你好 世界')).toBe(cjkRatio('你好世界'))
  })

  it('returns 0 for empty / nullish input', () => {
    expect(cjkRatio('')).toBe(0)
    expect(cjkRatio(undefined)).toBe(0)
    expect(cjkRatio(null)).toBe(0)
  })
})

describe('routeText', () => {
  it('routes a normal zh podcast segment (orig=zh, trans=en)', () => {
    const r = routeText('今天天气很好', 'The weather is nice today')
    expect(r.text_zh).toBe('今天天气很好')
    expect(r.text_en).toBe('The weather is nice today')
  })

  // Regression: Yao / Luo Fuli episodes — Chinese audio that was transcribed
  // under a wrong (en-US) locale, so text_original is English while the
  // Chinese lives in text_translated. Role-based routing would mislabel this;
  // content-routing must not.
  it('routes a wrong-locale episode (orig=en, trans=zh) by content', () => {
    const r = routeText(
      "Hello everyone, I'm Xiaojun.",
      '大家好，我是小军。',
    )
    expect(r.text_zh).toBe('大家好，我是小军。')
    expect(r.text_en).toBe("Hello everyone, I'm Xiaojun.")
  })

  it('falls back gracefully when translation is missing', () => {
    const r = routeText('今天天气很好', '')
    expect(r.text_zh).toBe('今天天气很好')
    expect(r.text_en).toBe('')
  })
})
