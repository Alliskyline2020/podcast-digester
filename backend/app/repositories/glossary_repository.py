"""
词库数据访问层（数据库版本）

提供线程安全的词库操作
"""
import aiosqlite
import json
from typing import Dict, List, Optional
from datetime import datetime

from app.config import DB_PATH


class GlossaryRepository:
    """词库数据访问"""

    @staticmethod
    async def get_all() -> Dict[str, List[str]]:
        """获取所有词库条目"""
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT correct, wrong_list FROM glossary") as cursor:
                rows = await cursor.fetchall()
                result = {}
                for row in rows:
                    correct = row['correct']
                    wrong_list = json.loads(row['wrong_list'])
                    result[correct] = wrong_list
                return result

    @staticmethod
    async def get_entry(correct: str) -> Optional[List[str]]:
        """获取单个词库条目"""
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT wrong_list FROM glossary WHERE correct = ?",
                (correct,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return json.loads(row['wrong_list'])
                return None

    @staticmethod
    async def add_entry(correct: str, wrong_list: List[str]) -> bool:
        """添加词库条目"""
        async with aiosqlite.connect(DB_PATH) as db:
            now = datetime.now().isoformat()
            wrong_json = json.dumps(wrong_list, ensure_ascii=False)

            await db.execute(
                """
                INSERT INTO glossary (correct, wrong_list, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(correct) DO UPDATE SET
                    wrong_list = CASE
                        WHEN wrong_list = '' THEN excluded.wrong_list
                        ELSE json_merge_patch(
                            COALESCE(
                                json_extract(glossary.wrong_list, '$'),
                                '[]'
                            ),
                            ?,
                            '[]'
                        )
                    END,
                    updated_at = excluded.updated_at
                """,
                (correct, wrong_json, now, now)
            )
            await db.commit()
            return True

    @staticmethod
    async def remove_entry(correct: str) -> bool:
        """删除词库条目"""
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "DELETE FROM glossary WHERE correct = ?",
                (correct,)
            )
            await db.commit()
            return True

    @staticmethod
    async def update_entry(correct: str, wrong_list: List[str]) -> bool:
        """更新词库条目"""
        async with aiosqlite.connect(DB_PATH) as db:
            now = datetime.now().isoformat()
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
            return True

    @staticmethod
    async def merge_entry(correct: str, new_wrong_list: List[str]) -> bool:
        """合并词库条目（不覆盖已有错误词）"""
        async with aiosqlite.connect(DB_PATH) as db:
            # 获取现有条目
            existing = await GlossaryRepository.get_entry(correct)

            if existing:
                # 合并错误词列表
                merged = list(set(existing + new_wrong_list))
                return await GlossaryRepository.update_entry(correct, merged)
            else:
                # 新条目
                return await GlossaryRepository.add_entry(correct, new_wrong_list)
