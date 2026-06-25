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
            # （pipeline）后续赋值；language 从实际转写文本检测（CJK→zh，否则→en），
            # 不信 Swift 桥接写死的 zh-CN locale——英文节目会被误判成 zh 导致跳过翻译。
            sample = " ".join(s.text_original for s in segments[:20])
            detected = "zh" if any("\u4e00" <= ch <= "\u9fff" for ch in sample) else "en"
            return Transcript(episode_id="", language=detected, segments=segments)

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


async def _probe_audio_language(audio_path: Path, asr) -> str:
    """用前 60 秒短样本探测音频语种。

    策略：用 en-US 跑短样本。
    - 英文音频：en-US 产出正常（segment 多、字符多）→ 继续用 en-US
    - 中文音频：en-US 产出垃圾（segment 极少）→ 改用 zh-CN

    这样完整音频只需跑一次（vs 后置兜底要跑两次）。

    Returns:
        "en-US" 或 "zh-CN"。探测失败默认 en-US（原行为）。
    """
    import tempfile
    import os
    sample_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            sample_path = f.name

        # ffmpeg 提取前 60 秒，转 16kHz mono wav（bridge 对 wav 兼容性最好）
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(audio_path), "-t", "60",
             "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", sample_path],
            capture_output=True, timeout=30,
        )
        if result.returncode != 0:
            logger.warning(
                f"短样本提取失败，默认 en-US：{result.stderr.decode()[:200]}"
            )
            return "en-US"

        probe = await asr.transcribe(Path(sample_path), language="en-US")
        total_chars = sum(len(s.text_original or "") for s in probe.segments)

        # 60 秒英文音频应产出 >= 5 segment 且 >= 200 字符。
        # 低于阈值视为 en-US 失败（多半是中文音频被当英文处理）。
        if len(probe.segments) >= 5 and total_chars >= 200:
            logger.info(
                f"短样本探测：en-US 正常 ({len(probe.segments)} segs, "
                f"{total_chars} chars) → 英文音频"
            )
            return "en-US"
        else:
            logger.info(
                f"短样本探测：en-US 疑似垃圾 ({len(probe.segments)} segs, "
                f"{total_chars} chars) → 中文音频，改用 zh-CN"
            )
            return "zh-CN"
    except Exception as e:
        logger.warning(f"语种探测异常 ({e})，默认 en-US")
        return "en-US"
    finally:
        if sample_path:
            try:
                os.unlink(sample_path)
            except OSError:
                pass
