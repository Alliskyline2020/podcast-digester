/**
 * 全局键盘快捷键绑定。
 *
 * 抽取自 PlayerView.vue：原实现把 keydown 处理函数、生命周期注册和
 * 业务回调全混在视图里。这里只负责：
 *   1. 跳过 input/textarea 内的按键（让表单正常工作）；
 *   2. 把按键映射到业务回调；
 *   3. 在组件 mount/unmount 时自动 add/remove 监听器。
 *
 * 用法：
 *   useKeyboardShortcuts({
 *     onSpace: () => togglePlay(),
 *     onSeek: (deltaSec) => seekRelative(deltaSec),
 *     onChapter: (direction) => navigateChapter(direction),
 *   })
 *
 * 按键映射：
 *   Space / 方向键 / J / K  —— 播放/seek/章节导航
 *
 * @param {Object} handlers
 * @param {() => void} handlers.onSpace       空格触发（通常是播放/暂停）
 * @param {(deltaSec: number) => void} handlers.onSeek   左右方向键 seek
 * @param {(direction: -1|1) => void} handlers.onChapter  J/K 跳章节
 */
import { onMounted, onUnmounted } from 'vue'

export function useKeyboardShortcuts({ onSpace, onSeek, onChapter }) {
  const handleKeydown = (e) => {
    // 表单输入元素里的按键不拦截，避免破坏输入体验
    const tag = e.target?.tagName
    if (tag === 'INPUT' || tag === 'TEXTAREA') return

    switch (e.key) {
      case ' ':
        if (onSpace) {
          e.preventDefault()
          onSpace()
        }
        break
      case 'ArrowLeft':
        if (onSeek) {
          e.preventDefault()
          onSeek(-5)
        }
        break
      case 'ArrowRight':
        if (onSeek) {
          e.preventDefault()
          onSeek(5)
        }
        break
      case 'j':
        if (onChapter) {
          e.preventDefault()
          onChapter(-1)
        }
        break
      case 'k':
        if (onChapter) {
          e.preventDefault()
          onChapter(1)
        }
        break
    }
  }

  onMounted(() => {
    window.addEventListener('keydown', handleKeydown)
  })

  onUnmounted(() => {
    window.removeEventListener('keydown', handleKeydown)
  })
}
