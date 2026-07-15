import { describe, it, expect } from 'vitest'
import { validatePodcastInput, MAX_INPUT_LENGTH } from '@/utils/validation'

describe('validatePodcastInput', () => {
  describe('empty / whitespace', () => {
    it('rejects empty string', () => {
      const r = validatePodcastInput('')
      expect(r.ok).toBe(false)
      expect(r.error).toMatch(/请输入/)
    })

    it('rejects whitespace-only string', () => {
      const r = validatePodcastInput('   \n\t  ')
      expect(r.ok).toBe(false)
    })

    it('rejects null/undefined', () => {
      expect(validatePodcastInput(null).ok).toBe(false)
      expect(validatePodcastInput(undefined).ok).toBe(false)
    })
  })

  describe('length limit', () => {
    it('rejects input over MAX_INPUT_LENGTH', () => {
      const long = 'https://www.youtube.com/watch?v=' + 'a'.repeat(MAX_INPUT_LENGTH)
      const r = validatePodcastInput(long)
      expect(r.ok).toBe(false)
      expect(r.error).toMatch(/过长/)
    })

    it('accepts input at exactly MAX_INPUT_LENGTH characters', () => {
      // 构造一个合法 URL 刚好 MAX_INPUT_LENGTH 长
      const base = 'https://www.youtube.com/watch?v='
      const padding = 'a'.repeat(MAX_INPUT_LENGTH - base.length)
      const r = validatePodcastInput(base + padding)
      expect(r.ok).toBe(true)
    })
  })

  describe('URL branch — supported hosts', () => {
    it.each([
      'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
      'https://youtu.be/dQw4w9WgXcQ',
      'https://m.youtube.com/watch?v=abc',
      'https://www.bilibili.com/video/BV1xx411c7mC',
      'https://b23.tv/abc123',
      'https://www.douyin.com/video/7123456789012345678',
      'https://v.douyin.com/abc123/',
      'https://xiaoyuzhou.com/podcast/123',
      'https://podcast.xiaoyuzhou.com/episode/abc',
    ])('accepts %s', (url) => {
      const r = validatePodcastInput(url)
      expect(r.ok).toBe(true)
      expect(r.normalized).toBe(url)
    })

    it('accepts protocol-relative URL', () => {
      const r = validatePodcastInput('//www.youtube.com/watch?v=abc')
      expect(r.ok).toBe(true)
    })

    it('accepts http:// (not just https)', () => {
      const r = validatePodcastInput('http://www.youtube.com/watch?v=abc')
      expect(r.ok).toBe(true)
    })

    // 小宇宙的真实主域是 xiaoyuzhoufm.com（xiaoyuzhou.com 是别名）。
    // 单集 id 是 24 位 hex，不是纯数字。回归：用户上报解析不了的链接。
    it.each([
      'https://www.xiaoyuzhoufm.com/episode/6a26b614a1049eb63a9b23e2',
      'https://xiaoyuzhoufm.com/episode/6a26b614a1049eb63a9b23e2',
      'https://podcast.xiaoyuzhoufm.com/episode/6a26b614a1049eb63a9b23e2',
    ])('accepts xiaoyuzhoufm.com link %s', (url) => {
      const r = validatePodcastInput(url)
      expect(r.ok).toBe(true)
      expect(r.normalized).toBe(url)
    })
  })

  describe('URL branch — unsupported hosts', () => {
    it('rejects unknown host with a helpful error', () => {
      const r = validatePodcastInput('https://example.com/foo')
      expect(r.ok).toBe(false)
      expect(r.error).toMatch(/不支持该站点/)
      expect(r.error).toMatch(/example\.com/)
      // 错误信息列出支持的站点，方便用户自救
      expect(r.error).toMatch(/YouTube/)
      expect(r.error).toMatch(/Bilibili/)
    })

    it('rejects malformed URL', () => {
      const r = validatePodcastInput('https://not a url with spaces')
      expect(r.ok).toBe(false)
    })
  })

  describe('local path branch', () => {
    it.each([
      '/Users/me/podcasts/episode1.m4a',
      '/tmp/recording.mp3',
      '~/Music/interview.wav',
      './relative/file.m4a',
      '../up/parent.mp3',
      'C:\\Users\\me\\file.m4a',
      'D:\\podcasts\\show.mp3',
    ])('accepts path %s', (path) => {
      const r = validatePodcastInput(path)
      expect(r.ok).toBe(true)
    })

    it('rejects paths with control characters', () => {
      const r = validatePodcastInput('/tmp/file\x00bad.m4a')
      expect(r.ok).toBe(false)
      expect(r.error).toMatch(/控制字符/)
    })
  })

  describe('unrecognized shape', () => {
    it('rejects random string', () => {
      const r = validatePodcastInput('just some random text')
      expect(r.ok).toBe(false)
      expect(r.error).toMatch(/无法识别/)
    })

    it('rejects URL-like string without proper structure', () => {
      const r = validatePodcastInput('javascript:alert(1)')
      // 不应该被当成 URL 接受（没有 http/https 前缀，也不像路径）
      expect(r.ok).toBe(false)
    })
  })

  describe('normalization', () => {
    it('trims surrounding whitespace from accepted input', () => {
      const r = validatePodcastInput('  https://youtu.be/abc  ')
      expect(r.ok).toBe(true)
      expect(r.normalized).toBe('https://youtu.be/abc')
    })
  })
})
