#!/usr/bin/env python3
"""
Worker 进程 - 轮询处理 pending 状态的节目
单例模式：确保同时只有一个 Worker 在运行

使用 fcntl 文件锁实现跨进程原子操作，防止竞态条件
"""
import asyncio
import fcntl
import logging
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Optional

# 添加 app 目录到路径
sys.path.insert(0, str(Path(__file__).parent))


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

from app.config import (
    WORKER_POLL_INTERVAL_SECONDS, WORKER_LOCK_FILE, PROCESS_CLEANUP_PATTERNS,
)


class WorkerLock:
    """Worker 进程锁（单例模式的核心实现）

    工作原理：
    1. 使用 fcntl.flock() 实现跨进程原子锁
    2. 非阻塞模式（LOCK_NB）避免进程间死锁
    3. 获取锁后写入当前 PID 到锁文件
    4. 异常退出时 OS 自动释放文件锁

    锁文件位置：/tmp/podcast_worker.pid
    文件权限：0o600（仅所有者可读写）

    与 ProcessLock 的区别：
    - ProcessLock 用于 ASR 转录锁（短期持有）
    - WorkerLock 用于 Worker 单例（长期持有）
    - 两者使用不同的锁文件，互不冲突

    Attributes:
        lock_file: 锁文件路径
        lock_fd: 文件描述符（获取锁后保持打开）

    Example:
        >>> lock = WorkerLock(Path("/tmp/worker.pid"))
        >>> with lock:
        ...     # 独占执行
        ...     run_worker()
    """

    def __init__(self, lock_file: Path):
        self.lock_file = lock_file
        self.lock_fd = None

    def __enter__(self):
        # 创建锁文件（如果不存在），权限设置为 0o600
        if not self.lock_file.exists():
            self.lock_file.touch(mode=0o600, exist_ok=True)
        else:
            # 确保现有文件权限正确
            self.lock_file.chmod(0o600)

        # 打开文件用于锁定
        self.lock_fd = open(self.lock_file, 'r+')

        try:
            # 尝试获取排他锁（非阻塞）
            fcntl.flock(self.lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            # 锁定成功，写入当前 PID
            self.lock_fd.seek(0)
            self.lock_fd.truncate()
            self.lock_fd.write(str(os.getpid()))
            self.lock_fd.flush()

            logger.info(f"Worker lock acquired: {self.lock_file} (PID: {os.getpid()})")
            return self
        except IOError:
            # 锁已被其他进程持有
            self.lock_fd.close()
            self.lock_fd = None

            # 尝试读取占用锁的进程 PID
            try:
                with open(self.lock_file, 'r') as f:
                    owner_pid = f.read().strip()
                logger.warning(f"Worker lock busy: {self.lock_file} (held by PID: {owner_pid})")
            except Exception:
                logger.warning(f"Worker lock busy: {self.lock_file}")
            raise

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.lock_fd:
            # 清空 PID 文件
            self.lock_fd.seek(0)
            self.lock_fd.truncate()

            # 释放锁
            fcntl.flock(self.lock_fd.fileno(), fcntl.LOCK_UN)
            self.lock_fd.close()
            logger.info(f"Worker lock released: {self.lock_file}")


def cleanup_old_processes():
    """清理可能残留的旧进程

    背景：
    - Worker 或 Whisper 进程异常终止时可能残留
    - 残留进程占用 CPU 和内存资源
    - 可能导致新的 ASR 任务无法获取锁

    清理策略：
    - 使用 pgrep 查找匹配进程名称的进程
    - 跳过当前进程（避免自杀）
    - 使用 kill -9 强制终止

    清理模式：
    - "whisper": 匹配 faster-whisper 相关进程
    - "faster-whisper": 匹配 whisper 模型加载进程
    - "python.*worker.py": 匹配旧的 worker 进程

    注意：此函数在 Worker 获取锁后调用，确保只有一个 Worker 在执行清理
    """
    for proc_pattern in PROCESS_CLEANUP_PATTERNS:
        try:
            result = subprocess.run(
                ["pgrep", "-f", proc_pattern],
                capture_output=True,
                text=True
            )
            if result.returncode == 0 and result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    try:
                        # 跳过当前进程
                        if int(pid) == os.getpid():
                            continue
                        subprocess.run(["kill", "-9", pid], capture_output=True)
                        logger.info(f"Killed old process: {pid} ({proc_pattern})")
                    except Exception as e:
                        logger.debug(f"Failed to kill {pid}: {e}")
        except Exception as e:
            logger.debug(f"Failed to search for {proc_pattern}: {e}")


class Worker:
    """独立 Worker 进程（单例模式，使用文件锁）

    工作流程：
    1. 启动时获取 WorkerLock（原子操作）
    2. 清理可能残留的旧进程
    3. 进入主循环，轮询 pending 状态的节目
    4. 对每个节目调用 pipeline 处理
    5. 处理完成后等待下一次轮询

    轮询机制：
    - 默认间隔：5 秒（可通过配置修改）
    - 每次轮询查询所有 pending 状态的节目
    - 串行处理，一次只处理一个节目

    与其他组件的交互：
    - EpisodeRepository: 查询 pending 状态的节目
    - UsageLogRepository: 获取节目的原始输入（URL）
    - pipeline: 执行完整的下载→ASR→LLM 流程

    错误处理：
    - 单个节目失败不影响其他节目
    - 失败的节目标记为 failed 状态
    - Worker 持续运行，不因单次失败退出

    Attributes:
        poll_interval: 轮询间隔（秒）
        running: 运行状态标志
        _worker_lock: Worker 锁实例
    """

    def __init__(self, poll_interval: int = None):
        """初始化 Worker

        Args:
            poll_interval: 轮询间隔（秒），默认使用配置值
        """
        self.poll_interval = poll_interval or WORKER_POLL_INTERVAL_SECONDS
        self.running = False
        self._worker_lock = None

    async def run(self):
        """主循环

        循环逻辑：
        1. 查询 pending 状态的节目
        2. 对每个节目：
           - 获取原始输入（从 usage_log）
           - 调用 pipeline.process_episode()
           - 处理成功/失败
        3. 等待 poll_interval 后下一轮

        注意：此方法不返回，直到 stop() 被调用
        """
        from app.database import EpisodeRepository, UsageLogRepository
        from app.ingest import pipeline

        logger.info("Worker started")

        # 优雅退出：SIGTERM/SIGINT → stop()，让当前轮处理完后主循环自然退出。
        # （fcntl 单例锁本就会随进程退出自动释放；此处只让循环体面收尾、
        # 避免被 SIGTERM 直接打断正在跑的 pipeline。）
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, self.stop)
            except (NotImplementedError, RuntimeError):
                # 非 POSIX 或无事件循环时回退：交给默认信号行为（进程退出）
                pass

        while self.running:
            try:
                # 查询 pending 状态的节目
                pending_episodes = await EpisodeRepository.get_by_statuses(["pending"])

                if pending_episodes:
                    logger.info(f"Found {len(pending_episodes)} pending episodes")

                    for episode in pending_episodes:
                        episode_id = episode["id"]
                        logger.info(f"Processing episode: {episode_id}")

                        # 获取原始输入（从 usage_log 中获取）
                        logs = await UsageLogRepository.get_by_episode(episode_id, limit=1)

                        if logs:
                            raw_input = logs[0]["payload_json"]
                            logger.info(f"Starting ingest for {episode_id} with input: {raw_input}")

                            try:
                                await pipeline.run_ingest(
                                    episode_id=episode_id,
                                    raw_input=raw_input,
                                    on_progress=None
                                )
                                logger.info(f"Successfully processed episode: {episode_id}")
                            except Exception as e:
                                logger.error(f"Failed to process episode {episode_id}: {e}", exc_info=True)
                                await EpisodeRepository.update_status(
                                    episode_id,
                                    "failed",
                                    error_msg=str(e)
                                )
                        else:
                            logger.warning(f"No usage log found for episode {episode_id}")

                # 等待下一次轮询
                await asyncio.sleep(self.poll_interval)

            except Exception as e:
                logger.error(f"Worker loop error: {e}")
                await asyncio.sleep(self.poll_interval)

    def start(self):
        """启动 Worker（原子获取锁）"""
        try:
            # 尝试获取 Worker 锁（原子操作）
            self._worker_lock = WorkerLock(WORKER_LOCK_FILE)

            with self._worker_lock:
                # 锁定成功，清理旧进程
                cleanup_old_processes()

                self.running = True

                try:
                    asyncio.run(self.run())
                finally:
                    logger.info("Worker stopped")
        except IOError:
            logger.warning("⚠️ Another Worker is already running. Exiting.")
            sys.exit(1)

    def stop(self):
        """停止 Worker"""
        self.running = False


def main():
    """主函数"""
    worker = Worker()
    worker.start()


if __name__ == "__main__":
    main()
