/**
 * 音频播放状态机：直接 seek + canplay 事件处理 + pendingSeek 兜底。
 *
 * 抽取自 PlayerView.vue。把 audioRef / canplay / pendingSeek 这套状态机集中
 * 在一个地方，PlayerView 只负责把模板上的事件绑到这些 handler。
 *
 * 关键解决：避免远距离 seek 在 audio 未就绪时丢失——未就绪时存为 pendingSeek，
 * canplay 后排空执行。ready 时直接写 audio.currentTime（浏览器对连续写入是
 * "最后一次胜出"，不需要应用层排队）。
 *
 * @param {Object} deps
 * @param {() => void} deps.seekTo              来自全局 usePlayer 的 seekTo，
 *                                               在 audioRef 不可用时兜底
 * @param {Object} deps.audioRef                模板 ref，绑到 <audio> 元素
 */
import { ref } from 'vue'

export function useAudioPlayback({ seekTo, audioRef }) {
  // ============ 内部状态 ============
  const audioReady = ref(false)
  const pendingSeek = ref(null)

  // ============ 实际执行 seek ============
  const executeSeek = (ms) => {
    if (!audioRef.value) return

    const audio = audioRef.value
    const targetTime = ms / 1000
    const wasPaused = audio.paused

    // 直接 seek —— 浏览器对 audio.currentTime 的 setter 是同步的，
    // 即使是 HTTP Range 流式音频也会立即更新属性并异步执行底层 seek。
    // 之前的版本先 pause() 再 seek 再 setTimeout 检查，反而引入了
    // "audio 看起来没动"的 UX bug（pause+100ms 延迟让用户误以为没响应）。
    audio.currentTime = targetTime

    // 如果之前在播放，保持播放状态；如果之前暂停了，也自动开始播放
    // （用户点击章节/金句的语义就是"跳到这里继续听"）。
    if (wasPaused) {
      audio.play().catch((err) => {
        // 通常是因为浏览器 autoplay policy；用户已经手动操作过页面，
        // 这里失败基本是 audio 状态不对，忽略即可
        console.warn('[useAudioPlayback] play after seek failed:', err)
      })
    }
  }

  /**
   * 对外暴露的 seek API：用户点击章节/金句/字幕段落时调用。
   * 直接执行 seek；不再做"pause-first + 100ms 延迟 + retry"那套复杂逻辑，
   * 那是历史上为自动滚动同步写的，但实际 user-click 场景反而不需要。
   */
  const localSeekTo = (ms) => {
    if (!ms && ms !== 0) {
      console.warn('[useAudioPlayback] invalid timestamp:', ms)
      return
    }

    if (!audioRef.value) {
      // audio 元素还没挂载，退到全局 usePlayer 的 seekTo 兜底
      seekTo(ms)
      return
    }

    const audio = audioRef.value

    // audio 数据还没就绪：保存为 pendingSeek，等 canplay 后执行
    if (!audioReady.value || audio.readyState < 2 || audio.duration === 0) {
      pendingSeek.value = ms
      return
    }

    executeSeek(ms)
  }

  // ============ <audio> 事件 handler ============

  const onCanPlay = (event) => {
    // 防 canplay 在 seek 时重复触发
    if (
      event &&
      event.type === 'canplay' &&
      audioReady.value &&
      audioRef.value &&
      audioRef.value.currentTime > 1
    ) {
      return
    }
    audioReady.value = true

    // 之前有等 ready 的 seek，现在执行
    if (pendingSeek.value !== null) {
      const ms = pendingSeek.value
      pendingSeek.value = null
      setTimeout(() => {
        if (audioRef.value && audioReady.value) {
          executeSeek(ms)
        }
      }, 0)
    }
  }

  const onLoadedData = () => {
    audioReady.value = true
  }

  const onCanPlayThrough = () => {
    audioReady.value = true
  }

  const onAudioSeeking = () => {
    // 主要用于日志/调试，目前无副作用
  }

  return {
    // state（对外只读；写仅通过下面的方法）
    audioReady,
    pendingSeek,
    // imperative API
    executeSeek,
    localSeekTo,
    // event handlers (绑到 <audio> 的 @canplay 等)
    onCanPlay,
    onLoadedData,
    onCanPlayThrough,
    onAudioSeeking,
  }
}
