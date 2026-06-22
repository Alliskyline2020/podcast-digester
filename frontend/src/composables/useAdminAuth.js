/**
 * Admin token 响应式状态。
 *
 * api.js 里的 fetchWithTimeout 直接读 localStorage（无响应式），那是底层机制；
 * 这个 composable 给 UI 用：能让组件在 token 变化时自动重渲染，并提供
 * 统一的 set/clear 入口。
 */
import { computed, ref } from 'vue'
import {
  getAdminToken as _getAdminToken,
  setAdminToken as _setAdminToken,
  clearAdminToken as _clearAdminToken,
} from '@/api'

// 模块级单例：所有使用 useAdminAuth() 的组件共享同一份状态
const tokenRef = ref(_getAdminToken())

export function useAdminAuth() {
  const hasToken = computed(() => !!tokenRef.value)

  /**
   * 保存 token（同时写入 localStorage 和响应式状态）。
   * @param {string} token
   */
  function setToken(token) {
    const trimmed = (token || '').trim()
    _setAdminToken(trimmed)
    tokenRef.value = trimmed
  }

  /** 清除 token（登出）。 */
  function clearToken() {
    _clearAdminToken()
    tokenRef.value = ''
  }

  return {
    token: tokenRef, // Ref<string>，组件可直接 v-model
    hasToken,
    setToken,
    clearToken,
  }
}
