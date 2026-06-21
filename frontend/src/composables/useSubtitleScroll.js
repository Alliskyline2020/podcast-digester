import { ref, nextTick } from 'vue'

/**
 * 字幕自动滚动 Composable
 *
 * 功能:
 * 1. 监听播放器时间变化，自动滚动字幕列表
 * 2. 支持手动触发滚动
 * 3. 智能定位策略（居中/顶部/底部）
 * 4. 提供清理函数防止内存泄漏
 *
 * @param {Ref<Object>} containerRef - 字幕容器的 DOM ref
 * @param {Ref<Array>} items - 字幕段落数据
 * @param {Object} options - 配置选项
 * @param {string} options.block - 滚动定位策略: 'center' | 'start' | 'end' | 'nearest'
 * @param {number} options.threshold - 时间阈值（毫秒），用于判断当前段落
 * @returns {Object} - 滚动控制方法
 */
export function useSubtitleScroll(containerRef, items, options = {}) {
  const {
    block = 'center',      // 默认居中显示
    threshold = 500        // 500ms 容差
  } = options

  const isScrolling = ref(false)
  const autoScrollEnabled = ref(false)  // 是否启用自动滚动
  const hasError = ref(false)
  const errorMessage = ref('')
  let scrollTimer = null

  /**
   * 查找当前播放位置对应的段落索引
   * 使用二分查找优化性能
   */
  const findActiveIndex = (currentTime) => {
    if (!items.value || items.value.length === 0) return -1

    // 使用二分查找优化性能
    let left = 0
    let right = items.value.length - 1

    while (left <= right) {
      const mid = Math.floor((left + right) / 2)
      const item = items.value[mid]

      // 检查是否在当前段落范围内（考虑阈值）
      // 阈值使得边界检测更宽松
      if (currentTime >= item.start_ms - threshold && currentTime <= item.end_ms + threshold) {
        // 如果在两个段落的重叠区域（当前段落的尾部超过开始时间）
        if (currentTime > item.end_ms && mid < items.value.length - 1) {
          const nextItem = items.value[mid + 1]
          // 如果也在下一个段落的阈值范围内
          if (currentTime >= nextItem.start_ms - threshold) {
            // 比较距离：选择距离段落中心更近的
            const distToCurrentEnd = currentTime - item.end_ms
            const distToNextStart = nextItem.start_ms - currentTime
            // 如果更接近下一个段落的开始，返回下一个
            if (distToNextStart < distToCurrentEnd) {
              return mid + 1
            }
          }
        }
        return mid
      } else if (currentTime < item.start_ms - threshold) {
        right = mid - 1
      } else {
        left = mid + 1
      }
    }

    return -1
  }

  /**
   * 滚动到指定段落
   */
  const scrollToIndex = (index) => {
    try {
      // 清除之前的错误状态
      hasError.value = false
      errorMessage.value = ''

      if (!containerRef.value || index < 0 || index >= items.value.length) {
        hasError.value = true
        errorMessage.value = 'Invalid scroll target or container not available'
        return
      }

      isScrolling.value = true

      // 清除之前的防抖定时器
      if (scrollTimer) {
        clearTimeout(scrollTimer)
      }

      nextTick(() => {
        const container = containerRef.value
        if (!container) {
          hasError.value = true
          errorMessage.value = 'Container not available during scroll'
          isScrolling.value = false
          return
        }

        const targetElement = container.querySelector(`[data-paragraph-id="${index}"]`)

        if (targetElement) {
          targetElement.scrollIntoView({
            behavior: 'smooth',
            block: block
          })
        } else {
          hasError.value = true
          errorMessage.value = `Target element at index ${index} not found`
        }

        // 防抖标记
        scrollTimer = setTimeout(() => {
          isScrolling.value = false
        }, 500)
      })
    } catch (error) {
      console.error('[useSubtitleScroll] Error in scrollToIndex:', error)
      hasError.value = true
      errorMessage.value = error.message
      isScrolling.value = false
    }
  }

  /**
   * 滚动到当前播放位置对应的段落
   */
  const scrollToActive = (currentTime) => {
    try {
      const activeIndex = findActiveIndex(currentTime)
      if (activeIndex >= 0) {
        scrollToIndex(activeIndex)
      }
    } catch (error) {
      console.error('[useSubtitleScroll] Error in scrollToActive:', error)
      hasError.value = true
      errorMessage.value = error.message
    }
  }

  /**
   * 清理函数 - 防止内存泄漏
   * 必须在组件 onUnmounted 时调用
   */
  const cleanup = () => {
    if (scrollTimer) {
      clearTimeout(scrollTimer)
      scrollTimer = null
    }
    hasError.value = false
    errorMessage.value = ''
    isScrolling.value = false
  }

  /**
   * 监听播放器时间变化自动滚动
   * 注意：需要在组件中手动调用 watch 方法来建立监听
   */
  const watchTime = (currentTimeRef, callback) => {
    return {
      isScrolling,
      onTimeUpdate: (newTime, oldTime) => {
        // 防止滚动事件循环触发
        if (isScrolling.value) return

        // 如果自动滚动已禁用，只更新当前段落索引，不滚动
        if (!autoScrollEnabled.value) {
          const newIndex = findActiveIndex(newTime)
          if (callback) callback(newIndex, false)  // false = 不滚动
          return
        }

        // 只在切换段落时滚动（避免频繁滚动）
        const oldIndex = findActiveIndex(oldTime)
        const newIndex = findActiveIndex(newTime)

        if (oldIndex !== newIndex) {
          scrollToActive(newTime)
          if (callback) callback(newIndex, true)  // true = 已滚动
        }
      }
    }
  }

  /**
   * 启用自动滚动
   * 当用户点击字幕tab时调用
   */
  const enableAutoScroll = () => {
    autoScrollEnabled.value = true
  }

  /**
   * 禁用自动滚动
   * 当用户手动滚动时调用
   */
  const disableAutoScroll = () => {
    autoScrollEnabled.value = false
  }

  return {
    isScrolling,
    autoScrollEnabled,
    hasError,
    errorMessage,
    scrollToActive,
    scrollToIndex,
    findActiveIndex,
    watchTime,
    enableAutoScroll,
    disableAutoScroll,
    cleanup
  }
}
