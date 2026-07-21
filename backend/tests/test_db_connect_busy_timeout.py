"""async 数据库连接 busy_timeout 回归测试。

背景：async 仓储方法原本都走 `aiosqlite.connect(DB_PATH)`，底层 sqlite3
默认 `timeout=5.0` 即 busy_timeout 仅 5s。pipeline 的 fire-and-forget 进度回调
`asyncio.create_task(IngestJobRepository.update_stages(...))` 会在收尾阶段并发
写库，多个写者争抢 WAL 的单写锁，5s 内拿不到即抛
`OperationalError('database is locked')`（进度条更新偶发失败，不影响最终数据）。

同步路径（`_sync_db`）早已用 `timeout=30.0` 修过同一根因。本测试保证 async
路径经统一的 `_connect()` 开 30s busy_timeout，让并发写排队串行化而非立即失败。
"""
import aiosqlite

from app import database


async def test_connect_sets_busy_timeout(monkeypatch, tmp_path):
    """`_connect()` 返回的连接 busy_timeout 必须为 30000ms。"""
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "probe.db"))

    async with database._connect() as db:
        cur = await db.execute("PRAGMA busy_timeout")
        (val,) = await cur.fetchone()
        assert isinstance(db, aiosqlite.Connection)

    assert val == 30000


async def test_get_db_inherits_busy_timeout(monkeypatch, tmp_path):
    """依赖注入用的 `get_db()` 同样走统一连接工厂（不能绕开 busy_timeout）。"""
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "probe.db"))

    # get_db 是 async def（供 DI），await 拿到带 30s busy_timeout 的连接
    async with (await database.get_db()) as db:
        cur = await db.execute("PRAGMA busy_timeout")
        (val,) = await cur.fetchone()

    assert val == 30000
