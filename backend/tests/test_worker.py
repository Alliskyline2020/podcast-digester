"""Worker 主循环回归：自愈 + 取源 + resume_episode 续点。

worker 是串行单 owner（fcntl 锁）。每轮：
1. _requeue_orphaned_mid_state：downloading/asr_running/llm_running 的孤儿
   （必然是上次崩溃残留）→ 重置 pending；
2. 串行处理 pending：resume_episode（无 checkpoint→全量；有→跳过已完成阶段）。
取源走 SourceRepository.resolve_raw_input（source.raw_input → usage_log paste 兜底）。
"""
from app import database as app_database
from app import pipeline as app_pipeline
import worker


async def test_worker_resumes_pending_episode_with_resolved_raw_input(monkeypatch):
    """pending episode + 能解析 raw_input → resume_episode 收到正确 URL。"""
    w = worker.Worker()
    seen = {}

    async def fake_get_by_statuses(statuses):
        # mid-state 自愈查询：返回空，聚焦 pending 路径
        if statuses != ["pending"]:
            return []
        return [{"id": "ep_1", "status": "pending"}]

    async def fake_resolve(eid):
        assert eid == "ep_1"
        return "https://example.com/podcast.mp3"

    async def fake_resume(episode_id, raw_input, on_progress=None):
        seen["episode_id"] = episode_id
        seen["raw_input"] = raw_input

    async def fake_sleep(_seconds):
        w.running = False  # 跑完一轮即退出

    monkeypatch.setattr(app_database.EpisodeRepository, "get_by_statuses", staticmethod(fake_get_by_statuses))
    monkeypatch.setattr(app_database.SourceRepository, "resolve_raw_input", staticmethod(fake_resolve))
    monkeypatch.setattr(app_pipeline.pipeline, "resume_episode", fake_resume)
    monkeypatch.setattr(worker.asyncio, "sleep", fake_sleep)

    w.running = True
    await w.run()

    assert seen.get("raw_input") == "https://example.com/podcast.mp3"
    assert seen.get("episode_id") == "ep_1"


async def test_worker_marks_failed_when_raw_input_unresolvable(monkeypatch):
    """pending episode + 解析不到 raw_input → 置 failed（可操作 error_msg），
    不调 resume_episode、不静默挂 pending 永远轮询。"""
    w = worker.Worker()
    statuses = []
    resume_called = []

    async def fake_get_by_statuses(statuses_arg):
        if statuses_arg != ["pending"]:
            return []
        return [{"id": "ep_orphan", "status": "pending"}]

    async def fake_resolve(_eid):
        return None

    async def fake_update_status(eid, status, error_msg=None, retry_count=None):
        statuses.append((eid, status, error_msg))

    async def fake_resume(eid, raw_input, on_progress=None):
        resume_called.append(eid)

    async def fake_sleep(_seconds):
        w.running = False

    monkeypatch.setattr(app_database.EpisodeRepository, "get_by_statuses", staticmethod(fake_get_by_statuses))
    monkeypatch.setattr(app_database.SourceRepository, "resolve_raw_input", staticmethod(fake_resolve))
    monkeypatch.setattr(app_database.EpisodeRepository, "update_status", staticmethod(fake_update_status))
    monkeypatch.setattr(app_pipeline.pipeline, "resume_episode", fake_resume)
    monkeypatch.setattr(worker.asyncio, "sleep", fake_sleep)

    w.running = True
    await w.run()

    assert resume_called == [], "无 raw_input 不应调用 resume_episode"
    failed = [s for eid, s, msg in statuses if s == "failed"]
    assert failed, f"无 raw_input 应置 failed，实际 {statuses}"
    assert any(msg and "原始输入" in msg for _eid, _s, msg in statuses), (
        f"error_msg 应提示原始输入缺失，实际 {statuses}"
    )


