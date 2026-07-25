"""save_episode_bundle 容错测试。

核心契约：文件 AtomicWriter.commit() 成功后，DB 状态更新失败 **不能**
触发 writer.rollback() —— 文件已持久化，DB 锁冲突是可重试的瞬时故障，
删文件会让整集 LLM 工作白费（systematic-debugging：真实事故中
ep_1784977817686 跑完 8 阶段，收尾 update_status_sync("ready") 撞
"database is locked" → rollback → 全部产物险些丢失）。
"""
import sqlite3

import pytest

from app import storage
from app.storage import save_episode_bundle


class _FakeWriter:
    """记录 commit/rollback 调用，可配置 write/commit 失败。"""

    def __init__(self, write_should_fail=False, commit_should_fail=False):
        self.write_should_fail = write_should_fail
        self.commit_should_fail = commit_should_fail
        self.committed = False
        self.rolled_back = False
        self.write_calls = []

    def write(self, name, data):
        self.write_calls.append(name)
        if self.write_should_fail:
            raise RuntimeError("disk full")

    def commit(self):
        if self.commit_should_fail:
            raise RuntimeError("commit failed")
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def _patch_status(monkeypatch, ready_raises=None, failed_raises=None):
    """替换 update_status_sync：ready 路径抛指定异常，failed 路径记录 + 可选抛。"""
    calls = {"ready": [], "failed": []}

    def fake_update(episode_id, status, error_msg=None):
        if status == "ready":
            calls["ready"].append((episode_id, error_msg))
            if ready_raises:
                raise ready_raises
        else:
            calls["failed"].append((episode_id, status, error_msg))
            if failed_raises:
                raise failed_raises

    monkeypatch.setattr(
        "app.database.EpisodeRepositorySync.update_status_sync",
        fake_update,
    )
    return calls


# --- 核心契约：文件 commit 成功后 DB ready 写失败 → 不毁文件 ---


def test_db_ready_failure_preserves_committed_files(monkeypatch, tmp_path):
    """文件已 commit → DB ready 写 locked → 文件不 rollback，best-effort 标 failed。"""
    writer = _FakeWriter()
    monkeypatch.setattr(storage, "AtomicWriter", lambda *a, **kw: writer)
    calls = _patch_status(
        monkeypatch,
        ready_raises=sqlite3.OperationalError("database is locked"),
    )

    # ready 写失败会 raise（让 worker 停；但文件已留，可后续恢复）
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        save_episode_bundle("ep1", tmp_path, outline={"entries": []})

    assert writer.committed is True, "文件应已 commit"
    assert writer.rolled_back is False, (
        "DB 状态写失败绝不能 rollback 已 commit 的文件（LLM 工作会白费）"
    )
    assert len(calls["ready"]) == 1
    assert len(calls["failed"]) == 1, "应 best-effort 标记 failed"
    assert calls["failed"][0][1] == "failed"


# --- 防御：ready 失败后标 failed 也失败 → 不冒泡二次异常 ---


def test_failed_marking_failure_does_not_mask_original(monkeypatch, tmp_path):
    """ready 写失败 + 标 failed 也失败 → 抛的是原始 ready 错误，不是二次 failed 错误。"""
    writer = _FakeWriter()
    monkeypatch.setattr(storage, "AtomicWriter", lambda *a, **kw: writer)
    _patch_status(
        monkeypatch,
        ready_raises=sqlite3.OperationalError("database is locked"),
        failed_raises=sqlite3.OperationalError("database is locked again"),
    )

    # 必须抛原始 ready 错误（locked），不是 failed 写的 "locked again"
    with pytest.raises(sqlite3.OperationalError, match="locked") as exc_info:
        save_episode_bundle("ep1", tmp_path, outline={"entries": []})

    assert "again" not in str(exc_info.value), (
        "二次 failed 写失败不应掩盖原始 ready 错误"
    )
    assert writer.rolled_back is False


# --- 原行为保护：文件写/commit 失败 → 仍 rollback + 标 failed ---


def test_file_write_failure_rolls_back_and_marks_failed(monkeypatch, tmp_path):
    """文件写入失败（commit 之前）→ rollback + 标 failed + raise（原行为）。"""
    writer = _FakeWriter(write_should_fail=True)
    monkeypatch.setattr(storage, "AtomicWriter", lambda *a, **kw: writer)
    calls = _patch_status(monkeypatch)

    with pytest.raises(RuntimeError, match="disk full"):
        save_episode_bundle("ep1", tmp_path, outline={"entries": []})

    assert writer.committed is False
    assert writer.rolled_back is True, "文件写失败应 rollback"
    assert len(calls["failed"]) == 1
    assert calls["failed"][0][1] == "failed"
    assert calls["ready"] == [], "文件没 commit 就失败，不该走 ready 路径"


def test_commit_failure_rolls_back_and_marks_failed(monkeypatch, tmp_path):
    """commit 本身失败 → rollback + 标 failed + raise。"""
    writer = _FakeWriter(commit_should_fail=True)
    monkeypatch.setattr(storage, "AtomicWriter", lambda *a, **kw: writer)
    calls = _patch_status(monkeypatch)

    with pytest.raises(RuntimeError, match="commit failed"):
        save_episode_bundle("ep1", tmp_path, outline={"entries": []})

    assert writer.rolled_back is True
    assert len(calls["failed"]) == 1


# --- 正常路径：文件 commit + DB ready 成功 ---


def test_happy_path_commits_and_marks_ready(monkeypatch, tmp_path):
    writer = _FakeWriter()
    monkeypatch.setattr(storage, "AtomicWriter", lambda *a, **kw: writer)
    calls = _patch_status(monkeypatch)

    save_episode_bundle("ep1", tmp_path, outline={"entries": []})

    assert writer.committed is True
    assert writer.rolled_back is False
    assert len(calls["ready"]) == 1
    assert calls["failed"] == []
