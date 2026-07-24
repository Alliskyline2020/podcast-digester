"""WorkerLock 单例互斥回归。

背景：worker 单例锁默认曾是全局 ``/tmp/podcast_worker.pid``，同机多实例/多项目会
共用一把锁互相挤掉（正是本次会话撞到的根因：旧实例 PID 7308 持全局锁，新 worker
起不来）。修复后默认锁文件在项目根 ``.worker_pid``；本测试不依赖默认路径，直接用
tmp_path 验证 fcntl 互斥语义：同文件第二把锁被拒、退出即释放、不同文件不冲突。
"""
import pytest

from worker import WorkerLock


def test_second_lock_on_same_file_is_rejected(tmp_path):
    """同一锁文件，第二把锁应被拒（fcntl LOCK_EX|LOCK_NB 失败抛 OSError）。"""
    lock_file = tmp_path / "worker.pid"
    first = WorkerLock(lock_file)
    first.__enter__()
    try:
        with pytest.raises(OSError):  # Python3 中 IOError 即 OSError
            WorkerLock(lock_file).__enter__()
    finally:
        first.__exit__(None, None, None)


def test_lock_releases_on_exit(tmp_path):
    """__exit__ 释放 flock 后，同一文件应能重新获取（验证锁不会泄漏）。"""
    lock_file = tmp_path / "worker.pid"
    with WorkerLock(lock_file):
        pass
    with WorkerLock(lock_file):
        pass


def test_different_lock_files_do_not_conflict(tmp_path):
    """不同锁文件互不影响（多实例/多项目各用各的锁文件时不应误判占用）。"""
    with WorkerLock(tmp_path / "a.pid"):
        with WorkerLock(tmp_path / "b.pid"):
            pass
