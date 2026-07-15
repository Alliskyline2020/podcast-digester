import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import SettingsView from '@/views/SettingsView.vue'

const mockGetLlmConfig = vi.fn()
const mockSaveLlmConfig = vi.fn()
const mockTestLlmConfig = vi.fn()

vi.mock('@/api', () => ({
  getLlmConfig: () => mockGetLlmConfig(),
  saveLlmConfig: (cfg) => mockSaveLlmConfig(cfg),
  testLlmConfig: (cfg) => mockTestLlmConfig(cfg),
}))

function makeRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/settings', name: 'settings', component: SettingsView },
      { path: '/', name: 'library', component: { template: '<div/>' } },
    ],
  })
}

describe('SettingsView', () => {
  beforeEach(() => {
    mockGetLlmConfig.mockReset()
    mockSaveLlmConfig.mockReset()
    mockTestLlmConfig.mockReset()
  })

  it('loads current config and masks the key', async () => {
    mockGetLlmConfig.mockResolvedValue({
      provider: 'deepseek', provider_type: 'openai_compatible',
      base_url: 'https://api.deepseek.com', model: 'deepseek-chat',
      has_api_key: true, api_key_masked: '****1234',
      providers: { deepseek: { title: 'DeepSeek', provider_type: 'openai_compatible',
        default_base_url: 'https://api.deepseek.com', default_model: 'deepseek-chat' } },
    })
    const router = makeRouter()
    router.push('/settings')
    await router.isReady()
    const w = mount(SettingsView, { global: { plugins: [router] } })
    await flushPromises()
    expect(w.find('select').element.value).toBe('deepseek')
    expect(w.find('[data-test="base-url"]').element.value).toBe('https://api.deepseek.com')
    expect(w.find('[data-test="key-status"]').text()).toContain('****1234')
  })

  it('save posts only changed fields (no api_key when untouched)', async () => {
    mockGetLlmConfig.mockResolvedValue({
      provider: 'deepseek', provider_type: 'openai_compatible',
      base_url: 'https://api.deepseek.com', model: 'deepseek-chat',
      has_api_key: true, api_key_masked: '****1234', providers: {},
    })
    mockSaveLlmConfig.mockResolvedValue({ ok: true })
    const router = makeRouter()
    router.push('/settings'); await router.isReady()
    const w = mount(SettingsView, { global: { plugins: [router] } })
    await flushPromises()
    await w.find('[data-test="save"]').trigger('click')
    await flushPromises()
    expect(mockSaveLlmConfig).toHaveBeenCalledTimes(1)
    const sent = mockSaveLlmConfig.mock.calls[0][0]
    expect(sent.api_key).toBeUndefined()       // 未改 key，不发
    expect(sent.provider).toBe('deepseek')
  })

  it('test calls testLlmConfig and shows the result', async () => {
    mockGetLlmConfig.mockResolvedValue({
      provider: 'deepseek', provider_type: 'openai_compatible',
      base_url: 'https://api.deepseek.com', model: 'deepseek-chat',
      has_api_key: false, api_key_masked: '', providers: {},
    })
    mockTestLlmConfig.mockResolvedValue({ ok: true, detail: '连通（模型 deepseek-chat）' })
    const router = makeRouter()
    router.push('/settings'); await router.isReady()
    const w = mount(SettingsView, { global: { plugins: [router] } })
    await flushPromises()
    // 填一个 key
    await w.find('[data-test="api-key"]').setValue('sk-test-1234')
    await w.find('[data-test="test"]').trigger('click')
    await flushPromises()
    expect(mockTestLlmConfig).toHaveBeenCalledTimes(1)
    expect(w.find('[data-test="test-result"]').text()).toContain('连通')
  })
})
