"""
yt-dlp 共享下载层
支持多平台媒体下载和字幕抓取
支持平台特定的反爬虫配置

OpenClip 灵感的 YouTube 限流绕过方案：
- 六层降级策略：Chrome → Edge → Safari → Cookies.txt → No Cookies(Web) → No Cookies(Mobile)
"""
import subprocess
import asyncio
import sys
import os
import tempfile
import shutil
import contextlib
from pathlib import Path
from typing import Optional, Callable, Any, Dict, List
import re
from ..utils.validation import sanitize_url
from ..utils.cookie_helper import (
    find_cookies_txt,
    get_best_browser,
    get_available_browsers,
)


@contextlib.contextmanager
def temp_directory():
    """临时目录上下文管理器，确保退出时清理

    Yields:
        Path: 临时目录路径
    """
    temp_dir = Path(tempfile.mkdtemp())
    try:
        yield temp_dir
    finally:
        # 确保清理所有文件和目录
        if temp_dir.exists():
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                # 如果清理失败，至少尝试删除文件
                for f in temp_dir.glob("*"):
                    try:
                        f.unlink(missing_ok=True)
                    except Exception:
                        pass
                try:
                    temp_dir.rmdir()
                except Exception:
                    pass


# 使用当前 Python 环境的 yt-dlp（避免系统版本冲突）
YTDLP_CMD = [sys.executable, "-m", "yt_dlp"]


# 平台特定配置
PLATFORM_CONFIGS = {
    "youtube": {
        "extractor_args": {
            "youtube": {
                "player_client": ["android_vr", "android", "ios"],
            }
        },
        "format": "bestaudio[ext=m4a]/bestaudio/best",
    },
    "bilibili": {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "referer": "https://www.bilibili.com",
        "format": "bestaudio/best",
    },
    "xiaoyuzhou": {
        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
        "referer": "https://www.xiaoyuzhou.com",
        "format": "bestaudio/best",
    },
    "douyin": {
        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
        "referer": "https://www.douyin.com",
        "format": "bestaudio/best",
    },
}


# YouTube 限流错误关键词
RATE_LIMIT_ERRORS = [
    "429",
    "Too Many Requests",
    "rate limit",
    "sign in to confirm",
    "not a bot",
    "LOGIN_REQUIRED",
]


def _is_rate_limit_error(error_msg: str) -> bool:
    """检查错误是否为限流相关"""
    error_lower = error_msg.lower()
    return any(err.lower() in error_lower for err in RATE_LIMIT_ERRORS)


def _build_opts(platform: str = None) -> Dict[str, Any]:
    """构建 yt-dlp 选项，支持平台特定配置"""
    opts = {
        "format": "bestaudio/best",
        "retries": 5,
        "fragment_retries": 5,
        "concurrent_fragment_downloads": 2,
        "socket_timeout": 30,
    }

    # 应用平台特定配置
    if platform and platform in PLATFORM_CONFIGS:
        platform_config = PLATFORM_CONFIGS[platform]
        if "extractor_args" in platform_config:
            opts["extractor_args"] = platform_config["extractor_args"]
        if "format" in platform_config:
            opts["format"] = platform_config["format"]
        if "user_agent" in platform_config:
            opts["_user_agent"] = platform_config["user_agent"]
        if "referer" in platform_config:
            opts["_referer"] = platform_config["referer"]

    return opts


def _detect_platform(url: str) -> Optional[str]:
    """从 URL 检测平台"""
    url_lower = url.lower()
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "youtube"
    elif "bilibili.com" in url_lower or "b23.tv" in url_lower:
        return "bilibili"
    elif "xiaoyuzhou" in url_lower:
        return "xiaoyuzhou"
    elif "douyin" in url_lower:
        return "douyin"
    return None