async def test_worker_requeues_orphaned_mid_state_to_pending(monkeypatch):
    """mid-state 孤儿（downloading/asr_running/llm_running）→ 重置 pending。
    串行单例保证这些必为崩溃残留，安全重置；retry_count 不动。"""
    w = worker.Worker()

    async def fake_get_by_statuses(statuses):
        if statuses == ["pending"]:
            return []  # 重置后本轮不再处理（resume 路径由后续轮次/真实 pipeline 接管）
        # mid-state 查询
        return [
            {"id": "ep_stuck_a", "status": "asr_running"},
            {"id": "ep_stuck_b", "status": "downloading"},
        ]

    resets = []

    async def fake_update_status(eid, status, error_msg=None, retry_count=None):
        if status == "pending":
            resets.append((eid, retry_count))

    async def fake_resolve(_eid):
        return None

    async def fake_resume(eid, raw_input, on_progress=None):
        pass

    async def fake_sleep(_seconds):
        w.running = False

    monkeypatch.setattr(app_database.EpisodeRepository, "get_by_statuses", staticmethod(fake_get_by_statuses))
    monkeypatch.setattr(app_database.EpisodeRepository, "update_status", staticmethod(fake_update_status))
    monkeypatch.setattr(app_database.SourceRepository, "resolve_raw_input", staticmethod(fake_resolve))
    monkeypatch.setattr(app_pipeline.pipeline, "resume_episode", fake_resume)
    monkeypatch.setattr(worker.asyncio, "sleep", fake_sleep)

    w.running = True
    await w.run()

    reset_ids = {eid for eid, _rc in resets}
    assert reset_ids == {"ep_stuck_a", "ep_stuck_b"}, (
        f"两个 mid-state 孤儿都应重置 pending，实际 {resets}"
    )
    # retry_count 未显式传（保留旧值），fake 收到 None
    assert all(rc is None for _eid, rc in resets), "重置不应清零 retry_count"


async def test_worker_mid_state_requeue_runs_before_pending_processing(monkeypatch):
    """自愈先于 pending 处理：本轮即把 mid-state 重置后并入同一轮 pending 处理。"""
    w = worker.Worker()
    order = []

    async def fake_get_by_statuses(statuses):
        order.append(f"query:{statuses}")
        if statuses == ["pending"]:
            return [{"id": "ep_pend", "status": "pending"}]
        return [{"id": "ep_stuck", "status": "llm_running"}]

    async def fake_update_status(eid, status, error_msg=None, retry_count=None):
        order.append(f"reset:{eid}->{status}")

    async def fake_resolve(eid):
        order.append(f"resolve:{eid}")
        return "https://example.com/x"

    async def fake_resume(eid, raw_input, on_progress=None):
        order.append(f"resume:{eid}")

    async def fake_sleep(_seconds):
        w.running = False

    monkeypatch.setattr(app_database.EpisodeRepository, "get_by_statuses", staticmethod(fake_get_by_statuses))
    monkeypatch.setattr(app_database.EpisodeRepository, "update_status", staticmethod(fake_update_status))
    monkeypatch.setattr(app_database.SourceRepository, "resolve_raw_input", staticmethod(fake_resolve))
    monkeypatch.setattr(app_pipeline.pipeline, "resume_episode", fake_resume)
    monkeypatch.setattr(worker.asyncio, "sleep", fake_sleep)

    w.running = True
    await w.run()

    # mid-state 查询/重置必须早于 pending 查询/处理
    mid_idx = order.index("reset:ep_stuck->pending")
    pend_resume_idx = order.index("resume:ep_pend")
    assert mid_idx < pend_resume_idx, (
        f"自愈应先于 pending 处理，实际顺序 {order}"
    )


async def test_worker_ensures_db_schema_before_first_poll(monkeypatch):
    """Regression: worker.run() 必须在首次轮询前 await init_db()。

    worker 可能与 API 并发启动（launchd 独立 plist / 手动并行起）；若早于 API 的
    init_db() 完成就开始轮询，首轮查 episode 会 'no such table: episode'（虽自愈，
    但留 ERROR 噪音）。worker 主动建表后才能独立冷启，不依赖 API 进程。
    """
    w = worker.Worker()
    order = []

    async def fake_init_db():
        order.append("init_db")

    async def fake_get_by_statuses(statuses):
        order.append(f"query:{statuses[0]}")
        return []

    async def fake_sleep(_seconds):
        w.running = False  # 跑完一轮即退出

    monkeypatch.setattr(app_database, "init_db", fake_init_db)
    monkeypatch.setattr(app_database.EpisodeRepository, "get_by_statuses", staticmethod(fake_get_by_statuses))
    monkeypatch.setattr(worker.asyncio, "sleep", fake_sleep)

    w.running = True
    await w.run()

    assert "init_db" in order, f"worker.run() 应调用 init_db，实际顺序 {order}"
    first_poll = next(i for i, x in enumerate(order) if x.startswith("query:"))
    assert order.index("init_db") < first_poll, (
        f"init_db 必须早于首次轮询查询，实际顺序 {order}"
    )


