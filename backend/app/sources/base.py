"""
Source 解析器基类和数据结构
"""
from pathlib import Path
from typing import Optional, Callable, Any
from dataclasses import dataclass
from ..models import Transcript


@dataclass
class ParseResult:
    """解析结果"""
    title: str
    audio_path: Path
    source_type: str
    duration_ms: Optional[int] = None
    language: Optional[str] = None
    extra: dict = None

    def __post_init__(self):
        if self.extra is None:
            self.extra = {}


class BaseSourceParser:
    """Source 解析器基类"""

    # 解析器优先级（数字越小优先级越高）
    PRIORITY: int = 100

    async def matches(self, raw_input: str) -> bool:
        """
        检测输入是否匹配此解析器

        Args:
            raw_input: 用户输入的 URL 或路径

        Returns:
            True 表示此解析器可以处理该输入
        """
        raise NotImplementedError

    async def parse(
        self,
        raw_input: str,
        episode_id: str,
        out_dir: Path,
        on_progress: Optional[Callable[[str, float], Any]] = None,
    ) -> ParseResult:
        """
        解析输入并下载媒体

        Args:
            raw_input: 用户输入
            episode_id: 节目 ID
            out_dir: 输出目录
            on_progress: 进度回调 (stage, progress) -> None

        Returns:
            ParseResult 包含标题、音频路径、可选的预转录等
        """
        raise NotImplementedError
