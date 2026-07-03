"""
Apple AFM 3 SpeechAnalyzer ASR 转录模块

✅ 彻底摒弃Whisper，100%使用Apple AFM 3 Core Advanced (20B参数)
- 🚀 极快转录速度 (10-20x faster than Whisper)
- 🎯 更高的准确性 (苹果最新AI)
- ⚡ 硬件加速 (Apple Silicon优化)
- 💾 系统级集成 (无需下载模型)

系统要求：
- macOS 26+ (Tahoe) ✅
- Apple Silicon (M1+) ✅
"""

import asyncio
import subprocess
import logging
import sys
import time
from pathlib import Path
from typing import Optional, Callable
from .models import Transcript, Segment

logger = logging.getLogger(__name__)

# Swift桥接工具路径（编译后的可执行文件）
BRIDGE_TOOL = Path(__file__).parent / "speech_analyzer_bridge"


class AppleASR:
    """Apple AFM 3 SpeechAnalyzer 转录器"""

    def __init__(self):
        """初始化Apple ASR"""
        if sys.platform != "darwin":
            raise RuntimeError("❌ Apple AFM 3 only available on macOS 26+")

        # 检查macOS版本
        try:
            result = subprocess.run(
                ["sw_vers", "-productVersion"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                raise RuntimeError("无法检测macOS版本")

            version_str = result.stdout.strip()
            major, minor = map(int, version_str.split('.')[:2])

            if major < 26:
                raise RuntimeError(f"❌ 需要macOS 26+，当前版本: {version_str}")

            logger.info(f"✅ macOS {version_str} - 支持AFM 3 Core Advanced")

        except Exception as e:
            raise RuntimeError(f"系统检查失败: {e}")

        # 检查工具是否存在
        if not BRIDGE_TOOL.exists():
            raise RuntimeError(
                f"❌ Swift桥接工具不存在: {BRIDGE_TOOL}\n"
                f"请运行: cd tools && ./build_apple_asr.sh"
            )

    @staticmethod
    def check_available() -> bool:
        """检查Apple ASR是否可用"""
        if sys.platform != "darwin":
            return False

        try:
            # 检查macOS版本
            result = subprocess.run(
                ["sw_vers", "-productVersion"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode != 0:
                return False

            version_str = result.stdout.strip()
            major = int(version_str.split('.')[0])

            return major >= 26 and BRIDGE_TOOL.exists()

        except Exception:
            return False

    async def transcribe(
        self,
        audio_path: Path,
        language: str = "en-US",
        on_progress: Optional[Callable] = None,
    ) -> Transcript:
        """
        使用Apple AFM 3转录音频文件

        Args:
            audio_path: 音频文件路径
            language: 语言代码 (zh-CN, en-US等)
            on_progress: 进度回调函数

        Returns:
            Transcript对象
        """
        logger.info(f"🚀 启动Apple AFM 3 Core Advanced转录...")
        logger.info(f"   音频: {audio_path.name}")
        logger.info(f"   语言: {language}")

        if on_progress:
            on_progress("transcribe", 0.0)

        start_time = time.time()

        try:
            # BRIDGE_TOOL 是编译好的 Mach-O 可执行文件，直接运行；
            # 之前用 ["swift", BRIDGE_TOOL, ...] 会让 swift 把二进制当源码解释，
            # 报 "invalid UTF-8 in source file" 然后回退到慢的 Whisper。
            # 第三个参数是 locale（如 "zh-CN"/"en-US"），传给桥接选择语音模型。
            cmd = [str(BRIDGE_TOOL), str(audio_path), language]

            logger.info(f"   执行命令: {' '.join(cmd)}")

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            # communicate() 已等待进程结束、读取 stdout/stderr 并填充 returncode，
            # 不需要再 gather wait()（之前 gather 返回 [tuple, int] 被错拆成
            # stdout/stderr，导致 stderr 实际是 returncode → 'int' has no .decode()）
            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode() if stderr else "未知错误"
                raise RuntimeError(f"❌ Apple ASR失败: {error_msg}")

            # 解析转录文本
            transcript_text = stdout.decode().strip()

            if not transcript_text:
                raise RuntimeError("❌ 转录结果为空")

            # 转换为Segment格式
            segments = self._parse_transcript(transcript_text)

            elapsed = time.time() - start_time
            logger.info(f"✅ AFM 3转录完成: {len(segments)} segments, 耗时: {elapsed:.2f}秒")

            if on_progress:
                on_progress("transcribe", 1.0)

            # Transcript 要求 episode_id + language。episode_id 留空，由调用方
            # （pipeline）后续赋值。
            #
            # language 直接来自 locale 参数——它由调用方的 AUDIO 探测决定
            # （run_asr -> _probe_audio_language 多窗口投票；lang_detect cascade）。
            # 我们故意【不】从输出文本里重新检测语种：文本可能是翻译过的 CC、或
            # ASR 在错 locale 下产出的垃圾，二者都不能作为 AUDIO 语种的证据
            # （task 6 修正：移除了原先的 text-override）。
            language = "zh" if language.startswith("zh") else "en"
            return Transcript(episode_id="", language=language, segments=segments)

        except subprocess.TimeoutExpired:
            raise RuntimeError("❌ Apple ASR超时 (超过2小时)")
        except Exception as e:
            logger.error(f"❌ Apple ASR失败: {e}")
            raise

    def _parse_transcript(self, text: str) -> list[Segment]:
        """
        解析桥接输出的 JSON 数组为 Segment 列表。

        桥接输出格式：[{"text": "...", "start_ms": int, "end_ms": int}, ...]
        每个 element 是 phrase 级别的 segment，带真实时间戳（来自 audioTimeRange）。

        Args:
            text: 桥接 stdout（JSON 数组）

        Returns:
            Segment 列表
        """
        import json
        segments = []

        try:
            items = json.loads(text)
        except json.JSONDecodeError as e:
            # 兜底：桥接回退到纯文本输出时按行切分，时间戳置 0
            logger.warning(f"ASR 输出非 JSON，回退纯文本解析: {e}")
            items = [{"text": ln.strip(), "start_ms": 0, "end_ms": 0}
                     for ln in text.strip().split("\n") if ln.strip()]

        for i, item in enumerate(items):
            seg_text = (item.get("text") or "").strip()
            if not seg_text:
                continue
            segments.append(Segment(
                id=i,
                start_ms=int(item.get("start_ms", 0) or 0),
                end_ms=int(item.get("end_ms", 0) or 0),
                text_original=seg_text,
                # Apple Speech API 不提供说话人区分（已确认无 speaker attribute）
                speaker="A",
            ))

        return segments


# 全局实例
apple_asr_instance: Optional[AppleASR] = None


def get_apple_asr() -> AppleASR:
    """获取Apple ASR实例（单例）"""
    global apple_asr_instance

    if apple_asr_instance is None:
        apple_asr_instance = AppleASR()
        logger.info("✅ Apple AFM 3 Core Advanced 初始化成功")

    return apple_asr_instance


async def run_asr(
    audio_path: Path,
    on_progress: Optional[Callable[[float], None]] = None,
) -> Transcript:
    """
    运行ASR转录（仅使用Apple AFM 3）

    Args:
        audio_path: 音频文件路径
        on_progress: 进度回调 (0-1)

    Returns:
        Transcript对象
    """
    logger.info(f"🎯 AFM 3 Core Advanced ASR转录")
    logger.info(f"   音频: {audio_path}")

    if on_progress:
        on_progress(0.0)

    # 获取Apple ASR实例
    asr = get_apple_asr()

    # 前置语种探测：YouTube metadata 通常没有 language 字段（实测 NA），
    # 而 AFM 3 的 locale 决定输出语种——用错 locale 会在中文音频上产出 ", , ," 垃圾。
    # 用前 60 秒短样本判断真实语种，避免跑完完整音频才发现用错。
    # AFM 3 跑 60 秒音频 < 5s，探测成本远低于"跑完整后再重跑"。
    locale = await _probe_audio_language(audio_path, asr)
    logger.info(f"   探测语种: {locale}")

    # 用选中的 locale 跑完整音频（只跑一次）
    transcript = await asr.transcribe(
        audio_path,
        language=locale,
        on_progress=on_progress
    )

    logger.info(f"✅ 转录完成: {len(transcript.segments)} segments")

    if on_progress:
        on_progress(1.0)

    return transcript


# ============================================================================
# Multi-window audio language probe (task 6)
# ============================================================================

# 默认探测语种——投票平票/全静音/不可用时回退到此值。
# 选 en-US 因为历史行为如此，且 Apple ASR 在 en-US locale 下对任何语种都至少
# 不会崩（最坏产出垃圾，但仍可继续完整转写）。
_DEFAULT_LOCALE = "en-US"

# 单窗口长度（秒）。60s 在 Apple ASR 上约 5s 转写，2 locale ≈ 10s/窗口。
_WINDOW_LENGTH = 60

# 采样窗口数。N=5 × 2 locale × ~5s ≈ 50s/episode；相对"跑完整 3.8 小时再重跑"
# 的成本可忽略。对双语 intro 节目（前 60s 英文、正文中文）尤其关键——单窗口
# 探测会把它们判成 en。
_WINDOW_COUNT = 5

# 语种优势阈值：A 数量 > B 数量 × 1.5 才算 A 占优，否则记 mixed。
# 1.5x 留出"双语片段"的容差，避免轻微多数就被判成单语。
_DOMINANCE_RATIO = 1.5

# CJK 与 ASCII 判定的"近零"阈值：低于此字符数视为该侧无产出。
_SILENCE_THRESHOLD = 5


def _count_ascii_letters(text: str) -> int:
    """Count ASCII letters (a-z, A-Z) — en-US ASR 的母语脚本产出。"""
    return sum(1 for ch in text if ch.isascii() and ch.isalpha())


def _count_cjk_chars(text: str) -> int:
    """Count CJK Unified Ideographs (U+4E00..U+9FFF) — zh-CN ASR 的母语脚本产出。

    不计 CJK 标点（、。「」等），与 migrate_language_fields 的 cjk_ratio 一致。
    """
    return sum(1 for ch in text if "一" <= ch <= "鿿")


def _probe_duration_seconds(audio_path: Path) -> Optional[float]:
    """用 ffprobe 取音频时长（秒）。失败返回 None。"""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(audio_path)],
            capture_output=True, timeout=15,
        )
        if result.returncode != 0:
            return None
        return float(result.stdout.decode().strip())
    except Exception as e:
        logger.warning(f"ffprobe 取时长失败 ({e})")
        return None


async def _extract_window_wav(
    audio_path: Path, start: float, length: int, sample_path: str
) -> bool:
    """提取 [start, start+length] 秒音频为 16kHz mono wav。成功返回 True。"""
    result = subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{start:.2f}", "-i", str(audio_path),
         "-t", str(length), "-ar", "16000", "-ac", "1",
         "-c:a", "pcm_s16le", sample_path],
        capture_output=True, timeout=30,
    )
    if result.returncode != 0:
        logger.debug(
            f"窗口提取失败 start={start:.1f}s: {result.stderr.decode()[:200]}"
        )
        return False
    return True


