"""
YouTube 解析器
使用 yt-dlp 下载音频和字幕
"""
import re
from pathlib import Path
from .base import BaseSourceParser, ParseResult
from .ytdlp_runner import run_ytdlp, fetch_youtube_subtitles
from ..utils.validation import validate_url, sanitize_url
from ..utils.video import get_video_title


class YouTubeParser(BaseSourceParser):
    """YouTube 视频解析器"""

    PRIORITY = 60
    DESCRIPTION = "android_vr 客户端取 m4a DASH；自动抓字幕跳过 ASR"

    # YouTube URL 匹配模式
    PATTERNS = [
        r"youtube\.com/watch\?v=[\w-]+",
        r"youtu\.be/[\w-]+",
        r"youtube\.com/shorts/[\w-]+",
    ]

    async def matches(self, raw_input: str) -> bool:
        """检测是否为 YouTube URL"""
        url = raw_input.strip()
        # 先验证 URL 格式是否合法
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
        """下载 YouTube 音频并尝试获取字幕"""
        # 清理 URL 以防止命令注入
        url = sanitize_url(raw_input.strip())

        # 下载音频（传递平台标识以应用 YouTube 特定配置）
        if on_progress:
            on_progress("download", 0.0)

        audio_path = await run_ytdlp(url, out_dir, on_progress, platform="youtube")

        # 尝试获取字幕（Fast Path）
        if on_progress:
            on_progress("subtitle", 0.0)

        transcript = await fetch_youtube_subtitles(url)

        # 从 YouTube 获取标题
        video_id = self._extract_video_id(url)
        title = await get_video_title(url, fallback_name=f"YouTube: {video_id}")

        result = ParseResult(
            title=title,
            audio_path=audio_path,
            source_type="youtube",
        )

        # 如果有字幕，放入 extra 跳过 ASR
        if transcript:
            result.extra["transcript"] = transcript

        return result

    def _extract_video_id(self, url: str) -> str:
        """从 URL 提取视频 ID"""
        patterns = [
            r"(?:v=|youtu\.be/)([\w-]+)",
            r"shorts/([\w-]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
        return "unknown"
