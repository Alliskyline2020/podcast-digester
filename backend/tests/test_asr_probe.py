"""
Unit tests for the robust multi-window audio language probe (task 6).

These tests MOCK the ASR (no real audio, no real Apple Speech). They lock the
per-window verdict logic and the majority-vote aggregation of
`_probe_audio_language` / `probe_audio_language_detailed`, and assert that
`AppleASR.transcribe` derives `Transcript.language` from the passed locale
argument (NOT from re-inspecting output text).

Real-audio integration check (the two confirmed-zh episodes) is run out-of-band
(see task-6-report.md); it is too host-specific/slow for the unit suite.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.asr_afm3 import (
    AppleASR,
    _probe_audio_language,
    _probe_window,
    probe_audio_language_detailed,
)
from app.models import Segment


# ---------------------------------------------------------------------------
# Helpers — build fake ASR transcripts with controlled character profiles.
# ---------------------------------------------------------------------------

ASCII_TEXT = (
    "The quick brown fox jumps over the lazy dog. "
    * 10  # ~430 ASCII letters
)
CJK_TEXT = (
    "今天我们来聊一聊人工智能领域的最新进展和未来的发展方向。"
    * 10  # ~330 CJK chars
)


def _segs(text: str, n: int = 5) -> list[Segment]:
    """Build n segments splitting text into roughly equal chunks."""
    if n <= 0:
        return []
    chunk_len = max(1, len(text) // n)
    out: list[Segment] = []
    for i in range(n):
        chunk = text[i * chunk_len : (i + 1) * chunk_len]
        if not chunk:
            chunk = text[:chunk_len] or "x"
        out.append(
            Segment(id=i, start_ms=0, end_ms=0, text_original=chunk)
        )
    return out


def _ascii_segments(n: int = 5) -> list[Segment]:
    return _segs(ASCII_TEXT, n)


def _cjk_segments(n: int = 5) -> list[Segment]:
    return _segs(CJK_TEXT, n)


def _empty_segments() -> list[Segment]:
    return [Segment(id=0, start_ms=0, end_ms=0, text_original=" ")]


def _read_start(path) -> float:
    """Read the START=<seconds> stamp our fake ffmpeg wrote into the wav."""
    try:
        txt = Path(path).read_text()
        for ln in txt.splitlines():
            if ln.startswith("START="):
                return float(ln.split("=", 1)[1])
    except Exception:
        pass
    return 0.0


def _build_asr(en_us_segs, zh_cn_segs, *, call_log: list | None = None):
    """Build a fake asr whose transcribe(path, language=loc) returns a
    Transcript whose segments depend on the locale.

    `en_us_segs`/`zh_cn_segs` may be a list, or a callable (start_seconds) -> list
    so per-window tests can vary output by start offset (read from the fake wav).
    """
    async def fake_transcribe(audio_path, language="en-US", on_progress=None):
        if call_log is not None:
            call_log.append((str(audio_path), language))
        start = _read_start(audio_path)
        if str(language).startswith("en"):
            segs = en_us_segs(start) if callable(en_us_segs) else en_us_segs
        else:
            segs = zh_cn_segs(start) if callable(zh_cn_segs) else zh_cn_segs
        from app.models import Transcript
        return Transcript(episode_id="", language=language, segments=segs)

    asr = SimpleNamespace()
    asr.transcribe = fake_transcribe
    return asr


@pytest.fixture(autouse=True)
def _no_ffmpeg_extraction(monkeypatch, tmp_path):
    """Replace ffmpeg/ffprobe subprocess with no-ops.

    The fake ffmpeg writes the requested `-ss` start offset (as text) into the
    output wav file, so a cooperating fake asr can vary its output per window
    without any real audio. The fake ffprobe is just a successful empty call
    (duration is monkeypatched per-test via `_probe_duration_seconds`).
    """
    import app.asr_afm3 as mod
    import subprocess

    def fake_run(cmd, *args, **kwargs):
        # cmd is the ffmpeg/ffprobe argv list.
        out = cmd[-1]
        # Find the -ss value so we can stamp it into the wav for the fake asr.
        start = "0"
        if "-ss" in cmd:
            i = cmd.index("-ss")
            if i + 1 < len(cmd):
                start = cmd[i + 1]
        # Only ffmpeg writes a wav file; ffprobe's last arg is the input path.
        if str(out).endswith(".wav"):
            Path(out).write_text(f"START={start}")
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout=b"", stderr=b""
        )

    monkeypatch.setattr(mod.subprocess, "run", fake_run)


# ===========================================================================
# _probe_window verdicts
# ===========================================================================

class TestProbeWindow:
    """Per-window dual-locale verdict with mocked ASR."""

    @pytest.mark.asyncio
    async def test_en_dominant_when_ascii_dominates(self, tmp_path):
        # en-US output has many ascii letters; zh-CN output has very few.
        asr = _build_asr(
            en_us_segs=_ascii_segments(5),
            zh_cn_segs=_segs("ok ok ok", 3),  # ~6 ascii, no cjk
        )
        result = await _probe_window(tmp_path / "w.wav", asr, start=0, length=60)
        assert result["verdict"] == "en"
        assert result["ascii"] > result["cjk"]

    @pytest.mark.asyncio
    async def test_zh_dominant_when_cjk_dominates(self, tmp_path):
        asr = _build_asr(
            en_us_segs=_segs("... , , ...", 3),  # garbage, no ascii letters
            zh_cn_segs=_cjk_segments(5),
        )
        result = await _probe_window(tmp_path / "w.wav", asr, start=0, length=60)
        assert result["verdict"] == "zh"
        assert result["cjk"] > result["ascii"]

    @pytest.mark.asyncio
    async def test_silent_when_both_near_zero(self, tmp_path):
        asr = _build_asr(
            en_us_segs=_empty_segments(),
            zh_cn_segs=_empty_segments(),
        )
        result = await _probe_window(tmp_path / "w.wav", asr, start=0, length=60)
        assert result["verdict"] == "silent"
        assert result["ascii"] == 0
        assert result["cjk"] == 0

    @pytest.mark.asyncio
    async def test_mixed_when_comparable(self, tmp_path):
        # Truly balanced ascii vs cjk: 50 ascii vs 55 cjk (ratio 0.91),
        # neither side dominates by 1.5x.
        balanced = ("abcdefghij 世界你好中文啦请问谢谢" * 5)
        asr = _build_asr(
            en_us_segs=_segs(balanced, 3),
            zh_cn_segs=_segs(balanced, 3),
        )
        result = await _probe_window(tmp_path / "w.wav", asr, start=0, length=60)
        assert result["verdict"] == "mixed"
        # Sanity: the two sides are within 1.5x of each other.
        assert result["ascii"] > 0 and result["cjk"] > 0


# ===========================================================================
# _probe_audio_language / probe_audio_language_detailed majority vote
# ===========================================================================

class TestProbeAudioLanguageMajority:
    """Majority vote over N windows."""

    @pytest.mark.asyncio
    async def test_majority_zh_when_4zh_1en(self, monkeypatch, tmp_path):
        # 4 windows zh-dominant, 1 en-dominant -> zh-CN.
        # Last start for duration=18000, window_count=5 is 17940s; pick the
        # final window (start > 17000) as the en one.
        garbage = "... , , ..."
        en_window_start_threshold = 17000.0

        def en_us_for(start):
            if start > en_window_start_threshold:
                return _ascii_segments(5)
            return _segs(garbage, 3)

        def zh_cn_for(start):
            if start > en_window_start_threshold:
                return _segs(garbage, 3)
            return _cjk_segments(5)

        asr = _build_asr(en_us_segs=en_us_for, zh_cn_segs=zh_cn_for)

        import app.asr_afm3 as mod
        monkeypatch.setattr(
            mod, "_probe_duration_seconds", lambda p: 18000.0
        )

        detailed = await probe_audio_language_detailed(
            tmp_path / "audio.m4a", asr
        )
        assert detailed["language"] == "zh-CN"
        assert detailed["low_confidence"] is False
        verdicts = [w["verdict"] for w in detailed["windows"]]
        assert verdicts.count("zh") >= 4

        # And the str wrapper agrees.
        s = await _probe_audio_language(tmp_path / "audio.m4a", asr)
        assert s == "zh-CN"

    @pytest.mark.asyncio
    async def test_majority_en_when_4en_1zh(self, monkeypatch, tmp_path):
        garbage = "... , , ..."
        zh_window_start_threshold = 17000.0

        def en_us_for(start):
            if start > zh_window_start_threshold:
                return _segs(garbage, 3)
            return _ascii_segments(5)

        def zh_cn_for(start):
            if start > zh_window_start_threshold:
                return _cjk_segments(5)
            return _segs(garbage, 3)

        asr = _build_asr(en_us_segs=en_us_for, zh_cn_segs=zh_cn_for)
        import app.asr_afm3 as mod
        monkeypatch.setattr(
            mod, "_probe_duration_seconds", lambda p: 18000.0
        )

        detailed = await probe_audio_language_detailed(
            tmp_path / "audio.m4a", asr
        )
        assert detailed["language"] == "en-US"
        assert detailed["low_confidence"] is False

    @pytest.mark.asyncio
    async def test_tied_marks_low_confidence(self, monkeypatch, tmp_path):
        # For duration=18000, window_count=5 the starts are
        # [0, 4485, 8970, 13455, 17940]. Make windows 0 & 2 zh, 1 & 3 en,
        # window 4 (last) silent -> tie.
        garbage = "... , , ..."
        zh_starts = {0.0, 8970.0}
        en_starts = {4485.0, 13455.0}

        def en_us_for(start):
            if start in en_starts:
                return _ascii_segments(5)
            if start in zh_starts:
                return _segs(garbage, 3)
            return _empty_segments()  # last window -> silent

        def zh_cn_for(start):
            if start in zh_starts:
                return _cjk_segments(5)
            if start in en_starts:
                return _segs(garbage, 3)
            return _empty_segments()

        asr = _build_asr(en_us_segs=en_us_for, zh_cn_segs=zh_cn_for)
        import app.asr_afm3 as mod
        monkeypatch.setattr(
            mod, "_probe_duration_seconds", lambda p: 18000.0
        )

        detailed = await probe_audio_language_detailed(
            tmp_path / "audio.m4a", asr
        )
        assert detailed["low_confidence"] is True
        # Tied vote: should fall back to default (en-US).
        assert detailed["language"] == "en-US"

    @pytest.mark.asyncio
    async def test_all_silent_returns_default_low_confidence(
        self, monkeypatch, tmp_path
    ):
        asr = _build_asr(
            en_us_segs=_empty_segments(),
            zh_cn_segs=_empty_segments(),
        )
        import app.asr_afm3 as mod
        monkeypatch.setattr(
            mod, "_probe_duration_seconds", lambda p: 18000.0
        )
        detailed = await probe_audio_language_detailed(
            tmp_path / "audio.m4a", asr
        )
        # No usable windows -> default + low_confidence.
        assert detailed["low_confidence"] is True
        assert detailed["language"] == "en-US"


# ===========================================================================
# transcribe derives language from the LOCALE argument, not output text
# ===========================================================================

class TestTranscribeLanguageFromLocale:
    """The text-override (asr_afm3.py:156-162) must be gone."""

    @pytest.mark.asyncio
    async def test_zh_locale_yields_zh_even_if_output_is_english(self, monkeypatch):
        """Pass language='zh-CN' but output text is pure English ASCII ->
        Transcript.language MUST be 'zh', not re-detected as 'en'."""
        # Patch the bridge subprocess so transcribe returns pure-English text
        # for a zh-CN locale request. This proves we don't re-detect from text.
        import app.asr_afm3 as mod
        from app.models import Transcript

        english_text = (
            '[{"text": "Welcome back to the show today", "start_ms": 0, "end_ms": 1000}, '
            '{"text": "we have a great episode for you", "start_ms": 1000, "end_ms": 2000}]'
        )

        async def fake_create_subprocess_exec(*cmd, **kwargs):
            proc = AsyncMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(
                return_value=(english_text.encode(), b"")
            )
            return proc

        monkeypatch.setattr(mod.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

        # Bypass AppleASR.__init__ host checks.
        asr = AppleASR.__new__(AppleASR)

        transcript = await asr.transcribe(
            Path("/fake/audio.m4a"), language="zh-CN"
        )
        assert transcript.language == "zh", (
            f"expected zh from locale, got {transcript.language!r} "
            "(text-override not removed?)"
        )

    @pytest.mark.asyncio
    async def test_en_locale_yields_en_even_if_output_is_chinese(self, monkeypatch):
        """Symmetric: language='en-US' with pure-CJK output text -> 'en'."""
        import app.asr_afm3 as mod

        chinese_text = (
            '[{"text": "今天我们来聊一聊", "start_ms": 0, "end_ms": 1000}, '
            '{"text": "人工智能的最新进展", "start_ms": 1000, "end_ms": 2000}]'
        )

        async def fake_create_subprocess_exec(*cmd, **kwargs):
            proc = AsyncMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(
                return_value=(chinese_text.encode(), b"")
            )
            return proc

        monkeypatch.setattr(mod.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

        asr = AppleASR.__new__(AppleASR)
        transcript = await asr.transcribe(
            Path("/fake/audio.m4a"), language="en-US"
        )
        assert transcript.language == "en"


# ===========================================================================
# Regression: callers unchanged (str return contract preserved)
# ===========================================================================

class TestBackwardCompatibility:
    """`_probe_audio_language` still returns a str for callers in lang_detect."""

    @pytest.mark.asyncio
    async def test_probe_audio_language_returns_str(self, monkeypatch, tmp_path):
        asr = _build_asr(
            en_us_segs=_ascii_segments(5),
            zh_cn_segs=_cjk_segments(5),
        )
        import app.asr_afm3 as mod
        monkeypatch.setattr(
            mod, "_probe_duration_seconds", lambda p: 18000.0
        )
        result = await _probe_audio_language(tmp_path / "audio.m4a", asr)
        assert isinstance(result, str)
        assert result in ("en-US", "zh-CN")
