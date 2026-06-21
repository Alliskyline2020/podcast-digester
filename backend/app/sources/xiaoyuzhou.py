"""
小宇宙解析器
支持 CDP (Chrome DevTools Protocol) 绕过反爬
"""
import re
import logging
from pathlib import Path
from .base import BaseSourceParser, ParseResult
from ..utils.validation import validate_url, sanitize_url
from ..utils.video import get_video_title

logger = logging.getLogger(__name__)


class XiaoyuzhouParser(BaseSourceParser):
    """小宇宙播客解析器"""

    PRIORITY = 45
    DESCRIPTION = "CDP 绕过反爬；支持 yt-dlp 备用"

    # 小宇宙 URL 匹配模式
    PATTERNS = [
        r"xiaoyuzhou\.com/episode/\d+",
        r"xiaoyuzhoufm\.com/episode/\d+",
    ]

    async def matches(self, raw_input: str) -> bool:
        """检测是否为小宇宙 URL"""
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
        """下载小宇宙音频"""
        url = sanitize_url(raw_input.strip())

        if on_progress:
            on_progress("download", 0.0)

        # 方案1: 先尝试 CDP 直接获取音频
        try:
            from .cdp_downloader import fetch_xiaoyuzhou_with_cdp, download_with_cdp
            import aiohttp

            if on_progress:
                on_progress("download", 0.2)

            cdp_result = await fetch_xiaoyuzhou_with_cdp(url)

            if cdp_result and cdp_result.get("audio_url"):
                if on_progress:
                    on_progress("download", 0.5)

                # 使用 CDP 下载音频
                audio_path = await download_with_cdp(cdp_result["audio_url"], out_dir)

                if audio_path and audio_path.exists():
                    if on_progress:
                        on_progress("download", 1.0)

                    return ParseResult(
                        title=cdp_result.get("title", "小宇宙播客"),
                        audio_path=audio_path,
                        source_type="xiaoyuzhou",
                    )

        except ImportError:
            logger.info("CDP modules not available, falling back to yt-dlp")
        except Exception as e:
            logger.warning(f"CDP download failed: {e}, falling back to yt-dlp")

        # 方案2: 回退到 yt-dlp
        from .ytdlp_runner import run_ytdlp

        if on_progress:
            on_progress("download", 0.5)

        try:
            audio_path = await run_ytdlp(url, out_dir, on_progress, platform="xiaoyuzhou")

            if on_progress:
                on_progress("download", 1.0)

            title = await get_video_title(url, fallback_name="小宇宙播客")

            return ParseResult(
                title=title,
                audio_path=audio_path,
                source_type="xiaoyuzhou",
            )

        except Exception as e:
            raise RuntimeError(f"小宇宙下载失败（CDP 和 yt-dlp 都不可用）: {e}")
