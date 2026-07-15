"""runtime_config: 运行时 LLM 配置覆写的读写。"""
import json

import pytest

from app.llm.runtime_config import (
    OVERRIDE_KEY,
    read_runtime_override,
    write_runtime_override,
)


@pytest.mark.database
async def test_write_then_read_roundtrip(temp_db):
    await write_runtime_override({"provider": "glm", "api_key": "sk-x", "model": "glm-4-flash"})
    got = read_runtime_override()
    assert got["provider"] == "glm"
    assert got["api_key"] == "sk-x"
    assert got["model"] == "glm-4-flash"


@pytest.mark.database
async def test_write_upserts_existing_row(temp_db):
    await write_runtime_override({"provider": "deepseek"})
    await write_runtime_override({"provider": "openai", "model": "gpt-4o-mini"})
    got = read_runtime_override()
    assert got == {"provider": "openai", "model": "gpt-4o-mini"}


@pytest.mark.unit
def test_read_returns_empty_when_db_missing(monkeypatch):
    # 指向一个不存在的路径：不得建文件、不得抛错
    from app import database as _db
    monkeypatch.setattr(_db, "DB_PATH", __import__("pathlib").Path("/tmp/pd-nonexistent-rt.db"))
    assert read_runtime_override() == {}


@pytest.mark.unit
def test_read_returns_empty_when_no_row(temp_db):
    # 表已建但无记录
    assert read_runtime_override() == {}
