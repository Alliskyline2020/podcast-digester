"""
Apple AFM 3 SpeechAnalyzer ASR 转录模块

使用Apple的SpeechAnalyzer API进行本地转录
需要macOS 26+ 和 Apple Silicon (M1+)

优势：
- 比Whisper快10-20倍（硬件加速）
- 更准确的中文识别
- 不需要下载模型文件
- 系统级优化
"""

import subprocess
import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional, Callable
from .models import Transcript, Segment

logger = logging.getLogger(__name__)

# Swift桥接工具路径
BRIDGE_TOOL = Path(__file__).parent.parent / "tools" / "speech_analyzer_bridge"


class AppleASR:
    """Apple AFM 3 SpeechAnalyzer 转录器"""

    def __init__(self):
        """初始化Apple ASR"""
        if sys.platform != "darwin":
            raise RuntimeError("Apple ASR only available on macOS")

        # 检查工具是否存在
        if not BRIDGE_TOOL.exists():
            logger.warning(f"Swift bridge tool not found at {BRIDGE_TOOL}")
            logger.warning("Falling back to Whisper")
            raise RuntimeError("Swift bridge tool not compiled")

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
            major, minor = map(int, version_str.split('.')[:2])

            # 需要macOS 26+
            if major >= 26:
                return BRIDGE_TOOL.exists()

        except Exception:
            pass

        return False

    async def transcribe(
        self,
        audio_path: Path,
        language: str = "zh-CN",
        on_progress: Optional[Callable] = None,
    ) -> Transcript:
        """
        转录音频文件

        Args:
            audio_path: 音频文件路径
            language: 语言代码 (zh-CN, en-US, etc.)
            on_progress: 进度回调函数

        Returns:
            Transcript对象
        """
        if on_progress:
            on_progress("transcribe", 0.0)

        logger.info(f"Starting Apple AFM 3 ASR for {audio_path}")

        try:
            # 调用Swift桥接工具
            cmd = [
                "swift",
                str(BRIDGE_TOOL),
                str(audio_path),
                language
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=7200,  # 2小时超时
                check=True
            )

            if result.returncode != 0:
                error_msg = result.stderr or "Unknown error"
                raise RuntimeError(f"Apple ASR failed: {error_msg}")

            # 解析转录文本
            transcript_text = result.stdout.strip()

            # 转换为Segment格式
            segments = self._parse_transcript(transcript_text)

            if on_progress:
                on_progress("transcribe", 1.0)

            return Transcript(segments=segments)

        except subprocess.TimeoutExpired:
            raise RuntimeError("Apple ASR timeout after 2 hours")
        except Exception as e:
            logger.error(f"Apple ASR failed: {e}")
            raise

    def _parse_transcript(self, text: str) -> list[Segment]:
        """
        解析转录文本为Segment列表

        Args:
            text: 转录文本

        Returns:
            Segment列表
        """
        segments = []

        # 简单按行分割（实际实现可能需要更复杂的解析）
        lines = text.strip().split('\n')

        for i, line in enumerate(lines):
            if line.strip():
                segment = Segment(
                    id=i,
                    start_ms=0,  # Apple ASR可能不提供精确时间戳
                    end_ms=0,
                    text_original=line.strip(),
                    text_clean=line.strip(),
                    speaker="A",
                    language="zh",
                )
                segments.append(segment)

        return segments


def try_apple_asr_first() -> Optional[AppleASR]:
    """
    尝试使用Apple ASR，如果不可用返回None

    Returns:
        AppleASR实例或None
    """
    try:
        if AppleASR.check_available():
            logger.info("✅ Using Apple AFM 3 SpeechAnalyzer (fast & accurate)")
            return AppleASR()
        else:
            logger.info("⚠️  Apple ASR not available, falling back to Whisper")
            return None
    except Exception as e:
        logger.warning(f"Apple ASR check failed: {e}")
        return None
