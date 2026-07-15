/**
 * API 客户端
 */
const API_BASE = '/api'

/**
 * 管理 X-Admin-Token。
 *
 * 当后端配置了 PODCAST_DIGESTER_ADMIN_TOKEN 时（公网部署场景），前端必须
 * 在每个写请求里带上相同 token。把它存在 localStorage 里，避免每次刷新都
 * 重新输入。
 *
 * 通过 setAdminToken(token) 设置（一般在登录/设置 UI 调用）；
 * 通过 clearAdminToken() 清除（登出）。
 */
const ADMIN_TOKEN_KEY = 'podcast_digester_admin_token'

export function getAdminToken() {
  try {
    return localStorage.getItem(ADMIN_TOKEN_KEY) || ''
  } catch {
    // localStorage 在某些隐私模式下会抛错，降级为无 token
    return ''
  }
}

export function setAdminToken(token) {
  try {
    if (token) localStorage.setItem(ADMIN_TOKEN_KEY, token)
    else localStorage.removeItem(ADMIN_TOKEN_KEY)
  } catch {
    // ignore
  }
}

export function clearAdminToken() {
  setAdminToken('')
}

/**
 * 带超时的 fetch 包装。
 * 默认 15s 超时；LLM 等长耗时端点调用方可显式传入更长 timeout。
 * 没有超时的 fetch 在后端 hang 会让 UI 永远转圈，这是排第一的 UX 抱怨。
 *
 * 同时自动注入 X-Admin-Token 头（如果 localStorage 里有），简化调用方。
 */
async function fetchWithTimeout(url, options = {}, timeoutMs = 15000) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  try {
    const token = getAdminToken()
    const headers = { ...(options.headers || {}) }
    if (token && !headers['X-Admin-Token']) {
      headers['X-Admin-Token'] = token
    }
    return await fetch(url, { ...options, headers, signal: controller.signal })
  } catch (err) {
    if (err.name === 'AbortError') {
      throw new Error(`请求超时 (${timeoutMs}ms): ${url}`)
    }
    throw err
  } finally {
    clearTimeout(timer)
  }
}

/**
 * 获取节目列表
 */
export async function listEpisodes() {
  // 该接口被前端轮询调用，超时必须短，否则拖慢整个 UI。
  const res = await fetchWithTimeout(`${API_BASE}/episodes`, {}, 8000)
  if (!res.ok) throw new Error('获取节目列表失败')
  const data = await res.json()
  return data.episodes
}

/**
 * 获取节目详情
 */
export async function fetchEpisode(episodeId) {
  const res = await fetchWithTimeout(`${API_BASE}/episode/${episodeId}`)
  if (!res.ok) throw new Error('获取节目详情失败')
  const data = await res.json()
  return data.episode
}

/**
 * 粘贴新节目
 */
export async function pasteEpisode(rawInput) {
  const res = await fetchWithTimeout(`${API_BASE}/paste`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ raw_input: rawInput }),
  })
  if (!res.ok) throw new Error('粘贴失败')
  const data = await res.json()
  return data.episode
}

/**
 * 删除节目
 */
export async function deleteEpisode(episodeId) {
  const res = await fetchWithTimeout(`${API_BASE}/episode/${episodeId}`, {
    method: 'DELETE',
  })
  if (!res.ok) throw new Error('删除失败')
  const data = await res.json()
  return data
}

/**
 * 取消正在处理的任务
 */
export async function cancelEpisode(episodeId) {
  const res = await fetchWithTimeout(`${API_BASE}/episode/${episodeId}/cancel`, {
    method: 'POST',
  })
  if (!res.ok) throw new Error('取消失败')
  const data = await res.json()
  return data
}

/**
 * 恢复失败的任务
 */
export async function resumeEpisode(episodeId, rawInput = null) {
  // raw_input 为 null 时，后端从 source 表读取原始 URL，前端无需再问用户要链接
  const res = await fetchWithTimeout(`${API_BASE}/episode/${episodeId}/resume`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ raw_input: rawInput }),
  })
  if (!res.ok) {
    const error = await res.json()
    throw new Error(error.detail || '恢复失败')
  }
  const data = await res.json()
  return data
}

/**
 * 标记播放
 */
export async function markPlayed(episodeId, positionMs = null) {
  const res = await fetchWithTimeout(`${API_BASE}/episode/${episodeId}/play`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ position_ms: positionMs }),
  })
  if (!res.ok) throw new Error('标记播放失败')
  return await res.json()
}

/**
 * 获取媒体 URL
 */
export function getMediaUrl(episodeId) {
  return `/media/${episodeId}/audio.mp3`
}

/**
 * 获取 fixture URL
 */
export function getFixtureUrl(fixtureId) {
  return `/fixtures/${fixtureId}/audio.mp3`
}

/**
 * 加载演示 fixture 节目。
 * 占位实现：后端尚无对应端点（POST /api/fixtures/load 或类似），
 * UI 中的 "试用演示数据" 按钮调用本函数时会得到明确错误而不是
 * 静默崩溃。等后端补齐 fixture-seeding 端点后再实现真实逻辑。
 */