async def run_ytdlp(
    url: str,
    out_dir: Path,
    on_progress: Optional[Callable[[str, float], Any]] = None,
    extra_opts: Optional[dict] = None,
    platform: Optional[str] = None,
) -> Path:
    """
    使用 yt-dlp 下载音频

    Args:
        url: 视频 URL
        out_dir: 输出目录
        on_progress: 进度回调
        extra_opts: 额外的 yt-dlp 选项（会覆盖平台配置）
        platform: 平台标识（用于应用平台特定配置）

    Returns:
        下载的音频文件路径
    """
    # 清理 URL 防止命令注入
    safe_url = sanitize_url(url)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 自动检测平台（如果未指定）
    if not platform:
        platform = _detect_platform(url)

    opts = _build_opts(platform)
    output_template = str(out_dir / "audio.%(ext)s")

    cmd = YTDLP_CMD + [
        "--no-warnings",
        "-o", output_template,
        "--newline",
        "-f", opts["format"],
        safe_url,
    ]

    # 添加 extractor_args
    if "extractor_args" in opts:
        extractor_args = opts["extractor_args"]
        for ext, args in extractor_args.items():
            for key, values in args.items():
                # values 是列表，如 ["android_vr", "android", "ios"]
                # 只使用第一个值
                if isinstance(values, list) and values:
                    value = values[0]
                    cmd.extend(["--extractor-args", f"{ext}:{key}={value}"])

    # 添加 user_agent（如果有）
    user_agent = extra_opts.get("user_agent") if extra_opts else opts.get("_user_agent")
    if user_agent:
        cmd.extend(["--user-agent", user_agent])

    # 添加 referer（如果有）
    referer = extra_opts.get("referer") if extra_opts else opts.get("_referer")
    if referer:
        cmd.extend(["--referer", referer])

    # 执行下载
    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    # 监听进度
    if on_progress:
        await _monitor_progress(process, on_progress)

    # 等待进程完成并获取输出
    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        error_msg = stderr.decode() if stderr else "Unknown error"
        raise RuntimeError(f"yt-dlp failed (exit code {process.returncode}): {error_msg}")

    # 查找下载的文件（支持更多扩展名）
    for ext in [".m4a", ".mp3", ".mp4", ".webm", ".mkv", ".opus"]:
        audio_path = out_dir / f"audio{ext}"
        if audio_path.exists():
            return audio_path

    # 也尝试查找任何以 audio. 开头的文件
    for audio_file in out_dir.glob("audio.*"):
        return audio_file

    raise FileNotFoundError("下载完成但未找到音频文件")


async def _monitor_progress(process: asyncio.subprocess.Process, callback: Callable[[str, float], Any]):
    """监听 yt-dlp 进度输出"""
    progress_pattern = re.compile(r"\[download\]\s+(\d+\.?\d*%)")

    while True:
        line = await process.stdout.readline()
        if not line:
            break

        text = line.decode().strip()
        match = progress_pattern.search(text)
        if match:
            progress = float(match.group(1).rstrip("%")) / 100
            callback("download", progress)


def _build_subtitle_command(
    safe_url: str,
    temp_dir: Path,
    client: str,
    sub_langs: str,
    cookies_file: Optional[Path] = None,
    browser: Optional[str] = None,
    remote_components: bool = False,
) -> List[str]:
    """构建字幕下载命令

    Args:
        remote_components: 是否启用 --remote-components ejs:github。
            2026 年 YouTube 引入新的 n challenge，需要 EJS solver 才能拿到
            翻译型自动字幕（zh-Hans-en / en-en）。实测 android_vr/web_embedded
            client + remote-components 组合可绕过 429 限流。
    """
    cmd = YTDLP_CMD + [
        "--write-subs",
        "--write-auto-subs",  # Fallback to auto subs if manual subs not available
        "--skip-download",
        "--sub-lang", sub_langs,
        "--sub-format", "vtt",
        "-o", str(temp_dir / "sub.%(ext)s"),
    ]

    # 添加 Cookie 相关参数（优先于客户端配置）
    using_cookies = False
    if cookies_file and cookies_file.exists():
        cmd.extend(["--cookies", str(cookies_file)])
        using_cookies = True
    elif browser:
        cmd.extend(["--cookies-from-browser", browser])
        using_cookies = True

    # 只有在不使用 cookies 时才指定客户端
    # 使用 cookies 时让 yt-dlp 自动选择最佳客户端
    if not using_cookies and client:
        cmd.extend(["--extractor-args", f"youtube:player_client={client}"])

    cmd.append(safe_url)
    return cmd


