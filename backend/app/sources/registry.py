"""
Source 解析器注册表
按优先级顺序匹配
"""
from .base import BaseSourceParser, ParseResult
from .fixture import FixtureParser
from .local import LocalFileParser
from .youtube import YouTubeParser
from .bilibili import BilibiliParser
from .douyin import DouyinParser
from .xiaoyuzhou import XiaoyuzhouParser


# 越靠前优先级越高
_PARSERS: list[BaseSourceParser] = [
    FixtureParser(),       # fixture id 精确匹配
    LocalFileParser(),     # 本地路径
    DouyinParser(),        # douyin.com / v.douyin.com
    XiaoyuzhouParser(),    # xiaoyuzhou.fm
    BilibiliParser(),      # bilibili.com / b23.tv
    YouTubeParser(),       # youtube.com / youtu.be
]

# 按 PRIORITY 排序
_PARSERS.sort(key=lambda p: p.PRIORITY)


async def resolve_source(raw_input: str) -> BaseSourceParser:
    """
    根据输入匹配对应的 Source 解析器

    Args:
        raw_input: 用户输入的 URL 或路径

    Returns:
        匹配的解析器

    Raises:
        ValueError: 无法找到匹配的解析器
    """
    for parser in _PARSERS:
        if await parser.matches(raw_input):
            return parser

    raise ValueError(f"无法识别的输入格式: {raw_input}")


def get_supported_sources() -> list[dict]:
    """获取所有支持的来源信息"""
    return [
        {
            "name": parser.__class__.__name__,
            "priority": parser.PRIORITY,
            "description": getattr(parser, "DESCRIPTION", ""),
        }
        for parser in _PARSERS
    ]
