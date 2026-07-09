"""_resume_internal 必须产出与 _process_internal 一致的完整产物。

回归背景：resume 路径 (pipeline.py `_resume_internal`) 与全量路径
(`_process_internal`) 在收尾阶段长期分叉，导致**任何走 resume 端点的 episode
都缺 highlight + product_insights**：

1. resume 完全没有 product_insights 阶段（全量 332-340 + DB 368-370）。
2. resume 的 highlight 阶段算出结果后既不写 highlight.json checkpoint，
   save_episode_bundle 又用 `intermediate.get('highlight')`——而
   `_load_intermediate_results` 根本不加载 highlight，所以恒为 None；
   也不写 HighlightRepository。
3. resume 的 save 阶段漏写四个派生数据 DB repo。

现场证据：ep_1783401350118 经 resume 端点处理后 status=ready，但磁盘上
highlight.json / product_insights.json 双双缺失，API 返回里两者为 None。
"""
import json

import pytest

from app.models import Segment, Transcript
from app.pipeline import AudioProcessPipeline


class _FakeModel:
    """带 model_dump() 的假模型，替代 HighlightCard / ProductInsights。
    避免 LLM 调用 + 不必构造每个 enum 字段。"""

    def __init__(self, payload):
        self._payload = dict(payload)

    def model_dump(self):
        return dict(self._payload)


def _transcript():
    segs = [
        Segment(id=0, start_ms=0, end_ms=60000, text_original="第一段"),
        Segment(id=1, start_ms=60000, end_ms=120000, text_original="第二段"),
    ]
    # language=zh → 跳过 translate 阶段，聚焦 highlight/product_insights
    return Transcript(episode_id="ep_resume", language="zh", segments=segs)


def _patch_resume_env(monkeypatch, *, highlight_return, capture):
    """把 resume 路径涉及的外部依赖全部替换成可观测的桩。"""

    # 输入校验：原样放行
    monkeypatch.setattr("app.utils.validation.validate_raw_input", lambda x: x)

    # 任务/节目仓储
    async def fake_job_get(episode_id):
        return {"episode_id": episode_id}

    async def fake_job_create(episode_id):
        return None

    async def fake_update_stages(episode_id, stages, current_stage):
        return None

    async def fake_episode_get(episode_id):
        return {"id": episode_id, "title": "测试标题"}

    monkeypatch.setattr("app.pipeline.IngestJobRepository.get_by_id", fake_job_get)
    monkeypatch.setattr("app.pipeline.IngestJobRepository.create", fake_job_create)
    monkeypatch.setattr("app.pipeline.IngestJobRepository.update_stages", fake_update_stages)
    monkeypatch.setattr("app.pipeline.EpisodeRepository.get_by_id", fake_episode_get)

    # LLM 阶段
    async def fake_extract_highlights(title, duration_min, chapters, summaries, transcript, progress_cb=None):
        capture["extract_highlights"] = {
            "title": title, "duration_min": duration_min,
            "chapters": chapters, "summaries": summaries,
        }
        return highlight_return

    async def fake_product_insights(episode_id, data_dir, progress_cb=None):
        capture["run_product_insights_stage"] = {"episode_id": episode_id}
        return _FakeModel({"product": {"items": []}})

    monkeypatch.setattr("app.pipeline.extract_highlights", fake_extract_highlights)
    monkeypatch.setattr("app.pipeline.run_product_insights_stage", fake_product_insights)

    # save_episode_bundle：只记录入参，不落盘也不翻状态
    def fake_save(episode_id, data_dir, transcript=None, outline=None, summaries=None, highlight=None):
        capture["save"] = {
            "episode_id": episode_id,
            "transcript": transcript,
            "outline": outline,
            "summaries": summaries,
            "highlight": highlight,
        }

    monkeypatch.setattr("app.pipeline.save_episode_bundle", fake_save)

    # 四个派生数据 repo 的 .set
    for name in ("OutlineRepository", "SummariesRepository",
                 "HighlightRepository", "ProductInsightsRepository"):
        async def fake_set(episode_id, data, _name=name):
            capture.setdefault("repo_set", {})[_name] = data
            return True

        monkeypatch.setattr(f"app.repositories.{name}.set", fake_set)


