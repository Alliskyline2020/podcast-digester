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


# CJK 检测：翻译结果里一个中文字符都没有 = LLM 原样回显英文（合并组 follower 的签名）
import re as _re
_CJK_RE = _re.compile(r"[一-鿿㐀-䶿]")


def _has_cjk(text: str) -> bool:
    """文本是否含至少一个中日韩表意字符。"""
    return bool(_CJK_RE.search(text or ""))


def _merge_group_ids(segments, translations_by_id) -> set:
    """识别需要按 1:1 重译的合并组 id 集合。

    背景：ASR 常把一句话切成多段分片。LLM 批量翻译时会把若干连续分片合并成
    一句完整中文、写到首段(leader)，其余 follower 段原样回显英文。结果是
    leader 拿到整句中文、follower 的 text_translated 是英文，前端拼出
    "中文完整句 + 英文残尾"。

    本函数找出每个"回显 follower + 其前导 leader"，返回它们全体的 id ——
    对这批 id 逐段独立重译(1:1)，leader 拿回自己分片的中文，follower 也有了自己的中文。

    - 回显段：翻译非空但不含任何 CJK 字符（纯英文回显）。
    - 缺失段（无翻译）：不算回显，仍交给现有 fill pass 处理。
    - leader：回显段往前、跳过连续回显后遇到的第一个非回显段。
    """
    n = len(segments)
    is_echo = []
    for seg in segments:
        t = (translations_by_id.get(seg.id) or "")
        is_echo.append(bool(t.strip()) and not _has_cjk(t))
    needs: set = set()
    for i in range(n):
        if not is_echo[i]:
            continue
        needs.add(segments[i].id)
        j = i - 1
        while j >= 0 and is_echo[j]:
            needs.add(segments[j].id)
            j -= 1
        if j >= 0:
            needs.add(segments[j].id)  # leader
    return needs


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

    async def translate_batch(batch: List, batch_idx: int, skip_progress: bool = False) -> List[Dict]:
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

                # 验证 ID 对齐。
                # LLM 偶尔会漏掉 1-2 个 id（token 限制或疏忽）。之前用严格 != 整批丢弃，
                # 导致大部分批次全废、翻译几乎为空。改为只警告、保留已有的部分翻译，
                # 下游（pipeline 的 merge / apply_translations）按 id 合并，缺的 segment
                # 保持未翻译。
                input_ids = {seg.id for seg in batch}
                output_ids = {t.get("id") for t in translations if t.get("id") is not None}
                missing = input_ids - output_ids
                if missing:
                    logger.warning(
                        f"Batch {batch_idx}: LLM 漏掉 {len(missing)} 个 id（保留其余 {len(output_ids & input_ids)} 条）"
                    )

                if progress_cb and not skip_progress:
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

    # === 补漏 pass ===
    # LLM 偶尔会漏掉几个 id（token 限制或疏忽），主流程只警告不重试，
    # 导致最终 transcript 出现零星未翻译 segment（如 1973/1980）。
    # 这里收集所有缺失的 segment，用更小的 batch 重试，仍失败的逐个兜底。
    # 这是"缺 X 个 segment"问题的根治方案。
    all_ids = {s.id for s in segments}

    async def _fill(missing_segs: List, batch_sz: int) -> None:
        if not missing_segs:
            return
        batches = [
            (missing_segs[i:i + batch_sz], i // batch_sz)
            for i in range(0, len(missing_segs), batch_sz)
        ]
        res = await asyncio.gather(*[
            translate_batch(b, idx, skip_progress=True) for b, idx in batches
        ])
        for r in res:
            translations.extend(r)

    def _missing() -> List:
        done = {t.get("id") for t in translations if t.get("id") is not None}
        return [s for s in segments if s.id not in done]

    after_main = _missing()
    if after_main:
        logger.info(f"[fill] 主流程漏 {len(after_main)} 个，用 batch=4 补翻")
        await _fill(after_main, 4)
        still = _missing()
        if still:
            logger.info(f"[fill] 仍漏 {len(still)} 个，逐个兜底")
            await _fill(still, 1)
        done = {t.get("id") for t in translations if t.get("id") is not None}
        covered = len(done & all_ids)
        miss_ids = sorted(all_ids - done)
        logger.info(
            f"[fill] 最终覆盖率 {covered}/{len(all_ids)} ({covered / len(all_ids):.2%})，"
            f"仍缺 {len(miss_ids)} 个{(' id=' + str(miss_ids[:20])) if miss_ids else ''}"
        )

    # === 合并组修复 pass ===
    # ASR 常把一句话切成多段分片。LLM 批量翻译时会把连续分片合并成一句完整中文、
    # 写到首段(leader)，其余 follower 原样回显英文（"中文完整句 + 英文残尾"的根因）。
    # 现有 fill 只补"缺失 id"，识别不了"存在但回显英文"的段。这里把每个合并组
    # (回显 follower + 其 leader) 逐段独立重译(batch=1，无跨段上下文 → LLM 无法再合并)，
    # 让每段都拿到与自身英文/时间戳对齐的中文。
    by_id = {t.get("id"): (t.get("text_zh") or "") for t in translations if t.get("id") is not None}
    needs_ids = _merge_group_ids(segments, by_id)
    if needs_ids:
        need_segs = [s for s in segments if s.id in needs_ids]
        logger.info(f"[merge-repair] 检出 {len(need_segs)} 段合并组(回显+leader)，逐段 1:1 重译")
        repair = await asyncio.gather(*[
            translate_batch([s], idx, skip_progress=True)
            for idx, s in enumerate(need_segs)
        ])
        repaired_map = {
            r.get("id"): r
            for batch_r in repair
            for r in batch_r
            if r.get("id") is not None
        }
        if repaired_map:
            # 重译成功的 id：用新结果替换旧翻译；失败的 id 保留旧翻译(不丢段)
            translations = [t for t in translations if t.get("id") not in repaired_map]
            translations.extend(repaired_map.values())
            logger.info(f"[merge-repair] 重译 {len(repaired_map)} 段")

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
