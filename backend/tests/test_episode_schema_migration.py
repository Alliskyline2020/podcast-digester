"""init_db schema 迁移回归测试（经 migrations runner）。

背景：fresh 安装时 init_db 建表曾漏建 episode.title_zh / episode.transcript，
而 pipeline 的 EpisodeRepository.update 与 update_transcript 会写入它们，
导致任何任务跑到写库即 'no such column' 崩溃。迁移 001（_m001_episode_columns，
经 run_migrations 调度）为历史/缺列库幂等补列；新库则由 CREATE TABLE 直接含。
"""
import sqlite3

import aiosqlite

from app.migrations.runner import run_migrations


def _make_legacy_episode_db(path) -> None:
    """建一个「旧 schema」episode 表（无 title_zh/transcript），模拟历史库。"""
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE episode (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            language TEXT,
            media_path TEXT,
            is_fixture INTEGER DEFAULT 0,
            error_msg TEXT,
            source_type TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            last_activity_ts TEXT,
            paragraph_mappings TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def _episode_columns(path) -> list[str]:
    conn = sqlite3.connect(path)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(episode)").fetchall()]
    conn.close()
    return cols


async def test_run_migrations_adds_missing_columns(tmp_path):
    """缺列的历史库 → 补齐 title_zh + transcript。"""
    db_path = tmp_path / "legacy.db"
    _make_legacy_episode_db(db_path)
    assert "title_zh" not in _episode_columns(db_path)

    async with aiosqlite.connect(db_path) as db:
        await run_migrations(db)

    cols = _episode_columns(db_path)
    assert "title_zh" in cols
    assert "transcript" in cols


async def test_run_migrations_idempotent(tmp_path):
    """已应用过的库再跑 → user_version 闸门挡住重跑、列不重复（幂等）。"""
    db_path = tmp_path / "legacy.db"
    _make_legacy_episode_db(db_path)

    async with aiosqlite.connect(db_path) as db:
        await run_migrations(db)  # 第一次：补列 + user_version=1
        await run_migrations(db)  # 第二次：user_version 已=1，不重跑

    cols = _episode_columns(db_path)
    assert cols.count("title_zh") == 1
    assert cols.count("transcript") == 1


async def test_run_migrations_preserves_data(tmp_path):
    """补列不破坏已有数据。"""
    db_path = tmp_path / "legacy.db"
    _make_legacy_episode_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO episode (id, title, status, created_at, updated_at) "
        "VALUES ('ep_1', 'hello', 'ready', '2026-01-01', '2026-01-01')"
    )
    conn.commit()
    conn.close()

    async with aiosqlite.connect(db_path) as db:
        await run_migrations(db)

    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT id, title, status, title_zh, transcript FROM episode WHERE id='ep_1'"
    ).fetchone()
    conn.close()
    assert row[0] == "ep_1"
    assert row[1] == "hello"
    assert row[2] == "ready"
    assert row[3] is None  # 新列默认 NULL
    assert row[4] is None
