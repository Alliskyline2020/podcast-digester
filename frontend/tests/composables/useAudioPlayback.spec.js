import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { useAudioPlayback } from '@/composables/useAudioPlayback'

/**
 * Test harness: fake <audio> element + usePlayer seekTo stub.
 */
function makeHarness({ readyState = 4, duration = 600, currentTime = 0 } = {}) {
  const audioRef = ref({
    readyState,
    duration,
    currentTime,
    pause: vi.fn(),
    play: vi.fn().mockResolvedValue(undefined),
  })
  const seekToExternal = vi.fn()
  const composable = useAudioPlayback({ seekTo: seekToExternal, audioRef })
  return { audioRef, seekToExternal, ...composable }
}

describe('useAudioPlayback', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  describe('localSeekTo sanity guards', () => {
    it('ignores invalid timestamp (null/undefined)', () => {
      const h = makeHarness()
      h.audioReady.value = true
      const ctBefore = h.audioRef.value.currentTime
      h.localSeekTo(undefined)
      h.localSeekTo(null)
      // 无效时间戳在入口直接 return：不写 currentTime、不存 pendingSeek、
      // 也不退到外部 seekTo。
      expect(h.audioRef.value.currentTime).toBe(ctBefore)
      expect(h.pendingSeek.value).toBe(null)
      expect(h.seekToExternal).not.toHaveBeenCalled()
    })

    it('accepts timestamp 0 (valid seek to start)', () => {
      const h = makeHarness()
      h.audioReady.value = true
      h.localSeekTo(0)
      // 0 是合法值，不应在 "invalid timestamp" 分支被拒绝；ready 时直接执行
      // seek，audio.currentTime 落到 0。
      expect(h.audioRef.value.currentTime).toBe(0)
    })
  })

  describe('audio not ready / not mounted', () => {
    it('defers via seekTo external when audioRef is null', () => {
      const audioRef = ref(null)
      const seekToExternal = vi.fn()
      const { localSeekTo } = useAudioPlayback({ seekTo: seekToExternal, audioRef })
      localSeekTo(5000)
      expect(seekToExternal).toHaveBeenCalledWith(5000)
    })

    it('stores pendingSeek when audioReady is false', () => {
      const h = makeHarness({ readyState: 1, duration: 0 })
      // audioReady 初始 false
      expect(h.audioReady.value).toBe(false)
      h.localSeekTo(5000)
      expect(h.pendingSeek.value).toBe(5000)
    })

    it('stores pendingSeek when duration is 0', () => {
      const h = makeHarness({ readyState: 4, duration: 0 })
      // 即使 readyState OK，duration 为 0 也不该执行 seek
      h.localSeekTo(5000)
      expect(h.pendingSeek.value).toBe(5000)
    })
  })

  describe('direct seek path', () => {
    it('applies each seek directly to audio.currentTime (last write wins)', () => {
      const h = makeHarness()
      h.audioReady.value = true
      // localSeekTo 在 ready 时直接 executeSeek（无排队）
      h.localSeekTo(1000)
      h.localSeekTo(3000)
      h.localSeekTo(4000)
      // 浏览器对 audio.currentTime 的连续写入：最后一次胜出
      expect(h.audioRef.value.currentTime).toBe(4)
    })
  })

  describe('onCanPlay triggers pendingSeek', () => {
    it('clears pendingSeek and executes it once audio becomes ready', () => {
      const h = makeHarness({ readyState: 2, duration: 0 })
      h.localSeekTo(7000)
      expect(h.pendingSeek.value).toBe(7000)

      // simulate audio finishing load
      h.audioRef.value.readyState = 4
      h.audioRef.value.duration = 600
      h.onCanPlay({ type: 'canplay' })

      expect(h.audioReady.value).toBe(true)
      expect(h.pendingSeek.value).toBe(null)

      vi.advanceTimersByTime(10)
      // pendingSeek 在 canplay 后被排空并执行 → currentTime 落到 7s
      // （seek 路径不再 pause；是否续播取决于 audio.paused）
      expect(h.audioRef.value.currentTime).toBe(7)
    })

    it('skips canplay if already ready and past 1s playback (avoid spurious replay)', () => {
      const h = makeHarness()
      // 模拟 already playing past 1s
      h.audioReady.value = true
      h.audioRef.value.currentTime = 5

      const pauseBefore = h.audioRef.value.pause.mock.calls.length
      h.onCanPlay({ type: 'canplay' })
      // 不应该触发新的 executeSeek
      vi.advanceTimersByTime(10)
      expect(h.audioRef.value.pause.mock.calls.length).toBe(pauseBefore)
    })
  })

  describe('executeSeek lands on target', () => {
    it('sets audio.currentTime = ms/1000', () => {
      const h = makeHarness()
      h.executeSeek(12345)
      expect(h.audioRef.value.currentTime).toBe(12.345)
    })

    it('resumes playback after seek only when audio was paused', () => {
      const h = makeHarness()
      // mock audio 默认无 paused 字段 → falsy → executeSeek 不会触发 play
      h.executeSeek(1000)
      expect(h.audioRef.value.play).not.toHaveBeenCalled()

      // 标记为暂停：seek 后自动续播（用户点章节/金句的语义是"跳到这里继续听"）
      h.audioRef.value.paused = true
      h.executeSeek(2000)
      expect(h.audioRef.value.play).toHaveBeenCalled()
    })

    it('does not retry-correct drift after seek', () => {
      const h = makeHarness()
      h.executeSeek(1000)
      expect(h.audioRef.value.currentTime).toBe(1)
      // 模拟浏览器漂移：currentTime 被外部改写后，seek 路径不会自动重试校正
      // （旧的 pause-first + 100ms retry 逻辑已移除）
      h.audioRef.value.currentTime = 50
      vi.advanceTimersByTime(110)
      expect(h.audioRef.value.currentTime).toBe(50)
    })
  })
})