# ---------- Phase 3：ASRError/LLMError(retryable=True) 接通 worker 跨轮次重试 ----------
#
# pipeline 现在把 ASR/LLM 失败包成 ASRError/LLMError（retryable=True）。这里验证
# worker._handle_episode_failure 收到这类异常时：配额内 → 退避 + 回 pending（重试）；
# 收到非可重试异常（裸 RuntimeError）→ 直接 failed。这是"第 N 步崩溃能恢复"的
# 最后一环：错误分类 → worker 退避重试 → 下轮 poll 按 checkpoint 续点。

async def test_worker_retries_when_resume_raises_retryable_asr_error(monkeypatch):
    """resume_episode 抛 ASRError(retryable=True) → 退避 + 回 pending（attempt 递增）。"""
    from app.errors import ASRError

    w = worker.Worker()
    updates = []

    async def fake_get_retry_count(eid):
        return 0  # 第一次失败

    async def fake_update_status(eid, status, error_msg=None, retry_count=None):
        updates.append((status, retry_count))

    monkeypatch.setattr(app_database.EpisodeRepository, "get_retry_count", staticmethod(fake_get_retry_count))
    monkeypatch.setattr(app_database.EpisodeRepository, "update_status", staticmethod(fake_update_status))
    # 退避sleep 不真正等待
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(worker.asyncio, "sleep", fake_sleep)

    result = await w._handle_episode_failure("ep_x", ASRError("ASR 超时"))

    assert result is True, "retryable + 配额内 → 应回 pending（返回 True）"
    assert updates == [("pending", 1)], f"应退避后回 pending 且 retry_count+1，实际 {updates}"
    assert slept, "应执行退避 sleep"


async def test_worker_marks_failed_when_resume_raises_non_retryable(monkeypatch):
    """resume_episode 抛裸 RuntimeError（无 retryable）→ 直接 failed，不重试。"""
    w = worker.Worker()
    updates = []

    async def fake_get_retry_count(eid):
        return 0

    async def fake_update_status(eid, status, error_msg=None, retry_count=None):
        updates.append((status, error_msg))

    monkeypatch.setattr(app_database.EpisodeRepository, "get_retry_count", staticmethod(fake_get_retry_count))
    monkeypatch.setattr(app_database.EpisodeRepository, "update_status", staticmethod(fake_update_status))
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(worker.asyncio, "sleep", fake_sleep)

    result = await w._handle_episode_failure("ep_y", RuntimeError("Apple AFM 3 only available on macOS 26+"))

    assert result is False, "非 retryable → 应终态 failed（返回 False）"
    assert any(s == "failed" for s, _ in updates), f"应置 failed，实际 {updates}"
    assert not slept, "永久错不应退避 sleep"


async def test_worker_marks_failed_when_retry_exhausted(monkeypatch):
    """retryable 但配额耗尽（retry_count 已达上限）→ 终态 failed，不再退避。"""
    from app.errors import LLMError

    w = worker.Worker()
    updates = []

    async def fake_get_retry_count(eid):
        from app.config import WORKER_MAX_DOWNLOAD_RETRIES
        return WORKER_MAX_DOWNLOAD_RETRIES  # 已耗尽

    async def fake_update_status(eid, status, error_msg=None, retry_count=None):
        updates.append(status)

    monkeypatch.setattr(app_database.EpisodeRepository, "get_retry_count", staticmethod(fake_get_retry_count))
    monkeypatch.setattr(app_database.EpisodeRepository, "update_status", staticmethod(fake_update_status))
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(worker.asyncio, "sleep", fake_sleep)

    result = await w._handle_episode_failure("ep_z", LLMError("429 持续"))

    assert result is False, "配额耗尽 → 应终态 failed"
    assert "failed" in updates
    assert not slept, "配额耗尽不应退避"
