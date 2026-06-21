"""
专业词库管理

用于维护和存储常见的转录错误和正确词汇映射
"""
import json
from pathlib import Path
from typing import Dict, List, Optional
import re


class Glossary:
    """专业词库"""

    def __init__(self, data_dir: Path):
        """
        初始化词库

        Args:
            data_dir: 数据目录
        """
        self.data_dir = data_dir
        self.glossary_file = data_dir / "glossary.json"
        self.cache = {}
        self._load()

    def _load(self):
        """加载词库"""
        if self.glossary_file.exists():
            with open(self.glossary_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.cache = data.get('entries', {})
        else:
            # 默认词库
            self.cache = {
                # 人名
                "张小珺": ["小军", "张小君", "小珺"],
                "谢赛宁": ["赛宁", "谢赛林"],
                "奥特曼": ["奥特别", "奥特慢"],
                # 地名
                "纽约": ["妞约"],
                "硅谷": ["硅固", "归谷"],
                # 常见科技词汇
                "人工智能": ["人工只能", "人之智能"],
                "区块链": ["区块练", "区块连"],
                "元宇宙": ["元宇审", "元宇宙"],
            }
            self._save()

    def _save(self):
        """保存词库"""
        self.glossary_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.glossary_file, 'w', encoding='utf-8') as f:
            json.dump({"entries": self.cache}, f, ensure_ascii=False, indent=2)

    def add_entry(self, correct: str, wrong: List[str]) -> None:
        """
        添加词库条目

        Args:
            correct: 正确的词汇
            wrong: 错误的词汇列表
        """
        if correct in self.cache:
            # 合并已存在的条目
            existing = set(self.cache[correct])
            existing.update(wrong)
            self.cache[correct] = list(existing)
        else:
            self.cache[correct] = wrong

        self._save()

    def remove_entry(self, correct: str) -> None:
        """
        删除词库条目

        Args:
            correct: 正确的词汇
        """
        if correct in self.cache:
            del self.cache[correct]
            self._save()

    def get_all_entries(self) -> Dict[str, List[str]]:
        """获取所有词库条目"""
        return self.cache.copy()

    def correct_text(self, text: str) -> str:
        """
        使用词库纠正文本

        Args:
            text: 待纠正的文本

        Returns:
            纠正后的文本
        """
        if not text:
            return text

        corrected = text

        # 按长度降序排序（优先匹配更长的词）
        for correct, wrong_list in sorted(
            self.cache.items(),
            key=lambda x: len(x[0]),
            reverse=True
        ):
            for wrong in wrong_list:
                # 精确匹配替换
                corrected = corrected.replace(wrong, correct)

        return corrected

    def correct_transcript(self, transcript_data: dict) -> tuple[dict, int]:
        """
        纠正完整字幕数据

        Args:
            transcript_data: 字幕数据

        Returns:
            (纠正后的字幕数据, 纠正的segment数量)
        """
        segments = transcript_data.get("segments", [])
        corrected_count = 0

        for seg in segments:
            original = seg.get("text_original", "")
            corrected = self.correct_text(original)

            if corrected != original:
                seg["text_original"] = corrected
                seg["text_corrected"] = True
                corrected_count += 1

        transcript_data["segments"] = segments
        return transcript_data, corrected_count

    def find_mistakes(self, text: str) -> List[Dict]:
        """
        在文本中查找可能的错误

        Args:
            text: 待检查的文本

        Returns:
            发现的错误列表 [{"wrong": "错误词", "correct": "正确词", "position": 位置}]
        """
        mistakes = []

        for correct, wrong_list in self.cache.items():
            for wrong in wrong_list:
                if wrong in text:
                    # 查找所有出现位置
                    start = 0
                    while True:
                        pos = text.find(wrong, start)
                        if pos == -1:
                            break
                        mistakes.append({
                            "wrong": wrong,
                            "correct": correct,
                            "position": pos,
                            "length": len(wrong)
                        })
                        start = pos + 1

        # 按位置排序
        mistakes.sort(key=lambda x: x["position"])
        return mistakes


# 全局词库实例（延迟加载）
_glossary_instance = None


def get_glossary(data_dir: Path = None) -> Glossary:
    """
    获取词库实例（单例模式，使用数据库版本）

    Args:
        data_dir: 数据目录

    Returns:
        词库实例
    """
    global _glossary_instance

    if _glossary_instance is None:
        if data_dir is None:
            from ..utils.paths import get_data_dir
            data_dir = get_data_dir()
        # 使用数据库版本（线程安全）
        from .glossary_db import Glossary as DBGlossary
        _glossary_instance = DBGlossary(data_dir)

    return _glossary_instance
