"""
阶段 4: 文本翻译
仅当全局 language != "zh" 或前端请求中带 force_translate=true 时进入此阶段。

特性：
- 触发机制：检查语言或强制翻译标志
- 批量打包：按 50 个 Segment 打包成一组
- Prompt 注入：提供"科技数码/播客专用中英词典"作为 System Prompt
- ID 对齐：严格要求 LLM 返回带有原 id 键的 K-V 结构
"""
import asyncio
import logging
from typing import List, Dict, Any, Optional, TYPE_CHECKING
from ..llm import chat_json
from ..prompts import TRANSLATE_SYSTEM, build_translate_user

if TYPE_CHECKING:
    from ..models import Transcript


logger = logging.getLogger(__name__)


# 科技数码/播客专用术语词典
TECH_TERMS_DICTIONARY = """
常用术语翻译参考：
- Snapdragon → 骁龙（而非"金鱼草"）
- Tensor → 张量
- Transformer → Transformer 架构
- LLM → 大语言模型
- Agent → Agent/智能体
- API → API/接口
- prompt → 提示词
- GPU → GPU/显卡
- NPU → NPU/神经网络处理器
- SoC → SoC/系统芯片
- DDR → DDR/内存
- PPI → PPI/像素密度
- Refresh Rate → 刷新率
- Frame Rate → 帧率
- Bitrate → 比特率/码率
- Codec → 编解码器
- Latency → 延迟
- Bandwidth → 带宽
- Throughput → 吞吐量
"""


async def translate_segments(
    transcript: "Transcript",
    progress_cb: Optional[callable] = None,
) -> List[Dict[str, Any]]:
    """
    翻译转录文本

    Args:
        transcript: Transcript 对象
        progress_cb: 进度回调

    Returns:
        翻译结果列表 [{"id": 0, "text_zh": "..."}, ...]
    """
    # 跳过已翻译的内容
    if transcript.language == "zh":
        logger.info("Content is already in Chinese, skipping translation")
        if progress_cb:
            progress_cb(1.0)
        return []

    from ..config import LLM_TRANSLATE_BATCH_SIZE
    batch_size = LLM_TRANSLATE_BATCH_SIZE
    semaphore = asyncio.Semaphore(4)  # 并发 4

    segments = transcript.segments
    total_batches = (len(segments) + batch_size - 1) // batch_size

    async def translate_batch(batch: List, batch_idx: int) -> List[Dict]:
        async with semaphore:
            block = "\n".join(
                f"{seg.id} | {seg.text_original}"
                for seg in batch
            )

            # 添加术语词典到系统提示
            system_prompt = TRANSLATE_SYSTEM + TECH_TERMS_DICTIONARY

            user_input = build_translate_user(block)

            try:
                result = await chat_json(
                    system=system_prompt,
                    user=user_input,
                    temperature=0.2,
                    response_format={"type": "json_object"},
                )

                translations = result.get("translations", [])

                # 验证 ID 对齐
                input_ids = {seg.id for seg in batch}
                output_ids = {t["id"] for t in translations}

                if input_ids != output_ids:
                    logger.warning(
                        f"Batch {batch_idx}: ID mismatch - input: {input_ids}, output: {output_ids}"
                    )
                    # 返回空结果，触发降级
                    return []

                if progress_cb:
                    progress_cb((batch_idx + 1) / total_batches)

                return translations

            except Exception as e:
                logger.error(f"Batch {batch_idx} translation failed: {e}")
                return []

    # 分批处理
    batches = []
    for i in range(0, len(segments), batch_size):
        batches.append((segments[i:i + batch_size], i // batch_size))

    results = await asyncio.gather(*[
        translate_batch(batch, idx) for batch, idx in batches
    ])

    # 合并结果
    translations = []
    for batch_result in results:
        translations.extend(batch_result)

    logger.info(f"Translation completed: {len(translations)} segments")

    if progress_cb:
        progress_cb(1.0)

    return translations


def apply_translations(transcript: "Transcript", translations: List[Dict]) -> None:
    """
    应用翻译结果到转录文本

    Args:
        transcript: Transcript 对象（会被就地修改）
        translations: 翻译结果列表
    """
    translation_map = {t["id"]: t["text_zh"] for t in translations}

    for seg in transcript.segments:
        if seg.id in translation_map:
            seg.text_translated = translation_map[seg.id]

    logger.info(f"Applied {len(translation_map)} translations")
