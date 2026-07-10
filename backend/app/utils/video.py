"""
视频标题获取工具
统一各平台的视频标题获取逻辑
"""
import logging
import subprocess
from typing import Optional

from .validation import sanitize_url
from .cookie_helper import find_cookies_txt, get_best_browser


logger = logging.getLogger(__name__)


# 超时配置（秒）
YTDLP_TIMEOUT = 30


async def get_video_title(
    url: str,
    fallback_name: str = "视频",
    platform: Optional[str] = None,
) -> str:
    """
    使用 yt-dlp 获取视频标题

    Args:
        url: 视频 URL
        fallback_name: 获取失败时的回退名称
        platform: 平台标识 (bilibili/youtube/...)。鉴权平台会注入 cookies，
            与 run_ytdlp 的下载路径保持一致——否则 bilibili 等反爬平台会在
            --get-title 处拿到 412，退回占位标题。

    Returns:
        视频标题
    """
    cmd = ["yt-dlp", "--get-title", "--no-warnings"]

    # 鉴权平台注入 cookies（反爬平台需要：bilibili 等）
    # 与 run_ytdlp 同一套策略：浏览器优先（多域名活跃会话），cookies.txt 兜底。
    if _platform_needs_cookies(platform):
        browser = get_best_browser()
        if browser:
            cmd.extend(["--cookies-from-browser", browser])
            logger.info(f"[{platform}] 标题获取使用浏览器 cookies: {browser}")
        else:
            cookies_file = find_cookies_txt()
            if cookies_file and cookies_file.exists():
                cmd.extend(["--cookies", str(cookies_file)])
                logger.info(f"[{platform}] 标题获取回退 cookies.txt")
            else:
                logger.warning(
                    f"[{platform}] 标题获取需要 cookie 鉴权但未找到浏览器 cookie 或 cookies.txt，"
                    f"大概率在 412 反爬处退回占位标题。"
                )

    try:
        safe_url = sanitize_url(url)
        result = subprocess.run(
            cmd + [safe_url],
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


def _platform_needs_cookies(platform: Optional[str]) -> bool:
    """查询平台是否需要 cookie 鉴权（基于 ytdlp_runner.PLATFORM_CONFIGS）。"""
    if not platform:
        return False
    # 懒加载，避免 utils 反向依赖 sources（层次倒置）
    from ..sources.ytdlp_runner import PLATFORM_CONFIGS

    config = PLATFORM_CONFIGS.get(platform)
    return bool(config and config.get("needs_cookies"))
