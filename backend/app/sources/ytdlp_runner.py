"""
yt-dlp 共享下载层
支持多平台媒体下载和字幕抓取
支持平台特定的反爬虫配置

OpenClip 灵感的 YouTube 限流绕过方案：
- 六层降级策略：Chrome → Edge → Safari → Cookies.txt → No Cookies(Web) → No Cookies(Mobile)
"""
import subprocess
import asyncio
import json
import sys
import os
import tempfile
import shutil
import contextlib
from pathlib import Path
from typing import Optional, Callable, Any, Dict, List
from dataclasses import dataclass, field
import re
from ..config import settings
from ..errors import DownloadError, DownloadTemporaryError
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


@dataclass(frozen=True)
class DownloadStrategy:
    """单个下载策略（YouTube 多 client fallback 用）。

    run_ytdlp 按 PLATFORM_CONFIGS[platform].strategies 顺序尝试；某策略失败且
    非 permanent（节点不可达 / 限流）时切换下一个，全部失败才抛
    DownloadTemporaryError 交 worker 跨轮次重试。

    字段：
        name: 日志标识，如 "default" / "android_vr"
        client: youtube player_client；None=不传 --extractor-args，让 yt-dlp
                自选可达节点（避免锁死单一故障 CDN 节点）
        preflight: 下载前是否预检 CDN 节点连通（仅 googlevideo 类有意义）
    """
    name: str
    client: Optional[str]
    preflight: bool


# 平台特定配置
#
# 每个平台定义一个 strategies 列表（有序）。needs_cookies 是平台级属性
# （"这个平台是否需要 cookie 鉴权"），被 app/utils/video.py 复用，与
# strategies（"用什么 client 组合"）正交。
PLATFORM_CONFIGS = {
    "youtube": {
        # 不锁定 player_client：固定 client（如 android_vr）会让 YouTube 把某些视频
        # 锁死到单一故障 CDN 节点（如 rr5---sn-ojnpo5-c3），换代理/重试都无法绕过。
        # 策略1 default（不传 client）→ yt-dlp 用默认 client 协商可达节点（实测 2026.08 美区 rr1 可达）。
        # 策略2 android_vr 兜底（default 拿到的节点预检不通 / 下载失败时再试）。
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "strategies": [
            DownloadStrategy(name="default", client=None, preflight=True),
            DownloadStrategy(name="android_vr", client="android_vr", preflight=True),
        ],
    },
    "bilibili": {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "referer": "https://www.bilibili.com",
        "format": "bestaudio/best",
        # Bilibili 反爬：不带有效 SESSDATA/buvid cookie 会直接 412。
        # 参考 feiskyer/video-skills：鉴权平台统一用 --cookies-from-browser。
        "needs_cookies": True,
        "strategies": [
            DownloadStrategy(name="default", client=None, preflight=False),
        ],
    },
    "xiaoyuzhou": {
        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
        "referer": "https://www.xiaoyuzhou.com",
        "format": "bestaudio/best",
        "strategies": [
            DownloadStrategy(name="default", client=None, preflight=False),
        ],
    },
    "douyin": {
        "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
        "referer": "https://www.douyin.com",
        "format": "bestaudio/best",
        "strategies": [
            DownloadStrategy(name="default", client=None, preflight=False),
        ],
    },
}

# 未知平台兜底（不预检、不锁 client）
_DEFAULT_STRATEGIES = [DownloadStrategy(name="default", client=None, preflight=False)]


# YouTube 限流错误关键词
RATE_LIMIT_ERRORS = [
    "429",
    "Too Many Requests",
    "rate limit",
    "sign in to confirm",
    "not a bot",
    "LOGIN_REQUIRED",
]