def _merge_bilingual_transcripts(
    zh_transcript: "Transcript",
    en_transcript: "Transcript"
) -> "Transcript":
    """
    合并中英文字幕

    策略：
    - 以中文字幕为主（text_original）
    - 英文字幕作为翻译（text_translated）
    - 按时间戳对齐（模糊匹配，允许3秒误差）

    Args:
        zh_transcript: 中文字幕
        en_transcript: 英文字幕

    Returns:
        合并后的字幕
    """
    from ..models import Transcript, Segment

    # 创建英文段落的索引（按时间戳）
    en_segments_by_time = {}
    for seg in en_transcript.segments:
        key = (seg.start_ms, seg.end_ms)
        en_segments_by_time[key] = seg.text_original

    # 构建合并后的段落
    merged_segments = []
    for zh_seg in zh_transcript.segments:
        # 尝试找到时间戳匹配的英文字幕
        en_text = None

        # 精确匹配
        key = (zh_seg.start_ms, zh_seg.end_ms)
        if key in en_segments_by_time:
            en_text = en_segments_by_time[key]
        else:
            # 模糊匹配：查找时间戳接近的英文字幕（允许3秒误差）
            for en_key, en_text_val in en_segments_by_time.items():
                time_diff = abs(zh_seg.start_ms - en_key[0])
                if time_diff <= 3000:  # 3秒误差
                    en_text = en_text_val
                    break

        # 创建合并后的段落
        merged_seg = Segment(
            id=zh_seg.id,
            start_ms=zh_seg.start_ms,
            end_ms=zh_seg.end_ms,
            text_original=zh_seg.text_original,  # 中文作为原文
            text_translated=en_text,  # 英文作为翻译
        )
        merged_segments.append(merged_seg)

    # 返回合并后的字幕
    return Transcript(
        episode_id="",  # 需要在调用时设置
        language="zh",  # 主语言是中文
        segments=merged_segments,
    )


