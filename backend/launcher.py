#!/usr/bin/env python3
"""
Podcast Digester 桌面版统一入口（launcher）

桌面打包（PyInstaller）后的单一二进制承担两个角色：
  - 默认：API 服务（进程内 uvicorn）+ 自动拉起 Worker 子进程
  - --worker：Worker 角色（队列轮询 / ASR / LLM 管线）

为什么需要它：
  历史上 API 与 Worker 是两个独立进程，用户忘记开 Worker 时
  「粘贴链接后一直不动」。桌面版由 launcher 统一管理：
  Electron 只需 spawn 本二进制并监控一个进程；
  本进程退出（SIGTERM/SIGINT）时会先回收 Worker 子进程，不留孤儿。

环境变量（Electron 主进程注入）：
  PODCAST_DIGESTER_HOST       默认 127.0.0.1
  PODCAST_DIGESTER_PORT       默认 8765
  PODCAST_DIGESTER_DATA_DIR   数据目录（桌面版指向 Application Support）
  PODCAST_DIGESTER_WEB_DIST   前端构建产物目录（存在则由后端托管 SPA）
  PODCAST_DIGESTER_NO_WORKER  设为 1 时不拉起 Worker（调试用）
"""
import asyncio
import atexit
import logging
import os
import signal
import subprocess
import sys
from pathlib import Path

logging.basicConfig(
    level=os.getenv("PODCAST_DIGESTER_LOG_LEVEL", "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("launcher")

IS_FROZEN = getattr(sys, "frozen", False)

# 让 `import app.*` 在源码模式下可用（frozen 模式 PyInstaller 已处理）
_BACKEND_DIR = Path(__file__).resolve().parent
if not IS_FROZEN and str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))


def run_worker() -> None:
    """Worker 角色入口：委托给既有 worker 模块（单例锁在其内部保证）。"""
    from worker import main as worker_main

    worker_main()


class WorkerSupervisor:
    """Worker 子进程监管：拉起、健康监测、退出回收。"""

    def __init__(self) -> None:
        self._proc: subprocess.Popen | None = None

    def start(self) -> None:
        if os.getenv("PODCAST_DIGESTER_NO_WORKER") == "1":
            logger.info("PODCAST_DIGESTER_NO_WORKER=1, skipping worker spawn")
            return
        if IS_FROZEN:
            cmd = [sys.executable, "--worker"]
        else:
            cmd = [sys.executable, str(_BACKEND_DIR / "worker.py")]
        self._proc = subprocess.Popen(
            cmd,
            cwd=str(_BACKEND_DIR),
            env=os.environ.copy(),
        )
        logger.info(f"Worker spawned (PID: {self._proc.pid})")

    def stop(self) -> None:
        """先 SIGTERM，宽限 5s 后 SIGKILL。"""
        if not self._proc or self._proc.poll() is not None:
            return
        logger.info(f"Stopping worker (PID: {self._proc.pid})")
        self._proc.terminate()
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            logger.warning("Worker did not exit in 5s, killing")
            self._proc.kill()
            self._proc.wait(timeout=5)
        logger.info("Worker stopped")

    def ensure_alive(self) -> None:
        """Worker 异常退出时拉起新实例（单例锁防重）。"""
        if self._proc and self._proc.poll() is not None:
            logger.warning(
                f"Worker exited unexpectedly (code {self._proc.returncode}), respawning"
            )
            self.start()


def run_api() -> None:
    """API 角色入口：uvicorn 进程内运行 + Worker 子进程监管。"""
    import uvicorn

    from app.config import settings

    supervisor = WorkerSupervisor()
    supervisor.start()
    atexit.register(supervisor.stop)

    def _handle_signal(signum, _frame):
        logger.info(f"Received signal {signum}, shutting down")
        supervisor.stop()
        # 交给 uvicorn 自身的信号处理完成优雅退出
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    config = uvicorn.Config(
        "app.main:app",
        host=settings.bind_host,
        port=settings.bind_port,
        log_level=settings.log_level.lower(),
        # 桌面单用户场景：单 worker 进程即可
        workers=1,
    )
    server = uvicorn.Server(config)
    try:
        server.run()
    finally:
        supervisor.stop()


def main() -> None:
    if "--worker" in sys.argv[1:]:
        run_worker()
    else:
        run_api()


if __name__ == "__main__":
    main()
