"""单一收敛点：把 Transcript 的 Segment 列表转成 SubtitleSegmenter 期望的 seg_dict 列表。

之前 `_generate_paragraph_mappings` 在 pipeline.py 里就地构造这些 dict，且直接喂
`seg.text_original`（raw ASR），并在 polish/translate 之前调用 —— 导致段落字幕
永远是 raw ASR（"我觉得 我觉得 这个 这个"），即便 polish 已产出干净的带标点文本。

P1 修复（语言命名重构 Phase 4a）：
1. 收敛到此 helper，统一构造逻辑。
2. 当 `text_with_punct` 存在时用它作为 segmenter 的 `text_original` 视图 —— 这样
   段落字幕反映润色后的标点+去口水话文本，而不是 raw ASR。
   源字段 `Segment.text_original` 保持不变（不可变，音频源语言文本绝不丢），
   这里只是 segmenter 的 *视图* 用润色变体；缺失时回退到源文本（content-loss 保证）。
3. pipeline 在 polish / translate 之后重新调用 `_generate_paragraph_mappings`，
   让最终的 paragraph_mappings 反映最完整的文本。

LLM 分段器（admin sync-subtitles 端点）走另一条数据路径（消费 raw transcript
dict，不经过 Transcript 模型），其迁移见后续任务，不在本 helper 范围内。
"""
from typing import Any, Dict, List


def segments_for_segmenter(transcript) -> List[Dict[str, Any]]:
    """Build segmenter input dicts from a Transcript.

    P1 fix: feed polished text when available so paragraphs reflect
    punctuation + filler removal, not raw ASR. `Segment.text_original`
    (the immutable audio-source text) is untouched; only the segmenter's
    VIEW of the per-segment text uses the polished variant, falling back
    to the source text when polish hasn't run or produced nothing.

    Each output dict carries the keys `SubtitleSegmenter.segment` reads:
    id, start_ms, end_ms, _index, text_original, text_translated.

    Args:
        transcript: a Transcript whose `episode_id` is already populated
            by the pipeline before this runs.

    Returns:
        List of seg dicts in segment order; `_index` is the enumeration
        position (matches the segmenter's own indexing convention).
    """
    out: List[Dict[str, Any]] = []
    for i, seg in enumerate(transcript.segments):
        out.append(
            {
                # id 保持现有语义：seg_<episode_id>_<seg.id>（seg.id 是 int）
                "id": f"seg_{transcript.episode_id}_{seg.id}",
                "start_ms": seg.start_ms,
                "end_ms": seg.end_ms,
                # P1 核心：优先用润色后的带标点文本
                "text_original": seg.text_with_punct or seg.text_original,
                "text_translated": seg.text_translated,
                "_index": i,
            }
        )
    return out
