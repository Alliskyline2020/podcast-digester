"""运行时 LLM 配置覆写：读写 app_setting.llm_config。

get_config() 每次同步读这里的 read_runtime_override()，使前端设置页
保存后对 API 与 Worker 两进程都即时生效（SQLite WAL 下跨进程读后写安全）。
"""
import json
import sqlite3
from datetime import datetime, timezone

OVERRIDE_KEY = "llm_config"


def _db_path():
    """取「当前生效」的 DB 路径。

    故意每次进函数读 app.database.DB_PATH 属性（而非 import 时拷贝），
    这样 conftest 的 temp_db fixture 替换该属性时能被正确感知。
    """
    from app import database  # 局部 import，避免与 config 的加载顺序耦合
    return database.DB_PATH


def read_runtime_override() -> dict:
    """同步读取运行时覆写。DB/表/记录缺失或任何异常都返回 {}，绝不抛错。"""
    try:
        path = _db_path()
        if not path.exists():
            return {}
        with sqlite3.connect(str(path)) as conn:
            row = conn.execute(
                "SELECT value FROM app_setting WHERE key=?", (OVERRIDE_KEY,)
            ).fetchone()
        return json.loads(row[0]) if row else {}
    except sqlite3.OperationalError:
        # 表尚未建（init_db 未跑过）
        return {}
    except Exception:
        # 任何意外都回退到「无覆写」，绝不阻塞 get_config()
        return {}


async def write_runtime_override(override: dict) -> None:
    """异步写入覆写（upsert）。供 PUT /api/admin/llm-config 使用。"""
    import aiosqlite

    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(str(_db_path())) as db:
        await db.execute(
            "INSERT INTO app_setting(key, value, updated_at) VALUES(?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (OVERRIDE_KEY, json.dumps(override, ensure_ascii=False), now),
        )
        await db.commit()
