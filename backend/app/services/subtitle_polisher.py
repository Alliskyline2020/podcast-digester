"""字幕优化:加正确标点 + 去口水话,不改语义/时间戳。

用户需求:中文 ASR 字幕标点不准 + 口水话多("然后呢""呃对""就是说"),
影响可读性。本服务用 LLM 做两件事:
1. 补充正确标点(根据语义断句)
2. 去除无意义口水话/填充词/重复词

铁律:
- 不改语义(不增删信息,不修正事实)
- 不改时间戳(start_ms/end_ms/id 完全不动)
- 只填充 text_with_punct 字段,text_original 保留作为原始备份
- 输出句数 = 输入句数,一一对应
"""
import json
import logging
from typing import List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


POLISH_SYSTEM = """你是专业的播客字幕编辑。对中文 ASR 字幕做两件事:

1. **补充正确标点**:ASR 输出的标点经常不准或位置错误。根据语义重新加正确的逗号、句号、问号、感叹号、顿号、分号,让字幕自然可读。原标点如果位置错就删掉重加。

2. **去除口水话和无意义填充**:删除"嗯""啊""呃""那个""然后呢""就是说""对吧""你看""的话""就是这个"等口头禅、语气词、无意义重复。但**保留有语义作用的词**:
   - "然后"表时间承接且必要 → 保留
   - "因为"表因果 → 保留
   - 人名/产品名/数字/专业术语 → 原样保留

**绝对铁律(违反任一条都算失败)**:
- 不改变语义,不增删信息,不修正事实错误,不补全省略内容
- 不改变句子核心意思,只优化"怎么说"不改"说什么"
- 输出句数必须严格等于输入句数,按 id 一一对应
- 每句输出必须对应输入的同一句(不改顺序、不合并、不拆分)
- 人名、产品名、公司名、数字、英文术语保持原样(如 Manus、OpenAI、2025)
- 如果某句已经很好(无需改),原样输出"""


def build_polish_user(inputs: List[dict]) -> str:
    """构建字幕优化的 user input。"""
    return f"""以下是 {len(inputs)} 句中文 ASR 字幕,逐句优化(加标点 + 去口水话)。

输入字幕(JSON 数组,每句含 id 和 text):
{json.dumps(inputs, ensure_ascii=False, indent=2)}

输出 JSON(严格格式):
{{
  "polished": [
    {{"id": 0, "text": "第 0 句优化后的文本"}},
    {{"id": 1, "text": "第 1 句优化后的文本"}}
  ]
}}

务必:
- polished 数组长度 = {len(inputs)}(与输入一一对应)
- 每个 id 与输入相同
- 只改标点和口水话,不改语义
- 不合并/拆分句子,不改顺序"""


async def polish_subtitles(
    segments: List,  # List[Segment]
    batch_size: int = 25,
    progress_cb: Optional[callable] = None,
    skip_if_punctuated: bool = True,
) -> tuple[List, int]:
    """批量优化字幕(加标点 + 去口水话)。

    只填充 segment.text_with_punct,其他字段(start_ms/end_ms/id/
    text_original/text_translated)完全不动。时间戳和播放不受影响。

    Args:
        segments: Segment 列表(会被就地修改 text_with_punct)
        batch_size: 每批处理多少句(默认 25,平衡上下文和成本)
        progress_cb: 进度回调 (0-1)
        skip_if_punctuated: 跳过已有 text_with_punct 的 segment(默认 True,
            避免重复处理/覆盖;重跑时只处理失败的)

    Returns:
        (segments, polished_count) 修改后的列表 + 实际优化的句数
    """
    from ..llm import chat_json

    total = len(segments)
    if total == 0:
        return segments, 0

    polished_count = 0
    failed_batches = 0
    skipped = 0

    for start in range(0, total, batch_size):
        batch = segments[start:start + batch_size]
        # 只处理有 text_original 的 segment;可选跳过已处理的
        inputs = []
        batch_to_process = []
        for s in batch:
            if not (s.text_original or "").strip():
                continue
            if skip_if_punctuated and (s.text_with_punct or "").strip():
                skipped += 1
                continue
            inputs.append({"id": s.id, "text": s.text_original or ""})
            batch_to_process.append(s)

        if not inputs:
            continue

        try:
            result = await chat_json(
                system=POLISH_SYSTEM,
                user=build_polish_user(inputs),
                temperature=0.2,
                max_tokens=8000,
                response_format={"type": "json_object"},
            )

            polished_map = {
                p.get("id"): (p.get("text") or "").strip()
                for p in result.get("polished", [])
            }

            batch_polished = 0
            for seg in batch_to_process:
                if seg.id in polished_map:
                    new_text = polished_map[seg.id]
                    if new_text:
                        seg.text_with_punct = new_text
                        batch_polished += 1
                        polished_count += 1

            logger.info(
                f"[polish] {start}-{start+len(batch)}/{total}: "
                f"{batch_polished}/{len(inputs)} 句优化"
            )
        except Exception as e:
            logger.warning(f"[polish] 批 {start}-{start+len(batch)} 失败: {e}")
            failed_batches += 1

        if progress_cb:
            progress_cb((start + len(batch)) / total)

    if failed_batches > 0:
        logger.warning(f"[polish] {failed_batches} 批失败,这些 segment 保留原 text_original")

    logger.info(
        f"[polish] 完成: {polished_count} 句优化, {skipped} 句跳过(已处理), "
        f"{failed_batches} 批失败"
    )
    return segments, polished_count


async def polish_episode_subtitles(
    episode_id: str,
    data_dir: Path,
    batch_size: int = 25,
) -> dict:
    """对单个 episode 的字幕做优化(加标点 + 去口水话)。

    加载 transcript.json → polish → 写回 transcript.json + DB。
    只改 text_with_punct,时间戳/语义不变。

    Returns:
        {"episode_id": ..., "total": ..., "polished": ..., "failed_batches": ...}
    """
    from ..models import Transcript, Segment
    from ..database import EpisodeRepository

    transcript_file = data_dir / "media" / episode_id / "transcript.json"
    if not transcript_file.exists():
        return {"episode_id": episode_id, "error": "transcript.json not found"}

    data = json.loads(transcript_file.read_text(encoding="utf-8"))
    language = data.get("language", "")
    if language != "zh":
        return {"episode_id": episode_id, "skipped": True, "reason": f"language={language}, 只处理中文"}

    segments = [Segment(**s) for s in data.get("segments", [])]
    if not segments:
        return {"episode_id": episode_id, "error": "no segments"}

    total = len(segments)
    logger.info(f"[polish] {episode_id}: {total} segments, language={language}")

    segments, polished_count = await polish_subtitles(segments, batch_size=batch_size)

    # 写回文件 + DB
    data["segments"] = [s.model_dump() for s in segments]
    transcript_file.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    await EpisodeRepository.update_transcript(episode_id, data)

    return {
        "episode_id": episode_id,
        "total": total,
        "polished": polished_count,
    }