export async function loadFixtureEpisode() {
  throw new Error('loadFixtureEpisode 尚未实现：等待后端 fixture-seeding 端点')
}

/**
 * 导出节目摘要
 * @param {string} episodeId - 节目ID
 * @param {string} format - 'html' 或 'png'
 * @param {Object} options - 导出选项
 * @returns {Promise<{download_url: string, format: string, expires_at: string, file_size: number}>}
 */
export async function exportEpisode(episodeId, format = 'html', options = {}) {
  // PNG 导出走 playwright，可能要十几秒；HTML 一般 <1s。给 60s 余量。
  const res = await fetchWithTimeout(`${API_BASE}/episodes/${episodeId}/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      format,
      include_transcript: options.includeTranscript || false,
      theme: options.theme || 'light',
      width: options.width || 1080
    })
  }, 60000)

  if (!res.ok) {
    const error = await res.json()
    throw new Error(error.detail || '导出失败')
  }

  return await res.json()
}

/**
 * 下载导出文件
 * @param {string} url - 下载URL
 * @param {string} filename - 建议的文件名
 */
export async function downloadExport(url, filename) {
  const res = await fetchWithTimeout(url)
  if (!res.ok) throw new Error('下载失败')

  const blob = await res.blob()
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = filename
  link.click()
  URL.revokeObjectURL(link.href)
}

/**
 * 获取节目详情（新版本，包含episode bundle）
 */
export async function getEpisode(episodeId) {
  const res = await fetchWithTimeout(`${API_BASE}/episode/${episodeId}`)
  if (!res.ok) throw new Error('获取节目详情失败')
  const data = await res.json()
  return data
}

/**
 * 获取字幕
 */
export async function getTranscript(episodeId) {
  const res = await fetchWithTimeout(`${API_BASE}/episodes/${episodeId}/transcript`)
  if (!res.ok) throw new Error('获取字幕失败')
  return await res.json()
}

/**
 * 更新字幕segment
 */
export async function updateTranscriptSegment(episodeId, { segment_index, text_original, note_to_glossary }) {
  const res = await fetchWithTimeout(`${API_BASE}/episodes/${episodeId}/segments/update`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ segment_index, text_original, note_to_glossary })
  })
  if (!res.ok) throw new Error('更新字幕失败')
  return await res.json()
}

/**
 * 应用词库纠错
 */
export async function applyGlossary(episodeId) {
  // 词库纠错会扫描所有 segment，大节目可能要十几秒
  const res = await fetchWithTimeout(`${API_BASE}/episodes/${episodeId}/apply-glossary`, {
    method: 'POST'
  }, 60000)
  if (!res.ok) throw new Error('词库纠错失败')
  return await res.json()
}

/**
 * 获取词库
 */
export async function getGlossary() {
  const res = await fetchWithTimeout(`${API_BASE}/glossary/entries`, {
    method: 'POST'
  })
  if (!res.ok) throw new Error('获取词库失败')
  return await res.json()
}

/**
 * 添加词库条目
 *
 * 注意:后端 GlossaryEntry 模型要求 wrong 是 list[str]，
 * 但调用方(如 PlayerView 的词库面板)习惯传单个字符串。
 * 这里统一包装成数组,避免 422 校验错误。
 */
export async function addGlossaryEntry({ correct, wrong }) {
  const wrongs = Array.isArray(wrong) ? wrong : [wrong]
  const res = await fetchWithTimeout(`${API_BASE}/glossary/add`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ correct, wrong: wrongs })
  })
  if (!res.ok) throw new Error('添加词库条目失败')
  return await res.json()
}

/**
 * 删除词库条目
 */
export async function deleteGlossaryEntry(correct) {
  const res = await fetchWithTimeout(`${API_BASE}/glossary/entries/${encodeURIComponent(correct)}`, {
    method: 'DELETE'
  })
  if (!res.ok) throw new Error('删除词库条目失败')
  return await res.json()
}

/**
 * 获取当前 LLM 配置（api_key 掩码）+ provider 预设列表
 * @returns {Promise<{provider,provider_type,base_url,model,has_api_key,api_key_masked,providers}>}
 */
export async function getLlmConfig() {
  const res = await fetchWithTimeout(`${API_BASE}/admin/llm-config`)
  if (!res.ok) throw new Error('获取 LLM 配置失败')
  return await res.json()
}

/**
 * 保存 LLM 配置。未改的字段（如 api_key）不要传。
 * @param {Object} cfg - { provider?, provider_type?, api_key?, base_url?, model? }
 */
export async function saveLlmConfig(cfg) {
  const res = await fetchWithTimeout(`${API_BASE}/admin/llm-config`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(cfg),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.message || '保存失败')
  }
  return await res.json()
}

/**
 * 测试连接（用当前表单值，无需先保存）。
 * @param {Object} cfg - 同 saveLlmConfig
 * @returns {Promise<{ok:boolean, detail:string}>}
 */
export async function testLlmConfig(cfg) {
  // 真实 LLM 调用，给 20s 余量
  const res = await fetchWithTimeout(`${API_BASE}/admin/llm-config/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(cfg),
  }, 20000)
  if (!res.ok) throw new Error('测试请求失败')
  return await res.json()
}
