"""B 链路测试：episode.description 列 + get_video_description + correct 开关。

覆盖把 YouTube 视频描述接进 DB、供 LLM 字幕纠错当上下文的整条链路：
- migration: init_db 后 episode 表有 description 列（老库 ALTER 补）
- EpisodeRepository.update 能存/读 description（_ALLOWED_UPDATE_FIELDS 含 description）
- config: llm_correct_transcript_enabled 默认关（避免意外对每集跑 ~100s LLM）
- get_video_description: yt-dlp --get-description 抓取 + 失败回退空串（不阻塞 pipeline）
"""
from datetime import datetime

import pytest

from app.database import EpisodeRepository
from app.models import EpisodeStatus


# --- migration: description 列存在 ---


@pytest.mark.unit
@pytest.mark.database
async def test_episode_table_has_description_column(temp_db):
    """init_db 后 episode 表必须有 description 列（老库 ALTER 补）。"""
    async with temp_db.execute("PRAGMA table_info(episode)") as cursor:
        cols = await cursor.fetchall()
    col_names = {col[1] for col in cols}
    assert "description" in col_names


# --- update 白名单含 description ---


@pytest.mark.unit
@pytest.mark.database
async def test_update_persists_description(temp_db):
    """EpisodeRepository.update(description=...) 应持久化并能读回。"""
    await EpisodeRepository.create({
        "id": "ep_desc_1",
        "title": "T",
        "status": EpisodeStatus.PENDING.value,
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    })

    ok = await EpisodeRepository.update(
        "ep_desc_1",
        description="本期聊月之暗面 Kimi K3 与中国大模型十年迁徙",
    )
    assert ok is True

    ep = await EpisodeRepository.get_by_id("ep_desc_1")
    assert ep["description"] == "本期聊月之暗面 Kimi K3 与中国大模型十年迁徙"


# --- config: correct 开关默认关 ---


@pytest.mark.unit
def test_llm_correct_transcript_disabled_by_default(monkeypatch):
    """默认关闭：避免意外对每个 episode 跑 ~100s LLM 纠错（成本/耗时）。"""
    monkeypatch.delenv("PODCAST_DIGESTER_LLM_CORRECT_TRANSCRIPT", raising=False)
    from app.config import Settings

    s = Settings()
    assert s.llm_correct_transcript_enabled is False


@pytest.mark.unit
def test_llm_correct_transcript_env_enables(monkeypatch):
    """env=true 时开关开启。"""
    monkeypatch.setenv("PODCAST_DIGESTER_LLM_CORRECT_TRANSCRIPT", "true")
    from app.config import Settings

    s = Settings()
    assert s.llm_correct_transcript_enabled is True


# --- get_video_description ---


class _FakeCompleted:
    """模拟 subprocess.run 返回的 CompletedProcess。"""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def capture_run(monkeypatch):
    """捕获 subprocess.run 收到的命令。"""
    state = {}

    def fake_run(cmd, **kwargs):
        state["cmd"] = list(cmd)
        state["kwargs"] = kwargs
        return state.get("result", _FakeCompleted(returncode=0, stdout=""))

    monkeypatch.setattr("app.utils.video.subprocess.run", fake_run)
    return state


@pytest.mark.asyncio
async def test_get_video_description_uses_get_description_flag(capture_run, monkeypatch):
    """应调 yt-dlp --get-description 并返回 stdout（去尾换行）。"""
    monkeypatch.setattr("app.utils.video.get_best_browser", lambda: None)
    capture_run["result"] = _FakeCompleted(returncode=0, stdout="本期简介内容\n")

    from app.utils.video import get_video_description

    desc = await get_video_description(
        "https://www.youtube.com/watch?v=abc", platform="youtube"
    )
    assert desc == "本期简介内容"
    assert "--get-description" in capture_run["cmd"]


