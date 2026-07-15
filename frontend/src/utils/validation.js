/**
 * 用户输入校验助手。
 *
 * 用于 LibraryView 的 paste/resume 表单。后端在 utils/validation.py 也有对应逻辑，
 * 这里只做客户端快速反馈，不替代服务端校验。
 */

/** 后端硬限制（models.py PasteRequest.raw_input max_length） */
export const MAX_INPUT_LENGTH = 2000

/**
 * 支持的源：
 * - YouTube / Bilibili / 抖音 / 小宇宙 URL
 * - 本地文件路径（POSIX 或 Windows 盘符）
 */
const SUPPORTED_HOSTS = [
  'youtube.com',
  'youtu.be',
  'www.youtube.com',
  'm.youtube.com',
  'bilibili.com',
  'www.bilibili.com',
  'b23.tv',
  'douyin.com',
  'www.douyin.com',
  'v.douyin.com',
  // 小宇宙真实主域是 xiaoyuzhoufm.com，xiaoyuzhou.com 是其别名，两者都要放行
  'xiaoyuzhou.com',
  'www.xiaoyuzhou.com',
  'podcast.xiaoyuzhou.com',
  'xiaoyuzhoufm.com',
  'www.xiaoyuzhoufm.com',
  'podcast.xiaoyuzhoufm.com',
]

/**
 * 判断输入是否是可识别的播客源 / 本地路径。
 * 不抛异常；返回 {ok, error} 便于表单内联展示。
 *
 * @param {string} raw
 * @returns {{ok: boolean, error?: string, normalized: string}}
 */
export function validatePodcastInput(raw) {
  const normalized = (raw || '').trim()
  if (!normalized) {
    return { ok: false, error: '请输入播客链接或本地文件路径', normalized }
  }
  if (normalized.length > MAX_INPUT_LENGTH) {
    return {
      ok: false,
      error: `输入过长（${normalized.length} > ${MAX_INPUT_LENGTH} 字符）`,
      normalized,
    }
  }

  // URL 分支
  if (/^https?:\/\//i.test(normalized) || /^\/\//.test(normalized)) {
    try {
      const url = new URL(normalized.startsWith('//') ? `https:${normalized}` : normalized)
      const host = url.hostname.toLowerCase()
      if (!SUPPORTED_HOSTS.includes(host)) {
        return {
          ok: false,
          error: `暂不支持该站点（${host}）。支持：YouTube / Bilibili / 抖音 / 小宇宙 / 本地路径`,
          normalized,
        }
      }
      return { ok: true, normalized }
    } catch {
      return { ok: false, error: 'URL 格式不正确', normalized }
    }
  }

  // 本地路径分支（POSIX 绝对路径、Windows 盘符、相对路径、~）
  // 简单规则：包含 / 或 \，且看起来不像随机字符串
  if (/^([A-Za-z]:[\\/]|[/~]|\.?\.?[/\\]|\w+[/\\])/.test(normalized)) {
    // 拒绝明显的控制字符
    if (/[\x00-\x1f]/.test(normalized)) {
      return { ok: false, error: '路径包含非法控制字符', normalized }
    }
    return { ok: true, normalized }
  }

  return {
    ok: false,
    error: '无法识别输入。请粘贴 YouTube/Bilibili/抖音/小宇宙 链接，或本地文件路径',
    normalized,
  }
}
