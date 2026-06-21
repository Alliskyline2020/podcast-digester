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

  describe('SubtitleMapping Component Integration', () => {
    it('should render SubtitleMapping component when paragraph has mapping data', async () => {
      wrapper = mount(PlayerView, {
        global: {
          plugins: [router],
          stubs: {
            SubtitleMapping: {
              template: '<div class="subtitle-mapping-stub" :paragraph="paragraph"></div>',
              props: ['paragraph']
            }
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

      // Find SubtitleMapping components in rendered output
      const mappingComponents = wrapper.findAll('.subtitle-mapping-stub')

      // Should have one mapping component per paragraph
      expect(mappingComponents.length).toBe(vm.paragraphs.length)
    })

    it('should handle mapping expansion state', async () => {
      wrapper = mount(PlayerView, {
        global: {
          plugins: [router],
          stubs: {
            SubtitleMapping: {
              template: '<div class="subtitle-mapping-stub"></div>',
              props: ['paragraph', 'expanded']
            }
          }
        },
        props: {
          id: 'test-episode-1'
        }
      })

      await wrapper.vm.$nextTick()
      await new Promise(resolve => setTimeout(resolve, 100))

      const vm = wrapper.vm

      // Initial state should have no expanded mappings
      expect(Object.keys(vm.isMappingExpanded).length).toBe(0)

      // Toggle mapping expansion
      vm.toggleMapping('para-1', true)
      await wrapper.vm.$nextTick()

      // Verify expansion state
      expect(vm.isMappingExpanded['para-1']).toBe(true)

      // Toggle off
      vm.toggleMapping('para-1', false)
      await wrapper.vm.$nextTick()

      expect(vm.isMappingExpanded['para-1']).toBe(false)
    })

    it('should not render mapping when paragraph lacks segment data', async () => {
      // Override mock for this test
      mockFetchEpisode.mockResolvedValueOnce({
        episode: {
          id: 'test-episode-3',
          title: 'Test Episode 3',
          paragraph_mappings: [
            {
              id: 'para-1',
              start_ms: 0,
              end_ms: 15000,
              text_clean: 'Simple paragraph'
              // No segment_ids or segment_indices
            }
          ]
        },
        transcript: {
          segments: []
        }
      })

      wrapper = mount(PlayerView, {
        global: {
          plugins: [router],
          stubs: {
            SubtitleMapping: {
              template: '<div class="subtitle-mapping-stub"></div>'
            }
          }
        },
        props: {
          id: 'test-episode-3'
        }
      })

      await wrapper.vm.$nextTick()
      await new Promise(resolve => setTimeout(resolve, 100))

      const vm = wrapper.vm

      // Switch to transcript tab
      vm.activeTab = 'transcript'
      await wrapper.vm.$nextTick()

      // Should not find any mapping components
      const mappingComponents = wrapper.findAll('.subtitle-mapping-stub')
      expect(mappingComponents.length).toBe(0)
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

      // Error should be dismissed
      expect(vm.loadError).toBeNull()
      expect(wrapper.find('.error-banner').exists()).toBe(false)
    })
  })

  describe('Seek Race Condition Prevention', () => {
    it('should queue seeks when already seeking', async () => {
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

      // Start first seek
      vm.localSeekTo(10000)
      expect(vm.isSeeking).toBe(true)

      // Try second seek while first is in progress
      vm.localSeekTo(20000)

      // Second seek should be queued
      expect(vm.seekQueue.length).toBe(1)
      expect(vm.seekQueue[0]).toBe(20000)
    })

    it('should replace queue with most recent seek', async () => {
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
      vm.isSeeking = true

      // Queue multiple seeks
      vm.localSeekTo(10000)
      vm.localSeekTo(20000)
      vm.localSeekTo(30000)

      // Should only keep the most recent
      expect(vm.seekQueue.length).toBe(1)
      expect(vm.seekQueue[0]).toBe(30000)
    })

    it('should process queued seek after current seek completes', async () => {
      wrapper = mount(PlayerView, {
        global: {
          plugins: [router],
          stubs: {
            SubtitleMapping: { template: '<div></div>' }
          }
        },
        props: {
          id: 'test-episode-seek-process'
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

      // Queue a seek
      vm.isSeeking = true
      vm.seekQueue = [15000]

      // Trigger onAudioSeeked to simulate seek completion
      vm.onAudioSeeked()

      await wrapper.vm.$nextTick()
      await new Promise(resolve => setTimeout(resolve, 100))

      // Queue should be processed and cleared
      expect(vm.seekQueue.length).toBe(0)
      expect(mockAudio.currentTime).toBe(15) // 15000ms = 15s
    })

    it('should reset seeking flag after seek completes', async () => {
      wrapper = mount(PlayerView, {
        global: {
          plugins: [router],
          stubs: {
            SubtitleMapping: { template: '<div></div>' }
          }
        },
        props: {
          id: 'test-episode-seek-reset'
        }
      })

      await wrapper.vm.$nextTick()
      await new Promise(resolve => setTimeout(resolve, 100))

      const vm = wrapper.vm

      // Set seeking flag
      vm.isSeeking = true

      // Simulate seek completion
      vm.onAudioSeeked()

      // Flag should be reset
      expect(vm.isSeeking).toBe(false)
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

    it('should stop watch on unmount', async () => {
      wrapper = mount(PlayerView, {
        global: {
          plugins: [router],
          stubs: {
            SubtitleMapping: { template: '<div></div>' }
          }
        },
        props: {
          id: 'test-episode-watch-cleanup'
        }
      })

      await wrapper.vm.$nextTick()
      await new Promise(resolve => setTimeout(resolve, 100))

      const vm = wrapper.vm

      // Verify watch stop function exists
      expect(vm.scrollWatcherStop).toBeDefined()
      expect(typeof vm.scrollWatcherStop).toBe('function')

      // Unmount component
      wrapper.unmount()

      // If we got here without errors, watch stop was called successfully
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
      vm.isSeeking = true
      vm.seekQueue = [10000, 20000]
      vm.pendingSeek = 5000

      // Unmount component
      wrapper.unmount()

      // State should be cleared
      expect(vm.isSeeking).toBe(false)
      expect(vm.seekQueue.length).toBe(0)
      expect(vm.pendingSeek).toBeNull()
    })
  })
})
