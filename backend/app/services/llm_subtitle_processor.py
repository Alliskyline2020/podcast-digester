"""
LLM 驱动的字幕处理服务

使用 LLM 进行智能分段、清洗和金句提取
"""
import json
import logging
import re
from typing import List, Dict, Any, Optional
from app.utils import clean_llm_text
from ..llm import complete

logger = logging.getLogger(__name__)


def _parse_llm_json(content: str, context: str = "LLM") -> Any:
    """容错地解析 LLM 返回的 JSON。

    LLM 偶发返回带 ```json 代码块、前置解释文本、或末尾多余字符的内容。
    本助手先尝试直接 parse，失败时回退到正则提取首个 {...} 对象。

    Args:
        content: LLM 原始返回文本
        context: 错误信息中标识调用方的字符串
    """
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if not match:
            raise ValueError(
                f"{context}: 返回不是合法 JSON: {content[:200]!r}"
            )
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as err:
            raise ValueError(
                f"{context}: JSON 解析失败: {content[:200]!r}"
            ) from err


class LLMSubtitleProcessor:
    """LLM 驱动的字幕处理器"""

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        """初始化。api_key/base_url 保留参数仅为向后兼容，实际配置走 app.llm.get_config()。"""
        # 不再自建客户端：所有调用经 app.llm.complete() 统一分发。

    async def segment_transcript(
        self,
        segments: List[Dict[str, Any]],
        episode_id: str
    ) -> List[Dict[str, Any]]:
        """
        使用 LLM 智能分段

        Args:
            segments: 原始字幕 segments
            episode_id: 节目 ID

        Returns:
            智能分段后的段落列表
        """
        # 计算总字符数，决定是否分批处理
        total_chars = sum(len(s.get('text_original', '') or '') for s in segments)

        # 如果文本太长（>50K字符），分批处理
        if total_chars > 50000:
            print(f"[LLM] Transcript too long ({total_chars} chars), using batch processing")
            return await self._segment_in_batches(segments, episode_id, batch_size=1000)  # 减小批次大小到1000

        # 准备输入文本
        transcript_text = self._prepare_transcript_text(segments)

        # LLM 分段提示词
        system_prompt = """你是一个专业的字幕分段专家。你的任务是将访谈类节目的字幕按照语义完整性分成段落。

分段原则：
1. **语义完整性**：每个段落应该表达一个完整的意思或观点
2. **话题识别**：当话题转变时应该开始新段落
3. **结构识别**：识别对话、说明、叙述等不同结构
4. **自然边界**：在自然的停顿或转换处分段
5. **合理长度**：段落长度建议在 100-300 字之间，可以根据内容灵活调整

注意事项：
- 保留说话人信息（如"主持人："）
- 保留重要的引用和强调
- 避免在句子中间分段
- 保留时间戳信息，用于后续定位

输入格式：
[00:00.123] 主持人: 欢迎来到节目...
[00:05.456] 嘉宾: 今天我们要讨论...
[00:10.789] 主持人: 那很有趣...

输出格式（JSON）：
{
  "paragraphs": [
    {
      "id": 0,
      "start_index": 0,
      "end_index": 3,
      "start_time": "00:00.123",
      "end_time": "00:15.456",
      "content": "主持人和嘉宾的对话内容...",
      "reasoning": "这是开场白，属于完整的话题引入"
    }
  ]
}

请严格按照 JSON 格式输出，不要添加任何其他内容。"""

        try:
            resp = await complete(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": transcript_text}
                ],
                temperature=0.3,  # 降低随机性
                response_format={"type": "json_object"}
            )

            # 解析响应
            content = resp.content
            if not content:
                raise ValueError("LLM returned empty content")

            result = _parse_llm_json(content, context="semantic_segment")

            # 转换为段落数据结构
            paragraphs = []
            seg_count = len(segments)
            for para in result.get("paragraphs", []):
                # 提取对应的 segments
                # LLM 返回的索引不可信：可能越界、倒序、或类型错误。
                # 这里做严格的 clamp + 校验，跳过无效段落而非崩溃。
                try:
                    start_idx = int(para.get("start_index", 0))
                    end_idx = int(para.get("end_index", 0))
                except (TypeError, ValueError):
                    continue
                if start_idx < 0 or end_idx < 0:
                    continue
                # clamp 到合法范围
                start_idx = max(0, min(start_idx, seg_count))
                end_idx = max(0, min(end_idx, seg_count))
                # 倒序或空区间直接跳过
                if end_idx <= start_idx:
                    continue
                para_segments = segments[start_idx:end_idx]
                if not para_segments:
                    continue

                # 清洗HTML标签和实体
                text_original = " ".join([s.get("text_original", "") or "" for s in para_segments])
                text_clean = self._rule_based_clean(text_original)
                text_translated = " ".join([s.get("text_translated", "") or "" for s in para_segments])

                paragraphs.append({
                    "id": len(paragraphs),
                    "start_ms": para_segments[0]["start_ms"],
                    "end_ms": para_segments[-1]["end_ms"],
                    "text_original": text_original,
                    "text_clean": text_clean,
                    "text_translated": text_translated,
                    "segment_indices": list(range(para["start_index"], para["end_index"]+1)),
                    "segment_ids": [s.get("id", "") or "" for s in para_segments],
                    "reasoning": para.get("reasoning", ""),
                    "llm_processed": True
                })

            return paragraphs

        except Exception as e:
            print(f"LLM 分段失败: {e}")
            # 如果是因为文本太长导致的失败，尝试分批处理
            if len(segments) > 1000:
                print(f"[LLM] Falling back to batch processing due to error")
                return await self._segment_in_batches(segments, episode_id, batch_size=3000)
            # Fallback to rule-based segmentation
            return self._rule_based_fallback(segments)

    async def _segment_in_batches(
        self,
        segments: List[Dict[str, Any]],
        episode_id: str,
        batch_size: int = 3000
    ) -> List[Dict[str, Any]]:
        """
        分批处理长文本

        Args:
            segments: 原始字幕 segments
            episode_id: 节目 ID
            batch_size: 每批处理的 segments 数量

        Returns:
            智能分段后的段落列表
        """
        all_paragraphs = []
        para_id_counter = 0

        for i in range(0, len(segments), batch_size):
            batch_segments = segments[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(segments) + batch_size - 1) // batch_size

            print(f"[LLM] Processing batch {batch_num}/{total_batches} ({len(batch_segments)} segments)")

            # 使用简化版本的分段（每批内部）
            batch_paragraphs = await self._segment_single_batch(batch_segments, para_id_counter)
            all_paragraphs.extend(batch_paragraphs)
            para_id_counter += len(batch_paragraphs)

        return all_paragraphs

    async def _segment_single_batch(
        self,
        segments: List[Dict[str, Any]],
        start_id: int
    ) -> List[Dict[str, Any]]:
        """
        对单个批次进行分段

        Args:
            segments: 批次内的 segments
            start_id: 起始段落ID

        Returns:
            该批次的段落列表
        """
        # 准备输入文本（带时间戳）
        transcript_text = self._prepare_transcript_text(segments)

        # 简化的系统提示词
        system_prompt = """将以下字幕按照语义完整性分成段落。

分段原则：
1. 语义完整性：每个段落应该表达一个完整的意思
2. 话题转变：话题改变时开始新段落
3. 合理长度：段落建议在100-300字之间

输入格式：
[00:12.74] 大家好我是小军。
[00:13.48] 本集节目我们来到了美国纽约。

输出格式（JSON）：
{
  "paragraphs": [
    {
      "start_time": "00:12.74",
      "end_time": "00:45.20",
      "content": "段落内容摘要"
    }
  ]
}

请严格按照 JSON 格式输出。"""

        try:
            resp = await complete(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": transcript_text}
                ],
                temperature=0.3,
                response_format={"type": "json_object"}
            )

            content = resp.content
            if not content:
                raise ValueError("LLM returned empty content")

            result = _parse_llm_json(content, context="semantic_segment")

            # 基于时间戳匹配segments
            paragraphs = []
            for para in result.get("paragraphs", []):
                start_time_str = para.get("start_time", "")
                end_time_str = para.get("end_time", "")

                if not start_time_str or not end_time_str:
                    continue

                # 解析时间戳
                start_time = self._parse_timestamp(start_time_str)
                end_time = self._parse_timestamp(end_time_str)

                if start_time is None or end_time is None:
                    continue

                # 根据时间戳找到对应的segments
                para_segments = []
                for seg in segments:
                    if start_time <= seg["start_ms"] <= end_time:
                        para_segments.append(seg)
                    elif seg["start_ms"] > end_time:
                        break

                if not para_segments:
                    continue

                # 清洗HTML标签和实体
                text_original = " ".join([s.get("text_original", "") or "" for s in para_segments])
                text_clean = self._rule_based_clean(text_original)
                text_translated = " ".join([s.get("text_translated", "") or "" for s in para_segments])

                paragraphs.append({
                    "id": start_id + len(paragraphs),
                    "start_ms": para_segments[0]["start_ms"],
                    "end_ms": para_segments[-1]["end_ms"],
                    "text_original": text_original,
                    "text_clean": text_clean,
                    "text_translated": text_translated,
                    "segment_indices": [s.get("_index", i) for i, s in enumerate(para_segments)],
                    "segment_ids": [s.get("id", "") or "" for s in para_segments],
                    "reasoning": para.get("content", ""),
                    "llm_processed": True
                })

            return paragraphs

        except Exception as e:
            print(f"Batch LLM segmentation failed: {e}")
            # 回退到规则分段
            return self._rule_based_fallback(segments)

    def _parse_timestamp(self, time_str: str) -> Optional[int]:
        """解析时间戳字符串为毫秒"""
        try:
            parts = time_str.split(":")
            if len(parts) == 3:
                minutes, seconds, centiseconds = parts
                return int(minutes) * 60000 + int(seconds) * 1000 + int(centiseconds) * 10
            elif len(parts) == 2:
                minutes, seconds = parts
                return int(minutes) * 60000 + int(float(seconds)) * 1000
        except (ValueError, AttributeError, TypeError) as e:
            logger.debug(f"timestamp parse failed for {time_str!r}: {e}")
            return None
        return None

    async def clean_text(
        self,
        text: str,
        context: str = ""
    ) -> str:
        """
        使用 LLM 智能清洗文本

        Args:
            text: 待清洗的文本
            context: 上下文信息（可选）

        Returns:
            清洗后的文本
        """
        system_prompt = """你是一个专业的文本清洗专家。请清洗以下文本，使其更易读。

清洗要求：
1. **移除 HTML 标签**：删除所有 HTML 标签（如 <b>, </b>, <i>, </i>）
2. **移除特殊符号**：删除 [音乐]、[笑声]、[掌声] 等
3. **智能处理语气词**：
   - 移除无意义的语气词（如单独的"嗯"、"啊"、"哦"）
   - 保留有意义的语气表达（如"嗯...确实"、"哦！原来"）
4. **保留重要格式**：保留引用、强调的标记
5. **清理空格**：合并多余空格，保持合理间距
6. **修正格式**：修正明显的识别错误

原文：
{context}

待清洗文本：
{text}

输出格式：
直接输出清洗后的文本，不要添加任何解释。"""

        try:
            resp = await complete(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"原文：{context}\n\n待清洗文本：{text}"}
                ],
                temperature=0.1,  # 降低随机性
            )

            cleaned_text = resp.content.strip()

            return cleaned_text

        except Exception as e:
            print(f"LLM 清洗失败: {e}")
            # Fallback to rule-based cleaning
            return self._rule_based_clean(text)

    async def correct_transcription(
        self,
        segments: List[Dict[str, Any]],
        episode_title: str = "",
        episode_description: str = "",
        batch_size: int = 50
    ) -> List[Dict[str, Any]]:
        """
        使用 LLM 纠正字幕中的 ASR 识别错误

        Args:
            segments: 原始字幕 segments
            episode_title: 节目标题（提供上下文）
            episode_description: 节目描述（提供更多上下文）
            batch_size: 每批处理的 segments 数量

        Returns:
            纠正后的 segments（保持原结构）
        """
        # 如果segments太少，直接返回
        if len(segments) <= 10:
            return segments

        all_corrected_segments = []

        # 分批处理
        for i in range(0, len(segments), batch_size):
            batch_segments = segments[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(segments) + batch_size - 1) // batch_size

            print(f"[LLM Correction] Processing batch {batch_num}/{total_batches} ({len(batch_segments)} segments)")

            # 准备批次的文本内容
            batch_text = "\n".join([
                f"{j+1}. {seg.get('text_original', '')}"
                for j, seg in enumerate(batch_segments)
            ])

            # 构建上下文
            context = f"""节目信息：
标题：{episode_title}
描述：{episode_description}

需要纠正的字幕（共{len(batch_segments)}条）：
{batch_text}

请纠正上述字幕中的识别错误，保持原意不变。"""

            try:
                resp = await complete(
                    messages=[
                        {
                            "role": "system",
                            "content": """你是专业的字幕纠错专家。任务：纠正ASR（自动语音识别）产生的字幕错误。

常见错误类型：
1. 人名错误（如"张小珺"→"小军"）
2. 地名错误
3. 专业术语错误
4. 同音字错误

纠正原则：
- 保持原文语气和风格
- 只纠正明显的识别错误
- 保留格式标记（如<b></b>）
- 保持原意不变
- 输出必须保持相同的行数

输出格式（JSON）:
{
  "corrected": [
    "纠正后的第1条",
    "纠正后的第2条",
    ...
  ]
}

注意：必须输出与输入相同数量的行，每行对应一条字幕。"""
                        },
                        {
                            "role": "user",
                            "content": context
                        }
                    ],
                    temperature=0.1,  # 低温度确保准确性
                    response_format={"type": "json_object"}
                )

                result = _parse_llm_json(resp.content, context="correct_batch")
                corrected_texts = result.get("corrected", [])

                # 验证数量
                if len(corrected_texts) != len(batch_segments):
                    print(f"[LLM Correction] Warning: Expected {len(batch_segments)} corrections, got {len(corrected_texts)}")
                    # 使用原文
                    corrected_texts = [seg.get('text_original', '') for seg in batch_segments]

                # 更新segments
                for j, seg in enumerate(batch_segments):
                    corrected_seg = seg.copy()
                    corrected_seg['text_original'] = corrected_texts[j]
                    corrected_seg['text_corrected'] = True  # 标记已纠错
                    all_corrected_segments.append(corrected_seg)

            except Exception as e:
                print(f"[LLM Correction] Batch {batch_num} failed: {e}")
                # 失败时使用原文
                all_corrected_segments.extend(batch_segments)

        return all_corrected_segments

    async def extract_insights(
        self,
        transcript: str,
        episode_id: str,
        max_insights: int = 5
    ) -> Dict[str, Any]:
        """
        使用 LLM 提取金句和洞察

        Args:
            transcript: 完整转录文本
            episode_id: 节目 ID
            max_insights: 最大金句数量

        Returns:
            金句提取结果
        """
        system_prompt = """你是一个专业的访谈内容分析师。请从以下访谈中提取最有价值的金句和洞察。

提取标准：
1. **价值判断**：金句应该是有洞见的观点、深刻的见解或有趣的细节
2. **避免泛泛而谈**：排除常见的陈述、客套话、无实质内容的话
3. **保留风格**：保留说话人的语气和风格
4. **标注信息**：
   - 重要性（high/medium/low）
   - 适用场景（哪些人会受益）
   - 背景说明（为什么重要）

访谈内容：
{transcript}

输出格式（JSON）：
{
  "insights": [
    {
      "quote": "金句原文",
      "speaker": "说话人（如有）",
      "timestamp_ms": 时间戳（毫秒）",
      "importance": "重要性评级",
      "context": "背景说明",
      "target_audience": "适用人群"
    }
  ]
}

请严格按照 JSON 格式输出，提取 3-5 个最有价值的金句。"""

        try:
            resp = await complete(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": transcript}
                ],
                temperature=0.2,
                response_format={"type": "json_object"}
            )

            result = _parse_llm_json(resp.content, context="llm_call")

            return {
                "episode_id": episode_id,
                "insights": result.get("insights", []),
                "llm_processed": True
            }

        except Exception as e:
            print(f"LLM 金句提取失败: {e}")
            return {
                "episode_id": episode_id,
                "insights": [],
                "error": str(e),
                "llm_processed": False
            }

    def _prepare_transcript_text(self, segments: List[Dict[str, Any]]) -> str:
        """
        准备转录文本供 LLM 处理

        Args:
            segments: 原始 segments

        Returns:
            格式化的文本
        """
        lines = []
        for seg in segments:
            # 跳过空文本
            text = seg.get('text_original', '') or seg.get('text', '') or ''
            if not text or not isinstance(text, str):
                continue

            time_str = f"[{seg.get('start_ms', 0)/1000:.2f}]"
            speaker = seg.get('speaker', '')

            if speaker:
                line = f"{time_str} {speaker}: {text}"
            else:
                line = f"{time_str} {text}"

            lines.append(line)

        return "\n".join(lines)

    def _rule_based_fallback(self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        规则分段回退方案（当 LLM 失败时）

        Args:
            segments: 原始 segments

        Returns:
            规则分段结果
        """
        # 使用更大的字符限制
        max_chars = 800
        min_chars = 300

        result = []
        current_para = {
            "id": 0,
            "segments": [],
            "text_original": ""
        }

        for i, seg in enumerate(segments):
            seg_text = seg.get("text_original", "") or ""
            if not isinstance(seg_text, str) or not seg_text:
                continue

            # 检查时间间隔
            time_gap = 0
            if current_para["segments"]:
                last_seg = current_para["segments"][-1]
                time_gap = (seg["start_ms"] - last_seg["end_ms"]) / 1000.0

            # 检查是否需要分段（宽松限制）
            would_exceed = len(current_para["text_original"]) + len(seg_text) > max_chars
            has_min_content = len(current_para["text_original"]) >= min_chars
            should_split = has_min_content and (would_exceed or time_gap > 5.0)

            if should_split and current_para["segments"]:
                result.append(self._finalize_para(current_para, len(result)))
                current_para = {
                    "id": len(result),
                    "segments": [seg],
                    "text_original": seg_text
                }
            else:
                separator = " " if current_para["text_original"] else ""
                current_para["text_original"] += separator + seg_text
                current_para["segments"].append(seg)

        if current_para["segments"]:
            result.append(self._finalize_para(current_para, len(result)))

        return result

    def _rule_based_clean(self, text: str) -> str:
        """
        规则清洗回退方案

        Args:
            text: 待清洗文本

        Returns:
            清洗后的文本
        """
        if not text or not isinstance(text, str):
            return ""

        # 使用集中的文本清洗工具（激进模式 + 移除特殊符号）
        return clean_llm_text(text)

    def _finalize_para(self, para: Dict, para_id: int) -> Dict[str, Any]:
        """
        完成段落处理

        Args:
            para: 段落数据
            para_id: 段落 ID

        Returns:
            完整的段落数据
        """
        segments = para["segments"]

        # 清洗HTML标签和实体
        text_clean = self._rule_based_clean(para["text_original"])

        return {
            "id": para_id,
            "start_ms": segments[0]["start_ms"],
            "end_ms": segments[-1]["end_ms"],
            "text_original": para["text_original"],
            "text_clean": text_clean,
            "text_translated": "",
            "segment_indices": [s.get("_index", i) for i, s in enumerate(segments)],
            "segment_ids": [s["id"] for s in segments],
            "llm_processed": False
        }
