/**
 * 音频播放状态机：seek 排队 + 事件处理。
 *
 * 抽取自 PlayerView.vue。把 audioRef / canplay / seeking / seeked 这套
 * 状态机集中在一个地方，PlayerView 只负责把模板上的事件绑到这些 handler。
 *
 * 关键解决：避免远距离 seek 在 audio 未就绪时丢失、避免快速连续 seek
 * 互相覆盖。pendingSeek + seekQueue 一起实现"最后一次 seek 生效"语义。
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
  const isSeeking = ref(false)
  const seekQueue = ref([])

  // ============ 实际执行 seek ============
  const executeSeek = (ms) => {
    if (!audioRef.value) return

    const audio = audioRef.value
    const targetTime = ms / 1000

    // 先暂停再 seek，避免某些浏览器在 play 中 seek 的竞态
    audio.pause()
    audio.currentTime = targetTime

    // 等待 seeked 事件确认跳转完成；超时回退一次
    setTimeout(() => {
      if (Math.abs(audio.currentTime - targetTime) < 1) {
        audio.play().catch((err) => {
          // 通常是因为浏览器 autoplay policy；用户已经手动操作过页面，
          // 这里失败基本是 audio 状态不对，忽略即可
          console.warn('[useAudioPlayback] play after seek failed:', err)
        })
      } else {
        console.warn('[useAudioPlayback] seek did not land, retrying once')
        audio.currentTime = targetTime
        setTimeout(() => audio.play().catch(() => {}), 100)
      }
    }, 100)
  }

  /**
   * 对外暴露的 seek API：处理"audio 还没 ready"和"正在 seek 中"两种竞态。
   */
  const localSeekTo = (ms) => {
    if (!ms && ms !== 0) {
      console.warn('[useAudioPlayback] invalid timestamp:', ms)
      return
    }

    // 正在 seek：只保留最新一次（丢弃队列里的旧值）
    if (isSeeking.value) {
      seekQueue.value = [ms]
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

    isSeeking.value = true
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

  const onAudioSeeked = () => {
    // seek 完成：清状态，处理队列里下一位
    isSeeking.value = false

    if (seekQueue.value.length > 0) {
      const nextSeek = seekQueue.value.shift()
      setTimeout(() => {
        if (audioRef.value && audioReady.value) {
          executeSeek(nextSeek)
        }
      }, 50)
    }
  }

  return {
    // state（对外只读；写仅通过下面的方法）
    audioReady,
    pendingSeek,
    isSeeking,
    seekQueue,
    // imperative API
    executeSeek,
    localSeekTo,
    // event handlers (绑到 <audio> 的 @canplay / @seeked 等)
    onCanPlay,
    onLoadedData,
    onCanPlayThrough,
    onAudioSeeking,
    onAudioSeeked,
  }
}
