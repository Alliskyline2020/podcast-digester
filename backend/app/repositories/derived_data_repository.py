"""
派生数据访问层

管理从transcript派生的数据（outline/summaries/highlight/product_insights）
这些数据存储在数据库中，确保数据一致性和并发安全
"""
import aiosqlite
import json
from typing import Dict, Any, Optional
from datetime import datetime

from app.database import _connect


class DerivedDataRepository:
    """派生数据访问基类"""

    @staticmethod
    async def get(episode_id: str, table_name: str) -> Optional[Dict[str, Any]]:
        """获取派生数据"""
        async with _connect() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                f"SELECT * FROM {table_name} WHERE episode_id = ?",
                (episode_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    data = dict(row)
                    # 解析JSON字段
                    json_field = None
                    if table_name == "outline":
                        json_field = "entries_json"
                    elif table_name == "summaries":
                        json_field = "summaries_json"
                    elif table_name == "highlight":
                        json_field = "highlights_json"
                    elif table_name == "product_insights":
                        json_field = "insights_json"

                    if json_field and data.get(json_field):
                        try:
                            # 移除_json后缀（而不是rstrip字符）
                            field_name = json_field[:-5] if json_field.endswith("_json") else json_field
                            data[field_name] = json.loads(data[json_field])
                        except json.JSONDecodeError:
                            field_name = json_field[:-5] if json_field.endswith("_json") else json_field
                            data[field_name] = {}

                    return data
                return None

    @staticmethod
    async def set(episode_id: str, table_name: str, data: Dict[str, Any], json_field_name: str) -> bool:
        """保存派生数据"""
        async with _connect() as db:
            json_value = json.dumps(data, ensure_ascii=False)
            now = datetime.now().isoformat()

            await db.execute(
                f"""
                INSERT INTO {table_name} (episode_id, {json_field_name}_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(episode_id) DO UPDATE SET
                    {json_field_name}_json = excluded.{json_field_name}_json,
                    updated_at = excluded.updated_at
                """,
                (episode_id, json_value, now)
            )
            await db.commit()
            return True

    @staticmethod
    async def delete(episode_id: str, table_name: str) -> bool:
        """删除派生数据"""
        async with _connect() as db:
            await db.execute(
                f"DELETE FROM {table_name} WHERE episode_id = ?",
                (episode_id,)
            )
            await db.commit()
            return True


class OutlineRepository(DerivedDataRepository):
    """章节大纲数据访问"""

    @staticmethod
    async def get(episode_id: str) -> Optional[Dict[str, Any]]:
        """获取章节大纲"""
        return await DerivedDataRepository.get(episode_id, "outline")

    @staticmethod
    async def set(episode_id: str, entries: list) -> bool:
        """保存章节大纲"""
        return await DerivedDataRepository.set(episode_id, "outline", entries, "entries")


class SummariesRepository(DerivedDataRepository):
    """章节摘要数据访问"""

    @staticmethod
    async def get(episode_id: str) -> Optional[Dict[str, Any]]:
        """获取章节摘要"""
        return await DerivedDataRepository.get(episode_id, "summaries")

    @staticmethod
    async def set(episode_id: str, summaries: list) -> bool:
        """保存章节摘要"""
        return await DerivedDataRepository.set(episode_id, "summaries", summaries, "summaries")


class HighlightRepository(DerivedDataRepository):
    """亮点金句数据访问"""

    @staticmethod
    async def get(episode_id: str) -> Optional[Dict[str, Any]]:
        """获取亮点金句"""
        return await DerivedDataRepository.get(episode_id, "highlight")

    @staticmethod
    async def set(episode_id: str, highlights: Dict[str, Any]) -> bool:
        """保存亮点金句"""
        return await DerivedDataRepository.set(episode_id, "highlight", highlights, "highlights")


class ProductInsightsRepository(DerivedDataRepository):
    """产品洞察数据访问"""

    @staticmethod
    async def get(episode_id: str) -> Optional[Dict[str, Any]]:
        """获取产品洞察"""
        return await DerivedDataRepository.get(episode_id, "product_insights")

    @staticmethod
    async def set(episode_id: str, insights: Dict[str, Any]) -> bool:
        """保存产品洞察"""
        return await DerivedDataRepository.set(episode_id, "product_insights", insights, "insights")
