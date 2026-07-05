"""
episode_loader 回退测试。

派生数据 (outline / summaries / highlight / product_insights) 在 DB 表为空时
必须回退到磁盘 checkpoint 文件, 而非只在 DB 读取"抛异常"时才回退。

现实场景: ep_1783264218536 全 pipeline 跑完后, save_episode_bundle 在
update_status_sync("ready") 处 'database is locked' 失败 (storage.py:239),
导致 pipeline.py:358-370 的 4 个派生表写入从未到达。resume (_resume_internal)
只重跑 save_episode_bundle, 不补写派生表。loader 若只对"异常"回退、对"空"不回退,
详情页这 4 个面板就会全是 None —— 尽管磁盘上 outline.json / summaries.json /
highlight.json / product_insights.json 都完好。

文件是 status=ready 之前就已原子落盘的 checkpoint, 应作为 DB 缺失时的权威来源。
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import app.deps
from app.services.episode_loader import load_episode_bundle

EP_ID = "ep_test_loader"


def _write_checkpoints(media_dir: Path) -> None:
    """落盘与 save_episode_bundle 一致的 4 份 checkpoint。"""
    media_dir.mkdir(parents=True, exist_ok=True)
    (media_dir / "outline.json").write_text(json.dumps({
        "entries": [{
            "index": 0,
            "title_zh": "开篇",
            "start_ms": 0,
            "end_ms": 1000,
            "start_segment_id": 0,
            "end_segment_id": 5,
        }]
    }, ensure_ascii=False), encoding="utf-8")
    (media_dir / "summaries.json").write_text(json.dumps([{
        "chapter_id": "ch0",
        # content_zh min_length=50 —— 与 pipeline 实际产物一致
        "content_zh": "本章深入介绍了节目的核心主题与嘉宾背景，全面覆盖了主要讨论线索、关键论点以及最终得出的重要结论，帮助听众快速把握全貌。",
        "key_points_zh": ["要点一", "要点二"],
        "cited_segment_ids": [0, 1, 2],
    }], ensure_ascii=False), encoding="utf-8")
    (media_dir / "highlight.json").write_text(json.dumps({
        "tldr_zh": "这是一期值得深听的对话，覆盖了关键议题与判断。",
        "worth_listening_verdict": "deep_listen",
        "verdict_confidence": "high",
        "target_audience_zh": "对科技与未来感兴趣的听众群体",
        "highlights": [{
            "kind": "insight",
            "text_zh": "核心洞察",
            "why_zh": "很有价值",
            "cited_segment_ids": [0],
            "start_ms": 100,
        }],
        "estimated_time_saved_min": 20,
    }, ensure_ascii=False), encoding="utf-8")
    (media_dir / "product_insights.json").write_text(json.dumps({
        "schema_version": 3,
        "product": {"items": []},
        "technical": {"items": []},
        "market": {"items": []},
        "mentioned_companies": ["Neuralink"],
        "mentioned_technologies": ["BCI"],
    }, ensure_ascii=False), encoding="utf-8")


def _episode_row() -> dict:
    return {
        "id": EP_ID,
        "title": "Test Episode",
        "status": "ready",
        "language": "en",
        "created_at": "2026-07-06T00:00:00",
        "updated_at": "2026-07-06T00:00:00",
    }


def _patch_repos_empty(monkeypatch) -> None:
    """DB 侧: episode 存在, 但 4 张派生表全空 (resume 后的真实态)。"""
    import app.services.episode_loader as L

    monkeypatch.setattr(
        L.EpisodeRepository, "get_by_id",
        AsyncMock(return_value=_episode_row()),
    )
    monkeypatch.setattr(
        L.SourceRepository, "get_by_episode",
        AsyncMock(return_value=None),
    )
    # 4 张派生表: DB 返回 None (无行) —— 不抛异常, 只是空。
    monkeypatch.setattr(L.OutlineRepository, "get", AsyncMock(return_value=None))
    monkeypatch.setattr(L.SummariesRepository, "get", AsyncMock(return_value=None))
    monkeypatch.setattr(L.HighlightRepository, "get", AsyncMock(return_value=None))
    monkeypatch.setattr(L.ProductInsightsRepository, "get", AsyncMock(return_value=None))


async def test_loader_falls_back_to_files_when_derived_db_empty(tmp_path, monkeypatch):
    """DB 派生表为空时, 4 份产物必须从磁盘 checkpoint 加载 (当前会失败: 全 None)。"""
    _write_checkpoints(tmp_path / "media" / EP_ID)
    monkeypatch.setattr(app.deps, "data_dir", tmp_path)
    _patch_repos_empty(monkeypatch)

    bundle = await load_episode_bundle(EP_ID)

    # outline
    assert bundle.outline is not None, "outline 应从 outline.json 回退加载"
    assert len(bundle.outline.entries) == 1
    # summaries
    assert len(bundle.chapter_summaries) == 1, "summaries 应从 summaries.json 回退加载"
    # highlight
    assert bundle.highlight is not None, "highlight 应从 highlight.json 回退加载"
    assert bundle.highlight.worth_listening_verdict.value == "deep_listen"
    # product_insights
    assert bundle.product_insights is not None, "product_insights 应从 product_insights.json 回退加载"
    assert bundle.product_insights.mentioned_companies == ["Neuralink"]


async def test_loader_prefers_db_when_derived_rows_exist(tmp_path, monkeypatch):
    """DB 有派生行时仍优先 DB (回退不应破坏正常路径)。"""
    _write_checkpoints(tmp_path / "media" / EP_ID)
    monkeypatch.setattr(app.deps, "data_dir", tmp_path)
    import app.services.episode_loader as L

    monkeypatch.setattr(
        L.EpisodeRepository, "get_by_id",
        AsyncMock(return_value=_episode_row()),
    )
    monkeypatch.setattr(
        L.SourceRepository, "get_by_episode",
        AsyncMock(return_value=None),
    )
    # DB 里的 outline 与磁盘不同 (多一章), 验证优先取 DB。
    # 注意: DerivedDataRepository.get 已把 entries_json 解析成 entries, 故 mock
    # 返回解析后形态 (loader 读 outline_data["entries"])。
    monkeypatch.setattr(L.OutlineRepository, "get", AsyncMock(return_value={
        "entries": [
            {"index": 0, "title_zh": "DB章", "start_ms": 0,
             "end_ms": 1, "start_segment_id": 0, "end_segment_id": 1},
            {"index": 1, "title_zh": "DB章2", "start_ms": 1,
             "end_ms": 2, "start_segment_id": 2, "end_segment_id": 3},
        ],
    }))
    monkeypatch.setattr(L.SummariesRepository, "get", AsyncMock(return_value=None))
    monkeypatch.setattr(L.HighlightRepository, "get", AsyncMock(return_value=None))
    monkeypatch.setattr(L.ProductInsightsRepository, "get", AsyncMock(return_value=None))

    bundle = await load_episode_bundle(EP_ID)

    assert bundle.outline is not None
    assert len(bundle.outline.entries) == 2, "DB 命中时应取 DB 的 2 章, 不回退磁盘的 1 章"
