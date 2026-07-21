"""
字幕分段服务

将零散的 subtitle segments 合并成段落，支持可配置的分段规则
优化：语义完整性、句子级别映射。

【解耦】清洗已上移到 LLM polish(写入 Segment.text_with_punct); 分段器是纯分组器——
不产文本、不做规则清洗, 段落 text_clean = 各 segment.text_with_punct 的投影。
"""
from typing import List, Dict, Any
from app.utils import clean_text  # 保留: deprecated clean_text 方法的兼容壳


class SubtitleSegmenter:
    """字幕分段服务，将零散的 segments 合并成段落（优化版）"""

    def __init__(
        self,
        max_chars: int = 500,        # 提高到500字符
        min_chars: int = 200,        # 提高到200字符
        merge_threshold: float = 3.0,  # 时间间隔阈值（秒）
        enable_cleaning: bool = True,  # 启用文本清洗
        extract_sentences: bool = True,  # 提取句子级别映射
    ):
        """
        初始化分段器

        Args:
            max_chars: 单个段落最大字符数（500）
            min_chars: 单个段落最小字符数（200）
            merge_threshold: 时间间隔阈值（秒），超过此值强制分段
            enable_cleaning: 是否清洗文本
            extract_sentences: 是否提取句子级别映射
        """
        self.max_chars = max_chars
        self.min_chars = min_chars
        self.merge_threshold = merge_threshold
        self.enable_cleaning = enable_cleaning
        self.extract_sentences = extract_sentences

    def clean_text(self, text: str, aggressive: bool = True) -> str:
        """[deprecated] 分段器已解耦, 不再内部清洗。保留仅为兼容外部调用。"""
        return clean_text(text, aggressive=aggressive)

    def extract_sentences_from_text(self, text: str, segments: List[Dict]) -> List[Dict]:
        """
        从段落文本和原始segments中提取句子级别映射

        Args:
            text: 清洗后的段落文本
            segments: 原始segments列表

        Returns:
            句子列表，每个包含：
                - id: 句子ID
                - text: 句子文本
                - start_ms: 开始时间
                - end_ms: 结束时间
                - segment_id: 对应的segment ID
                - segment_index: 对应的segment索引
        """
        sentences = []

        # 使用句子结束符切分
        sentence_ends = []
        for i, char in enumerate(text):
            if char in ['。', '！', '？', '.', '!', '?']:
                sentence_ends.append(i)

        # 如果没有句子结束符，整段作为一个句子
        if not sentence_ends and text:
            sentence_ends = [len(text) - 1]

        # 提取句子
        start_idx = 0
        for sent_id, end_idx in enumerate(sentence_ends):
            sent_text = text[start_idx:end_idx + 1].strip()
            if sent_text:
                # 找到对应的segment
                # 通过字符位置估算时间
                char_ratio = end_idx / len(text) if text else 0

                # 找到最接近的segment
                target_segment = None
                min_diff = float('inf')

                for seg in segments:
                    seg_start_ratio = seg.get('_char_start', 0) / len(text) if text else 0
                    diff = abs(seg_start_ratio - char_ratio)
                    if diff < min_diff:
                        min_diff = diff
                        target_segment = seg

                if target_segment:
                    sentences.append({
                        'id': sent_id,
                        'text': sent_text,
                        'start_ms': target_segment.get('start_ms', 0),
                        'end_ms': target_segment.get('end_ms', 0),
                        'segment_id': target_segment.get('id', ''),
                        'segment_index': target_segment.get('_index', 0)
                    })

            start_idx = end_idx + 1

        return sentences

    def segment(self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        将 segments 合并成段落（优化版）

        Args:
            segments: 原始字幕 segments

        Returns:
            段落列表，每个包含：
                - id: int (段落序号)
                - start_ms: int (开始时间)
                - end_ms: int (结束时间)
                - text_original: str (原文)
                - text_clean: str (清洗后的文本)
                - text_translated: str (译文)
                - sentences: List (句子级别映射)
                - segment_indices: List[int] (对应的 segments 索引)
                - segment_ids: List[str] (对应的 segment ID)
        """
        if not segments:
            return []

        # 第一遍：添加字符位置标记
        char_pos = 0
        for seg in segments:
            seg_text = seg.get("text_original", "")
            seg['_char_start'] = char_pos
            seg['_char_end'] = char_pos + len(seg_text)
            char_pos += len(seg_text)

        result = []
        current_para = {
            "id": 0,
            "segments": [],
            "text_original": "",
            "text_translated": "",
            "char_start": 0
        }

        for i, seg in enumerate(segments):
            # 添加索引标记
            seg['_index'] = i

            seg_text = seg.get("text_original", "")
            seg_trans = seg.get("text_translated", "")

            if not seg_text:
                continue

            # 检查时间间隔
            time_gap = 0
            if current_para["segments"]:
                last_seg = current_para["segments"][-1]
                time_gap = (seg["start_ms"] - last_seg["end_ms"]) / 1000.0

            # 检查是否需要开始新段落（语义完整性优先）
            would_exceed = len(current_para["text_original"]) + len(seg_text) > self.max_chars
            has_min_content = len(current_para["text_original"]) >= self.min_chars

            # 优先语义完整性：只有在超出很多时才分段
            should_split = has_min_content and (
                would_exceed and (len(current_para["text_original"]) + len(seg_text) > self.max_chars * 1.2) or
                time_gap > self.merge_threshold
            )

            if should_split and current_para["segments"]:
                # 保存当前段落
                result.append(self._finalize_paragraph(current_para, len(result)))
                # 开始新段落
                current_para = {
                    "id": len(result),
                    "segments": [seg],
                    "text_original": seg_text,
                    "text_translated": seg_trans,
                    "char_start": seg.get('_char_start', 0)
                }
            else:
                # 添加到当前段落
                # 第一个segment不加空格，后续segment加空格
                if current_para["text_original"]:
                    current_para["text_original"] += " " + seg_text
                else:
                    current_para["text_original"] = seg_text

                if seg_trans:
                    if current_para["text_translated"]:
                        current_para["text_translated"] += " " + seg_trans
                    else:
                        current_para["text_translated"] = seg_trans

                current_para["segments"].append(seg)

        # 保存最后一段
        if current_para["segments"]:
            result.append(self._finalize_paragraph(current_para, len(result)))

        return result

    def _finalize_paragraph(self, para: Dict, para_id: int) -> Dict[str, Any]:
        """
        将段落数据转换为最终格式（纯投影, 不清洗）。

        text_clean = 各 segment.text_with_punct 的投影(由 segmenter_input 保证存在,
        缺失回退 text_original)。清洗已由 LLM polish 完成, 分段器不再做规则清洗。

        Args:
            para: 段落原始数据
            para_id: 段落 ID

        Returns:
            格式化的段落数据（包含句子级别映射）
        """
        segments = para["segments"]

        # 投影: 用每个 segment 的 text_with_punct(清洗后展示文本)
        parts = [seg.get("text_with_punct") or seg.get("text_original", "") for seg in segments]
        text_clean = " ".join(p for p in parts if p).strip() or para["text_original"]

        # 提取句子级别映射
        sentences = []
        if self.extract_sentences and text_clean:
            sentences = self.extract_sentences_from_text(text_clean, segments)

        return {
            "id": para_id,
            "start_ms": segments[0]["start_ms"],
            "end_ms": segments[-1]["end_ms"],
            "text_original": para["text_original"],
            "text_clean": text_clean,
            "text_translated": para["text_translated"],
            "sentences": sentences,
            "segment_indices": [seg.get("_index", i) for i, seg in enumerate(segments)],
            "segment_ids": [seg["id"] for seg in segments]
        }
