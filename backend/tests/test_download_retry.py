"""下载错误分类 + retry_count 持久化 + worker 跨轮次重试。

回归背景：远程已用 comma-join player_client（`["android_vr","android","ios"]`）
+ `--fragment-retries 10` + `--socket-timeout 30` 治好了「单 client 锁死坏节点 →
下载无限挂起」的根因。本层补的是收尾两件事：

1. 错误分类（L1）：run_ytdlp 此前对任何失败都抛裸 RuntimeError，worker 无法区分
   「换 client/等一会能好」的临时错（节点不可达 / 限流）与「永远好不了」的永久错
   （URL 无效 / 视频删除）。现在映射到 DownloadTemporaryError(retryable=True) /
   DownloadError(retryable=False)。

2. worker 跨轮次重试（L4）：retryable 异常 + retry_count < max → 指数退避后回
   pending，下轮 poll 重拾；retry_count 列由 migration 002 提供。永久错直接 failed。
"""
import pytest

from app.database import EpisodeRepository
from app.errors import DownloadTemporaryError, DownloadError
from app.models import EpisodeStatus
from app.sources.ytdlp_runner import _classify_download_error


# ============================================================================
# L1: 错误分类（纯函数）
# ============================================================================

@pytest.mark.unit
@pytest.mark.parametrize("error_msg", [
    "HTTP Error 429 Too Many Requests",
    "rate limit exceeded",
    "Sign in to confirm you're not a bot",
    "LOGIN_REQUIRED",
])
def test_classify_rate_limit(error_msg):
    assert _classify_download_error(error_msg) == "rate_limit"


@pytest.mark.unit
@pytest.mark.parametrize("error_msg", [
    "Connection timed out",
    "connection refused",
    "read timed out",
    "[download] unexpected EOF",
    "network is unreachable",
    "No route to host",
])
def test_classify_node_unreachable(error_msg):
    assert _classify_download_error(error_msg) == "node_unreachable"


@pytest.mark.unit
@pytest.mark.parametrize("error_msg", [
    "Video unavailable",
    "Private video",
    "Unsupported URL",
    "This video has been removed",
])
def test_classify_permanent(error_msg):
    assert _classify_download_error(error_msg) == "permanent"


@pytest.mark.unit
def test_classify_empty_or_unknown_is_permanent():
    """空串 / 未知错误兜底为 permanent（保守：宁可不重试，不浪费 LLM 配额）。"""
    assert _classify_download_error("") == "permanent"
    assert _classify_download_error("some novel yt-dlp error text") == "permanent"


# ============================================================================
# retryable 属性（worker 据此分支）
# ============================================================================

@pytest.mark.unit
def test_download_temporary_error_is_retryable():
    """DownloadTemporaryError 必须 retryable=True，否则 worker 不会重试。"""
    assert DownloadTemporaryError("node down").retryable is True


@pytest.mark.unit
def test_download_error_is_not_retryable():
    """DownloadError（永久）必须 retryable=False。"""
    assert DownloadError("video deleted").retryable is False


# ============================================================================
# L4: retry_count 持久化（DB）
# ============================================================================

@pytest.mark.unit
@pytest.mark.database
async def test_get_retry_count_defaults_to_zero(temp_db):
    """新 episode 无 retry_count 列写入时，读取应兜底为 0（非 NULL 异常）。"""
    await EpisodeRepository.create({
        "id": "ep_retry_001",
        "title": "Retry Test",
        "status": EpisodeStatus.PENDING.value,
        "language": "en",
        "media_path": None,
        "is_fixture": False,
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-01T00:00:00",
    })
    assert await EpisodeRepository.get_retry_count("ep_retry_001") == 0


@pytest.mark.unit
@pytest.mark.database
async def test_update_status_persists_retry_count(temp_db):
    """update_status(retry_count=N) 应写库并能读回。"""
    await EpisodeRepository.create({
        "id": "ep_retry_002",
        "title": "Retry Persist",
        "status": EpisodeStatus.PENDING.value,
        "language": "en",
        "media_path": None,
        "is_fixture": False,
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-01T00:00:00",
    })

    await EpisodeRepository.update_status("ep_retry_002", "pending", retry_count=1)
    assert await EpisodeRepository.get_retry_count("ep_retry_002") == 1

    # 同时清空 error_msg 语义不受影响（带 retry_count 的中性状态）
    row = await EpisodeRepository.get_by_id("ep_retry_002")
    assert row["status"] == "pending"
    assert row["error_msg"] is None


