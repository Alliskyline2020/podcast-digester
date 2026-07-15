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
        <input id="base-url" data-test="base-url" v-model="form.base_url"
               placeholder="留空使用官方默认端点" />
      </div>

      <div class="field">
        <label for="model">模型</label>
        <input id="model" data-test="model" v-model="form.model" placeholder="如 deepseek-chat" />
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
import { reactive, ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { getLlmConfig, saveLlmConfig, testLlmConfig } from '@/api'

const router = useRouter()

const loaded = ref(false)
const loadError = ref('')
const providers = ref({})
const hasKey = ref(false)
const maskedKey = ref('')

const form = reactive({ provider: 'deepseek', api_key: '', base_url: '', model: '' })
const showKey = ref(false)

const testing = ref(false)
const testResult = ref(null)
const saving = ref(false)
const saveMsg = ref('')
const saveError = ref('')

function goBack() {
  if (window.history.length > 1) router.back()
  else router.push('/')
}

function onProviderChange() {
  const p = providers.value[form.provider]
  if (!p) return
  // 仅在用户未自定义时填入预设默认，避免覆盖已有改动
  if (!form.base_url) form.base_url = p.default_base_url || ''
  if (!form.model) form.model = p.default_model || ''
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
    form.api_key = ''  // 永不预填真实 key；留空 = 不改
    loaded.value = true
  } catch (e) {
    loadError.value = e.message || '加载配置失败'
    loaded.value = true
  }
}

/** 构造提交体：只包含有意义的字段。api_key 留空则不发（保留旧值）。 */
function buildPayload({ includeKeyIfAny }) {
  const body = {}
  if (form.provider) body.provider = form.provider
  if (form.base_url) body.base_url = form.base_url
  if (form.model) body.model = form.model
  if (includeKeyIfAny && form.api_key.trim()) body.api_key = form.api_key.trim()
  return body
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
    saveMsg.value = '已保存。下一次处理播客即生效（API 与 Worker 均立即生效）。'
    // 保存后刷新掩码状态
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
</style>