async def _probe_window(
    audio_path: Path, asr, start: float, length: int = _WINDOW_LENGTH
) -> dict:
    """单窗口双 locale 探测：用 en-US 和 zh-CN 各跑一遍，比较母语脚本产出。

    判定逻辑（native-script comparison）：
    - en-US 输出数 ASCII 字母；zh-CN 输出数 CJK 汉字。
    - en: ascii > cjk × DOMINANCE_RATIO
    - zh: cjk  > ascii × DOMINANCE_RATIO
    - silent: 两侧都接近 0（< _SILENCE_THRESHOLD）
    - mixed:  其它（双语片段、信噪比低等）

    Args:
        audio_path: 原始音频路径（ffmpeg 从中切窗）。
        asr: AppleASR 实例（或 mock）。
        start: 窗口起始秒。
        length: 窗口长度秒（默认 60）。

    Returns:
        dict: {verdict, ascii, cjk, start, length}
    """
    import os
    import tempfile

    sample_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            sample_path = f.name

        if not await _extract_window_wav(audio_path, start, length, sample_path):
            return {"verdict": "silent", "ascii": 0, "cjk": 0,
                    "start": start, "length": length}

        en_out = await asr.transcribe(Path(sample_path), language="en-US")
        en_text = " ".join(s.text_original or "" for s in en_out.segments)
        ascii_n = _count_ascii_letters(en_text)

        zh_out = await asr.transcribe(Path(sample_path), language="zh-CN")
        zh_text = " ".join(s.text_original or "" for s in zh_out.segments)
        cjk_n = _count_cjk_chars(zh_text)

        if ascii_n < _SILENCE_THRESHOLD and cjk_n < _SILENCE_THRESHOLD:
            verdict = "silent"
        elif ascii_n > cjk_n * _DOMINANCE_RATIO:
            verdict = "en"
        elif cjk_n > ascii_n * _DOMINANCE_RATIO:
            verdict = "zh"
        else:
            verdict = "mixed"

        return {"verdict": verdict, "ascii": ascii_n, "cjk": cjk_n,
                "start": start, "length": length}
    finally:
        if sample_path:
            try:
                os.unlink(sample_path)
            except OSError:
                pass


