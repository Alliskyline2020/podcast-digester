import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import SubtitleMapping from '@/components/SubtitleMapping.vue'

describe('SubtitleMapping', () => {
  it('renders segment mapping info', () => {
    const wrapper = mount(SubtitleMapping, {
      props: {
        paragraph: {
          id: 0,
          text_original: "测试段落",
          segment_indices: [0, 1, 2],
          segment_ids: ["seg1", "seg2", "seg3"]
        },
        expanded: false
      }
    })

    expect(wrapper.text()).toContain("3 段原始字幕")
  })

  it('expands to show segment details', async () => {
    const wrapper = mount(SubtitleMapping, {
      props: {
        paragraph: {
          id: 0,
          text_original: "测试",
          segment_indices: [0, 1],
          segment_ids: ["seg1", "seg2"]
        },
        expanded: true
      }
    })

    expect(wrapper.find('.segment-details').exists()).toBe(true)
  })
})
