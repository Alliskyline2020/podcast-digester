import { ref, computed, reactive } from 'vue'

// 🌐 全局状态 - 所有组件共享同一份state
const playerState = reactive({
  audioRef: null,
  currentTime: 0,
  duration: 0,
  bundle: null,
})

// 计算属性（computed）
const transcriptSegments = computed(() => {
  if (!playerState.bundle?.transcript?.segments) return []
  return playerState.bundle.transcript.segments
})

// 工具函数
const isCurrentSegment = (segment) => {
  if (!playerState.currentTime) return false
  return segment.start_ms <= playerState.currentTime && segment.end_ms > playerState.currentTime
}

const formatTime = (ms) => {
  if (!ms && ms !== 0) return '--:--'
  const seconds = Math.floor(ms / 1000)
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = seconds % 60
  return `${String(minutes).padStart(2, '0')}:${String(remainingSeconds).padStart(2, '0')}`
}

// 播放器控制方法
const seekTo = (ms) => {
  if (playerState.audioRef) {
    playerState.audioRef.currentTime = ms / 1000
    // 添加播放以确保 seek 生效
    if (playerState.audioRef.paused) {
      playerState.audioRef.play().catch(err => {
        console.warn('Autoplay prevented:', err)
      })
    }
  }
}

const togglePlay = () => {
  if (playerState.audioRef) {
    if (playerState.audioRef.paused) {
      playerState.audioRef.play().catch(err => {
        console.warn('Play failed:', err)
      })
    } else {
      playerState.audioRef.pause()
    }
  }
}

const onTimeUpdate = () => {
  if (playerState.audioRef) {
    playerState.currentTime = playerState.audioRef.currentTime * 1000
  }
}

const onLoadedMetadata = () => {
  if (playerState.audioRef) {
    playerState.duration = playerState.audioRef.duration * 1000
  }
}

const setBundle = (data) => {
  playerState.bundle = data
}

const setAudioRef = (ref) => {
  playerState.audioRef = ref
}

const seekRelative = (seconds) => {
  if (playerState.audioRef) {
    playerState.audioRef.currentTime = Math.max(
      0,
      Math.min(playerState.audioRef.duration, playerState.audioRef.currentTime + seconds)
    )
  }
}

// 重置状态（用于切换节目时清理）
const resetPlayer = () => {
  playerState.currentTime = 0
  playerState.duration = 0
  playerState.bundle = null
  // 注意：不重置audioRef，保持DOM引用
}

/**
 * 全局播放器状态管理
 *
 * 使用方式：
 * ```javascript
 * import { usePlayer } from '@/composables/player'
 *
 * const { bundle, setBundle, currentTime, formatTime } = usePlayer()
 * ```
 *
 * 特性：
 * - 所有组件共享同一份state
 * - bundle一旦设置，所有使用它的组件都会自动更新
 * - currentTime由audio元素的timeupdate事件驱动
 */
export function usePlayer() {
  return {
    // 状态 - 直接返回 reactive 对象的属性，不包装成 computed
    audioRef: computed(() => playerState.audioRef),
    currentTime: computed(() => playerState.currentTime),
    duration: computed(() => playerState.duration),
    bundle: computed(() => playerState.bundle),

    // 计算属性
    transcriptSegments,

    // 工具函数
    isCurrentSegment,
    formatTime,

    // 控制方法
    seekTo,
    togglePlay,
    seekRelative,
    onTimeUpdate,
    onLoadedMetadata,

    // 状态更新
    setBundle,
    setAudioRef,
    resetPlayer,
  }
}
