"""
视频标题获取工具
统一各平台的视频标题获取逻辑
"""
import asyncio
import logging
import subprocess
import sys
from typing import Optional

from .validation import sanitize_url
from .cookie_helper import find_cookies_txt, get_best_browser


logger = logging.getLogger(__name__)


# 超时配置（秒）
YTDLP_TIMEOUT = 30
# 瞬时失败重试（YouTube 下载完成后偶发限流/429；标题只在下载时取一次，
# 静默回退会留下永久占位标题，故失败时重试并留 warning 便于排查）。
TITLE_MAX_ATTEMPTS = 3
TITLE_RETRY_BACKOFF = 1.5

# 用当前 Python 环境（venv）的 yt_dlp 模块，与 sources.ytdlp_runner.YTDLP_CMD 一致。
# 真实事故：原用 ["yt-dlp"] 走系统 PATH，命中系统旧版 yt-dlp (2025.10.14) +
# macOS LibreSSL 2.8.3，YouTube --get-title 全部失败（exit=1），退回占位标题；
# 而下载路径用 venv 新版 (2026.07.04) 成功 → "下载成功但标题是 YouTube: <id>" 占位。
YT_DLP_CMD = [sys.executable, "-m", "yt_dlp"]


async def get_video_title(
    url: str,
    fallback_name: str = "视频",
    platform: Optional[str] = None,
    max_attempts: int = TITLE_MAX_ATTEMPTS,
) -> str:
    """
    使用 yt-dlp 获取视频标题（瞬时失败重试，全部失败留 warning）。

    Args:
        url: 视频 URL
        fallback_name: 全部重试失败时的回退名称
        platform: 平台标识 (bilibili/youtube/...)。鉴权平台会注入 cookies，
            与 run_ytdlp 的下载路径保持一致——否则 bilibili 等反爬平台会在
            --get-title 处拿到 412，退回占位标题。
        max_attempts: 最大尝试次数（含首次）。瞬时失败会指数退避重试。

    Returns:
        视频标题
    """
    cmd = YT_DLP_CMD + ["--get-title", "--no-warnings"]

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

    safe_url = sanitize_url(url)
    last_err = ""
    for attempt in range(1, max_attempts + 1):
        try:
            result = subprocess.run(
                cmd + [safe_url],
                capture_output=True,
                text=True,
                timeout=YTDLP_TIMEOUT,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
            last_err = (
                f"exit={result.returncode} "
                f"stderr={(result.stderr or '').strip()[:200]}"
            )
        except subprocess.TimeoutExpired:
            last_err = f"timeout after {YTDLP_TIMEOUT}s"
        except Exception as e:  # noqa: BLE001 — 守住任何异常，回退占位标题
            last_err = f"{type(e).__name__}: {e}"

        # 还有下一次尝试 → 退避后重试
        if attempt < max_attempts:
            await asyncio.sleep(TITLE_RETRY_BACKOFF * attempt)

    logger.warning(
        f"get_video_title 全部 {max_attempts} 次尝试失败 "
        f"(platform={platform}, url={url}): {last_err}；回退占位标题。"
    )
    return fallback_name


def _platform_needs_cookies(platform: Optional[str]) -> bool:
    """查询平台是否需要 cookie 鉴权（基于 ytdlp_runner.PLATFORM_CONFIGS）。"""
    if not platform:
        return False
    # 懒加载，避免 utils 反向依赖 sources（层次倒置）
    from ..sources.ytdlp_runner import PLATFORM_CONFIGS

    config = PLATFORM_CONFIGS.get(platform)
    return bool(config and config.get("needs_cookies"))
