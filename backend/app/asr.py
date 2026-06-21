"""
ASR 转录模块
支持多种转录引擎：
1. Apple AFM 3 SpeechAnalyzer (推荐，仅macOS 26+)
2. Whisper (跨平台备用)

使用 faster-whisper 进行本地语音识别

实现跨进程文件锁，确保整个系统只有一个 ASR 在运行
"""
import asyncio
import fcntl
import logging
import time
import platform
from pathlib import Path
from typing import Optional, Callable, Tuple, List
from functools import lru_cache

from faster_whisper import WhisperModel
from .models import Transcript, Segment
from .config import (
    WHISPER_MODEL, WHISPER_COMPUTE, WHISPER_DEVICE,
    WHISPER_BEAM_SIZE, WHISPER_MIN_SILENCE_DURATION_MS,
    MAX_MODEL_CACHE_SIZE,
    ASR_LOCK_FILE, ASR_MAX_WAIT_SECONDS,
    ASR_WAIT_SHORT_THRESHOLD, ASR_WAIT_MEDIUM_THRESHOLD,
    ASR_WAIT_SHORT_INTERVAL, ASR_WAIT_MEDIUM_INTERVAL, ASR_WAIT_LONG_INTERVAL,
)

logger = logging.getLogger(__name__)

# 尝试导入Apple ASR
try:
    from .asr_apple import AppleASR, try_apple_asr_first
    APPLE_ASR_AVAILABLE = True
except ImportError:
    APPLE_ASR_AVAILABLE = False
    logger.info("Apple ASR module not available")