def _majority_vote(verdicts: list[str]) -> tuple[str, bool]:
    """对非 silent 的窗口判定做多数投票。

    Returns:
        (language_locale, low_confidence):
        - language_locale: "en-US"/"zh-CN"，平票或无可投票窗口时回退默认。
        - low_confidence: True 当 (a) 无可投票窗口，(b) 平票，或 (c) 多数是 mixed。
    """
    votes = [v for v in verdicts if v != "silent"]
    if not votes:
        return _DEFAULT_LOCALE, True

    en_n = sum(1 for v in votes if v == "en")
    zh_n = sum(1 for v in votes if v == "zh")
    mixed_n = sum(1 for v in votes if v == "mixed")

    if zh_n > en_n:
        # zh 占多数——但若 mixed 也很多（>= zh），仍标低置信。
        low = mixed_n >= zh_n
        return "zh-CN", low
    if en_n > zh_n:
        low = mixed_n >= en_n
        return "en-US", low
    # 平票
    return _DEFAULT_LOCALE, True


async def probe_audio_language_detailed(
    audio_path: Path, asr, window_count: int = _WINDOW_COUNT
) -> dict:
    """多窗口双 locale 音频语种探测（详细版，供 migration 用）。

    在音频时长上均匀采样 window_count 个 60s 窗口（0%、25%、50%、75%、95%…），
    每个窗口用 en-US + zh-CN 各跑一遍 ASR，比较母语脚本产出判定该窗口语种，
    再对所有非 silent 窗口做多数投票。

    AUDIO-ONLY：判定只看 ASR 在不同 locale 下的实际产出，绝不读取已有的
    字幕/transcript 文本。

    成本：N=5 窗口 × 2 locale × ~5s ≈ 50s/episode。对 3.8 小时的双语 intro
    节目（前 60s 英文、正文中文），单窗口探测会误判，多窗口是必须的。

    ffprobe 不可用时退化为单前窗（length=60s），并记日志。

    Returns:
        dict: {language: "en-US"|"zh-CN", low_confidence: bool,
               windows: [per-window dict], duration_s: float|None,
               window_count_used: int}
    """
    duration = _probe_duration_seconds(audio_path)

    if duration is None or duration <= _WINDOW_LENGTH:
        # 退化：单前窗。ffprobe 不可用或音频太短。
        logger.info(
            f"多窗口探测退化为单前窗（duration={duration}, "
            f"ffprobe={'ok' if duration else 'unavailable'}）"
        )
        w = await _probe_window(audio_path, asr, start=0.0)
        language, low = _majority_vote([w["verdict"]])
        return {
            "language": language,
            "low_confidence": low,
            "windows": [w],
            "duration_s": duration,
            "window_count_used": 1,
        }

    # 在 [0, duration-_WINDOW_LENGTH] 上均匀取 window_count 个点。
    last_start = max(0.0, duration - _WINDOW_LENGTH)
    if window_count <= 1:
        starts = [0.0]
    else:
        starts = [last_start * (i / (window_count - 1)) for i in range(window_count)]

    windows = []
    for s in starts:
        try:
            w = await _probe_window(audio_path, asr, start=s)
        except Exception as e:
            logger.warning(f"窗口探测异常 start={s:.1f}s: {e}")
            w = {"verdict": "silent", "ascii": 0, "cjk": 0,
                 "start": s, "length": _WINDOW_LENGTH}
        windows.append(w)

    verdicts = [w["verdict"] for w in windows]
    language, low = _majority_vote(verdicts)
    logger.info(
        f"多窗口探测：verdicts={verdicts} -> {language} "
        f"(low_confidence={low})"
    )
    return {
        "language": language,
        "low_confidence": low,
        "windows": windows,
        "duration_s": duration,
        "window_count_used": len(windows),
    }


async def _probe_audio_language(audio_path: Path, asr) -> str:
    """多窗口双 locale 音频语种探测（向后兼容的 str 版本）。

    `probe_audio_language_detailed` 的薄包装。返回 "en-US" / "zh-CN"，
    调用方契约不变（run_asr / detect_source_language 仍只拿 str）。
    平票或探测失败时回退默认 en-US（与历史行为一致）。

    AUDIO-ONLY：见 probe_audio_language_detailed 的 docstring。
    """
    try:
        detailed = await probe_audio_language_detailed(audio_path, asr)
        return detailed["language"]
    except Exception as e:
        logger.warning(f"语种探测异常 ({e})，默认 {_DEFAULT_LOCALE}")
        return _DEFAULT_LOCALE
