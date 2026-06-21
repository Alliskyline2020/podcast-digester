"""
数据库迁移：将派生数据从文件系统迁移到数据库

新增表：
- outline（章节大纲）
- summaries（章节摘要）
- highlight（亮点金句）
- product_insights（产品洞察）

迁移策略：
1. 创建新表
2. 从文件系统读取现有数据
3. 导入到数据库
4. 保持文件系统作为备份
"""

import aiosqlite
import sqlite3
import json
from pathlib import Path
from typing import Dict, Any
from datetime import datetime

from app.config import DB_PATH, DATA_DIR


async def migrate_derived_data_to_db():
    """执行迁移：将派生数据从文件系统迁移到数据库"""

    print("="*60)
    print("开始迁移派生数据到数据库...")
    print("="*60)

    # 1. 创建新表
    await _create_tables()

    # 2. 迁移现有数据
    await _migrate_existing_data()

    print("\n迁移完成！")
    print("提示：原文件系统数据仍保留作为备份")


async def _create_tables():
    """创建新表"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        -- 章节大纲表
        CREATE TABLE IF NOT EXISTS outline (
            episode_id TEXT PRIMARY KEY,
            entries_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (episode_id) REFERENCES episode(id) ON DELETE CASCADE
        );

        -- 章节摘要表
        CREATE TABLE IF NOT EXISTS summaries (
            episode_id TEXT PRIMARY KEY,
            summaries_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (episode_id) REFERENCES episode(id) ON DELETE CASCADE
        );

        -- 亮点金句表
        CREATE TABLE IF NOT EXISTS highlight (
            episode_id TEXT PRIMARY KEY,
            highlights_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (episode_id) REFERENCES episode(id) ON DELETE CASCADE
        );

        -- 产品洞察表
        CREATE TABLE IF NOT EXISTS product_insights (
            episode_id TEXT PRIMARY KEY,
            insights_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (episode_id) REFERENCES episode(id) ON DELETE CASCADE
        );

        -- 创建索引
        CREATE INDEX IF NOT EXISTS idx_outline_updated ON outline(updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_summaries_updated ON summaries(updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_highlight_updated ON highlight(updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_product_insights_updated ON product_insights(updated_at DESC);
        """)

        await db.commit()
        print("✓ 创建新表成功")


async def _migrate_existing_data():
    """迁移现有数据"""

    # 获取所有episode
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM episode WHERE status = 'ready'")
    episode_ids = [row[0] for row in cursor.fetchall()]
    conn.close()

    print(f"\n找到 {len(episode_ids)} 个已完成的节目")

    async with aiosqlite.connect(DB_PATH) as db:
        for episode_id in episode_ids:
            media_dir = DATA_DIR / "media" / episode_id

            # 读取各个文件
            outline_data = _read_json_file(media_dir / "outline.json")
            summaries_data = _read_json_file(media_dir / "summaries.json")
            highlight_data = _read_json_file(media_dir / "highlight.json")
            insights_data = _read_json_file(media_dir / "product_insights.json")

            # 插入到数据库
            now = datetime.now().isoformat()

            if outline_data:
                await db.execute(
                    "INSERT OR REPLACE INTO outline (episode_id, entries_json, updated_at) VALUES (?, ?, ?)",
                    (episode_id, json.dumps(outline_data, ensure_ascii=False), now)
                )

            if summaries_data:
                await db.execute(
                    "INSERT OR REPLACE INTO summaries (episode_id, summaries_json, updated_at) VALUES (?, ?, ?)",
                    (episode_id, json.dumps(summaries_data, ensure_ascii=False), now)
                )

            if highlight_data:
                await db.execute(
                    "INSERT OR REPLACE INTO highlight (episode_id, highlights_json, updated_at) VALUES (?, ?, ?)",
                    (episode_id, json.dumps(highlight_data, ensure_ascii=False), now)
                )

            if insights_data:
                await db.execute(
                    "INSERT OR REPLACE INTO product_insights (episode_id, insights_json, updated_at) VALUES (?, ?, ?)",
                    (episode_id, json.dumps(insights_data, ensure_ascii=False), now)
                )

            await db.commit()
            print(f"  ✓ 迁移 {episode_id}")


def _read_json_file(file_path: Path) -> Dict[str, Any]:
    """安全读取JSON文件"""
    if file_path.exists():
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"  ⚠️  读取 {file_path.name} 失败: {e}")
            return {}
    return {}


if __name__ == "__main__":
    import asyncio
    asyncio.run(migrate_derived_data_to_db())
