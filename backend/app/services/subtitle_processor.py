"""SubtitleProcessor: 对齐时间戳的字幕润色(ZH)+翻译(EN)统一服务。

硬约束:
- 时间戳不可变: id/start_ms/end_ms 永不写(后置条件断言)。
- 语义不变: 只加标点+删白名单口水话; 越界(口水话感知 LCS 校验)即回退 text_original。
- 段落不丢: 段数不变; 每个有 text_original 的 segment, text_with_punct 非空。

下游金句/洞察读 text_translated or text_original, 跳转靠 start_ms; 本服务只写
text_with_punct/text_translated, 故不影响金句/洞察/点击播放。
"""
import logging
from typing import Callable, Optional

from ..llm import chat_json
from ..llm_pipeline import translate_segments
from .subtitle_align import semantic_ok

logger = logging.getLogger(__name__)

POLISH_BATCH_SIZE = 15
POLISH_MODEL = "deepseek-chat"
POLISH_MAX_TOKENS = 8000

POLISH_SYSTEM = """你是专业的播客字幕编辑。对 ASR 字幕(中文或英文)做两件事:

1. **补充正确标点**: ASR 标点经常不准/缺失/错位。根据语义重新加正确标点让字幕自然可读。
   - 中文: 逗号、句号、问号、感叹号、顿号、分号
   - 英文: comma, period, question mark, exclamation mark, semicolon, colon; 修正首字母大写与句末标点

2. **去除口水话和无意义填充**, 但保留有语义作用的词:
   - 中文: 删 "嗯""啊""呃""那个""然后呢""就是说""对吧""你看""的话""就是这个" 等口头禅/语气词/无意义重复
   - 英文: 删 "um", "uh", "er", "ah", "hmm", "you know", "I mean", "like"(填充), "sort of", "kind of", "basically", "actually", "literally"(填充), 以及无意义重复("the the", "I I")
   - 中文"然后/因为"、英文 "because/therefore/however/so"(表逻辑) → 保留
   - 人名/产品名/公司名/数字/术语 → 原样保留

**绝对铁律(违反任一条都算失败)**:
- 不改变语义, 不增删信息, 不修正事实, 不补全省略
- 输出语言与输入相同(不翻译)
- 输出句数严格等于输入句数, 按 id 一一对应, 不改顺序/不合并/不拆分
- 人名/产品名/公司名/数字/术语原样保留(Manus、OpenAI、2025、GPT-4)
- 某句已很好则原样输出"""


def _build_polish_user(inputs: list) -> str:
    import json
    return f"""以下是 {len(inputs)} 句 ASR 字幕(中文或英文), 逐句优化(加标点 + 去口水话)。保持每句原有语言, 不要翻译。

输入字幕(JSON 数组):
{json.dumps(inputs, ensure_ascii=False, indent=2)}

输出 JSON(严格格式):
{{
  "polished": [
    {{"id": 0, "text": "第 0 句优化后的文本"}}
  ]
}}

务必: polished 数组长度 = {len(inputs)}; 每个 id 与输入相同; 输出语言与输入相同; 只改标点和口水话, 不改语义; 不合并/拆分/换序。"""


class SubtitleProcessor:
    """字幕润色 + 翻译, 只写显示字段, 时间戳/语义/段数不变。"""

    # ---------- 不可变性 ----------
    def _snapshot(self, transcript) -> list:
        return [(s.id, s.start_ms, s.end_ms, s.text_original) for s in transcript.segments]

    def _assert_immutability(self, snapshot: list, transcript) -> None:
        cur = [(s.id, s.start_ms, s.end_ms, s.text_original) for s in transcript.segments]
        assert cur == snapshot, "不可变性违反: id/start_ms/end_ms/text_original 被改动"

    # ---------- 润色 ----------
    async def polish(self, transcript, progress_cb: Optional[Callable[[float], None]] = None) -> int:
        """润色所有 segment 的 text_with_punct(双语)。返回实际接受的句数。

        每个 text_original 非空的 segment, 处理后 text_with_punct 必非空:
        LLM 输出通过 semantic_ok 才接受, 否则回退 text_original(drift/语义被改/漏返/异常)。
        """
        segments = transcript.segments
        total = len(segments)
        if total == 0:
            return 0
        polished = 0
        for start in range(0, total, POLISH_BATCH_SIZE):
            batch = segments[start:start + POLISH_BATCH_SIZE]
            inputs = [{"id": s.id, "text": s.text_original}
                      for s in batch if (s.text_original or "").strip()]
            pmap: dict = {}
            if inputs:
                try:
                    result = await chat_json(
                        system=POLISH_SYSTEM,
                        user=_build_polish_user(inputs),
                        temperature=0.2,
                        model=POLISH_MODEL,
                        max_tokens=POLISH_MAX_TOKENS,
                        response_format={"type": "json_object"},
                    )
                    pmap = {p.get("id"): (p.get("text") or "").strip()
                            for p in result.get("polished", [])}
                except Exception as e:
                    logger.warning(f"[polish] 批 {start}-{start+len(batch)} LLM 失败, 整批回退原文: {e}")
            accepted = 0
            for s in batch:
                if not (s.text_original or "").strip():
                    continue  # 原文为空(ASR 空段): 不丢段, 不强行填空
                out = pmap.get(s.id, "")
                if out and semantic_ok(out, s.text_original):
                    s.text_with_punct = out
                    accepted += 1
                else:
                    s.text_with_punct = s.text_original  # 回退 = 零语义改动
            polished += accepted
            logger.info(f"[polish] 批 {start}-{start+len(batch)}/{total}: 接受 {accepted}/{len(inputs)}")
            if progress_cb:
                progress_cb((start + len(batch)) / total)
        return polished

    # ---------- 翻译(EN→ZH) ----------
    async def translate(self, transcript, progress_cb: Optional[Callable[[float], None]] = None) -> int:
        """EN→ZH 翻译, 写 text_translated。ZH 直接跳过。返回写入句数。

        复用经过验证的 translate_segments(1:1 by id, 自然对齐), 再做结构兜底:
        每个 EN segment 必须得到非空 text_translated(已有翻译 > 原文兜底), 绝不空/丢段。
        """
        if transcript.language == "zh":
            return 0
        segments = transcript.segments
        translations = await translate_segments(transcript, progress_cb=progress_cb)
        by_id = {t.get("id"): (t.get("text_zh") or t.get("text_translated") or "").strip()
                 for t in translations}
        translated = 0
        for s in segments:
            zh = by_id.get(s.id, "")
            if zh:
                s.text_translated = zh
                translated += 1
            elif not (s.text_translated or "").strip():
                # 结构兜底: translate_segments 漏掉的段 → 原文兜底, 绝不空
                s.text_translated = s.text_original or ""
        logger.info(f"[translate] 写入 {translated}/{len(segments)} 段 text_translated")
        return translated
