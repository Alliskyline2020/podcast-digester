import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createRouter, createMemoryHistory } from 'vue-router'
import SettingsView from '@/views/SettingsView.vue'

const mockGetLlmConfig = vi.fn()
const mockSaveLlmConfig = vi.fn()
const mockTestLlmConfig = vi.fn()
const mockListLlmModels = vi.fn()

vi.mock('@/api', () => ({
  getLlmConfig: () => mockGetLlmConfig(),
  saveLlmConfig: (cfg) => mockSaveLlmConfig(cfg),
  testLlmConfig: (cfg) => mockTestLlmConfig(cfg),
  listLlmModels: (cfg) => mockListLlmModels(cfg),
}))

function deepseekProviders(overrides = {}) {
  return {
    deepseek: Object.assign({
      title: 'DeepSeek', provider_type: 'openai_compatible',
      default_base_url: 'https://api.deepseek.com',
      base_urls: ['https://api.deepseek.com'],
      base_url_editable: false, default_model: 'deepseek-chat',
    }, overrides),
  }
}

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
  let wrapper

  beforeEach(() => {
    mockGetLlmConfig.mockReset()
    mockSaveLlmConfig.mockReset()
    mockTestLlmConfig.mockReset()
    mockListLlmModels.mockReset()
    // 默认无害返回,避免任何意外拉取污染断言
    mockListLlmModels.mockResolvedValue({ ok: false, detail: '' })
  })
  afterEach(() => { wrapper?.unmount(); wrapper = undefined })

  async function mountView(getCfg) {
    mockGetLlmConfig.mockResolvedValue(getCfg)
    const router = makeRouter()
    router.push('/settings'); await router.isReady()
    wrapper = mount(SettingsView, { global: { plugins: [router] } })
    await flushPromises()
    await flushPromises()
    return wrapper
  }

  it('masks the saved key and locks base_url to a select for deepseek', async () => {
    const w = await mountView({
      provider: 'deepseek', provider_type: 'openai_compatible',
      base_url: 'https://api.deepseek.com', model: 'deepseek-chat',
      has_api_key: true, api_key_masked: '****1234', providers: deepseekProviders(),
    })
    expect(w.find('[data-test="key-status"]').text()).toContain('****1234')
    const base = w.find('[data-test="base-url"]')
    expect(base.element.tagName).toBe('SELECT')
    expect(base.element.value).toBe('https://api.deepseek.com')
    expect(base.findAll('option').length).toBe(1)
  })

  it('save posts only changed fields (no api_key when untouched)', async () => {
    const w = await mountView({
      provider: 'deepseek', provider_type: 'openai_compatible',
      base_url: 'https://api.deepseek.com', model: 'deepseek-chat',
      has_api_key: true, api_key_masked: '****1234', providers: deepseekProviders(),
    })
    mockSaveLlmConfig.mockResolvedValue({ ok: true })
    await w.find('[data-test="save"]').trigger('click')
    await flushPromises()
    expect(mockSaveLlmConfig).toHaveBeenCalledTimes(1)
    const sent = mockSaveLlmConfig.mock.calls[0][0]
    expect(sent.api_key).toBeUndefined()
    expect(sent.provider).toBe('deepseek')
  })

  it('test calls testLlmConfig and shows the result', async () => {
    const w = await mountView({
      provider: 'deepseek', provider_type: 'openai_compatible',
      base_url: 'https://api.deepseek.com', model: 'deepseek-chat',
      has_api_key: false, api_key_masked: '', providers: deepseekProviders(),
    })
    mockTestLlmConfig.mockResolvedValue({ ok: true, detail: '连通(模型 deepseek-chat)' })
    await w.find('[data-test="api-key"]').setValue('sk-test-1234')
    await w.find('[data-test="test"]').trigger('click')
    await flushPromises()
    expect(mockTestLlmConfig).toHaveBeenCalledTimes(1)
    expect(w.find('[data-test="test-result"]').text()).toContain('连通')
  })

  it('renders glm coding endpoint as a second base_url option', async () => {
    const w = await mountView({
      provider: 'glm', provider_type: 'openai_compatible',
      base_url: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-4-flash',
      has_api_key: false, api_key_masked: '',
      providers: { glm: {
        title: '智谱 GLM', provider_type: 'openai_compatible',
        default_base_url: 'https://open.bigmodel.cn/api/paas/v4',
        base_urls: ['https://open.bigmodel.cn/api/paas/v4', 'https://open.bigmodel.cn/api/coding/paas/v4'],
        base_url_editable: false, default_model: 'glm-4-flash',
      } },
    })
    const base = w.find('[data-test="base-url"]')
    expect(base.element.tagName).toBe('SELECT')
    expect(base.findAll('option').length).toBe(2)
  })

  it('renders free-text input for compatible providers', async () => {
    const w = await mountView({
      provider: 'openai-compatible', provider_type: 'openai_compatible',
      base_url: 'https://my-proxy.local/v1', model: 'gpt-4o',
      has_api_key: true, api_key_masked: '****9999',
      providers: { 'openai-compatible': {
        title: 'OpenAI 兼容(自定义端点)', provider_type: 'openai_compatible',
        default_base_url: '', base_urls: [], base_url_editable: true, default_model: '',
      } },
    })
    const base = w.find('[data-test="base-url"]')
    expect(base.element.tagName).toBe('INPUT')
    expect(base.element.value).toBe('https://my-proxy.local/v1')
  })

  it('auto-fetches models on load when provider+key+base_url ready', async () => {
    mockListLlmModels.mockResolvedValue({ ok: true, models: ['deepseek-chat', 'deepseek-reasoner'] })
    const w = await mountView({
      provider: 'deepseek', provider_type: 'openai_compatible',
      base_url: 'https://api.deepseek.com', model: 'deepseek-chat',
      has_api_key: true, api_key_masked: '****1234', providers: deepseekProviders(),
    })
    expect(mockListLlmModels).toHaveBeenCalledTimes(1)
    const model = w.find('[data-test="model"]')
    expect(model.element.tagName).toBe('SELECT')
    expect(model.findAll('option').length).toBe(2)
  })

  it('manual fetch button populates the model select', async () => {
    mockListLlmModels.mockResolvedValue({ ok: true, models: ['deepseek-chat', 'deepseek-reasoner'] })
    const w = await mountView({
      provider: 'deepseek', provider_type: 'openai_compatible',
      base_url: 'https://api.deepseek.com', model: 'deepseek-chat',
      has_api_key: false, api_key_masked: '', providers: deepseekProviders(),
    })
    // 初始 hasKey=false -> 不自动拉取;手动填 key 后点「↻ 拉取」
    mockListLlmModels.mockClear()
    await w.find('[data-test="api-key"]').setValue('sk-test-1234')
    await w.find('[data-test="fetch-models"]').trigger('click')
    await flushPromises(); await flushPromises()
    expect(mockListLlmModels).toHaveBeenCalledTimes(1)
    const model = w.find('[data-test="model"]')
    expect(model.element.tagName).toBe('SELECT')
    expect(model.findAll('option').length).toBe(2)
  })

  it('falls back to manual input when fetch fails', async () => {
    mockListLlmModels.mockResolvedValue({ ok: false, detail: 'API Key 无效或未授权(401)' })
    const w = await mountView({
      provider: 'deepseek', provider_type: 'openai_compatible',
      base_url: 'https://api.deepseek.com', model: '',
      has_api_key: true, api_key_masked: '****1234', providers: deepseekProviders(),
    })
    await w.find('[data-test="fetch-models"]').trigger('click')
    await flushPromises(); await flushPromises()
    expect(w.find('[data-test="fetch-status"]').text()).toContain('API Key')
    expect(w.find('[data-test="model"]').element.tagName).toBe('INPUT')
  })
})
