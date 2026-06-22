<template>
  <div v-if="show" class="token-dialog-overlay" @click.self="$emit('cancel')">
    <div
      class="token-dialog-box"
      role="dialog"
      aria-modal="true"
      aria-labelledby="token-dialog-title"
    >
      <h3 id="token-dialog-title" class="token-dialog-title">
        {{ hasToken ? '管理 Token' : '输入 Admin Token' }}
      </h3>

      <p v-if="!hasToken" class="token-dialog-message">
        后端配置了 <code>PODCAST_DIGESTER_ADMIN_TOKEN</code>，所有写操作需要认证。
        在这里输入服务端配置的同一串 token 即可。Token 存在浏览器 localStorage，
        刷新页面不会丢失。
      </p>
      <p v-else class="token-dialog-message">
        已设置 admin token。如需切换或登出，可在下方操作。
      </p>

      <div class="token-dialog-input-group">
        <label for="token-input">Admin Token</label>
        <input
          id="token-input"
          v-model="inputValue"
          type="password"
          placeholder="粘贴 admin token..."
          class="token-dialog-input"
          :class="{ 'token-dialog-input-error': error }"
          :aria-invalid="!!error"
          :aria-describedby="error ? 'token-error' : undefined"
          autocomplete="off"
          @keyup.enter="save"
          @input="error = ''"
        />
        <p v-if="error" id="token-error" class="token-dialog-error" role="alert">
          {{ error }}
        </p>
      </div>

      <div class="token-dialog-actions">
        <button @click="$emit('cancel')" class="token-dialog-btn token-dialog-btn-cancel">
          取消
        </button>
        <button
          v-if="hasToken"
          @click="logout"
          class="token-dialog-btn token-dialog-btn-logout"
        >
          登出
        </button>
        <button
          @click="save"
          :disabled="!inputValue.trim()"
          class="token-dialog-btn token-dialog-btn-confirm"
        >
          保存
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useAdminAuth } from '@/composables/useAdminAuth'

const props = defineProps({
  show: { type: Boolean, default: false },
})
const emit = defineEmits(['cancel', 'saved', 'cleared'])

const { hasToken, setToken, clearToken } = useAdminAuth()

const inputValue = ref('')
const error = ref('')

// 每次打开时重置输入框 + 错误
watch(
  () => props.show,
  (show) => {
    if (show) {
      inputValue.value = ''
      error.value = ''
    }
  }
)

function save() {
  const trimmed = inputValue.value.trim()
  if (!trimmed) {
    error.value = 'Token 不能为空'
    return
  }
  setToken(trimmed)
  emit('saved', trimmed)
  emit('cancel')
}

function logout() {
  clearToken()
  emit('cleared')
  emit('cancel')
}
</script>

<style scoped>
.token-dialog-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.token-dialog-box {
  background: #ffffff;
  border-radius: 12px;
  padding: 24px;
  max-width: 440px;
  width: calc(100% - 32px);
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.15);
}

.token-dialog-title {
  margin: 0 0 8px;
  font-size: 18px;
  font-weight: 600;
  color: #111827;
}

.token-dialog-message {
  margin: 0 0 16px;
  color: #4b5563;
  font-size: 14px;
  line-height: 1.5;
}

.token-dialog-message code {
  font-family: 'SF Mono', 'Fira Code', monospace;
  font-size: 12px;
  background: #f3f4f6;
  padding: 1px 5px;
  border-radius: 3px;
  word-break: break-all;
}

.token-dialog-input-group {
  margin-bottom: 20px;
}

.token-dialog-input-group label {
  display: block;
  font-size: 13px;
  color: #374151;
  margin-bottom: 6px;
  font-weight: 500;
}

.token-dialog-input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  font-size: 14px;
  font-family: 'SF Mono', 'Fira Code', monospace;
}

.token-dialog-input:focus {
  outline: none;
  border-color: #4f8ef7;
  box-shadow: 0 0 0 3px rgba(79, 142, 247, 0.1);
}

.token-dialog-input-error {
  border-color: #ef4444;
}

.token-dialog-error {
  margin: 6px 0 0;
  color: #dc2626;
  font-size: 13px;
}

.token-dialog-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

.token-dialog-btn {
  padding: 8px 16px;
  border: none;
  border-radius: 6px;
  font-size: 14px;
  cursor: pointer;
  font-weight: 500;
}

.token-dialog-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.token-dialog-btn-cancel {
  background: #f3f4f6;
  color: #4b5563;
}

.token-dialog-btn-cancel:hover {
  background: #e5e7eb;
}

.token-dialog-btn-logout {
  background: #fee2e2;
  color: #991b1b;
}

.token-dialog-btn-logout:hover {
  background: #fecaca;
}

.token-dialog-btn-confirm {
  background: #4f8ef7;
  color: #ffffff;
}

.token-dialog-btn-confirm:hover:not(:disabled) {
  background: #3b7dd6;
}
</style>
