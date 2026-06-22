import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { defineComponent, h } from 'vue'
import { mount, unmount } from '@vue/test-utils'
import { useKeyboardShortcuts } from '@/composables/useKeyboardShortcuts'

/**
 * 因为 useKeyboardShortcuts 在 onMounted/onUnmounted 里 add/remove listener，
 * 必须在真实组件上下文里测试。
 */
function makeWrapper(handlers) {
  return defineComponent({
    name: 'TestHost',
    setup() {
      useKeyboardShortcuts(handlers)
      return () => h('div')
    },
  })
}

function dispatchKey(key, target = document.body) {
  const event = new KeyboardEvent('keydown', { key, bubbles: true })
  Object.defineProperty(event, 'target', { value: target, configurable: true })
  window.dispatchEvent(event)
}

describe('useKeyboardShortcuts', () => {
  let wrapper

  afterEach(() => {
    if (wrapper) {
      wrapper.unmount()
      wrapper = null
    }
  })

  it('binds keydown on mount', () => {
    const addSpy = vi.spyOn(window, 'addEventListener')
    wrapper = mount(makeWrapper({ onSpace: () => {}, onSeek: () => {}, onChapter: () => {} }))
    expect(addSpy).toHaveBeenCalledWith('keydown', expect.any(Function))
    addSpy.mockRestore()
  })

  it('removes keydown on unmount', () => {
    const removeSpy = vi.spyOn(window, 'removeEventListener')
    wrapper = mount(makeWrapper({ onSpace: () => {} }))
    wrapper.unmount()
    wrapper = null
    expect(removeSpy).toHaveBeenCalledWith('keydown', expect.any(Function))
    removeSpy.mockRestore()
  })

  it.each([
    [' ', 'onSpace', []],
    ['ArrowLeft', 'onSeek', [-5]],
    ['ArrowRight', 'onSeek', [5]],
    ['j', 'onChapter', [-1]],
    ['k', 'onChapter', [1]],
  ])('dispatches %s to %s with args %j', (key, handler, expectedArgs) => {
    const handlers = {
      onSpace: vi.fn(),
      onSeek: vi.fn(),
      onChapter: vi.fn(),
    }
    wrapper = mount(makeWrapper(handlers))
    dispatchKey(key)
    expect(handlers[handler]).toHaveBeenCalledTimes(1)
    expect(handlers[handler]).toHaveBeenCalledWith(...expectedArgs)
  })

  it('does not dispatch when target is INPUT', () => {
    const handlers = { onSpace: vi.fn() }
    wrapper = mount(makeWrapper(handlers))
    const input = document.createElement('input')
    document.body.appendChild(input)
    dispatchKey(' ', input)
    expect(handlers.onSpace).not.toHaveBeenCalled()
    document.body.removeChild(input)
  })

  it('does not dispatch when target is TEXTAREA', () => {
    const handlers = { onSeek: vi.fn() }
    wrapper = mount(makeWrapper(handlers))
    const textarea = document.createElement('textarea')
    document.body.appendChild(textarea)
    dispatchKey('ArrowLeft', textarea)
    expect(handlers.onSeek).not.toHaveBeenCalled()
    document.body.removeChild(textarea)
  })

  it('does not react to unmapped keys', () => {
    const handlers = {
      onSpace: vi.fn(),
      onSeek: vi.fn(),
      onChapter: vi.fn(),
    }
    wrapper = mount(makeWrapper(handlers))
    dispatchKey('Enter')
    dispatchKey('a')
    dispatchKey('Escape')
    expect(handlers.onSpace).not.toHaveBeenCalled()
    expect(handlers.onSeek).not.toHaveBeenCalled()
    expect(handlers.onChapter).not.toHaveBeenCalled()
  })

  it('tolerates missing handlers (no-op)', () => {
    wrapper = mount(makeWrapper({ onSpace: undefined, onSeek: undefined, onChapter: undefined }))
    // 不应该抛错
    expect(() => dispatchKey(' ')).not.toThrow()
    expect(() => dispatchKey('ArrowRight')).not.toThrow()
    expect(() => dispatchKey('k')).not.toThrow()
  })
})
