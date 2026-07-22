"""task_recovery 启动恢复路径的 ASR 阶段 resume 回归测试。

背景：服务重启时撞见「ASR 未完成（无 transcript.json）」的非终态任务，旧逻辑只
置 PENDING + warning「找不到原始输入」便放弃，任务永远卡死。修复后：能从
source/usage_log 解析出原始输入 → 经 audio_pipeline.resume_episode 重跑；解析
不到 → 置 FAILED 并给出可操作的 error_msg。
"""
import pytest

from app import task_recovery
from app import config as app_config
from app import database as app_database
from app import pipeline as app_pipeline


@pytest.fixture
def empty_media_dir(monkeypatch, tmp_path):
    """把 DATA_DIR 指向空临时目录，使 transcript.json / highlight.json 都不存在 → 走 else 分支。"""
    monkeypatch.setattr(app_config, "DATA_DIR", tmp_path)
    return tmp_path


async def test_asr_stage_resume_restarts_when_raw_input_resolved(empty_media_dir, monkeypatch):
    """无 transcript + 能解析 raw_input → resume_episode 被调用、状态置 PENDING。"""
    statuses = []

    async def fake_update_status(eid, status, error_msg=None):
        statuses.append((status, error_msg))

    async def fake_get_job(eid):
        return None

    async def fake_resolve(eid):
        return "https://example.com/audio.mp3"

    called = {}

    async def fake_resume(eid, raw_input, on_progress=None):
        called["episode_id"] = eid
        called["raw_input"] = raw_input

    monkeypatch.setattr(task_recovery.EpisodeRepository, "update_status", staticmethod(fake_update_status))
    monkeypatch.setattr(task_recovery.IngestJobRepository, "get_by_id", staticmethod(fake_get_job))
    monkeypatch.setattr(app_database.SourceRepository, "resolve_raw_input", staticmethod(fake_resolve))
    monkeypatch.setattr(app_pipeline.pipeline, "resume_episode", fake_resume)

    await task_recovery._recover_single_task("ep_1", "asr_running")

    assert called.get("raw_input") == "https://example.com/audio.mp3"
    assert called.get("episode_id") == "ep_1"
    assert any(s == "pending" for s, _ in statuses), f"应先置 PENDING 再重跑，实际 {statuses}"


async def test_asr_stage_resume_fails_when_no_raw_input(empty_media_dir, monkeypatch):
    """无 transcript + 解析不到 raw_input → 置 FAILED 且 error_msg 可读、不调 resume_episode。"""
    statuses = []

    async def fake_update_status(eid, status, error_msg=None):
        statuses.append((status, error_msg))

    async def fake_get_job(eid):
        return None

    async def fake_resolve(eid):
        return None

    resume_called = []

    async def fake_resume(eid, raw_input, on_progress=None):
        resume_called.append(eid)

    monkeypatch.setattr(task_recovery.EpisodeRepository, "update_status", staticmethod(fake_update_status))
    monkeypatch.setattr(task_recovery.IngestJobRepository, "get_by_id", staticmethod(fake_get_job))
    monkeypatch.setattr(app_database.SourceRepository, "resolve_raw_input", staticmethod(fake_resolve))
    monkeypatch.setattr(app_pipeline.pipeline, "resume_episode", fake_resume)

    await task_recovery._recover_single_task("ep_2", "asr_running")

    assert resume_called == [], "无原始输入时不应调用 resume_episode"
    failed = [s for s, msg in statuses if s == "failed"]
    assert failed, f"应置 FAILED，实际 {statuses}"
    assert any(msg and "原始输入" in msg for _, msg in statuses), (
        f"error_msg 应提示原始输入缺失，实际 {statuses}"
    )
