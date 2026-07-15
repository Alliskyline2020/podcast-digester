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
      base_url_editable: false, default_model: 'deepseek-chat', region: '国内',
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

  it('masks the saved key and shows locked base_url read-only for deepseek', async () => {
    const w = await mountView({
      provider: 'deepseek', provider_type: 'openai_compatible',
      base_url: 'https://api.deepseek.com', model: 'deepseek-chat',
      has_api_key: true, api_key_masked: '****1234', providers: deepseekProviders(),
    })
    expect(w.find('[data-test="key-status"]').text()).toContain('****1234')
    const base = w.find('[data-test="base-url"]')
    expect(base.element.tagName).toBe('INPUT')
    expect(base.element.value).toBe('https://api.deepseek.com')
    expect(base.element.readOnly).toBe(true)   // 锁定：只读
    expect(w.find('[data-test="base-url-locked"]').exists()).toBe(true)
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

  it('lists GLM and GLM Coding Plan as separate providers with their own locked url', async () => {
    const w = await mountView({
      provider: 'glm-coding', provider_type: 'openai_compatible',
      base_url: 'https://open.bigmodel.cn/api/coding/paas/v4', model: '',
      has_api_key: false, api_key_masked: '',
      providers: {
        glm: {
          title: '智谱 GLM', provider_type: 'openai_compatible',
          default_base_url: 'https://open.bigmodel.cn/api/paas/v4',
          base_url_editable: false, default_model: 'glm-4-flash', region: '国内',
        },
        'glm-coding': {
          title: '智谱 GLM Coding Plan', provider_type: 'openai_compatible',
          default_base_url: 'https://open.bigmodel.cn/api/coding/paas/v4',
          base_url_editable: false, default_model: '', region: '国内',
        },
      },
    })
    // Provider 下拉里两个独立项都在
    const provOptions = w.find('#provider').findAll('option').map(o => o.text())
    expect(provOptions).toContain('智谱 GLM')
    expect(provOptions).toContain('智谱 GLM Coding Plan')
    // 选 Coding Plan 时，base_url 锁定到 coding 端点（只读）
    const base = w.find('[data-test="base-url"]')
    expect(base.element.tagName).toBe('INPUT')
    expect(base.element.readOnly).toBe(true)
    expect(base.element.value).toBe('https://open.bigmodel.cn/api/coding/paas/v4')
  })

  it('renders free-text input for compatible providers', async () => {
    const w = await mountView({
      provider: 'openai-compatible', provider_type: 'openai_compatible',
      base_url: 'https://my-proxy.local/v1', model: 'gpt-4o',
      has_api_key: true, api_key_masked: '****9999',
      providers: { 'openai-compatible': {
        title: 'OpenAI 兼容(自定义端点)', provider_type: 'openai_compatible',
        default_base_url: '', base_url_editable: true, default_model: '', region: '',
      } },
    })
    const base = w.find('[data-test="base-url"]')
    expect(base.element.tagName).toBe('INPUT')
    expect(base.element.readOnly).toBe(false)   // 可编辑
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

  // ==================== 区域选择器（国内/国际）====================

  function fullProviders() {
    return {
      deepseek: { title: 'DeepSeek', provider_type: 'openai_compatible', default_base_url: 'https://api.deepseek.com', base_url_editable: false, default_model: 'deepseek-chat', region: '国内' },
      openai: { title: 'OpenAI', provider_type: 'openai_compatible', default_base_url: 'https://api.openai.com/v1', base_url_editable: false, default_model: 'gpt-4o-mini', region: '国际' },
      glm: { title: '智谱 GLM', provider_type: 'openai_compatible', default_base_url: 'https://open.bigmodel.cn/api/paas/v4', base_url_editable: false, default_model: 'glm-4-flash', region: '国内' },
      'glm-coding': { title: '智谱 GLM Coding Plan', provider_type: 'openai_compatible', default_base_url: 'https://open.bigmodel.cn/api/coding/paas/v4', base_url_editable: false, default_model: '', region: '国内' },
      'openai-compatible': { title: 'OpenAI 兼容(自定义端点)', provider_type: 'openai_compatible', default_base_url: '', base_url_editable: true, default_model: '', region: '' },
    }
  }

  it('renders a 国内/国际 region switch with two radios', async () => {
    const w = await mountView({
      provider: 'deepseek', provider_type: 'openai_compatible',
      base_url: 'https://api.deepseek.com', model: 'deepseek-chat',
      has_api_key: true, api_key_masked: '****1234', providers: fullProviders(),
    })
    const radios = w.findAll('.region-switch input[type="radio"]')
    expect(radios.length).toBe(2)
    expect(radios.map(r => r.element.value)).toEqual(expect.arrayContaining(['国内', '国际']))
  })

  it('国内 lists domestic vendors and compat; 国际 lists overseas and compat', async () => {
    const w = await mountView({
      provider: 'deepseek', provider_type: 'openai_compatible',
      base_url: 'https://api.deepseek.com', model: 'deepseek-chat',
      has_api_key: true, api_key_masked: '****1234', providers: fullProviders(),
    })
    let opts = w.find('#provider').findAll('option').map(o => o.text())
    expect(opts).toContain('DeepSeek')
    expect(opts).toContain('智谱 GLM Coding Plan')
    expect(opts).not.toContain('OpenAI')             // 国际厂商不在国内列表
    expect(opts).toContain('OpenAI 兼容(自定义端点)')  // 兼容常驻

    // 切到国际
    await w.find('.region-switch input[value="国际"]').setValue()
    await flushPromises()
    opts = w.find('#provider').findAll('option').map(o => o.text())
    expect(opts).toContain('OpenAI')
    expect(opts).not.toContain('DeepSeek')           // 国内厂商被滤掉
    expect(opts).toContain('OpenAI 兼容(自定义端点)')  // 兼容仍常驻
  })

  it('switching region resets provider to first vendor of new region', async () => {
    const w = await mountView({
      provider: 'deepseek', provider_type: 'openai_compatible',
      base_url: 'https://api.deepseek.com', model: 'deepseek-chat',
      has_api_key: true, api_key_masked: '****1234', providers: fullProviders(),
    })
    await w.find('.region-switch input[value="国际"]').setValue()
    await flushPromises()
    // 切到国际后 provider 重置为 openai，base_url 随之变成 openai 锁定端点
    // （jsdom 对动态 optgroup 的 select.value 反射不可靠，改测 base_url 更稳且更有意义）
    expect(w.find('[data-test="base-url"]').element.value).toBe('https://api.openai.com/v1')
  })

  it('derives region from saved provider on load', async () => {
    const w = await mountView({
      provider: 'openai', provider_type: 'openai_compatible',
      base_url: 'https://api.openai.com/v1', model: 'gpt-4o-mini',
      has_api_key: true, api_key_masked: '****9999', providers: fullProviders(),
    })
    const checked = w.findAll('.region-switch input[type="radio"]')
      .filter(r => r.element.checked).map(r => r.element.value)
    expect(checked).toEqual(['国际'])
  })

  it('defaults region to 国内 when saved provider is compat and keeps provider', async () => {
    const w = await mountView({
      provider: 'openai-compatible', provider_type: 'openai_compatible',
      base_url: 'https://my-proxy/v1', model: 'gpt-4o',
      has_api_key: true, api_key_masked: '****1', providers: fullProviders(),
    })
    const checked = w.findAll('.region-switch input[type="radio"]')
      .filter(r => r.element.checked).map(r => r.element.value)
    expect(checked).toEqual(['国内'])
    expect(w.find('#provider').element.value).toBe('openai-compatible')
  })
})