@pytest.mark.unit
@pytest.mark.database
async def test_retry_count_increments_across_rounds(temp_db):
    """模拟 worker 跨轮次重试：每轮 retry_count + 1，直到 max 后 failed。"""
    await EpisodeRepository.create({
        "id": "ep_retry_003",
        "title": "Increment",
        "status": EpisodeStatus.PENDING.value,
        "language": "en",
        "media_path": None,
        "is_fixture": False,
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-01T00:00:00",
    })

    # 三轮重试：0→1→2→3
    for expected in (1, 2, 3):
        current = await EpisodeRepository.get_retry_count("ep_retry_003")
        await EpisodeRepository.update_status(
            "ep_retry_003", "pending", retry_count=current + 1
        )
        assert await EpisodeRepository.get_retry_count("ep_retry_003") == expected

    # 配额耗尽 → 标 failed（retry_count 停在 3）
    await EpisodeRepository.update_status(
        "ep_retry_003", "failed", error_msg="exhausted"
    )
    assert (await EpisodeRepository.get_by_id("ep_retry_003"))["status"] == "failed"


# ============================================================================
# Worker._handle_episode_failure（重试决策，从 run() 抽出便于单测）
# ============================================================================

def _async_returning(value):
    """造一个返回固定值的 async 函数（mock get_retry_count 用）。"""
    async def _f(*args, **kwargs):
        return value
    return _f


@pytest.mark.unit
async def test_worker_retries_transient_error(monkeypatch):
    """retryable 异常 + 配额未耗尽 → 回 pending + retry_count+1，返回 True。"""
    from worker import Worker

    worker = Worker()
    monkeypatch.setattr("worker.WORKER_RETRY_BACKOFF", 0.0)  # 跳过退避等待
    monkeypatch.setattr(EpisodeRepository, "get_retry_count", _async_returning(1))

    updates = []

    async def record_update(episode_id, status, error_msg=None, retry_count=None):
        updates.append({"status": status, "error_msg": error_msg, "retry_count": retry_count})

    monkeypatch.setattr(EpisodeRepository, "update_status", record_update)

    result = await worker._handle_episode_failure(
        "ep_x", DownloadTemporaryError("connection timed out")
    )

    assert result is True
    assert len(updates) == 1
    assert updates[0]["status"] == "pending"
    assert updates[0]["retry_count"] == 2  # 原 1 + 1
    assert updates[0]["error_msg"] is None  # 中性 pending，清空 error_msg


@pytest.mark.unit
async def test_worker_marks_permanent_error_failed(monkeypatch):
    """DownloadError（永久）→ 直接 failed，且不查 retry_count。"""
    from worker import Worker

    worker = Worker()
    get_calls = []

    async def record_get(episode_id):
        get_calls.append(episode_id)
        return 0

    monkeypatch.setattr(EpisodeRepository, "get_retry_count", record_get)
    updates = []

    async def record_update(episode_id, status, error_msg=None, retry_count=None):
        updates.append({"status": status, "error_msg": error_msg, "retry_count": retry_count})

    monkeypatch.setattr(EpisodeRepository, "update_status", record_update)

    result = await worker._handle_episode_failure(
        "ep_y", DownloadError("video unavailable")
    )

    assert result is False
    assert get_calls == []  # 永久错不查 retry_count
    assert len(updates) == 1
    assert updates[0]["status"] == "failed"
    assert updates[0]["retry_count"] is None
    assert "video unavailable" in updates[0]["error_msg"]


@pytest.mark.unit
async def test_worker_exhausted_retries_marks_failed(monkeypatch):
    """retryable 但 retry_count 已达上限 → 标 failed，不再退避重排。"""
    from worker import Worker
    from app.config import WORKER_MAX_DOWNLOAD_RETRIES

    worker = Worker()
    # retry_count == max，不再 < max，走 failed 分支
    monkeypatch.setattr(
        EpisodeRepository, "get_retry_count", _async_returning(WORKER_MAX_DOWNLOAD_RETRIES)
    )
    updates = []

    async def record_update(episode_id, status, error_msg=None, retry_count=None):
        updates.append({"status": status, "error_msg": error_msg, "retry_count": retry_count})

    monkeypatch.setattr(EpisodeRepository, "update_status", record_update)

    result = await worker._handle_episode_failure(
        "ep_z", DownloadTemporaryError("still down")
    )

    assert result is False
    assert updates[0]["status"] == "failed"
    assert "still down" in updates[0]["error_msg"]
