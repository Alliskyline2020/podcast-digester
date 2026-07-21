"""pipeline 清洗接线集成测试: harvest → polish(entity_variants) 顺序与传参。"""
import pytest

from app.models import Segment, Transcript


@pytest.mark.asyncio
async def test_pipeline_harvests_entities_then_polishes(monkeypatch):
    """主流程 _clean_transcript: polish 前先 harvest_entities, 并把结果传给 polish。"""
    from app import pipeline as pl

    seq = []

    async def fake_harvest(text, glossary_variants=None):
        seq.append("harvest")
        return {"姚顺雨": "姚顺宇"}

    async def fake_polish(self_sp, transcript, progress_cb=None, entity_variants=None, force=False):
        seq.append(("polish", entity_variants))
        for s in transcript.segments:
            s.text_with_punct = s.text_original
        return 1

    async def fake_translate(self_sp, transcript, progress_cb=None):
        seq.append("translate")
        return 0

    async def fake_gen(self_pl, eid, tr):
        seq.append("gen")

    monkeypatch.setattr(pl, "harvest_entities", fake_harvest)
    monkeypatch.setattr(pl.SubtitleProcessor, "polish", fake_polish)
    monkeypatch.setattr(pl.SubtitleProcessor, "translate", fake_translate)
    monkeypatch.setattr(pl.AudioProcessPipeline, "_generate_paragraph_mappings", fake_gen)

    t = Transcript(episode_id="ep_x", language="zh", segments=[
        Segment(id=0, start_ms=0, end_ms=1, text_original="姚顺雨讲了")])
    # __new__ 跳过 __init__(无 data_dir/stages); _clean_transcript 必须对此鲁棒
    p = pl.AudioProcessPipeline.__new__(pl.AudioProcessPipeline)
    await pl.AudioProcessPipeline._clean_transcript(p, "ep_x", t)

    assert seq[0] == "harvest"
    assert seq[1][0] == "polish"
    assert seq[1][1] == {"姚顺雨": "姚顺宇"}  # 实体表注入 polish


@pytest.mark.asyncio
async def test_clean_transcript_survives_glossary_failure(monkeypatch):
    """glossary 读取失败时 _clean_transcript 不崩, 仍用空表收割+polish。"""
    from app import pipeline as pl

    async def fake_harvest(text, glossary_variants=None):
        return glossary_variants or {}

    async def fake_polish(self_sp, transcript, progress_cb=None, entity_variants=None, force=False):
        return 0

    async def fake_gen(self_pl, eid, tr):
        return None

    def boom(data_dir=None):
        raise RuntimeError("disk gone")

    monkeypatch.setattr(pl, "harvest_entities", fake_harvest)
    monkeypatch.setattr(pl.SubtitleProcessor, "polish", fake_polish)
    monkeypatch.setattr(pl.AudioProcessPipeline, "_generate_paragraph_mappings", fake_gen)
    monkeypatch.setattr(pl, "get_glossary", boom)

    t = Transcript(episode_id="ep_y", language="zh", segments=[
        Segment(id=0, start_ms=0, end_ms=1, text_original="测试")])
    p = pl.AudioProcessPipeline.__new__(pl.AudioProcessPipeline)
    # 不抛异常即通过
    await pl.AudioProcessPipeline._clean_transcript(p, "ep_y", t)
