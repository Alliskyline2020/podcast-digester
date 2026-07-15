<template>
  <div class="settings-view">
    <header class="settings-header">
      <button @click="goBack" class="icon-btn" title="返回">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M19 12H5M12 19l-7-7 7-7"/>
        </svg>
      </button>
      <h1 class="settings-title">LLM API 设置</h1>
    </header>

    <div v-if="loadError" class="error-message" role="alert">{{ loadError }}</div>

    <section v-if="loaded" class="settings-form">
      <div class="field">
        <label for="provider">Provider</label>
        <select id="provider" v-model="form.provider" @change="onProviderChange">
          <option v-for="(p, key) in providers" :key="key" :value="key">{{ p.title || key }}</option>
        </select>
      </div>

      <div class="field">
        <label for="api-key">API Key</label>
        <input
          id="api-key" data-test="api-key"
          v-model="form.api_key" :type="showKey ? 'text' : 'password'"
          @input="onKeyInput"
          :placeholder="hasKey ? '已保存（如需更换请在此输入新 key）' : '粘贴你的 API Key...'"
          autocomplete="off"
        />
        <button type="button" class="toggle-btn" @click="showKey = !showKey" :title="showKey ? '隐藏' : '显示'">
          {{ showKey ? '🙈' : '👁' }}
        </button>
        <p v-if="hasKey && !form.api_key" data-test="key-status" class="hint">
          当前已保存：<code>{{ maskedKey }}</code>（留空保存即不改动）
        </p>
        <p v-else data-test="key-status" class="hint">尚未保存 Key</p>
      </div>

      <div class="field">
        <label for="base-url">API 链接（base_url）</label>
        <select v-if="!baseUrlEditable" id="base-url" data-test="base-url" v-model="form.base_url">
          <option v-for="u in baseUrlOptions" :key="u" :value="u">{{ u }}</option>
        </select>
        <input v-else id="base-url" data-test="base-url" v-model="form.base_url"
               placeholder="https://your-endpoint/v1" />
      </div>

      <div class="field">
        <label for="model">模型</label>
        <div class="model-row">
          <select v-if="!manualModel && modelOptions.length" id="model" data-test="model"
                  v-model="form.model" :disabled="fetchingModels">
            <option v-for="m in modelOptions" :key="m" :value="m">{{ m }}</option>
          </select>
          <input v-else id="model" data-test="model" v-model="form.model"
                 :placeholder="fetchModelsError ? '手动输入模型名…' : '如 deepseek-chat'" />
          <button type="button" class="fetch-btn" data-test="fetch-models"
                  @click="fetchModels" :disabled="!canFetchModels || fetchingModels"
                  :title="canFetchModels ? '拉取模型列表' : '先填好 provider / key / base_url'">
            {{ fetchingModels ? '…' : '↻ 拉取' }}
          </button>
        </div>
        <p v-if="fetchingModels" data-test="fetch-status" class="hint">拉取模型中…</p>
        <p v-else-if="fetchModelsError" data-test="fetch-status" class="hint">{{ fetchModelsError }}</p>
      </div>

      <div class="actions">
        <button data-test="test" @click="onTest" :disabled="testing">
          {{ testing ? '测试中...' : '测试连接' }}
        </button>
        <button class="primary" data-test="save" @click="onSave" :disabled="saving">
          {{ saving ? '保存中...' : '保存' }}
        </button>
      </div>

      <p v-if="testResult" data-test="test-result"
         class="test-result" :class="testResult.ok ? 'ok' : 'fail'">
        {{ testResult.ok ? '✅' : '❌' }} {{ testResult.detail }}
      </p>
      <p v-if="saveMsg" class="test-result ok">{{ saveMsg }}</p>
      <p v-if="saveError" class="test-result fail">{{ saveError }}</p>
    </section>
  </div>
</template>

