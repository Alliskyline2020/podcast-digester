"""成功状态必须清空残留的 error_msg。

回归：EpisodeRepository.update_status / update_status_sync 的 else 分支
（不传 error_msg）只更新 status，不碰 error_msg。于是「先失败后成功」的
episode 在 status=ready 时仍带着旧的失败文本——save_episode_bundle 的
ready 路径（storage.py:239）和 task_recovery 的 ready 路径都命中这个 bug。

现场：ep_1783401350118 实际完整就绪，却长期显示 "Chapter split failed: ..."。
"""
from datetime import datetime

import pytest

from app.database import EpisodeRepository, EpisodeRepositorySync
from app.models import EpisodeStatus


def _episode_data(eid="ep_status"):
    return {
        "id": eid,
        "title": "T",
        "status": EpisodeStatus.PENDING.value,
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    }


@pytest.mark.unit
@pytest.mark.database
async def test_update_status_async_clears_stale_error_on_success(temp_db):
    await EpisodeRepository.create(_episode_data())
    await EpisodeRepository.update_status("ep_status", EpisodeStatus.FAILED.value, "boom")
    assert (await EpisodeRepository.get_by_id("ep_status"))["error_msg"] == "boom"

    # 转为 ready 且不带 error_msg ⇒ 必须清空旧错误
    await EpisodeRepository.update_status("ep_status", EpisodeStatus.READY.value)

    row = await EpisodeRepository.get_by_id("ep_status")
    assert row["status"] == EpisodeStatus.READY.value
    assert row["error_msg"] is None


@pytest.mark.unit
@pytest.mark.database
async def test_update_status_sync_clears_stale_error_on_success(temp_db):
    await EpisodeRepository.create(_episode_data("ep_sync"))
    EpisodeRepositorySync.update_status_sync("ep_sync", EpisodeStatus.FAILED.value, "boom")
    assert (await EpisodeRepository.get_by_id("ep_sync"))["error_msg"] == "boom"

    # save_episode_bundle 的 ready 路径走的就是这个 sync 调用
    EpisodeRepositorySync.update_status_sync("ep_sync", EpisodeStatus.READY.value)

    row = await EpisodeRepository.get_by_id("ep_sync")
    assert row["status"] == EpisodeStatus.READY.value
    assert row["error_msg"] is None
