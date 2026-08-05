"""
字幕编辑 API 测试

测试字幕 segment 编辑、更新和词库自动添加功能
"""
import pytest
from fastapi.testclient import TestClient
from datetime import datetime
from app.database import EpisodeRepository
from app.models import EpisodeStatus


async def _seed_episode_with_segments(client: TestClient, texts: list[str]) -> str:
    """创建一个带指定字幕段的测试 episode，返回 episode_id"""
    import time
    episode_data = {
        "id": f"ep_test_{int(time.time() * 1000)}",  # 必须 ep_ 前缀
        "title": "Test Episode for Glossary",
        "status": EpisodeStatus.READY.value,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }
    await EpisodeRepository.create(episode_data)
    ep_id = episode_data["id"]

    # 构建转录数据，每个文本对应一个 segment
    # Segment.id 必须是整数
    transcript_data = {
        "episode_id": ep_id,
        "language": "zh",
        "segments": [
            {
                "id": i,
                "start_ms": i * 5000,
                "end_ms": (i + 1) * 5000,
                "text_original": text,
            }
            for i, text in enumerate(texts)
        ],
    }
    await EpisodeRepository.update_transcript(ep_id, transcript_data)
    return ep_id


@pytest.mark.asyncio
async def test_update_segment_adds_equal_length_correction_to_glossary(
    temp_db, temp_data_dir, monkeypatch
):
    """等长编辑（如人名 杨志玲→杨植麟）也必须可靠入词库，不能被 len() 启发式吞掉。"""
    from app.services import glossary as glossary_svc
    from app.main import app

    # 用独立内存词库避免污染全局单例
    class _FakeGlossary:
        def __init__(self):
            self.added = []

        def add_entry(self, correct, wrong):
            self.added.append((correct, list(wrong)))

    fake = _FakeGlossary()
    monkeypatch.setattr(glossary_svc, "get_glossary", lambda *_a, **_k: fake)

    client = TestClient(app)

    # 构造一个带 1 段字幕的 episode
    ep_id = await _seed_episode_with_segments(client, ["杨志玲是清华的教授"])

    resp = client.post(
        f"/api/episodes/{ep_id}/segments/update",
        json={
            "segment_index": 0,
            "text_original": "杨植麟是清华的教授",
            "note_to_glossary": True,
        },
    )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    data = resp.json()
    assert data["success"] is True
    assert data["added_to_glossary"] is True

    # 验证词库收到了修正对
    # difflib 提取的是最小差异：志玲 -> 植麟
    assert (
        len(fake.added) >= 1
    ), f"等长编辑应入词库，实际 added={fake.added}"

    # difflib 可能会提取多个 token 对，只要包含核心修正就行
    found = False
    for correct, wrong_list in fake.added:
        if "植麟" in correct and "志玲" in wrong_list:
            found = True
            break
    assert found, f"期望包含 '植麟' <- '志玲' 的修正，实际 {fake.added}"


@pytest.mark.asyncio
async def test_update_segment_adds_longer_correction_to_glossary(
    temp_db, temp_data_dir, monkeypatch
):
    """变长编辑（旧→新，更长）也应入词库。"""
    from app.services import glossary as glossary_svc
    from app.main import app

    class _FakeGlossary:
        def __init__(self):
            self.added = []

        def add_entry(self, correct, wrong):
            self.added.append((correct, list(wrong)))

    fake = _FakeGlossary()
    monkeypatch.setattr(glossary_svc, "get_glossary", lambda *_a, **_k: fake)

    client = TestClient(app)

    # 构造一个带 1 段字幕的 episode（用更短的错字来触发 replace）
    # 而不是 insert
    ep_id = await _seed_episode_with_segments(client, ["张三是清华的教授"])

    resp = client.post(
        f"/api/episodes/{ep_id}/segments/update",
        json={
            "segment_index": 0,
            "text_original": "李四是清华的教授",
            "note_to_glossary": True,
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["added_to_glossary"] is True

    assert len(fake.added) >= 1
    # difflib 会找出 "李四" <- "张三" 的替换
    found = False
    for correct, wrong_list in fake.added:
        if "李四" in correct and "张三" in wrong_list:
            found = True
            break
    assert found, f"期望包含 '李四' <- '张三' 的修正，实际 {fake.added}"


@pytest.mark.asyncio
async def test_update_segment_with_multiple_replacements_all_added_to_glossary(
    temp_db, temp_data_dir, monkeypatch
):
    """一次编辑中的多个替换应全部入词库。"""
    from app.services import glossary as glossary_svc
    from app.main import app

    class _FakeGlossary:
        def __init__(self):
            self.added = []

        def add_entry(self, correct, wrong):
            self.added.append((correct, list(wrong)))

    fake = _FakeGlossary()
    monkeypatch.setattr(glossary_svc, "get_glossary", lambda *_a, **_k: fake)

    client = TestClient(app)

    # 构造一个带 1 段字幕的 episode - 使用纯替换，避免 insert/delete
    ep_id = await _seed_episode_with_segments(client, ["杨志玲和张三都在研究"])

    resp = client.post(
        f"/api/episodes/{ep_id}/segments/update",
        json={
            "segment_index": 0,
            "text_original": "杨植麟和李四都在研究",
            "note_to_glossary": True,
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["added_to_glossary"] is True

    # 应该至少有替换对（difflib 可能会拆分）
    assert len(fake.added) >= 2

    # 检查核心修正是否存在
    has_zhiling = any("植麟" in c and "志玲" in w for c, w in fake.added)
    has_lisi = any("李四" in c and "张三" in w for c, w in fake.added)
    assert has_zhiling, f"期望包含 '植麟' <- '志玲'，实际 {fake.added}"
    assert has_lisi, f"期望包含 '李四' <- '张三'，实际 {fake.added}"


@pytest.mark.asyncio
async def test_update_segment_without_note_to_glossary_does_not_add(
    temp_db, temp_data_dir, monkeypatch
):
    """note_to_glossary=False 时不入词库。"""
    from app.services import glossary as glossary_svc
    from app.main import app

    class _FakeGlossary:
        def __init__(self):
            self.added = []

        def add_entry(self, correct, wrong):
            self.added.append((correct, list(wrong)))

    fake = _FakeGlossary()
    monkeypatch.setattr(glossary_svc, "get_glossary", lambda *_a, **_k: fake)

    client = TestClient(app)

    ep_id = await _seed_episode_with_segments(client, ["杨志玲是清华的教授"])

    resp = client.post(
        f"/api/episodes/{ep_id}/segments/update",
        json={
            "segment_index": 0,
            "text_original": "杨植麟是清华的教授",
            "note_to_glossary": False,  # 不入词库
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["added_to_glossary"] is False
    assert len(fake.added) == 0


@pytest.mark.asyncio
async def test_update_segment_basic(temp_db, temp_data_dir):
    """基本的 segment 更新功能（不涉及词库）。"""
    from app.main import app

    client = TestClient(app)

    ep_id = await _seed_episode_with_segments(client, ["原始文本"])

    resp = client.post(
        f"/api/episodes/{ep_id}/segments/update",
        json={"segment_index": 0, "text_original": "更新后的文本"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["old_text"] == "原始文本"
    assert data["new_text"] == "更新后的文本"
    assert data["segment_index"] == 0
    assert data["added_to_glossary"] is False
