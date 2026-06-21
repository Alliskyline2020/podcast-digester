"""
视频标题获取工具
统一各平台的视频标题获取逻辑
"""
import logging
import subprocess
from .validation import sanitize_url


logger = logging.getLogger(__name__)


# 超时配置（秒）
YTDLP_TIMEOUT = 30


async def get_video_title(url: str, fallback_name: str = "视频") -> str:
    """
    使用 yt-dlp 获取视频标题

    Args:
        url: 视频 URL
        fallback_name: 获取失败时的回退名称

    Returns:
        视频标题
    """
    try:
        safe_url = sanitize_url(url)
        result = subprocess.run(
            ["yt-dlp", "--get-title", "--no-warnings", safe_url],
            capture_output=True,
            text=True,
            timeout=YTDLP_TIMEOUT,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except subprocess.TimeoutExpired:
        logger.warning(f"Timeout getting title for {url}")
    except Exception as e:
        logger.warning(f"Failed to get title for {url}: {e}")

    return fallback_name