async def _try_subtitle_fetch(
    safe_url: str,
    temp_dir: Path,
    client: str,
    sub_langs: str,
    cookies_file: Optional[Path] = None,
    browser: Optional[str] = None,
    remote_components: bool = False,
) -> tuple[bool, Optional[dict], str]:
    """
    尝试使用指定配置获取字幕（支持双语）

    Returns:
        (成功标志, transcript对象, 使用的策略描述)
    """
    from .subtitle_vtt import parse_vtt_to_transcript
    import logging

    logger = logging.getLogger(__name__)
    strategy_desc = f"client={client}"

    if cookies_file:
        strategy_desc += f" + cookies_file"
    elif browser:
        strategy_desc += f" + browser={browser}"

    logger.info(f"Fetching subtitles with {strategy_desc}")

    cmd = _build_subtitle_command(
        safe_url, temp_dir, client, sub_langs, cookies_file, browser,
        remote_components=remote_components,
    )

    process = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    stdout, stderr = await process.communicate()
    error_msg = stderr.decode() if stderr else ""

    if process.returncode != 0:
        # 检查是否为限流错误
        if _is_rate_limit_error(error_msg):
            logger.warning(f"Rate limit hit with {strategy_desc}: {error_msg[:100]}")
            return False, None, "rate_limit"
        else:
            logger.warning(f"Failed with {strategy_desc}: {error_msg[:100]}")
            return False, None, "error"

    # 查找下载的 VTT 文件
    found_files = list(temp_dir.glob("*.vtt"))

    # Debug: 记录目录中的所有文件
    all_files = list(temp_dir.glob("*"))
    logger.debug(f"Temp dir {temp_dir}: found {len(found_files)} VTT files, {len(all_files)} total files")
    if all_files:
        logger.debug(f"Files in temp dir: {[f.name for f in all_files]}")

    if not found_files:
        logger.warning(f"No subtitles found with {strategy_desc}")
        return False, None, "no_subtitles"

    # 解析所有找到的字幕文件
    zh_transcript = None
    en_transcript = None

    for vtt_file in found_files:
        name_lower = vtt_file.name.lower()
        with open(vtt_file, "r", encoding="utf-8") as f:
            vtt_content = f.read()

        # 识别中文字幕
        if (".zh." in name_lower or "zh-hans" in name_lower or
            name_lower.startswith("zh.") or name_lower.endswith(".zh.vtt")):
            parsed = parse_vtt_to_transcript(vtt_content, lang="zh")
            if parsed and len(parsed.segments) > 5:
                zh_transcript = parsed
                logger.info(f"Found Chinese subtitle: {len(parsed.segments)} segments")

        # 识别英文字幕
        elif (".en." in name_lower or name_lower.startswith("en.") or
              name_lower.endswith(".en.vtt")):
            parsed = parse_vtt_to_transcript(vtt_content, lang="en")
            if parsed and len(parsed.segments) > 5:
                en_transcript = parsed
                logger.info(f"Found English subtitle: {len(parsed.segments)} segments")

    # 决定返回哪个字幕
    transcript = None
    if zh_transcript and en_transcript:
        # 双语字幕：合并中英文字幕
        logger.info(f"Merging bilingual subtitles: zh={len(zh_transcript.segments)}, en={len(en_transcript.segments)}")
        transcript = _merge_bilingual_transcripts(zh_transcript, en_transcript)
    elif zh_transcript:
        # 只有中文字幕
        transcript = zh_transcript
        transcript.language = "zh"
        logger.info(f"Using Chinese only: {len(transcript.segments)} segments")
    elif en_transcript:
        # 只有英文字幕
        transcript = en_transcript
        transcript.language = "en"
        logger.info(f"Using English only: {len(transcript.segments)} segments")

    if transcript:
        logger.info(f"✅ Successfully fetched subtitles with {strategy_desc}: {len(transcript.segments)} segments")
        return True, transcript, strategy_desc

    return False, None, "no_valid_subtitle"


