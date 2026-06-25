"""
数据库初始化和管理
SQLite 单文件数据库

连接管理策略：
- 使用 aiosqlite 进行异步数据库操作
- 每个操作使用独立的 context manager（async with）
- SQLite 内置连接池，自动管理文件锁
- 不需要额外的连接池实现
"""
import aiosqlite
import sqlite3
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable
from datetime import datetime
import json
import logging
from functools import wraps

from .config import DB_PATH

logger = logging.getLogger(__name__)


# ==================== 事务管理 ====================

def transactional(func: Callable) -> Callable:
    """
    事务装饰器：确保数据库操作的原子性

    用法：
        @transactional
        async def my_operation(episode_id: str):
            # 多个数据库操作
            await EpisodeRepository.update(...)
            await IngestJobRepository.update(...)
            # 如果任何一个失败，所有更改都会回滚
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        async with aiosqlite.connect(DB_PATH) as db:
            try:
                # 开始事务
                await db.execute("BEGIN")

                # 将数据库连接传递给被装饰的函数
                result = await func(*args, **kwargs, _db=db)

                # 提交事务
                await db.commit()
                return result
            except Exception as e:
                # 回滚事务
                await db.rollback()
                logger.error(f"Transaction failed, rolled back: {e}")
                raise
    return wrapper


async def init_db():
    """初始化数据库表"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        -- 节目表
        CREATE TABLE IF NOT EXISTS episode (
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
        );

        -- 来源表
        CREATE TABLE IF NOT EXISTS source (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            episode_id TEXT NOT NULL,
            source_type TEXT NOT NULL,
            raw_input TEXT NOT NULL,
            resolved_url TEXT,
            requires_auth INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (episode_id) REFERENCES episode(id) ON DELETE CASCADE
        );

        -- 处理任务表
        CREATE TABLE IF NOT EXISTS ingest_job (
            episode_id TEXT PRIMARY KEY,
            current_stage TEXT NOT NULL DEFAULT 'pending',
            stages_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (episode_id) REFERENCES episode(id) ON DELETE CASCADE
        );

        -- 用户行为埋点
        CREATE TABLE IF NOT EXISTS usage_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            event_type TEXT NOT NULL,
            episode_id TEXT NOT NULL,
            payload_json TEXT,
            FOREIGN KEY (episode_id) REFERENCES episode(id) ON DELETE CASCADE
        );

        -- LLM 成本记录
        CREATE TABLE IF NOT EXISTS cost_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            task TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            cost_usd REAL DEFAULT 0.0,
            latency_ms INTEGER DEFAULT 0,
            prompt_version INTEGER DEFAULT 2,
            episode_id TEXT,
            success INTEGER DEFAULT 1,
            error TEXT
        );

        -- 前端 UI 状态
        CREATE TABLE IF NOT EXISTS episode_view_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            episode_id TEXT NOT NULL UNIQUE,
            highlight_collapsed INTEGER DEFAULT 1,
            last_played_position_ms INTEGER DEFAULT 0,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (episode_id) REFERENCES episode(id) ON DELETE CASCADE
        );

        -- 索引
        CREATE INDEX IF NOT EXISTS idx_episode_status ON episode(status);
        CREATE INDEX IF NOT EXISTS idx_episode_last_activity ON episode(last_activity_ts DESC);
        CREATE INDEX IF NOT EXISTS idx_usage_log_episode ON usage_log(episode_id);
        CREATE INDEX IF NOT EXISTS idx_cost_log_episode ON cost_log(episode_id);
        CREATE INDEX IF NOT EXISTS idx_cost_log_ts ON cost_log(ts DESC);
        """)

        await db.commit()


async def get_db() -> aiosqlite.Connection:
    """获取数据库连接（依赖注入用）

    注意：返回的连接需要由调用者管理生命周期。
    推荐使用 async with 语句确保连接正确关闭。

    示例：
        async with get_db() as db:
            await db.execute(...)
    """
    return aiosqlite.connect(DB_PATH)


# ==================== 数据访问层 ====================

class EpisodeRepository:
    """节目数据访问"""

    # 允许更新的字段白名单（防止SQL注入）
    _ALLOWED_UPDATE_FIELDS = {
        "title", "title_zh", "status", "language", "media_path", "is_fixture",
        "error_msg", "source_type", "last_activity_ts", "paragraph_mappings"
    }

    @staticmethod
    async def create(episode: dict) -> None:
        """创建节目记录（带错误处理）"""
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("""
                    INSERT INTO episode (
                        id, title, status, language, media_path, is_fixture, error_msg,
                        source_type, created_at, updated_at, paragraph_mappings
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    episode["id"], episode["title"], episode["status"],
                    episode.get("language"), episode.get("media_path"),
                    int(episode.get("is_fixture", False)), episode.get("error_msg"),
                    episode.get("source_type"),
                    episode["created_at"].isoformat() if isinstance(episode["created_at"], datetime) else episode["created_at"],
                    episode["updated_at"].isoformat() if isinstance(episode["updated_at"], datetime) else episode["updated_at"],
                    json.dumps(episode.get("paragraph_mappings")) if episode.get("paragraph_mappings") else None,
                ))
                await db.commit()
        except aiosqlite.IntegrityError as e:
            logger.error(f"Integrity error creating episode {episode.get('id')}: {e}")
            raise ValueError(f"节目ID {episode.get('id')} 已存在")
        except aiosqlite.DatabaseError as e:
            logger.error(f"Database error creating episode {episode.get('id')}: {e}")
            raise

    @staticmethod
    async def get_by_id(episode_id: str) -> Optional[dict]:
        """获取节目记录（带错误处理）"""
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT * FROM episode WHERE id = ?", (episode_id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        data = dict(row)
                        # Deserialize paragraph_mappings JSON if present
                        if data.get("paragraph_mappings"):
                            try:
                                data["paragraph_mappings"] = json.loads(data["paragraph_mappings"])
                            except json.JSONDecodeError as e:
                                logger.error(f"Failed to parse paragraph_mappings for {episode_id}: {e}")
                                data["paragraph_mappings"] = None
                        return data
                    return None
        except aiosqlite.DatabaseError as e:
            logger.error(f"Database error getting episode {episode_id}: {e}")
            raise

    @staticmethod
    async def list_all() -> List[dict]:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM episode
                ORDER BY COALESCE(last_activity_ts, updated_at) DESC
            """) as cursor:
                rows = await cursor.fetchall()
                episodes = []
                for row in rows:
                    data = dict(row)
                    # Deserialize paragraph_mappings JSON if present
                    if data.get("paragraph_mappings"):
                        data["paragraph_mappings"] = json.loads(data["paragraph_mappings"])
                    episodes.append(data)
                return episodes

    @staticmethod
    async def get_by_statuses(statuses: List[str]) -> List[dict]:
        """
        根据状态列表查询节目

        Args:
            statuses: 状态列表（如 ['pending', 'downloading']）

        Returns:
            符合状态的节目列表
        """
        if not statuses:
            return []

        # 验证状态值（防止注入无效值）
        valid_statuses = {"pending", "downloading", "asr_running",
                         "llm_running", "ready", "failed"}
        validated = [s for s in statuses if s in valid_statuses]

        if not validated:
            return []

        placeholders = ",".join("?" * len(validated))
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(f"""
                SELECT * FROM episode
                WHERE status IN ({placeholders})
                ORDER BY created_at ASC
            """, tuple(validated)) as cursor:
                rows = await cursor.fetchall()
                episodes = []
                for row in rows:
                    data = dict(row)
                    # Deserialize paragraph_mappings JSON if present
                    if data.get("paragraph_mappings"):
                        data["paragraph_mappings"] = json.loads(data["paragraph_mappings"])
                    episodes.append(data)
                return episodes

    @staticmethod
    async def update_status(episode_id: str, status: str, error_msg: Optional[str] = None) -> None:
        async with aiosqlite.connect(DB_PATH) as db:
            now = datetime.now().isoformat()
            if error_msg:
                await db.execute("""
                    UPDATE episode SET status = ?, error_msg = ?, updated_at = ?
                    WHERE id = ?
                """, (status, error_msg, now, episode_id))
            else:
                await db.execute("""
                    UPDATE episode SET status = ?, updated_at = ?
                    WHERE id = ?
                """, (status, now, episode_id))
            await db.commit()

    @staticmethod
    async def update(episode_id: str, **fields) -> bool:
        """
        更新指定字段（仅允许白名单内的字段）

        Args:
            episode_id: 节目ID
            **fields: 要更新的字段键值对

        Returns:
            bool: 是否更新成功

        Raises:
            ValueError: 如果包含不允许的字段
        """
        if not fields:
            return False

        # 验证字段名在白名单中
        invalid_fields = set(fields.keys()) - EpisodeRepository._ALLOWED_UPDATE_FIELDS
        if invalid_fields:
            raise ValueError(f"不允许更新的字段: {invalid_fields}")

        fields["updated_at"] = datetime.now().isoformat()

        # Serialize paragraph_mappings if present
        values = []
        for key, value in fields.items():
            if key == "paragraph_mappings" and value is not None:
                try:
                    values.append(json.dumps(value))
                except (TypeError, ValueError) as e:
                    logger.error(f"Failed to serialize paragraph_mappings: {e}")
                    raise ValueError("paragraph_mappings 格式错误")
            else:
                values.append(value)

        set_clause = ", ".join(f"{k} = ?" for k in fields.keys())
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute(
                    f"UPDATE episode SET {set_clause} WHERE id = ?",
                    values + [episode_id]
                )
                await db.commit()
                return cursor.rowcount > 0
        except aiosqlite.DatabaseError as e:
            logger.error(f"Database error updating episode {episode_id}: {e}")
            raise

    @staticmethod
    async def update_transcript(episode_id: str, transcript_data: dict) -> bool:
        """
        更新字幕数据

        Args:
            episode_id: 节目ID
            transcript_data: 字幕数据 {"segments": [...], "language": "zh"}

        Returns:
            bool: 是否更新成功
        """
        from .models import Transcript

        # 验证transcript数据
        if not transcript_data or "segments" not in transcript_data:
            return False

        # 转换为Transcript模型
        try:
            transcript = Transcript(
                episode_id=episode_id,
                language=transcript_data.get("language", "unknown"),
                segments=transcript_data.get("segments", [])
            )
        except Exception as e:
            logger.error(f"Failed to validate transcript data: {e}")
            return False

        # 序列化为JSON
        transcript_json = json.dumps(transcript.model_dump(), ensure_ascii=False)

        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "UPDATE episode SET transcript = ?, updated_at = ? WHERE id = ?",
                (transcript_json, datetime.now().isoformat(), episode_id)
            )
            await db.commit()
            success = cursor.rowcount > 0

        # 同步写文件 transcript.json(与 DB 保持一致)。
        # 前端列表 API 的 load_highlight_fast 已改成 DB 优先,但 transcript.json
        # 仍被 get_duration_fast / worker 重算 / pipeline fallback 等多处读取,
        # 只改 DB 不改文件会导致数据源不一致。在数据访问层统一处理,所有调用方
        # (apply_glossary / update_transcript_segment / 未来其他入口)自动同步。
        if success:
            try:
                import asyncio
                from pathlib import Path
                transcript_file = Path(DB_PATH).parent / "media" / episode_id / "transcript.json"
                transcript_file.parent.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(
                    lambda: transcript_file.write_text(
                        json.dumps(transcript.model_dump(), ensure_ascii=False, indent=2),
                        encoding="utf-8"
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to sync transcript.json for {episode_id}: {e}")

        return success

    @staticmethod
    async def delete(episode_id: str) -> bool:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "DELETE FROM episode WHERE id = ?", (episode_id,)
            )
            await db.commit()
            return cursor.rowcount > 0

    @staticmethod
    async def update_last_activity(episode_id: str) -> None:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE episode SET last_activity_ts = ? WHERE id = ?
            """, (datetime.now().isoformat(), episode_id))
            await db.commit()


