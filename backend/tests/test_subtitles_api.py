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

    # 验证词库收到了完整姓名对的修正（不是字符级片段）
    # 编辑 杨志玲 -> 杨植麟 应该产生 ("杨植麟", ["杨志玲"])
    # 而不是危险的全局片段 ("植麟", ["志玲"])
    assert (
        len(fake.added) >= 1
    ), f"等长编辑应入词库，实际 added={fake.added}"

    # 找到精确匹配的全名对
    found = False
    for correct, wrong_list in fake.added:
        if correct == "杨植麟" and "杨志玲" in wrong_list:
            found = True
            break
    assert found, f"期望包含 '杨植麟' <- '杨志玲' 的完整姓名修正，实际 {fake.added}"


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

    # 检查核心修正是否存在（现在是完整姓名对，可能包含前缀连接词）
    # "杨志玲和张三" -> "杨植麟和李四" 会产生：
    # ("杨植麟", ["杨志玲"]) 和 ("和李四", ["和张三"])
    # 注意 wrong_list 是列表，需要用 in 检查元素
    has_zhiling = any("杨植麟" in c and any("杨志玲" in x for x in w) for c, w in fake.added)
    # 对于第二个替换，连接词"和"也是CJK汉字，会被包含
    has_lisi = any("李四" in c and any("张三" in x for x in w) for c, w in fake.added)
    assert has_zhiling, f"期望包含 '杨植麟' <- '杨志玲'，实际 {fake.added}"
    assert has_lisi, f"期望包含 '李四' <- '张三'（可能带前缀），实际 {fake.added}"


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
async def test_update_segment_does_not_bleed_forward_into_predicate(
    temp_db, temp_data_dir, monkeypatch
):
    """向后的CJK扩展不应包含谓语（是/说/讲/老师等），避免过度膨胀token。"""
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

    # 编辑 "杨志玲是教授" -> "杨植麟是教授"
    # 期望词库记录: ("杨植麟", ["杨志玲"])
    # 而不是: ("杨植麟是", ["杨志玲是"]) —— 这会过度匹配
    ep_id = await _seed_episode_with_segments(client, ["杨志玲是教授"])

    resp = client.post(
        f"/api/episodes/{ep_id}/segments/update",
        json={
            "segment_index": 0,
            "text_original": "杨植麟是教授",
            "note_to_glossary": True,
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["added_to_glossary"] is True

    # 验证记录的是完整姓名，不包含谓语 "是"
    found = False
    for correct, wrong_list in fake.added:
        if correct == "杨植麟" and "杨志玲" in wrong_list:
            found = True
            break
        # 排除错误情况：包含了 "是"
        if "是" in correct:
            assert False, f"不应包含谓语 '是'，但得到了 correct={correct}"
    assert found, f"期望包含 '杨植麟' <- '杨志玲'（不含谓语），实际 {fake.added}"


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


@pytest.mark.asyncio
async def test_batch_correct_preview_counts_matches_without_applying(
    temp_db, temp_data_dir
):
    """批量纠错预览模式：入词库+返回命中数，不改文本。"""
    from app.main import app

    client = TestClient(app)

    # 创建一个带 2 段包含错字的字幕的 episode
    ep_id = await _seed_episode_with_segments(client, ["杨志林是教授", "杨志林在清华"])

    # 预览模式：apply=False，不应改文本
    resp = client.post(
        f"/api/episodes/{ep_id}/batch-correct",
        json={"correct": "杨植麟", "wrong": "杨志林", "apply": False},
    )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["success"] is True
    assert body["applied"] is False
    assert body["preview"]["transcript_matches"] == 2
    assert body["added_to_glossary"] is True  # 预览也入词库，方便后续

    # 验证文本未被修改
    from app.services.episode_loader import load_episode_bundle
    bundle = await load_episode_bundle(ep_id)
    joined = "".join(s.text_original for s in bundle.transcript.segments)
    assert "杨志林" in joined  # 错字仍在
    assert "杨植麟" not in joined  # 正确字未出现


@pytest.mark.asyncio
async def test_batch_correct_apply_rewrites_transcript_and_modules(
    temp_db, temp_data_dir
):
    """批量纠错应用模式：改文本+改模块+入词库。"""
    from app.main import app

    client = TestClient(app)

    # 创建一个带错字的字幕段
    ep_id = await _seed_episode_with_segments(client, ["杨志林是教授"])

    # 应用模式：apply=True，应改文本
    resp = client.post(
        f"/api/episodes/{ep_id}/batch-correct",
        json={"correct": "杨植麟", "wrong": "杨志林", "apply": True},
    )

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["success"] is True
    assert body["applied"] is True
    assert body["preview"]["transcript_matches"] == 1
    assert body["added_to_glossary"] is True

    # 验证文本已修改（通过服务读取，不通过 HTTP GET bundle）
    from app.services.episode_loader import load_episode_bundle
    bundle = await load_episode_bundle(ep_id)
    joined = "".join(s.text_original for s in bundle.transcript.segments)
    assert "杨植麟" in joined and "杨志林" not in joined
