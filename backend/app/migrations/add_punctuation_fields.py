"""
数据库迁移：添加字幕标点字段支持

新增字段：
- episode.text_with_punct: 存储带标点的字幕JSON（可选）
- transcript段落的text_with_punct字段

迁移策略：
1. 添加text_with_punct字段到episode表（可选）
2. 不强制迁移现有数据（按需处理）
3. 在处理新字幕时自动生成带标点版本
"""

import aiosqlite
import sqlite3
import json
from pathlib import Path
from typing import Dict, Any

from app.config import DB_PATH, DATA_DIR


async def add_punctuation_fields():
    """添加标点字段支持"""
    print("="*60)
    print("添加字幕标点字段支持...")
    print("="*60)

    async with aiosqlite.connect(DB_PATH) as db:
        # 添加 text_with_punct 字段到 episode 表（可选，用于快速查询）
        try:
            await db.execute("""
                ALTER TABLE episode
                ADD COLUMN text_with_punct TEXT
            """)
            print("✓ 添加 episode.text_with_punct 字段")
        except Exception as e:
            if "duplicate column" in str(e):
                print("✓ episode.text_with_punct 字段已存在")
            else:
                print(f"⚠️  添加字段失败: {e}")

        await db.commit()
        print("\n迁移完成！")
        print("注意：现有字幕不会自动添加标点，需要手动触发处理")


def migrate_existing_transcripts():
    """
    迁移现有transcript.json文件，添加text_with_punct字段

    这是一个独立函数，可以按需运行
    """
    print("="*60)
    print("迁移现有字幕文件...")
    print("="*60)

    media_dir = DATA_DIR / "media"

    # 找到所有已完成的节目
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM episode WHERE status = 'ready'")
    episode_ids = [row[0] for row in cursor.fetchall()]
    conn.close()

    print(f"\n找到 {len(episode_ids)} 个已完成的节目")

    updated_count = 0
    for episode_id in episode_ids:
        transcript_file = media_dir / episode_id / "transcript.json"

        if not transcript_file.exists():
            continue

        try:
            with open(transcript_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 检查是否已经有 text_with_punct
            if "segments" in data:
                has_punct = any(
                    "text_with_punct" in seg
                    for seg in data["segments"]
                )

                if not has_punct:
                    # 为每个段落添加 text_with_punct 字段（初始等于text_original）
                    for seg in data["segments"]:
                        seg["text_with_punct"] = seg.get("text_original", "")

                    # 保存
                    with open(transcript_file, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)

                    updated_count += 1
                    print(f"  ✓ 更新 {episode_id}")

        except Exception as e:
            print(f"  ⚠️  更新 {episode_id} 失败: {e}")

    print(f"\n完成！更新了 {updated_count} 个字幕文件")


if __name__ == "__main__":
    import asyncio

    # 添加字段支持
    asyncio.run(add_punctuation_fields())

    # 可选：迁移现有文件
    # migrate_existing_transcripts()
