"""
数据库测试fixtures

提供数据库相关的测试工具
"""
import pytest
import asyncio
from typing import AsyncGenerator
from pathlib import Path
import aiosqlite


@pytest.fixture
async def db_connection(temp_dir: Path) -> AsyncGenerator[aiosqlite.Connection, None]:
    """
    创建数据库连接fixture

    Args:
        temp_dir: 临时目录

    Yields:
        数据库连接
    """
    from app.config import DB_PATH
    import app.config

    # 保存原始DB_PATH
    original_db_path = DB_PATH

    # 创建临时数据库
    test_db_path = temp_dir / "test.db"

    # 修改DB_PATH为测试路径
    app.config.DB_PATH = str(test_db_path)

    # 创建连接
    async with aiosqlite.connect(test_db_path) as db:
        # 启用外键约束
        await db.execute("PRAGMA foreign_keys = ON")
        # 创建表结构
        await db.executescript(_get_schema_sql())
        await db.commit()

        yield db

    # 恢复原始DB_PATH
    app.config.DB_PATH = original_db_path


def _get_schema_sql() -> str:
    """
    获取数据库表结构的SQL

    Returns:
        创建表的SQL语句
    """
    return """
    CREATE TABLE IF NOT EXISTS episode (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        language TEXT,
        url TEXT,
        is_fixture INTEGER DEFAULT 0,
        created_at TEXT NOT NULL,
        last_activity_ts TEXT,
        current_stage TEXT,
        stages TEXT,
        overall_progress REAL DEFAULT 0.0,
        tldr_zh TEXT,
        worth_listening_verdict TEXT,
        verdict_confidence TEXT,
        target_audience_zh TEXT,
        highlights_count INTEGER DEFAULT 0,
        duration_min INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS transcript (
        episode_id TEXT PRIMARY KEY,
        segments_json TEXT NOT NULL,
        paragraph_mappings_json TEXT,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (episode_id) REFERENCES episode(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS outline (
        episode_id TEXT PRIMARY KEY,
        entries_json TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (episode_id) REFERENCES episode(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS summaries (
        episode_id TEXT PRIMARY KEY,
        summaries_json TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (episode_id) REFERENCES episode(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS highlight (
        episode_id TEXT PRIMARY KEY,
        highlights_json TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (episode_id) REFERENCES episode(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS product_insights (
        episode_id TEXT PRIMARY KEY,
        insights_json TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (episode_id) REFERENCES episode(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS glossary (
        correct TEXT PRIMARY KEY,
        wrong_list TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS usage_log (
        id TEXT PRIMARY KEY,
        timestamp TEXT NOT NULL,
        endpoint TEXT NOT NULL,
        status_code INTEGER NOT NULL,
        duration_ms REAL NOT NULL
    );

    CREATE INDEX IF NOT EXISTS idx_episode_status ON episode(status);
    CREATE INDEX IF NOT EXISTS idx_episode_created_at ON episode(created_at);
    CREATE INDEX IF NOT EXISTS idx_transcript_updated_at ON transcript(updated_at);
    CREATE INDEX IF NOT EXISTS idx_usage_log_timestamp ON usage_log(timestamp);
    """
