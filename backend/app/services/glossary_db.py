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
        """加载词库（同步,直接 sqlite3 读)。

        原实现用 asyncio.create_task fire-and-forget,在 FastAPI 异步上下文里
        __init__ 立即返回时 cache 还是空的,首次 get_entries() 拿到 0 条。
        改成同步读取,确保 cache 在 __init__ 后立即可用。
        """
        import sqlite3
        import json
        import logging
        from app.config import DB_PATH

        self.cache = {}
        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("SELECT correct, wrong_list FROM glossary")
                for row in cursor.fetchall():
                    self.cache[row['correct']] = json.loads(row['wrong_list'])
        except Exception as e:
            logging.getLogger(__name__).warning(f"glossary 加载失败: {e}")

    async def _async_load(self):
        """异步加载词库"""
        from app.repositories import GlossaryRepository
        self.cache = await GlossaryRepository.get_all()

    async def save(self):
        """保存词库（实际上数据已经保存在数据库中，此方法为兼容性保留）"""
        # 数据库版本不需要显式保存，每次操作都立即持久化
        pass

    def add_entry(self, correct: str, wrong: List[str]) -> None:
        """添加词库条目(同步)。

        原实现用 asyncio.create_task fire-and-forget,router async handler
        调用时实际没等待,cache 不更新,DB 写也可能丢失。改成同步 sqlite3。
        """
        import sqlite3
        import json
        import logging
        from app.config import DB_PATH
        from datetime import datetime

        # 合并已存在条目
        if correct in self.cache:
            existing = set(self.cache[correct])
            existing.update(wrong)
            wrong = list(existing)

        now = datetime.now().isoformat()
        wrong_json = json.dumps(wrong, ensure_ascii=False)

        try:
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
            # 同步更新 cache,立即可读
            self.cache[correct] = wrong
        except Exception as e:
            logging.getLogger(__name__).warning(f"glossary add_entry 失败: {e}")

    def remove_entry(self, correct: str) -> None:
        """删除词库条目(同步)。

        原实现是 async,但 router 没 await(直接 glossary.remove_entry(correct)),
        返回的 coroutine 被丢弃 → 完全不工作。改成同步。
        """
        import sqlite3
        import logging
        from app.config import DB_PATH

        try:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("DELETE FROM glossary WHERE correct = ?", (correct,))
            if correct in self.cache:
                del self.cache[correct]
        except Exception as e:
            logging.getLogger(__name__).warning(f"glossary remove_entry 失败: {e}")

    def correct_text(self, text: str) -> str:
        """使用词库纠正文本(占位符法,避免子串过度替换)。

        原实现直接 replace,当 wrong 是 correct 的子串时会过度替换:
        例如 词库 "张小珺 ← 小珺",文本 "张小珺" 里的 "小珺" 会被
        替换成 "张小珺",变成 "张张小珺"。

        修复用三步占位符法:
        1. 把所有 correct 词替换成唯一占位符(保护它们)
        2. 替换所有 wrong → 对应 correct(此时占位符不会被错误命中)
        3. 恢复占位符为 correct
        """
        if not text:
            return text

        # 第一步:保护所有 correct 词(替换成占位符)
        placeholders = {}
        result = text
        for i, correct in enumerate(self.cache.keys()):
            if correct and correct in result:
                ph = f"\x00PH{i}\x00"
                placeholders[ph] = correct
                result = result.replace(correct, ph)

        # 第二步:替换 wrong → correct(占位符不受影响)
        for correct, wrong_list in self.cache.items():
            for wrong in (wrong_list or []):
                if wrong and wrong in result:
                    result = result.replace(wrong, correct)

        # 第三步:恢复占位符
        for ph, correct in placeholders.items():
            result = result.replace(ph, correct)

        return result

    def correct_transcript(self, transcript_data: dict) -> tuple[dict, int]:
        """使用词库纠正转录文本(同步)。

        原实现是 async,但 routers/subtitles.py 的 apply_glossary_to_episode
        同步调用(await 缺失),导致 cannot unpack coroutine 报 500。
        纯字符串操作不需要 async,改成同步。
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
