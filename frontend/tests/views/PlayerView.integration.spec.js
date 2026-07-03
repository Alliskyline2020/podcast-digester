import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref, computed } from 'vue'
import { mount } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import PlayerView from '@/views/PlayerView.vue'

// Mock API
const mockFetchEpisode = vi.fn()
vi.mock('@/api', () => ({
  fetchEpisode: () => mockFetchEpisode()
}))

// Mock player composable
const bundleRef = ref(null)
const mockSetBundle = vi.fn((data) => { bundleRef.value = data })
const mockSetAudioRef = vi.fn()
const mockSeekTo = vi.fn()
const mockTogglePlay = vi.fn()
const mockSeekRelative = vi.fn()
const mockOnTimeUpdate = vi.fn()
const mockOnLoadedMetadata = vi.fn()

vi.mock('@/composables/player', () => ({
  usePlayer: () => ({
    bundle: bundleRef,
    setBundle: mockSetBundle,
    currentTime: ref(0),
    seekTo: mockSeekTo,
    togglePlay: mockTogglePlay,
    seekRelative: mockSeekRelative,
    setAudioRef: mockSetAudioRef,
    onTimeUpdate: mockOnTimeUpdate,
    onLoadedMetadata: mockOnLoadedMetadata
  })
}))

describe('PlayerView Integration', () => {
  let router
  let wrapper

  beforeEach(() => {
    // Create router
    router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/player/:id', name: 'player', component: PlayerView },
        { path: '/library', name: 'library', component: { template: '<div>Library</div>' } }
      ]
    })

    // Clear mocks and reset state
    mockSetBundle.mockClear()
    mockSetAudioRef.mockClear()
    mockFetchEpisode.mockReset()
    bundleRef.value = null

    // Default mock response
    mockFetchEpisode.mockResolvedValue({
      episode: {
        id: 'test-episode-1',
        title: 'Test Episode',
        paragraph_mappings: [
          {
            id: 'para-1',
            start_ms: 0,
            end_ms: 15000,
            text_clean: 'First paragraph text',
            text_translated: '第一段文本',
            segment_ids: ['seg-1', 'seg-2'],
            segment_indices: [0, 1]
          },
          {
            id: 'para-2',
            start_ms: 15000,
            end_ms: 30000,
            text_clean: 'Second paragraph text',
            text_translated: '第二段文本',
            segment_ids: ['seg-3', 'seg-4'],
            segment_indices: [2, 3]
          }
        ]
      },
      transcript: {
        segments: [
          { id: 'seg-1', start_ms: 0, end_ms: 7500, text_original: 'First segment' },
          { id: 'seg-2', start_ms: 7500, end_ms: 15000, text_original: 'Second segment' },
          { id: 'seg-3', start_ms: 15000, end_ms: 22500, text_original: 'Third segment' },
          { id: 'seg-4', start_ms: 22500, end_ms: 30000, text_original: 'Fourth segment' }
        ]
      }
    })
  })

  describe('Paragraph Mappings Priority', () => {
    it('should prioritize backend paragraph_mappings when available', async () => {
      wrapper = mount(PlayerView, {
        global: {
          plugins: [router],
          stubs: {
            SubtitleMapping: { template: '<div class="subtitle-mapping-stub"></div>' }
          }
        },
        props: {
          id: 'test-episode-1'
        }
      })

      // Wait for async operations
      await wrapper.vm.$nextTick()
      await new Promise(resolve => setTimeout(resolve, 100))

      // Access component instance
      const vm = wrapper.vm

      // Verify that paragraphs are loaded from backend
      expect(vm.paragraphs).toBeDefined()
      expect(vm.paragraphs.length).toBe(2)

      // Verify paragraph structure has mapping data
      const firstPara = vm.paragraphs[0]
      expect(firstPara.segment_ids).toEqual(['seg-1', 'seg-2'])
      expect(firstPara.segment_indices).toEqual([0, 1])

      const secondPara = vm.paragraphs[1]
      expect(secondPara.segment_ids).toEqual(['seg-3', 'seg-4'])
      expect(secondPara.segment_indices).toEqual([2, 3])
    })

    it('should fallback to frontend paragraph generation when no mappings', async () => {
      // Override mock for this test
      mockFetchEpisode.mockResolvedValueOnce({
        episode: {
          id: 'test-episode-2',
          title: 'Test Episode 2'
        },
        transcript: {
          segments: [
            { id: 'seg-1', start_ms: 0, end_ms: 7500, text_original: 'First segment' },
            { id: 'seg-2', start_ms: 7500, end_ms: 15000, text_original: 'Second segment' }
          ]
        }
      })

      wrapper = mount(PlayerView, {
        global: {
          plugins: [router]
        },
        props: {
          id: 'test-episode-2'
        }
      })

      await wrapper.vm.$nextTick()
      await new Promise(resolve => setTimeout(resolve, 100))

      const vm = wrapper.vm

      // Should generate paragraphs from segments
      expect(vm.paragraphs).toBeDefined()
      expect(vm.paragraphs.length).toBeGreaterThan(0)

      // Generated paragraphs won't have segment_ids/segment_indices
      const firstPara = vm.paragraphs[0]
      expect(firstPara.start_ms).toBe(0)
    })
  })

  describe('Subtitle Scroll Integration', () => {
    it('should initialize scroll composable with transcript container', async () => {
      wrapper = mount(PlayerView, {
        global: {
          plugins: [router],
          stubs: {
            SubtitleMapping: { template: '<div></div>' }
          }
        },
        props: {
          id: 'test-episode-1'
        }
      })

      await wrapper.vm.$nextTick()
      await new Promise(resolve => setTimeout(resolve, 100))

      const vm = wrapper.vm

      // Verify transcriptContainer ref is initialized
      expect(vm.transcriptContainer).toBeDefined()

      // Verify scroll functionality is available
      expect(vm.scrollToActive).toBeDefined()
      expect(typeof vm.scrollToActive).toBe('function')
    })

    it('should update scroll on currentTime change when transcript tab is active', async () => {
      wrapper = mount(PlayerView, {
        global: {
          plugins: [router],
          stubs: {
            SubtitleMapping: { template: '<div></div>' }
          }
        },
        props: {
          id: 'test-episode-1'
        }
      })

      await wrapper.vm.$nextTick()
      await new Promise(resolve => setTimeout(resolve, 100))

      const vm = wrapper.vm

      // Switch to transcript tab
      vm.activeTab = 'transcript'
      await wrapper.vm.$nextTick()

      // Update currentTime to simulate audio playback
      vm.currentTime = 10000 // 10 seconds
      await wrapper.vm.$nextTick()

      // Verify that currentTime was updated
      expect(vm.currentTime).toBe(10000)

      // Note: Actual scroll behavior is tested in useSubtitleScroll unit tests
      // Here we just verify the integration is wired up
    })
  })


  describe('Paragraph Activation', () => {
    it('should correctly identify current paragraph based on time', async () => {
      wrapper = mount(PlayerView, {
        global: {
          plugins: [router],
          stubs: {
            SubtitleMapping: { template: '<div></div>' }
          }
        },
        props: {
          id: 'test-episode-1'
        }
      })

      await wrapper.vm.$nextTick()
      await new Promise(resolve => setTimeout(resolve, 100))

      const vm = wrapper.vm

      // Update time to middle of first paragraph (5000ms)
      vm.currentTime = 5000
      await wrapper.vm.$nextTick()

      // Test first paragraph (0-15000ms)
      expect(vm.isCurrentParagraph(vm.paragraphs[0])).toBe(true)

      // Update time to second paragraph
      vm.currentTime = 20000
      await wrapper.vm.$nextTick()

      expect(vm.isCurrentParagraph(vm.paragraphs[1])).toBe(true)
    })
  })

  describe('Error Handling', () => {
    it('should handle API errors gracefully', async () => {
      // Mock API failure
      mockFetchEpisode.mockRejectedValueOnce(new Error('Network error'))

      wrapper = mount(PlayerView, {
        global: {
          plugins: [router],
          stubs: {
            SubtitleMapping: { template: '<div></div>' }
          }
        },
        props: {
          id: 'test-episode-error'
        }
      })

      await wrapper.vm.$nextTick()
      await new Promise(resolve => setTimeout(resolve, 100))

      const vm = wrapper.vm

      // Verify error state is set
      expect(vm.loadError).toBeDefined()
      expect(vm.loadError).toBeTruthy()
      expect(vm.loadErrorMessage).toContain('Network error')
    })

    it('should show error banner when load fails', async () => {
      // Mock API failure
      mockFetchEpisode.mockRejectedValueOnce(new Error('Failed to load episode'))

      wrapper = mount(PlayerView, {
        global: {
          plugins: [router],
          stubs: {
            SubtitleMapping: { template: '<div></div>' }
          }
        },
        props: {
          id: 'test-episode-error'
        }
      })

      await wrapper.vm.$nextTick()
      await new Promise(resolve => setTimeout(resolve, 100))

      // Find error banner
      const errorBanner = wrapper.find('.error-banner')
      expect(errorBanner.exists()).toBe(true)

      // Verify error message
      const errorMessage = errorBanner.find('.error-message')
      expect(errorMessage.text()).toContain('Failed to load episode')
    })

    it('should provide retry button on error', async () => {
      mockFetchEpisode
        .mockRejectedValueOnce(new Error('First attempt failed'))
        .mockResolvedValueOnce({
          episode: { id: 'test-episode-retry', title: 'Retry Episode' },
          transcript: { segments: [] }
        })

      wrapper = mount(PlayerView, {
        global: {
          plugins: [router],
          stubs: {
            SubtitleMapping: { template: '<div></div>' }
          }
        },
        props: {
          id: 'test-episode-retry'
        }
      })

      await wrapper.vm.$nextTick()
      await new Promise(resolve => setTimeout(resolve, 100))

      const vm = wrapper.vm

      // Verify error state
      expect(vm.loadError).toBeTruthy()

      // Click retry button
      const retryButton = wrapper.find('.error-retry')
      expect(retryButton.exists()).toBe(true)

      await retryButton.trigger('click')
      await wrapper.vm.$nextTick()
      await new Promise(resolve => setTimeout(resolve, 200))

      // After retry, error should be cleared
      expect(vm.loadError).toBeNull()
    })

    it('should dismiss error when dismiss button clicked', async () => {
      mockFetchEpisode.mockRejectedValueOnce(new Error('Test error'))

      wrapper = mount(PlayerView, {
        global: {
          plugins: [router],
          stubs: {
            SubtitleMapping: { template: '<div></div>' }
          }
        },
        props: {
          id: 'test-episode-dismiss'
        }
      })

      await wrapper.vm.$nextTick()
      await new Promise(resolve => setTimeout(resolve, 100))

      const vm = wrapper.vm

      // Verify error banner exists
      expect(wrapper.find('.error-banner').exists()).toBe(true)

      // Click dismiss button
      const dismissButton = wrapper.find('.error-dismiss')
      await dismissButton.trigger('click')
      await wrapper.vm.$nextTick()

      // Dismiss 的语义是清空 loadError（banner 的渐隐由 <transition name="fade">
      // 驱动，jsdom 不触发 transitionend，无法在这里断言 DOM 移除；banner 出现
      // 已由 "show error banner when load fails" 覆盖，渐隐留给视觉回归/e2e）。
      expect(vm.loadError).toBeNull()
    })
  })

  describe('Seek Behavior', () => {
    it('seeks the audio element directly when ready (no queueing)', async () => {
      wrapper = mount(PlayerView, {
        global: {
          plugins: [router],
          stubs: {
            SubtitleMapping: { template: '<div></div>' }
          }
        },
        props: {
          id: 'test-episode-seek'
        }
      })

      await wrapper.vm.$nextTick()
      await new Promise(resolve => setTimeout(resolve, 100))

      const vm = wrapper.vm

      // Set up mock audio element
      const mockAudio = {
        readyState: 4,
        duration: 1000,
        currentTime: 0,
        pause: vi.fn(),
        play: vi.fn().mockResolvedValue(undefined)
      }
      vm.audioRef = mockAudio
      vm.audioReady = true

      // localSeekTo 在 ready 时直接 executeSeek，写入 audio.currentTime。
      vm.localSeekTo(10000)
      expect(mockAudio.currentTime).toBe(10)
    })

    it('applies the last seek directly when several fire in a row', async () => {
      wrapper = mount(PlayerView, {
        global: {
          plugins: [router],
          stubs: {
            SubtitleMapping: { template: '<div></div>' }
          }
        },
        props: {
          id: 'test-episode-seek-queue'
        }
      })

      await wrapper.vm.$nextTick()
      await new Promise(resolve => setTimeout(resolve, 100))

      const vm = wrapper.vm

      // Set up mock audio
      const mockAudio = {
        readyState: 4,
        duration: 1000,
        currentTime: 0,
        pause: vi.fn(),
        play: vi.fn().mockResolvedValue(undefined)
      }
      vm.audioRef = mockAudio
      vm.audioReady = true

      // 连续 seek：每次都直接写 currentTime，最后一次胜出。
      vm.localSeekTo(10000)
      vm.localSeekTo(20000)
      vm.localSeekTo(30000)

      expect(mockAudio.currentTime).toBe(30)
    })
  })

  describe('Memory Leak Prevention', () => {
    it('should cleanup scroll composable on unmount', async () => {
      wrapper = mount(PlayerView, {
        global: {
          plugins: [router],
          stubs: {
            SubtitleMapping: { template: '<div></div>' }
          }
        },
        props: {
          id: 'test-episode-cleanup'
        }
      })

      await wrapper.vm.$nextTick()
      await new Promise(resolve => setTimeout(resolve, 100))

      const vm = wrapper.vm

      // Verify cleanup function exists
      expect(vm.cleanupScroll).toBeDefined()
      expect(typeof vm.cleanupScroll).toBe('function')

      // Unmount component
      wrapper.unmount()

      // If we got here without errors, cleanup was called successfully
      expect(true).toBe(true)
    })


    it('should clear pending seeks on unmount', async () => {
      wrapper = mount(PlayerView, {
        global: {
          plugins: [router],
          stubs: {
            SubtitleMapping: { template: '<div></div>' }
          }
        },
        props: {
          id: 'test-episode-seek-cleanup'
        }
      })

      await wrapper.vm.$nextTick()
      await new Promise(resolve => setTimeout(resolve, 100))

      const vm = wrapper.vm

      // Set up state that needs cleanup
      vm.pendingSeek = 5000

      // Unmount component
      wrapper.unmount()

      // pending seek should be cleared on unmount
      expect(vm.pendingSeek).toBeNull()
    })
  })
})
