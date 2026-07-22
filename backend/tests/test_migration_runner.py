"""迁移 runner 的幂等性与 user_version 行为测试。

保证：fresh 库 init_db 后 user_version 推进到最新、演进列就位；重复跑不重跑、
不报错（幂等）。
"""
import sqlite3

from app import database
from app.migrations.runner import MIGRATIONS, run_migrations


def _user_version(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    v = conn.execute("PRAGMA user_version").fetchone()[0]
    conn.close()
    return v


def _episode_cols(db_path: str) -> set:
    conn = sqlite3.connect(db_path)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(episode)")}
    conn.close()
    return cols


async def test_init_db_advances_user_version_to_latest(monkeypatch, tmp_path):
    """fresh 库 init_db 后 user_version == MIGRATIONS 末条，且演进列就位。"""
    db_path = tmp_path / "fresh.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))

    await database.init_db()

    expected = MIGRATIONS[-1][0]
    assert _user_version(str(db_path)) == expected
    cols = _episode_cols(str(db_path))
    assert {"title_zh", "transcript"} <= cols


async def test_runner_is_idempotent_on_rerun(monkeypatch, tmp_path):
    """已应用到的库再跑 run_migrations → 不重跑、user_version 不变。"""
    db_path = tmp_path / "fresh.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    await database.init_db()
    before = _user_version(str(db_path))

    # 在已是最新版本的库上再跑一次 runner（模拟重启后再 init_db）
    import aiosqlite
    async with aiosqlite.connect(str(db_path)) as db:
        returned = await run_migrations(db)

    assert returned == before
    assert _user_version(str(db_path)) == before


async def test_m001_backfills_missing_columns(monkeypatch, tmp_path):
    """早期缺列库（手动建无 title_zh/transcript 的 episode）→ 迁移 001 幂等补齐。"""
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db_path))
    # 模拟「老 schema」：episode 表没有 title_zh / transcript 列
    conn.execute(
        "CREATE TABLE episode (id TEXT PRIMARY KEY, title TEXT, status TEXT, "
        "created_at TEXT, updated_at TEXT)"
    )
    conn.execute("PRAGMA user_version = 0")
    conn.commit()
    conn.close()

    import aiosqlite
    async with aiosqlite.connect(str(db_path)) as db:
        await run_migrations(db)

    cols = _episode_cols(str(db_path))
    assert {"title_zh", "transcript"} <= cols, f"迁移未补齐列，实际 {cols}"
    assert _user_version(str(db_path)) == 1
