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
    WORKER_POLL_INTERVAL_SECONDS, WORKER_LOCK_FILE,
    WORKER_MAX_DOWNLOAD_RETRIES, WORKER_RETRY_BACKOFF,
)

# mid-state：episode 处于这些状态时若被 worker 发现，必然是上次进程崩溃留下的
# 孤儿——worker 串行单例（fcntl 锁 + 阻塞式 await），poll 期间不处理任何任务，
# 故 poll 中看到的 mid-state 不可能是「正被本 worker 处理」。安全重置 pending 续跑。
_MID_PROCESS_STATUSES = ["downloading", "asr_running", "llm_running"]


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

        每轮：
        1. 自愈：把 downloading/asr_running/llm_running 的孤儿重置 pending
           （worker 串行单例，这些状态必为上次崩溃残留）。
        2. 串行处理 pending（FIFO）：resume_episode——无 checkpoint→全量跑；
           有 checkpoint→跳过已完成阶段。比 run_ingest 更省（重试/恢复不重做
           已完成的下载/ASR）。
        3. sleep poll_interval。

        单 owner 模型：API 只置状态、不跑 pipeline（resume 端点也只入队），
        故不存在 API/worker 抢同一集的竞态；mid-state 只能是 worker 自身崩溃残留。
        """
        from app.database import EpisodeRepository, SourceRepository
        from app.pipeline import pipeline as audio_pipeline

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
                # 1. 自愈：重置 mid-state 孤儿 → pending（首轮即启动扫描）。
                await self._requeue_orphaned_mid_state()

                # 2. 串行处理 pending（FIFO）。
                pending_episodes = await EpisodeRepository.get_by_statuses(["pending"])

                if pending_episodes:
                    logger.info(f"Found {len(pending_episodes)} pending episodes")

                    for episode in pending_episodes:
                        episode_id = episode["id"]
                        logger.info(f"Processing episode: {episode_id}")

                        # 取原始输入：source.raw_input → usage_log paste 兜底
                        # （与 resume 端点同路径）。
                        raw_input = await SourceRepository.resolve_raw_input(episode_id)

                        if not raw_input:
                            # 找不到原始输入（极早期崩溃 / source 表损坏）：置 failed
                            # 给可操作提示，而非静默 skipping 让它永远挂 pending。
                            logger.warning(f"No raw_input found for episode {episode_id}, marking failed")
                            await EpisodeRepository.update_status(
                                episode_id, "failed",
                                error_msg="找不到原始输入(URL/路径)，请在界面手动重新提交",
                            )
                            continue

                        logger.info(f"Starting resume for {episode_id} with input: {raw_input}")
                        try:
                            await audio_pipeline.resume_episode(
                                episode_id, raw_input, on_progress=None
                            )
                            logger.info(f"Successfully processed episode: {episode_id}")
                        except Exception as e:
                            await self._handle_episode_failure(episode_id, e)

                # 等待下一次轮询
                await asyncio.sleep(self.poll_interval)

            except Exception as e:
                logger.error(f"Worker loop error: {e}")
                await asyncio.sleep(self.poll_interval)

    async def _requeue_orphaned_mid_state(self) -> int:
        """把 downloading/asr_running/llm_running 的 episode 重置 pending。

        worker 串行单例 + fcntl 锁：本方法运行时本 worker 未在处理任何任务
        （run() 是阻塞串行），故这些 mid-state 必为上次进程崩溃残留的孤儿，
        安全重置。retry_count 保留（崩溃不计入瞬时重试预算，但保留可观测性）。

        Returns:
            重置的 episode 数。
        """
        from app.database import EpisodeRepository

        stuck = await EpisodeRepository.get_by_statuses(_MID_PROCESS_STATUSES)
        for ep in stuck:
            eid = ep["id"]
            logger.warning(
                f"[self-heal] re-enqueue stuck {eid} "
                f"(status={ep.get('status')}) → pending"
            )
            await EpisodeRepository.update_status(eid, "pending")
        return len(stuck)

    async def _handle_episode_failure(self, episode_id: str, exc: Exception) -> bool:
        """处理单集处理异常（从 run() 抽出便于单测）。

        - retryable 异常（DownloadTemporaryError 等）+ 配额未耗尽 → 指数退避后
          回 pending，下轮 poll 重拾；返回 True。
        - 永久错误（DownloadError 等）或配额耗尽 → 标 failed；返回 False。

        Returns:
            True 若已重排为 pending（重试中）；False 若已终态 failed。
        """
        from app.database import EpisodeRepository  # 与 run() 同：函数局部导入

        if getattr(exc, "retryable", False):
            retry_count = await EpisodeRepository.get_retry_count(episode_id)
            if retry_count < WORKER_MAX_DOWNLOAD_RETRIES:
                logger.warning(
                    f"Episode {episode_id} transient failure, "
                    f"will retry (attempt {retry_count + 1}/"
                    f"{WORKER_MAX_DOWNLOAD_RETRIES}): {exc}"
                )
                # 退避阻塞当前轮——单用户自托管场景可接受；
                # 给瞬时故障（代理断流 / YT 短时限流）时间消散。
                await asyncio.sleep(WORKER_RETRY_BACKOFF * (2 ** retry_count))
                await EpisodeRepository.update_status(
                    episode_id, "pending", retry_count=retry_count + 1
                )
                return True
            logger.error(
                f"Episode {episode_id} exhausted "
                f"{WORKER_MAX_DOWNLOAD_RETRIES} retries: {exc}"
            )
        logger.error(f"Failed to process episode {episode_id}: {exc}", exc_info=True)
        await EpisodeRepository.update_status(episode_id, "failed", error_msg=str(exc))
        return False

    def start(self):
        """启动 Worker（原子获取锁）"""
        try:
            # 尝试获取 Worker 锁（原子操作）
            self._worker_lock = WorkerLock(WORKER_LOCK_FILE)

            with self._worker_lock:
                # 锁定成功即证明无活动 worker（同 DATA_DIR）：fcntl flock 由 OS 在
                # 进程死亡时自动释放，取到锁 = 上一个实例已退出。早期按进程名 pgrep + kill -9
                # 的「清理旧进程」会误杀其它克隆/同名进程（曾跨克隆误杀生产 worker），已移除。
                # 不同 DATA_DIR 的 worker 用各自锁文件，本就独立运行，互不该杀。
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
