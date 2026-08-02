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