class IngestJobRepository:
    """处理任务数据访问"""

    @staticmethod
    async def create(episode_id: str) -> bool:
        """创建处理任务记录。

        Returns:
            True 表示新建成功；False 表示该 episode 已有任务记录（未覆盖既有进度）。
        """
        async with aiosqlite.connect(DB_PATH) as db:
            now = datetime.now().isoformat()
            cursor = await db.execute("""
                INSERT INTO ingest_job (episode_id, current_stage, stages_json, created_at, updated_at)
                VALUES (?, 'pending', '[]', ?, ?)
                ON CONFLICT(episode_id) DO NOTHING
            """, (episode_id, now, now))
            await db.commit()
            return cursor.rowcount > 0

    @staticmethod
    async def get_by_id(episode_id: str) -> Optional[dict]:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM ingest_job WHERE episode_id = ?", (episode_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    data = dict(row)
                    data["stages"] = json.loads(data["stages_json"])
                    return data
                return None

    @staticmethod
    async def update_stages(episode_id: str, stages: list, current_stage: str) -> None:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE ingest_job SET stages_json = ?, current_stage = ?, updated_at = ?
                WHERE episode_id = ?
            """, (json.dumps(stages), current_stage, datetime.now().isoformat(), episode_id))
            await db.commit()


class CostLogRepository:
    """LLM 成本记录"""

    @staticmethod
    async def log(cost_data: dict) -> None:
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO cost_log (
                    ts, task, model, prompt_tokens, completion_tokens, total_tokens,
                    cost_usd, latency_ms, prompt_version, episode_id, success, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                cost_data["ts"].isoformat() if isinstance(cost_data["ts"], datetime) else cost_data["ts"],
                cost_data["task"], cost_data["model"],
                cost_data.get("prompt_tokens", 0),
                cost_data.get("completion_tokens", 0),
                cost_data.get("total_tokens", 0),
                cost_data.get("cost_usd", 0.0),
                cost_data.get("latency_ms", 0),
                cost_data.get("prompt_version", 2),
                cost_data.get("episode_id"),
                int(cost_data.get("success", True)),
                cost_data.get("error")
            ))
            await db.commit()

    @staticmethod
    async def get_total_cost(episode_id: Optional[str] = None) -> float:
        async with aiosqlite.connect(DB_PATH) as db:
            if episode_id:
                async with db.execute(
                    "SELECT SUM(cost_usd) FROM cost_log WHERE episode_id = ?",
                    (episode_id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    return row[0] or 0.0 if row else 0.0
            else:
                async with db.execute("SELECT SUM(cost_usd) FROM cost_log") as cursor:
                    row = await cursor.fetchone()
                    return row[0] or 0.0 if row else 0.0


class UsageLogRepository:
    """用户行为埋点数据访问"""

    @staticmethod
    async def log(log_data: dict) -> None:
        """记录日志"""
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO usage_log (ts, event_type, episode_id, payload_json)
                VALUES (?, ?, ?, ?)
            """, (
                log_data.get("ts", datetime.now().isoformat()),
                log_data["event_type"],
                log_data["episode_id"],
                log_data.get("payload_json"),
            ))
            await db.commit()

    @staticmethod
    async def get_by_episode(episode_id: str, limit: int = 10) -> list[dict]:
        """获取某个 episode 的日志记录"""
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM usage_log
                WHERE episode_id = ?
                ORDER BY ts DESC
                LIMIT ?
            """, (episode_id, limit)) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]


class ViewStateRepository:
    """前端 UI 状态持久化"""

    @staticmethod
    async def get(episode_id: str) -> Optional[dict]:
        """获取 episode 的视图状态"""
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM episode_view_state WHERE episode_id = ?",
                (episode_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    @staticmethod
    async def update(episode_id: str, **fields) -> None:
        """更新视图状态字段"""
        allowed_fields = {"highlight_collapsed", "last_played_position_ms"}
        if not fields:
            return

        # 验证字段名
        invalid_fields = set(fields.keys()) - allowed_fields
        if invalid_fields:
            raise ValueError(f"Invalid fields: {invalid_fields}")

        # 检查记录是否存在
        existing = await ViewStateRepository.get(episode_id)

        if existing:
            # 更新现有记录
            set_clauses = ", ".join(f"{k} = ?" for k in fields.keys())
            values = list(fields.values()) + [datetime.now().isoformat()]
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    f"UPDATE episode_view_state SET {set_clauses}, updated_at = ? WHERE episode_id = ?",
                    (*values, episode_id)
                )
                await db.commit()
        else:
            # 创建新记录
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("""
                    INSERT INTO episode_view_state (episode_id, highlight_collapsed, last_played_position_ms, updated_at)
                    VALUES (?, ?, ?, ?)
                """, (episode_id, fields.get("highlight_collapsed", 1), fields.get("last_played_position_ms", 0), datetime.now().isoformat()))
                await db.commit()


class SourceRepository:
    """原始输入源管理"""

    @staticmethod
    async def create(episode_id: str, source_type: str, raw_input: str, resolved_url: str = None, requires_auth: bool = False) -> None:
        """创建源记录"""
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                INSERT INTO source (episode_id, source_type, raw_input, resolved_url, requires_auth, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (episode_id, source_type, raw_input, resolved_url, 1 if requires_auth else 0, datetime.now().isoformat()))
            await db.commit()

    @staticmethod
    async def get_by_episode(episode_id: str) -> Optional[dict]:
        """获取 episode 的源记录"""
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM source WHERE episode_id = ?",
                (episode_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None


# ==================== 同步方法（用于非异步上下文）====================

def _sync_connect():
    """获取同步数据库连接"""
    import aiosqlite
    return aiosqlite.connect(DB_PATH)


class EpisodeRepositorySync:
    """Episode 同步数据访问（用于需要同步操作的上下文）"""

    @staticmethod
    def get_by_id_sync(episode_id: str) -> Optional[dict]:
        """同步获取节目"""
        import sqlite3
        with sqlite3.connect(DB_PATH) as db:
            db.row_factory = sqlite3.Row
            cursor = db.execute(
                "SELECT * FROM episode WHERE id = ?", (episode_id,)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    @staticmethod
    def update_status_sync(episode_id: str, status: str, error_msg: Optional[str] = None) -> None:
        """同步更新状态"""
        import sqlite3
        with sqlite3.connect(DB_PATH) as db:
            now = datetime.now().isoformat()
            if error_msg:
                db.execute("""
                    UPDATE episode SET status = ?, error_msg = ?, updated_at = ?
                    WHERE id = ?
                """, (status, error_msg, now, episode_id))
            else:
                db.execute("""
                    UPDATE episode SET status = ?, updated_at = ?
                    WHERE id = ?
                """, (status, now, episode_id))
            db.commit()


class IngestJobRepositorySync:
    """IngestJob 同步数据访问"""

    @staticmethod
    def get_by_id_sync(episode_id: str) -> Optional[dict]:
        """同步获取任务"""
        import sqlite3
        with sqlite3.connect(DB_PATH) as db:
            db.row_factory = sqlite3.Row
            cursor = db.execute(
                "SELECT * FROM ingest_job WHERE episode_id = ?", (episode_id,)
            )
            row = cursor.fetchone()
            if row:
                data = dict(row)
                data["stages"] = json.loads(data["stages_json"])
                return data
            return None
