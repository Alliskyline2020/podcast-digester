"""save_episode_bundle 必须在线程里跑，不阻塞 async event loop。

回归背景（database is locked，历史 32 次 episode 收尾失败）：
sync save_episode_bundle 内部调 EpisodeRepositorySync.update_status_sync
（sync sqlite3 写）。直接在 async pipeline 里同步调用会阻塞 event loop，
与 aiosqlite 后台线程死锁——后台线程持有写锁后，其结果回调需要 event loop
处理才能释放连接，而 event loop 已被 sync 调用阻塞，busy_timeout 30s 后
抛 'database is locked'，整集 rollback（所有 LLM 工作白费）。

现场证据：ep_1785599679743 经 ASR→correct→polish→highlight→insights 全部
成功（产物均落盘），但收尾 update_status_sync("ready") 等锁 67s 后失败，
status 误标 failed。api.err.log 同期空白 → 排除 API 元凶，是 worker 自身
async/sync 死锁。

修复：_save_bundle 用 asyncio.to_thread 把 sync 函数移到线程池，event loop
继续转，死锁条件消除。
"""
import asyncio
import time

import pytest

from app.pipeline import AudioProcessPipeline


@pytest.mark.unit
async def test_save_bundle_runs_off_event_loop(tmp_path, monkeypatch):
    """_save_bundle 必须把 save_episode_bundle 移到线程，event loop 不被阻塞。

    判据：save 内部 time.sleep(0.3)（模拟 sync 等 DB 锁）期间，并发的 heartbeat
    必须持续 tick（相邻 tick 间隙 < 0.2s）。若直接同步调用，event loop 阻塞，
    heartbeat 在 save 期间不 tick，会出现 ≥0.3s 的间隙。
    """
    pipeline = object.__new__(AudioProcessPipeline)
    pipeline.data_dir = tmp_path

    def slow_save(episode_id, data_dir, **kwargs):
        time.sleep(0.3)

    monkeypatch.setattr("app.pipeline.save_episode_bundle", slow_save)

    ticks = []

    async def heartbeat():
        for _ in range(7):
            ticks.append(time.monotonic())
            await asyncio.sleep(0.05)

    async def delayed_save():
        await asyncio.sleep(0.1)  # 让 heartbeat 先起
        await pipeline._save_bundle(
            "ep",
            transcript=None,
            outline={"entries": []},
            summaries=[],
            highlight=None,
        )

    await asyncio.gather(heartbeat(), delayed_save())

    gaps = [ticks[i + 1] - ticks[i] for i in range(len(ticks) - 1)]
    assert gaps, "heartbeat 没产出 tick"
    assert max(gaps) < 0.2, (
        f"event loop 被 save 阻塞！最大间隙 {max(gaps):.2f}s"
        f"（sync 0.3s 阻塞会导致 ≥0.3s 间隙）"
    )