class ProcessLock:
    """跨进程文件锁

    使用 fcntl 实现跨进程锁，确保多个 Python 进程互斥。

    工作原理：
    1. 打开锁文件
    2. 尝试获取排他锁（LOCK_EX）
    3. 使用非阻塞模式（LOCK_NB），避免进程间死锁
    4. 成功获取锁后才能执行关键代码
    5. 退出时释放锁（LOCK_UN）

    注意事项：
    - 锁文件必须位于所有进程可访问的位置（如 /tmp）
    - 进程异常退出时，OS 会自动释放文件锁
    - 使用 0o600 权限确保只有文件所有者能访问

    Attributes:
        lock_file: 锁文件路径
        lock_fd: 文件描述符（获取锁后保持打开）
    """

    def __init__(self, lock_file: Path):
        """初始化进程锁

        Args:
            lock_file: 锁文件路径（建议使用 /tmp 下的文件）
        """
        self.lock_file = lock_file
        self.lock_fd = None

    def __enter__(self):
        """获取进程锁（上下文管理器入口）

        Returns:
            ProcessLock: 自身实例，支持 with 语句

        Raises:
            IOError: 锁被其他进程持有时
            OSError: 文件操作失败时
        """
        # 创建锁文件（如果不存在），权限设置为 0o600
        if not self.lock_file.exists():
            self.lock_file.touch(mode=0o600, exist_ok=True)
        else:
            # 确保现有文件权限正确
            self.lock_file.chmod(0o600)

        # 打开文件用于锁定
        self.lock_fd = open(self.lock_file, 'r')

        try:
            # 尝试获取排他锁（非阻塞）
            # LOCK_EX: 排他锁（写入锁）
            # LOCK_NB: 非阻塞模式（立即返回失败）
            fcntl.flock(self.lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            logger.info(f"Process lock acquired: {self.lock_file}")
            return self
        except IOError:
            # 锁已被其他进程持有
            self.lock_fd.close()
            self.lock_fd = None
            logger.warning(f"Process lock busy: {self.lock_file}")
            raise

    def __exit__(self, exc_type, exc_val, exc_tb):
        """释放进程锁（上下文管理器出口）

        无论是否发生异常，都会正确释放文件锁。
        Python 的 with 语句保证此方法一定会被调用。

        Args:
            exc_type: 异常类型（如果无异常则为 None）
            exc_val: 异常值
            exc_tb: 异常追踪信息
        """
        if self.lock_fd:
            # 释放锁
            # LOCK_UN: 解锁
            fcntl.flock(self.lock_fd.fileno(), fcntl.LOCK_UN)
            self.lock_fd.close()
            logger.info(f"Process lock released: {self.lock_file}")


def get_model() -> WhisperModel:
    """获取 Whisper 模型（LRU 缓存，限制内存使用）"""
    @lru_cache(maxsize=MAX_MODEL_CACHE_SIZE)
    def _load_model(model_name: str, device: str, compute_type: str) -> WhisperModel:
        logger.info(f"Loading Whisper model: {model_name} ({device}, {compute_type})")
        return WhisperModel(
            model_name,
            device=device,
            compute_type=compute_type,
        )

    compute_type = "int8" if WHISPER_COMPUTE == "int8" else "float16"
    return _load_model(WHISPER_MODEL, WHISPER_DEVICE, compute_type)


def _run_transcribe_blocking(model, audio_path: str, initial_prompt: str):
    """同步执行转录的包装函数"""
    return model.transcribe(
        audio_path,
        language=None,  # 自动检测语言
        initial_prompt=initial_prompt,
        vad_parameters={
            "min_silence_duration_ms": WHISPER_MIN_SILENCE_DURATION_MS,
        },
        word_timestamps=False,
        condition_on_previous_text=False,  # 防止长文件漂移
        beam_size=WHISPER_BEAM_SIZE,
    )


async def run_asr(
    audio_path: Path,
    on_progress: Optional[Callable[[float], None]] = None,
) -> Tuple[Transcript, str, int]:
    """
    运行 ASR 转录

    策略：
    1. 优先使用 Apple AFM 3 SpeechAnalyzer (快速、准确、macOS 26+)
    2. Fallback 到 Whisper (跨平台、兼容性好)

    跨进程锁保护：整个系统同时只能有一个 ASR 在运行

    Args:
        audio_path: 音频文件路径
        on_progress: 进度回调 (0-1)

    Returns:
        (Transcript, language, duration_ms)
    """
    # 技术术语 initial prompt，防止音译
    initial_prompt = """以下是一些技术术语的正确的书写方式：
OpenAI, Agent, API, prompt, LLM, Python, JavaScript, TypeScript, Rust, Go, Java
React, Vue, Angular, Docker, Kubernetes, Git, GitHub, GitLab
DeepSeek, Claude, ChatGPT, GPT-4, Gemini
数据库, 算法, 架构, 微服务, 前端, 后端, 全栈
产品经理, PM, 研发, 运维, 测试, 设计师
用户体验, UX, UI, 交互, 接口, 文档
"""

    logger.info(f"ASR: Waiting for lock (audio={audio_path.name})...")

    # 等待获取进程锁（带有重试机制）
    waited = 0
    wait_interval = ASR_WAIT_SHORT_INTERVAL

    while waited < ASR_MAX_WAIT_SECONDS:
        try:
            # 尝试获取进程锁
            with ProcessLock(ASR_LOCK_FILE):
                logger.info(f"ASR: Lock acquired, starting transcription for {audio_path.name}")

                try:
                    if on_progress:
                        on_progress(0.0)

                    # 策略1: 尝试使用 Apple AFM 3 (优先)
                    if APPLE_ASR_AVAILABLE:
                        apple_asr = try_apple_asr_first()
                        if apple_asr:
                            try:
                                logger.info("🚀 Using Apple AFM 3 SpeechAnalyzer (10-20x faster)")
                                transcript = await apple_asr.transcribe(
                                    audio_path,
                                    language="zh-CN",
                                    on_progress=lambda stage, progress: on_progress(progress * 0.8) if on_progress else None
                                )

                                # 获取音频时长
                                duration_ms = 0  # Apple ASR可能不提供精确时长
                                language = "zh"

                                logger.info(f"✅ Apple AFM 3 transcription completed")
                                return (transcript, language, duration_ms)

                            except Exception as e:
                                logger.warning(f"Apple ASR failed: {e}, falling back to Whisper")
                                if on_progress:
                                    on_progress(0.1)  # 重置进度

                    # 策略2: 使用 Whisper (fallback)
                    model = get_model()

                    start_time = time.time()
                    logger.info(f"Starting ASR for {audio_path}")

                    # 在线程池中运行阻塞的转录操作，避免阻塞事件循环
                    loop = asyncio.get_event_loop()
                    segments_info, info = await loop.run_in_executor(
                        None,  # 使用默认线程池
                        _run_transcribe_blocking,
                        model,
                        str(audio_path),
                        initial_prompt,
                    )

                    duration_ms = int(info.duration * 1000)
                    language = info.language
                    if language in ("zh", "yue"):
                        language = "zh"
                    elif language in ("en", "english"):
                        language = "en"
                    else:
                        language = "unknown"

                    # 构建 Segment 列表
                    segments = []
                    for i, seg in enumerate(segments_info):
                        if seg.text.strip():
                            segments.append(Segment(
                                id=i,
                                start_ms=int(seg.start * 1000),
                                end_ms=int(seg.end * 1000),
                                text_original=seg.text.strip(),
                            ))

                    if on_progress:
                        on_progress(1.0)

                    latency = int((time.time() - start_time) * 1000)
                    logger.info(f"ASR completed for {audio_path}: {len(segments)} segments, {latency}ms")

                    return (
                        Transcript(
                            episode_id="",  # 需要在调用时设置
                            language=language,
                            segments=segments,
                        ),
                        language,
                        duration_ms,
                    )
                finally:
                    logger.info("ASR: Processing complete, releasing lock")

            # 锁已释放，返回结果
            break

        except IOError:
            # 锁被占用，等待后重试
            logger.info(f"ASR: Lock busy, waiting {wait_interval}s...")
            await asyncio.sleep(wait_interval)
            waited += wait_interval
            # 渐进式增加等待时间
            if waited < ASR_WAIT_SHORT_THRESHOLD:
                wait_interval = ASR_WAIT_SHORT_INTERVAL
            elif waited < ASR_WAIT_MEDIUM_THRESHOLD:
                wait_interval = ASR_WAIT_MEDIUM_INTERVAL
            else:
                wait_interval = ASR_WAIT_LONG_INTERVAL
        except Exception as e:
            logger.error(f"ASR: Unexpected error: {e}")
            raise

    if waited >= ASR_MAX_WAIT_SECONDS:
        raise TimeoutError(f"ASR: Timeout waiting for lock after {ASR_MAX_WAIT_SECONDS}s")


def get_model_info() -> dict:
    """获取当前模型信息"""
    return {
        "model": WHISPER_MODEL,
        "compute": WHISPER_COMPUTE,
        "device": WHISPER_DEVICE,
    }