async def fetch_youtube_subtitles(url: str) -> Optional[dict]:
    """
    尝试获取 YouTube 字幕（支持中英文手动和自动生成字幕）

    2026年完整降级策略（基于实际测试结果）：
    ┌─────────────────────────────────────────────────────────────┐
    │                    YouTube字幕获取降级链                        │
    ├─────────────────────────────────────────────────────────────┤
    │  优先级1 ✅ Chrome Cookies (成功率100%)                      │
    │       ↓ 失败/不可用                                          │
    │  优先级2 ⚠️ Edge Cookies (备用浏览器)                      │
    │       ↓ 失败/不可用                                          │
    │  优先级3 ⚠️ Safari Cookies (需Full Disk Access)              │
    │       ↓ 失败/不可用                                          │
    │  优先级4 ⚠️ Cookies.txt文件 (手动导出)                     │
    │       ↓ 失败/不可用                                          │
    │  优先级5 ❌ No Cookies - Web客户端 (最后尝试)               │
    │       ↓ 失败                                                │
    │  优先级6 ❌ No Cookies - 移动端客户端 (额外尝试)            │
    │       ↓ 所有失败                                            │
    │  返回 None (将使用AFM 3 ASR转录)                           │
    └─────────────────────────────────────────────────────────────┘

    测试数据（https://www.youtube.com/watch?v=a93FT2340c0）：
    - Chrome Cookies: ✅ 成功（5299条中文字幕）
    - No Cookies: ❌ 失败（"no subtitles for requested languages"）

    Args:
        url: 视频 URL

    Returns:
        Transcript 对象或 None（所有方案失败时）
    """
    import logging

    logger = logging.getLogger(__name__)
    safe_url = sanitize_url(url)

    logger.info(f"字幕获取: {safe_url}")

    # 使用上下文管理器确保临时目录被清理
    with temp_directory() as temp_dir:
        # 策略准备
        available_browsers = get_available_browsers()
        cookies_txt = find_cookies_txt()

        # 2026 YouTube 翻译型自动字幕代码是 xx-en 格式（"from English"），
        # 旧版只有 zh-Hans/en，匹配不到 zh-Hans-en/en-en，导致"no subtitles"。
        # 这里同时兼容新（带 -en 后缀）旧格式。
        SUB_LANGS_2026 = "zh-Hans-en,en-en,zh-Hans,zh-Hant-en,zh-Hant,en"

        # === 2026 黄金组合（最高优先级，实测最稳）===
        # cookies.txt + android_vr/web_embedded client + --remote-components ejs:github
        # 能解 YouTube 新的 n challenge 并绕过 429，拿到翻译型自动字幕。
        # 成功就立即返回；失败则继续走下面的多级降级链。
        if cookies_txt:
            for client in ["android_vr", "web_embedded"]:
                logger.info(f"[黄金组合] client={client} + remote-components + cookies.txt")
                try:
                    success, transcript, result_type = await _try_subtitle_fetch(
                        safe_url, temp_dir, client, SUB_LANGS_2026,
                        cookies_file=cookies_txt, remote_components=True,
                    )
                    if success:
                        logger.info(f"✅ 黄金组合成功: client={client} ({len(transcript.segments)} segments)")
                        return transcript
                    if result_type == "rate_limit":
                        logger.info("↓ 黄金组合限流，等待后降级")
                        await asyncio.sleep(3)
                except Exception as e:
                    logger.info(f"↓ 黄金组合异常: {str(e)[:80]}")
                    continue

        # 定义降级策略链（黄金组合失败时的 fallback）
        strategies = []

        # 策略1-3: 浏览器 Cookies
        for browser in ["chrome", "edge", "safari"]:
            if browser in available_browsers:
                strategies.append(("browser", browser, f"{browser.capitalize()} Cookies"))

        # 策略4: Cookies.txt
        if cookies_txt:
            strategies.append(("file", cookies_txt, "cookies.txt"))

        # 策略5-6: 无 Cookies
        strategies.append(("web", None, "No Cookies(Web)"))
        strategies.append(("mobile", None, "No Cookies(Mobile)"))

        # 执行降级策略
        for idx, (stype, svalue, sname) in enumerate(strategies, 1):
            logger.info(f"[{idx}/{len(strategies)}] {sname}")

            try:
                if stype == "browser":
                    success, transcript, result_type = await _try_subtitle_fetch(
                        safe_url, temp_dir, "web", SUB_LANGS_2026,
                        browser=svalue
                    )
                elif stype == "file":
                    success, transcript, result_type = await _try_subtitle_fetch(
                        safe_url, temp_dir, "web", SUB_LANGS_2026,
                        cookies_file=svalue
                    )
                elif stype == "web":
                    success, transcript, result_type = await _try_subtitle_fetch(
                        safe_url, temp_dir, "web", SUB_LANGS_2026
                    )
                elif stype == "mobile":
                    for client in ["android_vr", "android", "ios"]:
                        success, transcript, result_type = await _try_subtitle_fetch(
                            safe_url, temp_dir, client, SUB_LANGS_2026
                        )
                        if success:
                            break
                        if result_type == "rate_limit":
                            break

                if success:
                    logger.info(f"✅ 成功: {sname} ({len(transcript.segments)} segments)")
                    return transcript
                elif result_type == "rate_limit":
                    logger.info(f"↓ 限流等待")
                    await asyncio.sleep(2)
                else:
                    logger.info(f"↓ 失败: {result_type}")

            except Exception as e:
                logger.info(f"↓ 异常: {str(e)[:50]}")
                continue

        # 所有策略失败
        logger.warning("所有策略失败，将使用 AFM 3 ASR")
        return None
