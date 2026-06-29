#!/usr/bin/env python3
"""重跑 SubtitleProcessor 修复已有 episode 的 drift + 补翻译。

每个 episode:
1. 加载 transcript.json
2. 快照关键字段 → polish → translate → 断言不可变性
3. 写回 transcript.json + DB
4. 打印覆盖率(text_with_punct / text_translated)

强制覆盖已有 text_with_punct(skip_if_punctuated=False 语义: polish 总是重算并校验)。
"""
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.services.subtitle_processor import SubtitleProcessor
from app.models import Transcript
from app.database import EpisodeRepository

DATA_DIR = Path(__file__).parent.parent / "data" / "media"
DONE_MARKER = ".sp_processed"
processor = SubtitleProcessor()


def coverage(segments: list) -> dict:
    n = len(segments)
    with_orig = sum(1 for s in segments if (s.text_original or "").strip())
    with_punct = sum(1 for s in segments if (s.text_with_punct or "").strip())
    with_trans = sum(1 for s in segments if (s.text_translated or "").strip())
    return {
        "total": n,
        "text_with_punct": f"{with_punct}/{with_orig}",
        "text_translated": f"{with_trans}/{n}",
    }


async def process_one(ep_dir: Path) -> dict:
    tf = ep_dir / "transcript.json"
    if not tf.exists():
        return {"episode": ep_dir.name, "error": "no transcript.json"}
    data = json.loads(tf.read_text(encoding="utf-8"))
    transcript = Transcript.model_validate(data)

    snap = processor._snapshot(transcript)
    polished = await processor.polish(transcript)
    translated = await processor.translate(transcript)
    processor._assert_immutability(snap, transcript)  # 时间戳/原文/段数未变

    data["segments"] = [s.model_dump() for s in transcript.segments]
    tf.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = await EpisodeRepository.update_transcript(transcript.episode_id, data)
    # 仅在 DB 写入成功后落 marker，中断后可断点续跑；失败则下次重试该 episode。
    if ok:
        (ep_dir / DONE_MARKER).write_text("ok", encoding="utf-8")

    return {
        "episode": ep_dir.name,
        "language": transcript.language,
        "polished": polished,
        "translated": translated,
        **coverage(transcript.segments),
    }


async def main():
    episodes = sorted(p for p in DATA_DIR.iterdir() if (p / "transcript.json").exists())
    print(f">>> 发现 {len(episodes)} 个 episode")
    results = []
    for ep in episodes:
        if (ep / DONE_MARKER).exists():
            print(f">>> 跳过 {ep.name}（已处理，删除 .sp_processed 可重跑）", flush=True)
            continue
        print(f">>> 处理 {ep.name} ...", flush=True)
        try:
            r = await process_one(ep)
        except Exception as e:
            r = {"episode": ep.name, "error": str(e)}
            print(f"    ❌ {e}", flush=True)
        print(f"    {r}", flush=True)
        results.append(r)
    print("=== 汇总 ===")
    for r in results:
        print(r)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(main())
