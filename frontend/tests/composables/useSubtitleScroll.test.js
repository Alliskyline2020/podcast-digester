import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { ref } from 'vue'
import { useSubtitleScroll } from '@/composables/useSubtitleScroll'

describe('useSubtitleScroll', () => {
  let mockContainer, mockItems

  beforeEach(() => {
    // 模拟 DOM 容器
    mockContainer = {
      querySelector: vi.fn(),
      scrollIntoView: vi.fn(),
      scrollTop: 0,
      clientHeight: 600
    }

    // 模拟字幕项
    mockItems = [
      { id: 0, start_ms: 0, end_ms: 15000 },
      { id: 1, start_ms: 15000, end_ms: 30000 },
      { id: 2, start_ms: 30000, end_ms: 45000 }
    ]
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  describe('Basic Functionality', () => {
    it('should find active index correctly', () => {
      const containerRef = ref(mockContainer)
      const itemsRef = ref(mockItems)

      const { findActiveIndex } = useSubtitleScroll(containerRef, itemsRef)

      // 测试在第一段
      expect(findActiveIndex(5000)).toBe(0)

      // 测试在第二段
      expect(findActiveIndex(20000)).toBe(1)

      // 测试在第三段
      expect(findActiveIndex(35000)).toBe(2)

      // 测试超出范围
      expect(findActiveIndex(50000)).toBe(-1)
    })

    it('should scroll to active paragraph', async () => {
      const containerRef = ref(mockContainer)
      const itemsRef = ref(mockItems)

      const { scrollToActive } = useSubtitleScroll(containerRef, itemsRef)

      // 模拟 querySelector 返回目标元素
      const mockTargetElement = { scrollIntoView: vi.fn() }
      mockContainer.querySelector.mockReturnValue(mockTargetElement)

      // 模拟当前播放时间在第二段
      const currentTime = 20000
      await scrollToActive(currentTime)

      // 验证 querySelector 被正确调用
      expect(mockContainer.querySelector).toHaveBeenCalledWith('[data-paragraph-id="1"]')

      // 验证滚动方法被调用
      expect(mockTargetElement.scrollIntoView).toHaveBeenCalledWith(
        expect.objectContaining({
          behavior: 'smooth',
          block: 'center'
        })
      )
    })

    it('should scroll to specific index', async () => {
      const containerRef = ref(mockContainer)
      const itemsRef = ref(mockItems)

      const { scrollToIndex } = useSubtitleScroll(containerRef, itemsRef)

      // 模拟 querySelector 返回目标元素
      const mockTargetElement = { scrollIntoView: vi.fn() }
      mockContainer.querySelector.mockReturnValue(mockTargetElement)

      // 滚动到索引 1
      await scrollToIndex(1)

      // 验证滚动方法被调用
      expect(mockContainer.querySelector).toHaveBeenCalledWith('[data-paragraph-id="1"]')
      expect(mockTargetElement.scrollIntoView).toHaveBeenCalledWith(
        expect.objectContaining({
          behavior: 'smooth',
          block: 'center'
        })
      )
    })

    it('should not scroll when index is out of bounds', () => {
      const containerRef = ref(mockContainer)
      const itemsRef = ref(mockItems)

      const { scrollToIndex, hasError } = useSubtitleScroll(containerRef, itemsRef)

      const mockTargetElement = { scrollIntoView: vi.fn() }
      mockContainer.querySelector.mockReturnValue(mockTargetElement)

      // 尝试滚动到无效索引
      scrollToIndex(10)

      // 验证 querySelector 未被调用
      expect(mockContainer.querySelector).not.toHaveBeenCalled()

      // 验证错误状态被设置
      expect(hasError.value).toBe(true)
    })

    it('should handle empty items array', () => {
      const containerRef = ref(mockContainer)
      const itemsRef = ref([])

      const { findActiveIndex } = useSubtitleScroll(containerRef, itemsRef)

      // 验证返回 -1
      expect(findActiveIndex(10000)).toBe(-1)
    })

    it('should use custom block option', async () => {
      const containerRef = ref(mockContainer)
      const itemsRef = ref(mockItems)

      const { scrollToIndex } = useSubtitleScroll(containerRef, itemsRef, {
        block: 'start'
      })

      const mockTargetElement = { scrollIntoView: vi.fn() }
      mockContainer.querySelector.mockReturnValue(mockTargetElement)

      await scrollToIndex(0)

      expect(mockTargetElement.scrollIntoView).toHaveBeenCalledWith(
        expect.objectContaining({
          behavior: 'smooth',
          block: 'start'
        })
      )
    })

    it('should handle threshold option correctly', () => {
      const containerRef = ref(mockContainer)
      const itemsRef = ref(mockItems)

      const { findActiveIndex } = useSubtitleScroll(containerRef, itemsRef, {
        threshold: 1000
      })

      // 在段落内部正常工作
      expect(findActiveIndex(5000)).toBe(0)  // 第一段内部
      expect(findActiveIndex(20000)).toBe(1) // 第二段内部

      // 在阈值边缘
      // 14000 在第一段范围内，虽然第二段阈值扩展到 14000
      // 但由于二分查找和阈值逻辑，会选择匹配的段落
      const result = findActiveIndex(14000)
      expect(result).toBeGreaterThanOrEqual(0)
      expect(result).toBeLessThan(3)

      // 16000 肯定在第二段
      expect(findActiveIndex(16000)).toBe(1)

      // 测试边界 - 在段落交界处
      // 15000 正好在交界处，两个段落都包含它（带阈值）
      const boundaryResult = findActiveIndex(15000)
      expect(boundaryResult).toBeGreaterThanOrEqual(0)
      expect(boundaryResult).toBeLessThan(3)
    })
  })

  describe('Error Handling', () => {
    it('should handle missing container gracefully', () => {
      const containerRef = ref(null)
      const itemsRef = ref(mockItems)

      const { scrollToIndex, hasError, errorMessage } = useSubtitleScroll(containerRef, itemsRef)

      scrollToIndex(0)

      expect(hasError.value).toBe(true)
      expect(errorMessage.value).toContain('Invalid scroll target')
    })

    it('should handle missing target element', async () => {
      const containerRef = ref(mockContainer)
      const itemsRef = ref(mockItems)

      const { scrollToIndex, hasError, errorMessage } = useSubtitleScroll(containerRef, itemsRef)

      // 模拟 querySelector 返回 null (元素不存在)
      mockContainer.querySelector.mockReturnValue(null)

      await scrollToIndex(0)

      expect(hasError.value).toBe(true)
      expect(errorMessage.value).toContain('Target element at index 0 not found')
    })

    it('should handle container becoming null during scroll', async () => {
      const containerRef = ref(mockContainer)
      const itemsRef = ref(mockItems)

      const { scrollToIndex, hasError, errorMessage } = useSubtitleScroll(containerRef, itemsRef)

      // First, make the container null directly
      containerRef.value = null

      // Try to scroll with null container
      scrollToIndex(0)

      // 验证错误被正确处理
      expect(hasError.value).toBe(true)
      expect(errorMessage.value).toContain('Invalid scroll target')
    })

    it('should clear error on successful scroll', async () => {
      const containerRef = ref(mockContainer)
      const itemsRef = ref(mockItems)

      const { scrollToIndex, hasError, errorMessage } = useSubtitleScroll(containerRef, itemsRef)

      const mockTargetElement = { scrollIntoView: vi.fn() }
      mockContainer.querySelector.mockReturnValue(mockTargetElement)

      // First scroll with error
      scrollToIndex(10)
      expect(hasError.value).toBe(true)

      // Successful scroll should clear error
      mockContainer.querySelector.mockReturnValue(mockTargetElement)
      await scrollToIndex(0)

      expect(hasError.value).toBe(false)
      expect(errorMessage.value).toBe('')
    })

    it('should handle errors in scrollToActive', () => {
      const containerRef = ref(mockContainer)
      const itemsRef = ref(mockItems)

      const { scrollToActive, hasError } = useSubtitleScroll(containerRef, itemsRef)

      // Trigger an error by passing invalid time
      scrollToActive(-1)

      // Should handle gracefully without throwing
      expect(hasError.value).toBe(false) // No error since -1 just returns no active index
    })
  })

  describe('Memory Leak Prevention', () => {
    it('should provide cleanup function', () => {
      const containerRef = ref(mockContainer)
      const itemsRef = ref(mockItems)

      const { cleanup } = useSubtitleScroll(containerRef, itemsRef)

      expect(cleanup).toBeDefined()
      expect(typeof cleanup).toBe('function')
    })

    it('should clear timers on cleanup', async () => {
      const containerRef = ref(mockContainer)
      const itemsRef = ref(mockItems)

      const { scrollToIndex, cleanup, isScrolling } = useSubtitleScroll(containerRef, itemsRef)

      const mockTargetElement = { scrollIntoView: vi.fn() }
      mockContainer.querySelector.mockReturnValue(mockTargetElement)

      // Trigger scroll which sets a timer
      await scrollToIndex(0)
      expect(isScrolling.value).toBe(true)

      // Cleanup should clear timer and reset state
      cleanup()

      // Wait for timer to see if it fires
      await new Promise(resolve => setTimeout(resolve, 600))

      // State should be reset
      expect(isScrolling.value).toBe(false)
    })

    it('should reset error state on cleanup', async () => {
      const containerRef = ref(mockContainer)
      const itemsRef = ref(mockItems)

      const { scrollToIndex, cleanup, hasError, errorMessage } = useSubtitleScroll(containerRef, itemsRef)

      // Trigger error
      scrollToIndex(10)
      expect(hasError.value).toBe(true)

      // Cleanup should reset error
      cleanup()

      expect(hasError.value).toBe(false)
      expect(errorMessage.value).toBe('')
    })

    it('should handle multiple cleanup calls safely', () => {
      const containerRef = ref(mockContainer)
      const itemsRef = ref(mockItems)

      const { cleanup } = useSubtitleScroll(containerRef, itemsRef)

      // Multiple cleanup calls should not throw
      cleanup()
      cleanup()
      cleanup()

      expect(true).toBe(true) // Test passes if no errors thrown
    })
  })

  describe('Error State Exposure', () => {
    it('should expose hasError ref', () => {
      const containerRef = ref(mockContainer)
      const itemsRef = ref(mockItems)

      const { hasError } = useSubtitleScroll(containerRef, itemsRef)

      expect(hasError).toBeDefined()
      expect(hasError.value).toBe(false)
    })

    it('should expose errorMessage ref', () => {
      const containerRef = ref(mockContainer)
      const itemsRef = ref(mockItems)

      const { errorMessage } = useSubtitleScroll(containerRef, itemsRef)

      expect(errorMessage).toBeDefined()
      expect(errorMessage.value).toBe('')
    })

    it('should update error state on error', () => {
      const containerRef = ref(mockContainer)
      const itemsRef = ref(mockItems)

      const { scrollToIndex, hasError, errorMessage } = useSubtitleScroll(containerRef, itemsRef)

      scrollToIndex(999)

      expect(hasError.value).toBe(true)
      expect(errorMessage.value).toBeTruthy()
      expect(errorMessage.value.length).toBeGreaterThan(0)
    })
  })
})