@pytest.mark.asyncio
async def test_get_video_description_returns_empty_on_failure(capture_run, monkeypatch):
    """yt-dlp 失败时返回空串（不抛异常、不阻塞 pipeline）。"""
    monkeypatch.setattr("app.utils.video.get_best_browser", lambda: None)
    capture_run["result"] = _FakeCompleted(returncode=1, stdout="", stderr="HTTP Error 412")

    from app.utils.video import get_video_description

    desc = await get_video_description(
        "https://www.youtube.com/watch?v=abc", platform="youtube"
    )
    assert desc == ""


# --- pipeline _correct_transcript helper（A 集成）---


def _build_transcript():
    """构造 12 段的 Transcript（>10 才会触发纠错）。段0 含「预知面」待纠。"""
    from app.models import Transcript, Segment

    texts = ["预知面 Kimi K3", "正常段二", "正常段三"] + [f"段{i}" for i in range(3, 12)]
    return Transcript(
        episode_id="ep_corr",
        language="zh",
        segments=[
            Segment(id=i, start_ms=i * 1000, end_ms=i * 1000 + 999, text_original=t)
            for i, t in enumerate(texts)
        ],
    )


@pytest.mark.unit
@pytest.mark.database
async def test_correct_transcript_writes_back_and_passes_context(temp_db, monkeypatch):
    """纠错后写回 text_original；title+description 作为术语表上下文被传入。"""
    from app.models import EpisodeStatus
    from app.pipeline import AudioProcessPipeline

    await EpisodeRepository.create({
        "id": "ep_corr",
        "title": "原始",
        "status": EpisodeStatus.PENDING.value,
        "created_at": datetime.now(),
        "updated_at": datetime.now(),
    })
    await EpisodeRepository.update(
        "ep_corr",
        title="对话叶奇意：月之暗面杨植麟",
        description="本期聊 Kimi K3 与 DeepSeek",
    )

    captured = {}

    async def fake_correct(self, segments, episode_title="", episode_description="", batch_size=50):
        captured["title"] = episode_title
        captured["desc"] = episode_description
        out = []
        for s in segments:
            ns = dict(s)
            if "预知面" in (s.get("text_original") or ""):
                ns["text_original"] = s["text_original"].replace("预知面", "月之暗面")
                ns["text_corrected"] = True
            else:
                ns["text_corrected"] = False
            out.append(ns)
        return out

    monkeypatch.setattr(
        "app.services.llm_subtitle_processor.LLMSubtitleProcessor.correct_transcription",
        fake_correct,
    )

    pipeline = object.__new__(AudioProcessPipeline)  # helper 不依赖 self 状态
    transcript = _build_transcript()
    await pipeline._correct_transcript("ep_corr", transcript)

    # 纠错段写回
    assert transcript.segments[0].text_original == "月之暗面 Kimi K3"
    # 未纠错段保留原文
    assert transcript.segments[1].text_original == "正常段二"
    # title + description 作为上下文传入（B 与 A 的集成点）
    assert captured["title"] == "对话叶奇意：月之暗面杨植麟"
    assert captured["desc"] == "本期聊 Kimi K3 与 DeepSeek"


@pytest.mark.unit
@pytest.mark.database
async def test_correct_transcript_swallows_llm_failure(temp_db, monkeypatch):
    """LLM 异常时不抛、保留 raw ASR（不阻塞 pipeline）。"""
    from app.pipeline import AudioProcessPipeline

    async def boom(*args, **kwargs):
        raise RuntimeError("LLM down")

    monkeypatch.setattr(
        "app.services.llm_subtitle_processor.LLMSubtitleProcessor.correct_transcription",
        boom,
    )

    pipeline = object.__new__(AudioProcessPipeline)
    transcript = _build_transcript()
    original_text = transcript.segments[0].text_original

    await pipeline._correct_transcript("ep_corr", transcript)  # 不应抛

    assert transcript.segments[0].text_original == original_text  # 原文不变