<script setup>
import { reactive, ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { getLlmConfig, saveLlmConfig, testLlmConfig, listLlmModels } from '@/api'

const router = useRouter()

const loaded = ref(false)
const loadError = ref('')
const providers = ref({})
const hasKey = ref(false)
const maskedKey = ref('')

const form = reactive({ provider: 'deepseek', api_key: '', base_url: '', model: '' })
const showKey = ref(false)

// base_url 锁定下拉状态
const baseUrlOptions = ref([])
const baseUrlEditable = ref(false)
// 模型自动拉取状态
const modelOptions = ref([])
const fetchingModels = ref(false)
const fetchModelsError = ref('')
const manualModel = ref(false)

const testing = ref(false)
const testResult = ref(null)
const saving = ref(false)
const saveMsg = ref('')
const saveError = ref('')

let fetchTimer = null
onUnmounted(() => { if (fetchTimer) clearTimeout(fetchTimer) })

const canFetchModels = computed(() =>
  !!form.provider && !!form.base_url && (!!form.api_key.trim() || hasKey.value)
)

function goBack() {
  if (window.history.length > 1) router.back()
  else router.push('/')
}

function applyProviderBaseUrls() {
  const p = providers.value[form.provider] || {}
  baseUrlOptions.value = p.base_urls || []
  // 缺 base_url_editable 字段时:无锁定列表即视为可自由输入
  baseUrlEditable.value = p.base_url_editable ?? baseUrlOptions.value.length === 0
  if (baseUrlEditable.value) {
    if (!form.base_url) form.base_url = p.default_base_url || ''
  } else if (!baseUrlOptions.value.includes(form.base_url)) {
    form.base_url = baseUrlOptions.value[0] || ''
  }
}

function onProviderChange() {
  const p = providers.value[form.provider] || {}
  applyProviderBaseUrls()
  if (!form.model) form.model = p.default_model || ''
  modelOptions.value = []
  fetchModelsError.value = ''
  manualModel.value = false
  if (canFetchModels.value) fetchModels()
}

function onKeyInput() {
  // 输入 key 时防抖拉取(对应「填前三项后自动拉取」)
  if (fetchTimer) clearTimeout(fetchTimer)
  fetchTimer = setTimeout(() => { fetchModels() }, 400)
}

async function load() {
  try {
    const cfg = await getLlmConfig()
    providers.value = cfg.providers || {}
    form.provider = cfg.provider || 'deepseek'
    form.base_url = cfg.base_url || ''
    form.model = cfg.model || ''
    hasKey.value = !!cfg.has_api_key
    maskedKey.value = cfg.api_key_masked || ''
    form.api_key = ''  // 永不预填真实 key;留空 = 不改
    applyProviderBaseUrls()
    loaded.value = true
    if (canFetchModels.value) fetchModels()  // 进入页若三项齐全,自动拉一次
  } catch (e) {
    loadError.value = e.message || '加载配置失败'
    loaded.value = true
  }
}

/** 构造提交体(保存/测试用):只含非空字段;api_key 留空不发。 */
function buildPayload({ includeKeyIfAny }) {
  const body = {}
  if (form.provider) body.provider = form.provider
  if (form.base_url) body.base_url = form.base_url
  if (form.model) body.model = form.model
  if (includeKeyIfAny && form.api_key.trim()) body.api_key = form.api_key.trim()
  return body
}

/** 构造模型拉取请求体:带 provider_type 让后端选对 adapter;空 key 不发(后端用已保存值)。 */
function buildModelsPayload() {
  const body = { provider: form.provider, base_url: form.base_url }
  if (form.api_key.trim()) body.api_key = form.api_key.trim()
  const p = providers.value[form.provider]
  if (p && p.provider_type) body.provider_type = p.provider_type
  return body
}

async function fetchModels() {
  if (!canFetchModels.value) return
  fetchingModels.value = true
  fetchModelsError.value = ''
  try {
    const res = await listLlmModels(buildModelsPayload())
    if (res.ok && Array.isArray(res.models) && res.models.length) {
      modelOptions.value = res.models
      manualModel.value = false
      if (!modelOptions.value.includes(form.model)) form.model = modelOptions.value[0]
    } else {
      modelOptions.value = []
      fetchModelsError.value = (res && res.detail) || '该端点未返回模型列表,可手动输入'
      manualModel.value = true
    }
  } catch (e) {
    modelOptions.value = []
    fetchModelsError.value = e.message || '拉取失败,可手动输入'
    manualModel.value = true
  } finally {
    fetchingModels.value = false
  }
}

async function onTest() {
  testing.value = true
  testResult.value = null
  try {
    testResult.value = await testLlmConfig(buildPayload({ includeKeyIfAny: true }))
  } catch (e) {
    testResult.value = { ok: false, detail: e.message || '测试失败' }
  } finally {
    testing.value = false
  }
}

async function onSave() {
  saving.value = true
  saveMsg.value = ''
  saveError.value = ''
  try {
    await saveLlmConfig(buildPayload({ includeKeyIfAny: true }))
    saveMsg.value = '已保存。下一次处理播客即生效(API 与 Worker 均立即生效)。'
    hasKey.value = hasKey.value || !!form.api_key.trim()
    form.api_key = ''
    showKey.value = false
    await load()
  } catch (e) {
    saveError.value = e.message || '保存失败'
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.settings-view {
  max-width: 640px;
  margin: 0 auto;
  padding: 24px 20px 64px;
}
.settings-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
}
.settings-title {
  font-size: 20px;
  font-weight: 600;
  color: #1f2937;
}
.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px; height: 36px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
  color: #4b5563;
  cursor: pointer;
}
.icon-btn:hover { border-color: #d1d5db; }
.settings-form {
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
  position: relative;
}
.field label {
  font-size: 14px;
  font-weight: 500;
  color: #374151;
}
.field input, .field select {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  font-size: 14px;
  font-family: 'SF Mono', 'Fira Code', monospace;
  background: #fff;
}
.field input:focus, .field select:focus {
  outline: none;
  border-color: #4f8ef7;
  box-shadow: 0 0 0 3px rgba(79, 142, 247, 0.1);
}
.toggle-btn {
  position: absolute;
  right: 8px;
  bottom: 30px;
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 16px;
}
.hint {
  font-size: 12px;
  color: #6b7280;
}
.hint code {
  font-family: 'SF Mono', monospace;
  background: #f3f4f6;
  padding: 1px 5px;
  border-radius: 4px;
}
.actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
}
.actions button {
  padding: 9px 18px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  background: #fff;
  color: #374151;
}
.actions button:disabled { opacity: 0.5; cursor: not-allowed; }
.actions button.primary {
  background: #4f8ef7;
  border-color: #4f8ef7;
  color: #fff;
}
.test-result {
  font-size: 13px;
  padding: 8px 12px;
  border-radius: 8px;
}
.test-result.ok { background: #ecfdf5; color: #065f46; }
.test-result.fail { background: #fee2e2; color: #991b1b; }
.error-message {
  color: #991b1b;
  background: #fee2e2;
  padding: 10px 12px;
  border-radius: 8px;
  margin-bottom: 12px;
}
.model-row {
  display: flex;
  gap: 8px;
  align-items: stretch;
}
.model-row select, .model-row input {
  flex: 1;
}
.fetch-btn {
  padding: 0 14px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  background: #fff;
  color: #374151;
  white-space: nowrap;
}
.fetch-btn:hover:not(:disabled) { border-color: #4f8ef7; color: #4f8ef7; }
.fetch-btn:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
