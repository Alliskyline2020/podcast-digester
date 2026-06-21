"""
字幕标点恢复服务
使用LLM为字幕文本添加标点符号，提升可读性

优化版本：
- 每个段落独立处理，避免复杂的合并和分配逻辑
- 使用结构化输出（JSON）确保LLM响应稳定
- 更小的批次大小（50）降低单次调用复杂度
"""
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path
import json
from datetime import datetime

logger = logging.getLogger(__name__)


class PunctuationRestorer:
    """
    标点恢复器（优化版）

    策略：
    - 每个段落独立处理，避免分配问题
    - 使用JSON格式确保LLM输出稳定
    - 批量处理降低API调用次数
    """

    # 每批处理的段落数（优化：50个段落/批）
    BATCH_SIZE = 50

    def __init__(self):
        self.cache = {}

    async def restore_punctuation(
        self,
        segments: List[Dict[str, Any]],
        episode_id: str,
        progress_cb: Optional[callable] = None
    ) -> List[Dict[str, Any]]:
        """
        为字幕段落添加标点符号

        优化策略：
        - 每个段落独立处理（避免合并带来的分配问题）
        - 使用更简单的LLM调用方式
        - 直接为每个段落添加标点

        Args:
            segments: 字幕段落列表
            episode_id: 节目ID
            progress_cb: 进度回调

        Returns:
            添加了标点符号的字幕段落列表
        """
        if not segments:
            return segments

        total = len(segments)
        logger.info(f"[Punctuation] 开始处理 {episode_id}, 共 {total} 个段落")

        # 优化策略：每个段落独立处理，避免复杂的合并和分配逻辑
        punctuated_segments = []

        # 分批处理（每批50个段落，降低单次复杂度）
        BATCH_SIZE = 50
        total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE

        for batch_idx in range(0, total, BATCH_SIZE):
            batch_end = min(batch_idx + BATCH_SIZE, total)
            batch_segments = segments[batch_idx:batch_end]
            batch_num = batch_idx // BATCH_SIZE + 1

            logger.info(f"[Punctuation] 处理批次 {batch_num}/{total_batches}")

            # 为这一批段落添加标点
            punctuated_batch = await self._process_batch_optimized(batch_segments)
            punctuated_segments.extend(punctuated_batch)

            if progress_cb:
                progress = batch_end / total
                progress_cb(progress)

        logger.info(f"[Punctuation] 完成 {episode_id}")
        return punctuated_segments

    async def _process_batch_optimized(self, segments: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        优化的批处理：每个段落独立添加标点

        策略：
        - 构建包含多个段落的单个提示词
        - 要求LLM为每个段落独立添加标点
        - 使用JSON格式确保输出稳定
        """
        if not segments:
            return []

        # 构建输入文本（每个段落一行，带编号）
        input_lines = []
        for i, seg in enumerate(segments):
            text = seg.get("text_original", "").strip()
            if text:
                # 使用简单的JSON格式标记段落
                input_lines.append(f'"{i}": "{text}"')

        input_text = "\n".join(input_lines)

        system_prompt = """你是专业的中文标点编辑。请为每个字幕文本添加标点符号。

要求：
1. 只添加标点符号（。！？，、；：），不要修改文字内容
2. 保持原句的语义和结构
3. 标点要符合中文语法规范
4. 返回JSON格式，每个段落对应一个键值对

示例：
输入：
"0": "大家好我是小明"
"1": "今天天气真好"

输出：
{
  "0": "大家好，我是小明。",
  "1": "今天天气真好。"
}"""

        user_prompt = f"""请为以下字幕文本添加标点符号：

{input_text}

请直接返回JSON格式的结果："""

        try:
            from app.llm import chat_json
            from pydantic import BaseModel, RootModel
            from typing import Dict

            # 定义响应模型（使用RootModel）
            class PunctuationResponse(RootModel[Dict[str, str]]):
                pass

            try:
                # 使用chat_json获取结构化响应
                response = await chat_json(
                    system=system_prompt,
                    user=user_prompt,
                    temperature=0.1
                )

                # 解析响应
                if isinstance(response, PunctuationResponse):
                    # RootModel实例，直接获取数据
                    punctuated_dict = response.root
                elif isinstance(response, dict):
                    punctuated_dict = response
                elif hasattr(response, 'root'):
                    punctuated_dict = response.root
                else:
                    # 尝试解析
                    import json
                    if isinstance(response, str):
                        punctuated_dict = json.loads(response)
                    else:
                        punctuated_dict = dict(response)

                # 构建结果
                result = []
                for i, seg in enumerate(segments):
                    seg_copy = seg.copy()
                    key = str(i)
                    if key in punctuated_dict:
                        seg_copy["text_with_punct"] = punctuated_dict[key]
                    else:
                        # Fallback: 使用原文
                        seg_copy["text_with_punct"] = seg.get("text_original", "")
                    result.append(seg_copy)

                return result

            except Exception as e:
                logger.warning(f"[Punctuation] 结构化调用失败: {e}，使用fallback")
                # Fallback: 每个段落保持原文
                return [
                    {**seg, "text_with_punct": seg.get("text_original", "")}
                    for seg in segments
                ]

        except Exception as e:
            logger.error(f"[Punctuation] 批处理失败: {e}")
            # 失败时返回原文（不带标点）
            return [
                {**seg, "text_with_punct": seg.get("text_original", "")}
                for seg in segments
            ]

    async def check_if_processed(self, episode_id: str) -> bool:
        """
        检查是否已经处理过标点

        Args:
            episode_id: 节目ID

        Returns:
            是否已处理
        """
        import aiosqlite
        from app.config import DB_PATH

        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT text_with_punct FROM transcript WHERE episode_id = ? LIMIT 1",
                (episode_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row and row.get("text_with_punct"):
                    return True
        return False


# 全局实例
punctuation_restorer = PunctuationRestorer()