@pytest.mark.unit
async def test_resume_writes_highlight_runs_product_insights_and_saves(
    monkeypatch, temp_data_dir
):
    """existing={transcript,outline,summaries:True, highlight:False} —— 正是
    ep_1783401350118 命中的场景。resume 必须补齐 highlight + product_insights。"""
    highlight_model = _FakeModel({"tldr_zh": "测试亮点"})
    capture: dict = {}
    _patch_resume_env(monkeypatch, highlight_return=highlight_model, capture=capture)

    pipe = AudioProcessPipeline(temp_data_dir)
    existing = {"transcript": True, "outline": True, "summaries": True, "highlight": False}
    intermediate = {
        "transcript": _transcript(),
        "chapters": [{"index": 0, "title_zh": "第一章", "start_segment_id": 0,
                      "end_segment_id": 1, "start_ms": 0, "end_ms": 120000}],
        "summaries": [{"title_zh": "第一章", "summary": "概要"}],
    }

    await pipe._resume_internal(
        "ep_resume", "https://example.com/x", lambda *a: None, existing, intermediate
    )

    # 1. highlight 阶段跑过
    assert "extract_highlights" in capture, "highlight 阶段未执行"

    # 2. highlight.json checkpoint 落盘（新增的 _checkpoint_json）
    highlight_file = temp_data_dir / "media" / "ep_resume" / "highlight.json"
    assert highlight_file.exists(), "highlight.json 未写盘——resume 路径丢了亮点卡"
    assert json.loads(highlight_file.read_text())["tldr_zh"] == "测试亮点"

    # 3. product_insights 阶段跑过（resume 路径此前完全没有这一阶段）
    assert "run_product_insights_stage" in capture, "product_insights 阶段未执行"

    # 4. save 拿到的是算出的 highlight，不是 None
    assert capture["save"]["highlight"] is highlight_model, (
        "save_episode_bundle 收到 highlight=None——旧 bug：用了 intermediate.get('highlight')"
    )

    # 5. 两个此前缺失的 DB repo 被写入
    assert "HighlightRepository" in capture.get("repo_set", {}), "HighlightRepository 未写"
    assert "ProductInsightsRepository" in capture.get("repo_set", {}), (
        "ProductInsightsRepository 未写"
    )


@pytest.mark.unit
async def test_resume_reuses_existing_highlight_but_still_runs_product_insights(
    monkeypatch, temp_data_dir
):
    """existing.highlight=True（highlight.json 已存在）：resume 应复用而非重算，
    但仍要跑 product_insights 并把已存在的 highlight 交给 save。"""
    # 预置 highlight.json，模拟上一轮已完成 highlight 的 checkpoint。
    # 写全 HighlightCard 必填字段，与 extract_highlights 真实落盘的形态一致。
    media_dir = temp_data_dir / "media" / "ep_reuse"
    media_dir.mkdir(parents=True, exist_ok=True)
    (media_dir / "highlight.json").write_text(json.dumps({
        "tldr_zh": "已存在的亮点",
        "worth_listening_verdict": "skim_outline",
        "verdict_confidence": "high",
        "target_audience_zh": "测试受众",
    }, ensure_ascii=False))

    capture: dict = {}
    _patch_resume_env(
        monkeypatch,
        highlight_return=_FakeModel({"tldr_zh": "不应被使用"}),
        capture=capture,
    )

    pipe = AudioProcessPipeline(temp_data_dir)
    existing = {"transcript": True, "outline": True, "summaries": True, "highlight": True}
    intermediate = {
        "transcript": _transcript(),
        "chapters": [{"index": 0, "title_zh": "第一章", "start_segment_id": 0,
                      "end_segment_id": 1, "start_ms": 0, "end_ms": 120000}],
        "summaries": [{"title_zh": "第一章", "summary": "概要"}],
    }

    await pipe._resume_internal(
        "ep_reuse", "https://example.com/x", lambda *a: None, existing, intermediate
    )

    # highlight 未重算
    assert "extract_highlights" not in capture, "已存在 highlight 不应重算"

    # product_insights 仍跑（resume 此前即便 highlight 在也从不跑这一阶段）
    assert "run_product_insights_stage" in capture

    # save 收到的是从 checkpoint 复用的 highlight，不是 None
    assert capture["save"]["highlight"] is not None, (
        "复用分支没加载 highlight，save 收到 None"
    )
    assert capture["save"]["highlight"].model_dump()["tldr_zh"] == "已存在的亮点"
