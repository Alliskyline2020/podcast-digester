"""导出字幕段落构建: 把 transcript segments 按段落分组, 标注重点加粗。

纯函数, 无 I/O, 完全可单测。供 export 路由在 include_transcript=True 时调用,
产出模板友好的段落视图(含每段是否含亮点标记), 亮点段落(来自 highlight.cited_segment_ids)
的字幕文本在模板中渲染为加粗。
"""
from typing import Any, Dict, Iterable, List, Optional

# 无 paragraph_mappings 时, 扁平段按字符预算切成可读段落
TRANSCRIPT_FALLBACK_CHARS = 320


def _fmt_time(ms: int) -> str:
    """毫秒 → mm:ss"""
    seconds = max(0, int(ms or 0)) // 1000
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _seg_text(seg: Dict[str, Any]) -> str:
    """优先用 LLM 清洗后的展示文本(text_with_punct), 缺失回退原文。"""
    return ((seg.get("text_with_punct") or seg.get("text_original") or "")).strip()


def _segment_view(seg: Optional[Dict[str, Any]], highlighted: set) -> Optional[Dict[str, Any]]:
    if not seg:
        return None
    text = _seg_text(seg)
    if not text:
        return None
    return {"text": text, "highlight": seg.get("id") in highlighted}


def _chunk_flat(segments: List[Dict[str, Any]], highlighted: set) -> List[Dict[str, Any]]:
    """无段落映射时: 按字符预算把扁平段聚合成可读段落。"""
    paras: List[Dict[str, Any]] = []
    cur_views: List[Dict[str, Any]] = []
    cur_chars = 0
    cur_start: Optional[int] = None
    for seg in segments:
        v = _segment_view(seg, highlighted)
        if not v:
            continue
        if cur_start is None:
            cur_start = seg.get("start_ms", 0)
        cur_views.append(v)
        cur_chars += len(v["text"])
        if cur_chars >= TRANSCRIPT_FALLBACK_CHARS:
            paras.append({
                "start_time": _fmt_time(cur_start),
                "has_highlight": any(s["highlight"] for s in cur_views),
                "segments": cur_views,
            })
            cur_views, cur_chars, cur_start = [], 0, None
    if cur_views:
        paras.append({
            "start_time": _fmt_time(cur_start),
            "has_highlight": any(s["highlight"] for s in cur_views),
            "segments": cur_views,
        })
    return paras


def build_transcript_paragraphs(
    segments: List[Dict[str, Any]],
    paragraph_mappings: Optional[List[Dict[str, Any]]],
    highlighted_ids: Iterable[int],
) -> List[Dict[str, Any]]:
    """构建导出字幕的段落视图。

    Args:
        segments: transcript segments(dict), 含 id/start_ms/text_with_punct/text_original
        paragraph_mappings: 段落映射(每项含 segment_indices:[int] + start_ms); None→扁平切块
        highlighted_ids: 需加粗的 segment id(来自 highlight.cited_segment_ids)

    Returns:
        [{start_time:str, has_highlight:bool, segments:[{text, highlight}]}, ...]
    """
    if not segments:
        return []
    highlighted = set(highlighted_ids or [])

    if not paragraph_mappings:
        return _chunk_flat(segments, highlighted)

    seg_by_id: Dict[Any, Dict[str, Any]] = {s.get("id"): s for s in segments}
    paras: List[Dict[str, Any]] = []
    for pm in paragraph_mappings:
        idxs = pm.get("segment_indices") or []
        views = [_segment_view(seg_by_id.get(i), highlighted) for i in idxs]
        views = [v for v in views if v]
        if not views:
            continue
        start_ms = pm.get("start_ms")
        if start_ms is None and idxs:
            start_ms = seg_by_id.get(idxs[0], {}).get("start_ms", 0)
        paras.append({
            "start_time": _fmt_time(start_ms or 0),
            "has_highlight": any(v["highlight"] for v in views),
            "segments": views,
        })
    return paras


def _highlighted_segment_ids(highlights: Iterable[Any]) -> set:
    """从 highlights(对象或 dict)收集所有 cited_segment_ids。"""
    ids: set = set()
    for hl in highlights or []:
        cited = getattr(hl, "cited_segment_ids", None)
        if cited is None and isinstance(hl, dict):
            cited = hl.get("cited_segment_ids")
        if cited:
            ids.update(cited)
    return ids


def build_transcript_export(
    transcript_data: Optional[Dict[str, Any]],
    paragraph_mappings: Optional[List[Dict[str, Any]]],
    highlights: Iterable[Any],
    include_transcript: bool,
) -> List[Dict[str, Any]]:
    """装配导出字幕段落(路由层薄封装调用此纯函数)。

    include_transcript=False 或无 segments → 返回 [](不渲染版块)。
    否则取 transcript_data.segments + 段落映射 + highlights 的 cited_segment_ids,
    产出 build_transcript_paragraphs 的段落视图。
    """
    if not include_transcript:
        return []
    segments = (transcript_data or {}).get("segments") or []
    if not segments:
        return []
    highlighted = _highlighted_segment_ids(highlights)
    return build_transcript_paragraphs(segments, paragraph_mappings, highlighted)

