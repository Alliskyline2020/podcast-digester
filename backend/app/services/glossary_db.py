"""
专业词库管理（数据库版本）

提供线程安全的词库操作，使用SQLite存储
"""
from pathlib import Path
from typing import Dict, List, Optional
import re


class Glossary:
    """专业词库（线程安全版本）"""

    def __init__(self, data_dir: Path):
        """
        初始化词库

        Args:
            data_dir: 数据目录
        """
        self.data_dir = data_dir
        self.cache = {}
        self._load()

    def _load(self):
        """加载词库（从数据库）"""
        # 异步加载在第一次调用时执行
        import asyncio
        try:
            # 尝试获取运行中的事件循环
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 如果在异步上下文中，创建任务
                asyncio.create_task(self._async_load())
            else:
                # 如果没有运行中的循环，直接运行
                loop.run_until_complete(self._async_load())
        except RuntimeError:
            # 如果没有事件循环，使用同步方式
            import sqlite3
            import json
            from app.config import DB_PATH

            # 用 with 确保 conn 在任何路径下都被关闭
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("SELECT correct, wrong_list FROM glossary")
                rows = cursor.fetchall()
                self.cache = {}
                for row in rows:
                    self.cache[row['correct']] = json.loads(row['wrong_list'])

    async def _async_load(self):
        """异步加载词库"""
        from app.repositories import GlossaryRepository
        self.cache = await GlossaryRepository.get_all()

    async def save(self):
        """保存词库（实际上数据已经保存在数据库中，此方法为兼容性保留）"""
        # 数据库版本不需要显式保存，每次操作都立即持久化
        pass

    def add_entry(self, correct: str, wrong: List[str]) -> None:
        """
        添加词库条目（同步版本，用于兼容）

        Args:
            correct: 正确的词汇
            wrong: 错误的词汇列表
        """
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self._async_add_entry(correct, wrong))
            else:
                loop.run_until_complete(self._async_add_entry(correct, wrong))
        except RuntimeError:
            # 回退到同步操作
            import sqlite3
            import json
            from app.config import DB_PATH
            from datetime import datetime

            now = datetime.now().isoformat()
            wrong_json = json.dumps(wrong, ensure_ascii=False)

            # with 语句会在退出块时自动 commit/rollback，并关闭连接资源
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute(
                    """
                    INSERT INTO glossary (correct, wrong_list, created_at, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(correct) DO UPDATE SET
                        wrong_list = excluded.wrong_list,
                        updated_at = excluded.updated_at
                    """,
                    (correct, wrong_json, now, now)
                )

    async def _async_add_entry(self, correct: str, wrong: List[str]) -> None:
        """异步添加词库条目"""
        from app.repositories import GlossaryRepository

        if correct in self.cache:
            # 合并已存在的条目
            existing = set(self.cache[correct])
            existing.update(wrong)
            wrong = list(existing)

        await GlossaryRepository.add_entry(correct, wrong)
        # 更新缓存
        self.cache[correct] = await GlossaryRepository.get_entry(correct)

    async def remove_entry(self, correct: str) -> None:
        """
        删除词库条目

        Args:
            correct: 要删除的正确词汇
        """
        from app.repositories import GlossaryRepository

        await GlossaryRepository.remove_entry(correct)
        if correct in self.cache:
            del self.cache[correct]

    def correct_text(self, text: str) -> str:
        """
        使用词库纠正文本

        Args:
            text: 原始文本

        Returns:
            纠正后的文本
        """
        if not text:
            return text

        result = text

        # 按长度降序排序，优先匹配长词组
        for correct, wrong_list in sorted(
            self.cache.items(),
            key=lambda x: len(x[0]),
            reverse=True
        ):
            for wrong in wrong_list:
                result = result.replace(wrong, correct)

        return result

    async def correct_transcript(self, transcript_data: dict) -> tuple[dict, int]:
        """
        使用词库纠正转录文本

        Args:
            transcript_data: 转录数据字典

        Returns:
            (纠正后的transcript_data, 纠正的segment数量)
        """
        segments = transcript_data.get("segments", [])
        corrected_count = 0

        for seg in segments:
            original = seg.get("text_original", "")
            corrected = self.correct_text(original)

            if corrected != original:
                seg["text_original"] = corrected
                corrected_count += 1

        return transcript_data, corrected_count

    async def get_entries(self) -> Dict[str, List[str]]:
        """
        获取所有词库条目

        Returns:
            词库字典 {correct: [wrong1, wrong2, ...]}
        """
        return self.cache.copy()

    async def get_stats(self) -> dict:
        """
        获取词库统计信息

        Returns:
            统计信息字典
        """
        return {
            "total_entries": len(self.cache),
            "total_wrong_words": sum(len(v) for v in self.cache.values()),
        }
