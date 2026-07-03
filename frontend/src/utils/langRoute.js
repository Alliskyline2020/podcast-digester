/**
 * Content-based language routing for subtitle display.
 *
 * Mirrors backend `migrate_language_fields.route_segment`: given the two text
 * candidates a paragraph carries (the audio-source/polished text and the
 * translation), decide which is Chinese and which is English by CJK ratio.
 *
 * This is locale-agnostic on purpose. `text_original` is NOT reliable evidence
 * of the audio language — for episodes originally transcribed under a wrong ASR
 * locale (e.g. Yao Shunyu: Chinese audio, but text_original is English), the
 * role fields are swapped. Routing by script content is correct in both cases.
 */

const CJK_RE = /[一-鿿]/g

/**
 * Fraction of non-space characters that are CJK ideographs.
 * @param {string} [text]
 * @returns {number} 0..1
 */
export function cjkRatio(text) {
  if (!text) return 0
  let total = 0
  for (const ch of text) {
    if (/\s/.test(ch)) continue
    total++
  }
  if (total === 0) return 0
  const cjk = (text.match(CJK_RE) || []).length
  return cjk / total
}

/**
 * Route an (original, translated) text pair into {text_zh, text_en} by content.
 *
 * `original` is the audio-source / polished text (typically `text_clean ||
 * text_original`); `translated` is the translation, if any. The more-Chinese
 * candidate becomes `text_zh`, the other `text_en`.
 *
 * @param {string} [original]
 * @param {string} [translated]
 * @returns {{text_zh: string, text_en: string}}
 */
export function routeText(original, translated) {
  const orig = original || ''
  const trans = translated || ''
  const origZh = cjkRatio(orig)
  const transZh = cjkRatio(trans)
  if (origZh >= transZh) {
    return { text_zh: orig, text_en: trans }
  }
  return { text_zh: trans, text_en: orig }
}
