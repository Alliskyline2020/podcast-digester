"""
Bilibili 解析器
使用 yt-dlp 下载，支持 Bilibili Cookie
"""
import re
from pathlib import Path
from .base import BaseSourceParser, ParseResult
from .ytdlp_runner import run_ytdlp
from ..utils.validation import validate_url, sanitize_url
from ..utils.video import get_video_title


class BilibiliParser(BaseSourceParser):
    """Bilibili 视频解析器"""

    PRIORITY = 50
    DESCRIPTION = "yt-dlp + UA/Referer 头，支持稿件/BV 号"

    # Bilibili URL 匹配模式
    PATTERNS = [
        r"bilibili\.com/video/BV[a-zA-Z0-9]{10}",
        r"b23\.tv/BV[a-zA-Z0-9]{10}",
        r"bilibili\.com/video/av\d+",
    ]

    async def matches(self, raw_input: str) -> bool:
        """检测是否为 Bilibili URL"""
        url = raw_input.strip()
        if not validate_url(url):
            return False
        return any(re.search(pattern, url) for pattern in self.PATTERNS)

    async def parse(
        self,
        raw_input: str,
        episode_id: str,
        out_dir: Path,
        on_progress=None,
    ) -> ParseResult:
        """下载 Bilibili 音频"""
        url = sanitize_url(raw_input.strip())

        if on_progress:
            on_progress("download", 0.0)

        # 传递平台标识以应用 Bilibili 特定配置
        audio_path = await run_ytdlp(url, out_dir, on_progress, platform="bilibili")

        # 获取标题
        bv_id = self._extract_bv(url)
        title = await get_video_title(url, fallback_name=f"Bilibili: {bv_id}")

        return ParseResult(
            title=title,
            audio_path=audio_path,
            source_type="bilibili",
        )

    def _extract_bv(self, url: str) -> str:
        """从 URL 提取 BV 号"""
        # BV 号格式: BV 后面跟 10 位字符（数字和大小写字母）
        match = re.search(r"BV[a-zA-Z0-9]{10}", url)
        if match:
            return match.group(0)
        return "unknown"
