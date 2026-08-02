"""有序、幂等的数据库迁移 runner（基于 ``PRAGMA user_version``）。

设计
----
- **baseline schema**（所有 ``CREATE TABLE IF NOT EXISTS``）放在
  :func:`app.database.init_db` 里，保证 fresh 库开箱即用、零迁移即可运行。
- 之后的 **schema 演进** 走本 runner：每条迁移是一个
  ``(version, name, fn)``，runner 按 version 升序、仅跑 ``version > 当前 user_version``
  的，跑完 ``PRAGMA user_version = N``。
- 每条迁移必须 **幂等**（重复跑不报错、不改坏数据）：baseline 的
  ``CREATE TABLE IF NOT EXISTS`` 可能已把列建好，迁移要能 no-op。

为什么用 runner（而非旧的 ``migrations/*.py``）
----------------------------------------------
旧目录下的脚本是旧项目「文件系统 → DB」的一次性 **数据搬运** 工具，其 schema 部分
已被 ``init_db`` 的 ``CREATE TABLE IF NOT EXISTS`` 逐字覆盖；数据搬运对 fresh 安装无
意义。本 runner 只管 schema 演进；一次性数据修复工具（如
``migrate_language_fields.py``）作为独立 CLI 保留在包内，按需手动 ``python -m`` 运行。

新增迁移
--------
1. 写一个 ``async def _mNNN_xxx(db) -> None``（**幂等**：先查 ``PRAGMA table_info``
   再 ``ALTER TABLE ADD COLUMN``，或用 ``IF NOT EXISTS``）。
2. 追加到 ``MIGRATIONS``，version 单调递增。
"""
from __future__ import annotations

import logging
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

# (版本号, 名称, 迁移函数)。版本号必须单调递增、不重用、不跳过已发布版本。
Migration = tuple[int, str, Callable[["object"], Awaitable[None]]]


async def _m001_episode_columns(db) -> None:
    """补齐 episode 表历史缺失列（``title_zh`` / ``transcript``）。

    这两列被 pipeline 的 ``EpisodeRepository.update``（title_zh）与
    ``update_transcript``（transcript）写入。baseline 的 ``CREATE TABLE`` 已含；
    本迁移兜底早期（缺列）库，幂等：列已存在则跳过。
    """
    cur = await db.execute("PRAGMA table_info(episode)")
    existing = {row[1] for row in await cur.fetchall()}
    for col, decl in (("title_zh", "TEXT"), ("transcript", "TEXT")):
        if col not in existing:
            await db.execute(f"ALTER TABLE episode ADD COLUMN {col} {decl}")
            logger.info("[migrate] 001 episode: ADD COLUMN %s %s", col, decl)


async def _m002_episode_description_retry(db) -> None:
    """补齐 episode.description（术语表/元数据）与 retry_count（下载重试计数）。

    - description：episode 的视频描述。pipeline 用 title + description 当 LLM
      字幕纠错的术语表上下文（纠正 ASR 同音字 / 专有名词，如「预知面→月之暗面」），
      并兼作元数据。
    - retry_count：worker 跨轮次下载重试计数（节点死锁 / 代理抽风 / 限流的指数
      退避重试），与 run_ytdlp 内层的 client 回退（秒级）互补。

    baseline CREATE TABLE 未含；本迁移幂等兜底，列已存在则跳过。
    """
    cur = await db.execute("PRAGMA table_info(episode)")
    existing = {row[1] for row in await cur.fetchall()}
    for col, decl in (
        ("description", "TEXT"),
        ("retry_count", "INTEGER DEFAULT 0"),
    ):
        if col not in existing:
            await db.execute(f"ALTER TABLE episode ADD COLUMN {col} {decl}")
            logger.info("[migrate] 002 episode: ADD COLUMN %s %s", col, decl)


MIGRATIONS: list[Migration] = [
    (1, "episode_columns_title_zh_transcript", _m001_episode_columns),
    (2, "episode_description_retry_count", _m002_episode_description_retry),
]


async def run_migrations(db) -> int:
    """按 ``user_version`` 升序跑未应用的迁移，幂等。

    返回应用后的 ``user_version``。在 ``init_db`` 的同一连接上调用，复用其事务边界。
    """
    cur = await db.execute("PRAGMA user_version")
    applied = (await cur.fetchone())[0]
    pending = [m for m in MIGRATIONS if m[0] > applied]
    if not pending:
        return applied

    for version, name, fn in pending:
        logger.info("[migrate] applying %03d %s", version, name)
        await fn(db)
        await db.execute(f"PRAGMA user_version = {version}")
        await db.commit()

    logger.info("[migrate] done: user_version=%d (applied %d migration(s))", version, len(pending))
    return version
