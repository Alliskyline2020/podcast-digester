"""
数据库迁移：将词库从文件系统迁移到数据库

词库表结构：
- correct: 正确词汇（主键）
- wrong_list: 错误词汇列表（JSON数组）
- created_at: 创建时间
- updated_at: 更新时间
"""

import aiosqlite
import sqlite3
import json
from pathlib import Path
from datetime import datetime

from app.config import DB_PATH, DATA_DIR


async def migrate_glossary_to_db():
    """执行迁移：将词库从文件系统迁移到数据库"""

    print("="*60)
    print("开始迁移词库到数据库...")
    print("="*60)

    # 1. 创建表
    await _create_table()

    # 2. 迁移现有数据
    await _migrate_existing_data()

    print("\n迁移完成！")


async def _create_table():
    """创建词库表"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS glossary (
            correct TEXT PRIMARY KEY,
            wrong_list TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_glossary_updated ON glossary(updated_at DESC);
        """)
        await db.commit()
        print("✓ 创建glossary表成功")


async def _migrate_existing_data():
    """迁移现有词库数据"""
    glossary_file = DATA_DIR / "glossary.json"

    if not glossary_file.exists():
        print("⚠️  未找到现有词库文件，将使用默认词库")
        # 使用默认词库
        default_entries = {
            "张小珺": ["小军", "张小君", "小珺"],
            "谢赛宁": ["赛宁", "谢赛林"],
            "奥特曼": ["奥特别", "奥特慢"],
            "纽约": ["妞约"],
            "硅谷": ["硅固", "归谷"],
            "人工智能": ["人工只能", "人之智能"],
            "区块链": ["区块练", "区块连"],
            "元宇宙": ["元宇审", "元宇宙"],
        }
        await _save_entries(default_entries)
        print(f"✓ 导入默认词库 ({len(default_entries)} 条)")
        return

    # 读取现有词库
    try:
        with open(glossary_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            entries = data.get('entries', {})

        await _save_entries(entries)
        print(f"✓ 导入现有词库 ({len(entries)} 条)")

    except Exception as e:
        print(f"⚠️  读取词库文件失败: {e}")
        print("将使用默认词库")


async def _save_entries(entries: dict):
    """保存词库条目到数据库"""
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.now().isoformat()

        for correct, wrong_list in entries.items():
            wrong_json = json.dumps(wrong_list, ensure_ascii=False)
            await db.execute(
                """
                INSERT INTO glossary (correct, wrong_list, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(correct) DO UPDATE SET
                    wrong_list = excluded.wrong_list,
                    updated_at = excluded.updated_at
                """,
                (correct, wrong_json, now, now)
            )

        await db.commit()


if __name__ == "__main__":
    import asyncio
    asyncio.run(migrate_glossary_to_db())
