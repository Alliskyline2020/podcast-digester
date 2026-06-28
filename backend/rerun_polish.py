"""批量对中文 episode 的字幕做优化(加标点 + 去口水话)。

用法:python rerun_polish.py
"""
import asyncio
import json
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.config import DB_PATH
from app.services.subtitle_polisher import polish_episode_subtitles

DATA_DIR = Path(DB_PATH).parent


async def main():
    conn = sqlite3.connect(DB_PATH)
    # 只处理 ready + language=zh 的 episode
    rows = conn.execute(
        "SELECT id, title, language FROM episode WHERE status='ready' AND language='zh' ORDER BY created_at"
    ).fetchall()
    conn.close()

    print(f"=== 字幕优化(加标点 + 去口水话)===")
    print(f"待处理: {len(rows)} 个中文 episode")
    print(f"开始: {time.strftime('%H:%M:%S')}\n")

    results = []
    for ep_id, title, lang in rows:
        print(f">>> {ep_id}")
        print(f"    title: {(title or '')[:60]}")
        start = time.time()
        try:
            r = await polish_episode_subtitles(ep_id, DATA_DIR)
            elapsed = time.time() - start
            if r.get("skipped"):
                print(f"    ⏭️  跳过: {r.get('reason')}")
            elif r.get("error"):
                print(f"    ❌ 失败: {r['error']}")
            else:
                print(f"    ✅ {r.get('polished', 0)}/{r.get('total', 0)} 句优化 ({elapsed:.1f}s)")
            r["elapsed"] = elapsed
            results.append(r)
        except Exception as e:
            print(f"    ❌ 异常: {str(e)[:200]}")
            results.append({"episode_id": ep_id, "error": str(e)})
        print()

    # 汇总
    print(f"{'='*60}")
    ok = sum(1 for r in results if r.get("polished", 0) > 0)
    total_polished = sum(r.get("polished", 0) for r in results)
    total_segs = sum(r.get("total", 0) for r in results)
    print(f"完成: {ok}/{len(results)} 个 episode 成功")
    print(f"总优化句数: {total_polished}/{total_segs}")
    print(f"结束: {time.strftime('%H:%M:%S')}")


if __name__ == "__main__":
    asyncio.run(main())
