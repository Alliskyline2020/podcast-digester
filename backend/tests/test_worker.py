"""Worker 主循环取源路径回归。

背景：worker.py 历史上从 ``usage_log.payload_json`` 取原始输入，既不走 source 表、
也不限 ``event_type='paste'``，在「pipeline 还没写 source 就崩」的早期失败、或非 paste
事件下会取错源甚至卡死。修复后与 task_recovery / 手动「恢复」按钮同路径：
``SourceRepository.resolve_raw_input``（source.raw_input → usage_log paste 兜底）。

取源逻辑见 worker.run()；resume 路径的对照测试在 test_task_recovery_asr.py。
"""
from app import database as app_database
from app.ingest import pipeline as ingest_pipeline
import worker


async def test_worker_uses_resolve_raw_input(monkeypatch):
    """pending episode + 能解析 raw_input → pipeline.run_ingest 收到正确 URL。"""
    w = worker.Worker()
    seen = {}

    async def fake_get_by_statuses(statuses):
        assert statuses == ["pending"]
        return [{"id": "ep_1"}]

    async def fake_resolve(eid):
        assert eid == "ep_1"
        return "https://example.com/podcast.mp3"

    async def fake_run_ingest(episode_id, raw_input, on_progress=None):
        seen["episode_id"] = episode_id
        seen["raw_input"] = raw_input

    async def fake_sleep(_seconds):
        # 跑完一轮即让 while self.running 退出，避免死循环
        w.running = False

    monkeypatch.setattr(app_database.EpisodeRepository, "get_by_statuses", staticmethod(fake_get_by_statuses))
    monkeypatch.setattr(app_database.SourceRepository, "resolve_raw_input", staticmethod(fake_resolve))
    monkeypatch.setattr(ingest_pipeline, "run_ingest", fake_run_ingest)
    monkeypatch.setattr(worker.asyncio, "sleep", fake_sleep)

    w.running = True
    await w.run()

    assert seen.get("raw_input") == "https://example.com/podcast.mp3"
    assert seen.get("episode_id") == "ep_1"


async def test_worker_skips_episode_without_raw_input(monkeypatch):
    """pending episode + 解析不到 raw_input → 不调 run_ingest、不抛错（仅记 warning）。"""
    w = worker.Worker()
    ingest_called = []

    async def fake_get_by_statuses(_statuses):
        return [{"id": "ep_orphan"}]

    async def fake_resolve(_eid):
        return None

    async def fake_run_ingest(episode_id, raw_input, on_progress=None):
        ingest_called.append(episode_id)

    async def fake_sleep(_seconds):
        w.running = False

    monkeypatch.setattr(app_database.EpisodeRepository, "get_by_statuses", staticmethod(fake_get_by_statuses))
    monkeypatch.setattr(app_database.SourceRepository, "resolve_raw_input", staticmethod(fake_resolve))
    monkeypatch.setattr(ingest_pipeline, "run_ingest", fake_run_ingest)
    monkeypatch.setattr(worker.asyncio, "sleep", fake_sleep)

    w.running = True
    await w.run()

    assert ingest_called == [], "无 raw_input 不应调用 run_ingest"
