"""
抖音解析器
支持 CDP 绕过反爬
"""
import asyncio
import re
from pathlib import Path
from .base import BaseSourceParser, ParseResult
from ..utils.validation import validate_url, sanitize_url
from ..utils.video import get_video_title


class DouyinParser(BaseSourceParser):
    """抖音视频解析器"""

    PRIORITY = 40
    DESCRIPTION = "CDP 绕过反爬；支持 yt-dlp 备用"

    # 抖音 URL 匹配模式
    PATTERNS = [
        r"douyin\.com/.*video/\d+",        # 匹配所有含 video 的路径
        r"v\.douyin\.com/\w+",           # 短链接
    ]

    async def matches(self, raw_input: str) -> bool:
        """检测是否为抖音 URL"""
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
        """下载抖音音频"""
        url = sanitize_url(raw_input.strip())

        if on_progress:
            on_progress("download", 0.0)

        # 方案1: 先尝试 CDP 直接获取音频
        try:
            from .cdp_downloader import download_with_cdp

            # 抖音需要先从页面获取视频 URL
            cdp_audio_url = await self._fetch_douyin_audio_url(url)

            if cdp_audio_url:
                if on_progress:
                    on_progress("download", 0.5)

                audio_path = await download_with_cdp(cdp_audio_url, out_dir)

                if audio_path and audio_path.exists():
                    if on_progress:
                        on_progress("download", 1.0)

                    title = await get_video_title(url, fallback_name="抖音视频")

                    return ParseResult(
                        title=title,
                        audio_path=audio_path,
                        source_type="douyin",
                    )

        except ImportError:
            pass
        except Exception as e:
            pass

        # 方案2: 回退到 yt-dlp
        from .ytdlp_runner import run_ytdlp

        if on_progress:
            on_progress("download", 0.5)

        audio_path = await run_ytdlp(url, out_dir, on_progress, platform="douyin")

        if on_progress:
            on_progress("download", 1.0)

        title = await get_video_title(url, fallback_name="抖音视频")

        return ParseResult(
            title=title,
            audio_path=audio_path,
            source_type="douyin",
        )

    async def _fetch_douyin_audio_url(self, url: str) -> str:
        """使用 CDP 获取抖音音频 URL"""
        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                try:
                    context = await browser.new_context()
                    page = await context.new_page()

                    await page.goto(url, wait_until="networkidle", timeout=30000)
                    await asyncio.sleep(3)

                    # 抖音音频通常在 video 标签中
                    audio_url = await page.evaluate("""
                        () => {
                            const video = document.querySelector('video');
                            return video ? video.src : null;
                        }
                    """)

                    return audio_url
                finally:
                    # 确保任何异常路径都关闭 browser，防止 Chromium 进程泄漏
                    await browser.close()

        except Exception:
            return None