# 永久性错误关键词（视频 / URL 层面）。
# 只有这些明确标志才判 permanent；网络中断 / 节点断流 / 下载中途失败 / 未知错误
# 一律 node_unreachable（保守重试优先）。worker 有 max_download_retries 上限兜底，
# 不会无限重试；而把临时错误误判永久会导致 fallback 失效 + episode 直接 failed。
PERMANENT_ERROR_PATTERNS = [
    "video unavailable",
    "private video",
    "is private",
    "members-only",
    "member only",
    "unsupported url",
    "video not found",
    "no longer available",
    "has been removed",
    "removed by the uploader",
    "age-restricted",
    "age restricted",
    "no video formats",
    "geo-restricted",
    "geo restricted",
    "premieres in",
    "this video is not available",
]


def _is_rate_limit_error(error_msg: str) -> bool:
    """检查错误是否为限流相关"""
    error_lower = error_msg.lower()
    return any(err.lower() in error_lower for err in RATE_LIMIT_ERRORS)


def _classify_download_error(error_msg: str) -> str:
    """把 yt-dlp 错误文本分类为下载 fallback 决策用的类型。

    策略（保守重试优先）：
      1. 限流标志 → rate_limit（等待 + 换 client）
      2. 明确的视频/URL 永久错误 → permanent（不再试）
      3. 其余一律 node_unreachable —— 含下载中途断流（"X bytes read, Y more
         expected"）、连接超时/重置、5xx、未知错误。换 client/重试有救。

    Returns:
        "rate_limit" | "permanent" | "node_unreachable"
    """
    if _is_rate_limit_error(error_msg):
        return "rate_limit"
    error_lower = error_msg.lower()
    if any(p in error_lower for p in PERMANENT_ERROR_PATTERNS):
        return "permanent"
    return "node_unreachable"


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
    使用 yt-dlp 下载音频（多策略 fallback 编排器）

    遍历 PLATFORM_CONFIGS[platform].strategies 依次尝试：
      - permanent 错误（URL 无效/视频私有删除）→ 立即抛 DownloadError，不再试
      - node_unreachable / rate_limit → 退避后切换下一个策略
      - 全部策略失败 → DownloadTemporaryError（retryable），交 worker 跨轮次重试

    内层（秒级换 client）与 worker 外层（分钟级跨轮次）互补，避免单一故障点。

    Args:
        url: 视频 URL
        out_dir: 输出目录
        on_progress: 进度回调
        extra_opts: 额外选项（user_agent/referer 覆盖平台配置；保留兼容，当前无调用方）
        platform: 平台标识（未指定则自动检测）

    Returns:
        下载的音频文件路径

    Raises:
        DownloadError: 永久性失败（不可重试）
        DownloadTemporaryError: 所有策略失败（临时性，worker 可重试）
    """
    import logging
    logger = logging.getLogger(__name__)

    # 清理 URL 防止命令注入
    safe_url = sanitize_url(url)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 自动检测平台（如果未指定）
    if not platform:
        platform = _detect_platform(url)

    config = PLATFORM_CONFIGS.get(platform, {})
    strategies = config.get("strategies") or _DEFAULT_STRATEGIES
    platform_name = platform or "unknown"

    logger.info(
        f"[{platform_name}] 开始下载，共 {len(strategies)} 个策略："
        f"{[s.name for s in strategies]}"
    )

    last_error_type: Optional[str] = None
    last_error_msg: Optional[str] = None

    for idx, strategy in enumerate(strategies, 1):
        logger.info(
            f"[{platform_name}] 策略 {idx}/{len(strategies)}: {strategy.name} "
            f"(client={strategy.client}, preflight={strategy.preflight})"
        )

        success, error_type, error_msg, audio_path = await _try_audio_download(
            safe_url=safe_url,
            out_dir=out_dir,
            strategy=strategy,
            config=config,
            on_progress=on_progress,
            extra_opts=extra_opts,
        )

        if success:
            logger.info(f"[{platform_name}] ✅ 策略 {strategy.name} 下载成功：{audio_path.name}")
            return audio_path

        last_error_type = error_type
        last_error_msg = error_msg

        # permanent 错误：换策略也没用，立即抛出
        if error_type == "permanent":
            logger.warning(
                f"[{platform_name}] 策略 {strategy.name} 永久性失败：{(error_msg or '')[:200]}"
            )
            raise DownloadError(
                f"下载失败（永久）：{(error_msg or 'unknown')[:500]}",
                source_type=platform_name,
                url=safe_url,
            )

        # node_unreachable / rate_limit：退避后换下一个策略
        has_next = idx < len(strategies)
        logger.info(
            f"[{platform_name}] 策略 {strategy.name} {error_type}：{(error_msg or '')[:120]}"
            + ("，退避后切换下一个策略" if has_next else "（已是最后策略）")
        )
        if has_next:
            # rate_limit 等久一点（YouTube 瞬时限流需要冷却）；node_unreachable 短退避即可
            await asyncio.sleep(2 if error_type == "rate_limit" else 1)

    # 所有策略失败 → 临时性错误，交 worker 跨轮次重试
    raise DownloadTemporaryError(
        f"所有下载策略失败（最后错误类型={last_error_type}）：{(last_error_msg or 'unknown')[:500]}",
        source_type=platform_name,
        url=safe_url,
        suggested_retry_seconds=60,
    )


async def _get_download_url(
    safe_url: str, strategy: DownloadStrategy, timeout: int = 20
) -> Optional[str]:
    """用 yt-dlp -g 拿该策略下的真实媒体 URL（走 extractor，不下载）。

    用于下载前预检：拿到 URL 后可单独测 CDN 节点连通性。extractor 走
    www.youtube.com，与 googlevideo CDN 是两条路径，因此能拿到 URL 不代表
    CDN 可达——这正是预检要区分的。

    返回首个 http(s) 行；extractor 失败或超时返回 None（调用方不阻塞，回退到直接下载）。
    """
    import logging
    logger = logging.getLogger(__name__)

    cmd = YTDLP_CMD + [
        "-g", "--no-warnings",
        "--socket-timeout", str(settings.ytdlp_socket_timeout),
    ]
    if strategy.client:
        cmd += ["--extractor-args", f"youtube:player_client={strategy.client}"]
    cmd.append(safe_url)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode == 0:
            for line in stdout.decode(errors="ignore").splitlines():
                line = line.strip()
                if line.startswith("http"):
                    return line
    except asyncio.TimeoutError:
        logger.debug(f"[{strategy.name}] -g 超时（{timeout}s），跳过预检")
    except Exception as e:
        logger.debug(f"[{strategy.name}] -g 失败：{str(e)[:80]}，跳过预检")
    return None


def _probe_node_reachable(node_url: str, timeout: int) -> bool:
    """测 CDN host HTTP 连通性（走 HTTPS_PROXY 环境变量代理）。

    任何 HTTP 响应（含 403/404/405）都算「节点可达」——只关心 TCP/TLS 握手
    能否完成。连接异常 / 超时 → 不可达。其他异常（SSL 等）保守视为可达，
    不阻塞下载（预检本身失败不应阻断正常流程）。
    """
    import requests
    try:
        requests.head(node_url, timeout=timeout, allow_redirects=True)
        return True
    except (requests.ConnectionError, requests.Timeout):
        return False
    except Exception:
        return True


async def _preflight_node(node_url: str) -> bool:
    """异步预检 CDN 节点连通性（requests 同步，丢到线程池）。"""
    return await asyncio.to_thread(
        _probe_node_reachable, node_url, settings.ytdlp_preflight_timeout
    )


async def _try_audio_download(
    safe_url: str,
    out_dir: Path,
    strategy: DownloadStrategy,
    config: Dict[str, Any],
    on_progress: Optional[Callable[[str, float], Any]] = None,
    extra_opts: Optional[dict] = None,
) -> tuple[bool, Optional[str], Optional[str], Optional[Path]]:
    """单次下载尝试（一个 strategy 一次 yt-dlp 子进程）。

    Returns:
        (success, error_type, error_msg, audio_path)
        error_type ∈ {"node_unreachable", "rate_limit", "permanent", None}
    """
    import logging
    logger = logging.getLogger(__name__)

    output_template = str(out_dir / "audio.%(ext)s")

    # 1. 预检 CDN 节点（仅 preflight 策略 + 全局开关开启）
    #    用 yt-dlp -g 拿真实 URL → 测 host 连通 → 不通直接换策略，
    #    避免一次 30s+ 的撞墙下载。-g 失败（拿不到 URL）不阻塞，回退直接下载。
    if strategy.preflight and settings.ytdlp_node_preflight:
        node_url = await _get_download_url(safe_url, strategy)
        if node_url:
            reachable = await _preflight_node(node_url)
            host_match = re.match(r"https?://([^/]+)", node_url)
            host_str = host_match.group(1) if host_match else node_url[:60]
            if not reachable:
                logger.info(f"[{strategy.name}] 预检节点不可达：{host_str} → 跳过此策略")
                return False, "node_unreachable", f"预检节点不可达: {host_str}", None
            logger.info(f"[{strategy.name}] 预检节点可达：{host_str}")

    # 2. 构建 cmd（传输参数从 settings 读，不再硬编码）
    cmd = YTDLP_CMD + [
        "--no-warnings",
        "-o", output_template,
        "--newline",
        "--socket-timeout", str(settings.ytdlp_socket_timeout),
        "--retries", str(settings.ytdlp_retries),
        "--fragment-retries", str(settings.ytdlp_fragment_retries),
        "--concurrent-fragments", str(settings.ytdlp_concurrent_fragments),
        "-f", config.get("format", "bestaudio/best"),
    ]

    if strategy.client:
        cmd += ["--extractor-args", f"youtube:player_client={strategy.client}"]

    # user_agent：extra_opts 覆盖平台配置（保留兼容）
    user_agent = extra_opts.get("user_agent") if extra_opts else config.get("user_agent")
    if user_agent:
        cmd += ["--user-agent", user_agent]

    # referer：extra_opts 覆盖平台配置
    referer = extra_opts.get("referer") if extra_opts else config.get("referer")
    if referer:
        cmd += ["--referer", referer]

    # Cookies（needs_cookies 平台：浏览器优先，cookies.txt 兜底）
    # YouTube 音频走 default/android_vr 客户端无需 cookie；bilibili 不带 cookie 会 412。
    # 浏览器是多域名活跃会话（最可靠）；cookies.txt 通常是单站点导出，对其他平台
    # 无效——因此浏览器优先，cookies.txt 仅作兜底。
    if config.get("needs_cookies"):
        browser = get_best_browser()
        if browser:
            cmd += ["--cookies-from-browser", browser]
            logger.info(f"[{strategy.name}] 使用浏览器 cookies 鉴权下载: {browser}")
        else:
            cookies_file = find_cookies_txt()
            if cookies_file and cookies_file.exists():
                cmd += ["--cookies", str(cookies_file)]
                logger.info(f"[{strategy.name}] 无浏览器 cookie，回退 cookies.txt 鉴权下载")
            else:
                logger.warning(
                    f"[{strategy.name}] 需要 cookie 鉴权但未找到浏览器 cookie 或 cookies.txt，"
                    f"大概率在 412 反爬处失败。请在 Chrome 登录该平台，或放置 cookies.txt。"
                )

    cmd.append(safe_url)

    # 3. 执行下载
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
        error_msg = stderr.decode(errors="ignore") if stderr else "Unknown error"
        error_type = _classify_download_error(error_msg)
        return False, error_type, f"yt-dlp failed (exit code {process.returncode}): {error_msg}", None

    # 4. 查找下载的文件（支持更多扩展名）
    for ext in [".m4a", ".mp3", ".mp4", ".webm", ".mkv", ".opus"]:
        audio_path = out_dir / f"audio{ext}"
        if audio_path.exists():
            return True, None, None, audio_path

    # 也尝试查找任何以 audio. 开头的文件
    for audio_file in out_dir.glob("audio.*"):
        return True, None, None, audio_file

    return False, "permanent", "下载完成但未找到音频文件", None


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
        # NOTE: --write-auto-subs 已禁用 (2026-06-25)
        # YouTube 自动字幕质量不可控，对低质量音频会产出 ", , ," 这类垃圾数据。
        # 没有 manual CC 时让 yt-dlp 直接 fail，由 pipeline.py 的 ASR 兜底处理。
        # 若需临时恢复调查，取消下一行注释即可：
        # "--write-auto-subs",
        "--write-info-json",  # Phase 3: feeds detect_source_language (manual_cc/metadata levels)
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


def merge_bilingual(
    zh_transcript: "Transcript",
    en_transcript: "Transcript",
    source_lang: str,
) -> "Transcript":
    """
    合并中英文字幕（Phase 3: source-driven）。

    策略：
    - 由 source_lang 决定哪一侧是「原文」（audio 实际语种），另一侧是翻译。
    - 时间戳/ids 来自源语言那一侧（source dictates the timeline）。
    - 按时间戳对齐另一侧文本（模糊匹配，允许3秒误差），无匹配则空字符串。
    - 同时填充新的 text_zh/text_en 与旧的 text_original/text_translated，
      保证 Phase 4 迁移消费者前旧字段仍可用，且按 source 正确赋值（修复旧 bug）。

    Args:
        zh_transcript: 中文字幕
        en_transcript: 英文字幕
        source_lang: 音频实际语种 "zh" 或 "en"（由 detect_source_language 决定）

    Returns:
        合并后的字幕
    """
    from ..models import Transcript, Segment

    if source_lang == "en":
        # EN 是源：时间轴来自 EN，ZH 是翻译
        # 构建 ZH 文本索引（按时间戳）
        zh_segments_by_time = {}
        for seg in zh_transcript.segments:
            key = (seg.start_ms, seg.end_ms)
            zh_segments_by_time[key] = seg.text_original

        merged_segments = []
        for en_seg in en_transcript.segments:
            zh_text = None
            key = (en_seg.start_ms, en_seg.end_ms)
            if key in zh_segments_by_time:
                zh_text = zh_segments_by_time[key]
            else:
                # 模糊匹配：查找时间戳接近的中文字幕（允许3秒误差）
                for zh_key, zh_text_val in zh_segments_by_time.items():
                    time_diff = abs(en_seg.start_ms - zh_key[0])
                    if time_diff <= 3000:  # 3秒误差
                        zh_text = zh_text_val
                        break

            merged_seg = Segment(
                id=en_seg.id,
                start_ms=en_seg.start_ms,
                end_ms=en_seg.end_ms,
                text_en=en_seg.text_original,            # source
                text_zh=zh_text or "",                   # other (empty if no match)
                text_original=en_seg.text_original,      # source (legacy field, correct)
                text_translated=zh_text or "",           # other (legacy field, correct)
            )
            merged_segments.append(merged_seg)

        return Transcript(
            episode_id="",  # 需要在调用时设置
            language="en",
            segments=merged_segments,
        )

    # 默认 source_lang == "zh"：时间轴来自 ZH，EN 是翻译
    en_segments_by_time = {}
    for seg in en_transcript.segments:
        key = (seg.start_ms, seg.end_ms)
        en_segments_by_time[key] = seg.text_original

    merged_segments = []
    for zh_seg in zh_transcript.segments:
        en_text = None
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

        merged_seg = Segment(
            id=zh_seg.id,
            start_ms=zh_seg.start_ms,
            end_ms=zh_seg.end_ms,
            text_zh=zh_seg.text_original,            # source
            text_en=en_text or "",                   # other (empty if no match)
            text_original=zh_seg.text_original,      # source (legacy field, correct)
            text_translated=en_text or "",           # other (legacy field, correct)
        )
        merged_segments.append(merged_seg)

    return Transcript(
        episode_id="",  # 需要在调用时设置
        language="zh",
        segments=merged_segments,
    )


def _load_info_json(temp_dir: Path) -> Optional[dict]:
    """Load the yt-dlp info-json written alongside the VTT subtitles.

    yt-dlp writes `sub.info.json` (matching the `-o sub.%(ext)s` template).
    Returns None if absent or unreadable — detection then falls back to
    metadata/default levels.
    """
    candidates = list(temp_dir.glob("*.info.json"))
    for candidate in candidates:
        try:
            with open(candidate, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            import logging
            logging.getLogger(__name__).warning(
                f"Failed to read info-json {candidate}: {e}"
            )
    return None


def _populate_single_lang(
    transcript: "Transcript",
    source_lang: str,
) -> "Transcript":
    """Populate the new text_zh/text_en fields on a single-lang CC transcript.

    Single-lang path: the fetched CC IS the audio's source language.
    - zh-only: text_zh = text_original (source); text_en stays None (no EN CC).
    - en-only: text_en = text_original (source); text_zh stays None (filled by
      the pipeline translate step later).
    Legacy text_original is unchanged (already correct). Segments are rebuilt as
    Segment objects so the new fields are settable.
    """
    from ..models import Transcript, Segment

    new_segments = []
    for seg in transcript.segments:
        if source_lang == "zh":
            new_seg = Segment(
                id=seg.id,
                start_ms=seg.start_ms,
                end_ms=seg.end_ms,
                text_original=seg.text_original,
                text_translated=seg.text_translated,
                text_with_punct=seg.text_with_punct,
                speaker=seg.speaker,
                text_zh=seg.text_original,
                text_en=None,
            )
        else:  # en
            new_seg = Segment(
                id=seg.id,
                start_ms=seg.start_ms,
                end_ms=seg.end_ms,
                text_original=seg.text_original,
                text_translated=seg.text_translated,
                text_with_punct=seg.text_with_punct,
                speaker=seg.speaker,
                text_en=seg.text_original,
                text_zh=None,
            )
        new_segments.append(new_seg)

    return Transcript(
        episode_id=transcript.episode_id,
        language=source_lang,
        segments=new_segments,
    )


async def _pick_source_and_merge(
    zh_transcript: "Transcript",
    en_transcript: "Transcript",
    info_json: Optional[dict],
) -> "Transcript":
    """Decide audio source language from info_json, then merge zh+en accordingly.

    Pure helper extracted from _try_subtitle_fetch so detection+merge is
    unit-testable without spawning yt-dlp. In the CC path there is NO audio
    (yt-dlp uses --skip-download), so audio_path=None — detection relies on
    the manual_cc + metadata levels only.
    """
    import logging
    from .lang_detect import detect_source_language

    logger = logging.getLogger(__name__)
    result = await detect_source_language(
        available_langs=["zh", "en"], info_json=info_json, audio_path=None, asr=None
    )
    logger.info(f"source-lang detection: {result.lang} (basis={result.basis}, {result.reason})")
    return merge_bilingual(zh_transcript, en_transcript, result.lang)


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
        # 文件名格式 sub.{lang}.vtt，lang 可能是 en / zh-Hans / en-zh-Hans（英文翻译自中文）
        # / zh-Hans-en（中文翻译自英文）。按"目标语言"= lang 第一段 判断归属：
        #   en-zh-Hans → 目标 en → 英文；zh-Hans-en → 目标 zh → 中文
        name_parts = vtt_file.name.split('.')
        lang_code = name_parts[1] if len(name_parts) >= 3 else ""
        target_lang = lang_code.split('-')[0].lower()

        with open(vtt_file, "r", encoding="utf-8") as f:
            vtt_content = f.read()

        if target_lang.startswith("zh"):
            parsed = parse_vtt_to_transcript(vtt_content, lang="zh")
            if parsed and len(parsed.segments) > 5:
                zh_transcript = parsed
                logger.info(f"Found Chinese subtitle ({lang_code}): {len(parsed.segments)} segments")
        elif target_lang == "en":
            parsed = parse_vtt_to_transcript(vtt_content, lang="en")
            if parsed and len(parsed.segments) > 5:
                en_transcript = parsed
                logger.info(f"Found English subtitle ({lang_code}): {len(parsed.segments)} segments")

    # 决定返回哪个字幕
    transcript = None
    if zh_transcript and en_transcript:
        # 双语字幕：先检测音频源语种，再按源合并
        logger.info(f"Merging bilingual subtitles: zh={len(zh_transcript.segments)}, en={len(en_transcript.segments)}")
        info_json = _load_info_json(temp_dir)
        transcript = await _pick_source_and_merge(zh_transcript, en_transcript, info_json)
    elif zh_transcript:
        # 只有中文字幕：ZH 是源，填充新字段
        transcript = _populate_single_lang(zh_transcript, source_lang="zh")
        logger.info(f"Using Chinese only: {len(transcript.segments)} segments")
    elif en_transcript:
        # 只有英文字幕：EN 是源，填充新字段（zh 由后续 translate 步骤填充）
        transcript = _populate_single_lang(en_transcript, source_lang="en")
        logger.info(f"Using English only: {len(transcript.segments)} segments")

    if transcript:
        logger.info(f"✅ Successfully fetched subtitles with {strategy_desc}: {len(transcript.segments)} segments")
        return True, transcript, strategy_desc

    return False, None, "no_valid_subtitle"


def _has_subtitles_signal(output: str) -> bool:
    """解析 yt-dlp --list-subs 输出, 判断视频是否存在任何字幕。

    yt-dlp 在 manual 与 auto 字幕都缺失时会同时打印两行:
        XEhf371Aeso has no subtitles
        XEhf371Aeso has no automatic captions
    只有当二者同时出现才判定为「确定无字幕」(返回 False)。
    其余情况 (有字幕清单 / 只缺其一 / 输出为空) 一律保守返回 True,
    避免误杀可下载字幕的视频, 让其继续走策略链。
    """
    if not output:
        return True
    no_manual = "has no subtitles" in output
    no_auto = "has no automatic captions" in output
    return not (no_manual and no_auto)


async def _video_has_any_subtitles(url: str, cookies_txt=None) -> bool:
    """~10s 探测视频是否有任何字幕 (manual 或 auto)。

    用 yt-dlp --list-subs --skip-download 快速判定, 用于无字幕视频的
    fail-fast: 探测明确无字幕时, 跳过整条 ~30min 的 CC 策略链直接回退 ASR。

    带重试 (最多 3 次): 首次 --list-subs 常因 YouTube 瞬时限流超时 (实测
    ep_1783401350118 首跑 40s 超时, 数分钟后仅 3.7s 成功)。单次失败不应退回
    30-45min 策略链 grind。拿到明确结论 (有/无字幕) 立即返回; 全部超时/异常
    才保守返回 True (不阻断), 宁可多试也不要误杀有字幕视频。
    """
    import logging
    logger = logging.getLogger(__name__)
    cmd = YTDLP_CMD + [
        "--skip-download", "--list-subs", "--no-warnings",
        "--socket-timeout", "15",
        url,
    ]
    if cookies_txt:
        cmd += ["--cookies", str(cookies_txt)]

    for attempt in range(1, 4):
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=25)
            return _has_subtitles_signal((stdout or b"").decode("utf-8", "ignore"))
        except Exception as e:
            logger.info(f"字幕存在性探测 {attempt}/3 失败: {str(e)[:60]}")
            if attempt < 3:
                await asyncio.sleep(3)
    logger.info("字幕探测 3 次均失败, 保守放行 (不 fail-fast)")
    return True


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

        # fail-fast: 先用 --list-subs (~10s) 探测视频是否有任何字幕。
        # 明确无字幕 (manual + auto 均无) 时直接返回 None, 避免逐条策略重试
        # (每条 ~4min 超时) 白烧 30-45min 才回退 ASR。探测本身异常则放行。
        if not await _video_has_any_subtitles(safe_url, cookies_txt):
            logger.info("视频无任何字幕 (manual+auto 均无), 跳过 CC 抓取链, 回退 ASR")
            return None

        # 2026 YouTube 翻译型自动字幕代码是 xx-en 格式（"from English"），
        # 旧版只有 zh-Hans/en，匹配不到 zh-Hans-en/en-en，导致"no subtitles"。
        # 这里同时兼容新（带 -en 后缀）旧格式。
        SUB_LANGS_2026 = "zh-Hans-en,en-en,zh-Hans,zh-Hant-en,zh-Hant,en,en-zh-Hans,zh-Hans-zh-Hans,zh-Hant-zh-Hans"

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
