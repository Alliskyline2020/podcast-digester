"""fresh 安装 init_db 是否创建派生数据表的回归测试。

背景：outline/summaries/highlight/product_insights 四张派生表早期只存在于
migrations/add_derived_data_tables.py，而该迁移从未接到任何启动路径；init_db()
的建表脚本原本也不含这四张表。结果 fresh 克隆 → 启动 → 跑任意任务，一到
DerivedDataRepository.set（持久化洞察/大纲/摘要/亮点）即
'no such table: outline'，整集 failed。

本测试用全新空库跑 init_db，断言四张派生表 + 索引被建出，保证新用户开箱即用
（这正是排查「全新用户是否同样中招」的回归闸门）。
"""
import sqlite3

from app import database


DERIVED_TABLES = ("outline", "summaries", "highlight", "product_insights")
DERIVED_INDEXES = (
    "idx_outline_updated",
    "idx_summaries_updated",
    "idx_highlight_updated",
    "idx_product_insights_updated",
)


def _objects(db_path: str) -> tuple[set, set]:
    conn = sqlite3.connect(db_path)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    indexes = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'")}
    conn.close()
    return tables, indexes


async def test_init_db_creates_derived_data_tables(monkeypatch, tmp_path):
    """fresh 空 DB 跑 init_db → 四张派生表 + 四个索引必须存在。"""
    db_path = tmp_path / "fresh.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))

    await database.init_db()

    tables, indexes = _objects(str(db_path))
    for t in DERIVED_TABLES:
        assert t in tables, f"派生表 {t} 未被 init_db 创建（新用户会撞 'no such table: {t}'）"
    for idx in DERIVED_INDEXES:
        assert idx in indexes, f"派生索引 {idx} 未被创建"


async def test_init_db_creates_glossary_table(monkeypatch, tmp_path):
    """fresh 空 DB 跑 init_db → glossary 词库表必须存在（前端词库功能 + apply-glossary 依赖它）。

    迁移 migrate_glossary_to_db.py 建表但从未接启动路径；新用户一点「词库」或
    apply-glossary 即 'no such table: glossary'。列须含 correct/wrong_list/
    created_at/updated_at（对齐 GlossaryRepository 的 SELECT/INSERT）。
    """
    db_path = tmp_path / "fresh.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    await database.init_db()

    tables, indexes = _objects(str(db_path))
    assert "glossary" in tables, "词库表 glossary 未被 init_db 创建（新用户用词库功能会撞 'no such table: glossary'）"
    assert "idx_glossary_updated" in indexes

    conn = sqlite3.connect(str(db_path))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(glossary)")}
    conn.close()
    assert {"correct", "wrong_list", "created_at", "updated_at"} <= cols, (
        f"glossary 缺列，实际 {cols}"
    )


async def test_init_db_derived_tables_match_repository_columns(monkeypatch, tmp_path):
    """派生表 schema 必须与 DerivedDataRepository.set 写入的列对齐（episode_id / *_json / updated_at）。"""
    db_path = tmp_path / "fresh.db"
    monkeypatch.setattr(database, "DB_PATH", str(db_path))
    await database.init_db()

    conn = sqlite3.connect(str(db_path))
    for table, json_col in (
        ("outline", "entries_json"),
        ("summaries", "summaries_json"),
        ("highlight", "highlights_json"),
        ("product_insights", "insights_json"),
    ):
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        assert {"episode_id", json_col, "updated_at"} <= cols, (
            f"{table} 缺列：期望含 episode_id/{json_col}/updated_at，实际 {cols}"
        )
    conn.close()
