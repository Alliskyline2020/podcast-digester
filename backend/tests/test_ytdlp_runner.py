"""
Characterization tests for merge_bilingual (Phase 3: source-driven behavior).

These tests lock the NEW CORRECT behavior of the bilingual CC merge:
- The audio's detected source language (passed as `source_lang`) drives which
  text becomes the source of truth (`text_original`) and populates the new
  `text_zh` / `text_en` fields.
- When source_lang == "zh": timestamps/ids from ZH, ZH is source, EN is translation.
- When source_lang == "en": timestamps/ids from EN, EN is source, ZH is translation.

These supersede the Phase 0 characterization tests, which locked the OLD buggy
behavior (English was hardcoded as text_original regardless of source language).
"""
import asyncio
import pytest
from app.models import Segment, Transcript
from app.sources.ytdlp_runner import merge_bilingual, _pick_source_and_merge


def _zh(segments):
    return Transcript(episode_id="test_ep", language="zh", segments=segments)


def _en(segments):
    return Transcript(episode_id="test_ep", language="en", segments=segments)


class TestMergeBilingualZhSource:
    """source_lang="zh": ZH dictates timeline + is the source of truth."""

    def test_exact_timestamp_match(self):
        zh = _zh([
            Segment(id=0, start_ms=0, end_ms=5000, text_original="你好世界"),
            Segment(id=1, start_ms=5000, end_ms=10000, text_original="这是测试"),
        ])
        en = _en([
            Segment(id=0, start_ms=0, end_ms=5000, text_original="Hello world"),
            Segment(id=1, start_ms=5000, end_ms=10000, text_original="This is a test"),
        ])

        result = merge_bilingual(zh, en, "zh")

        assert len(result.segments) == 2
        assert result.language == "zh"
        # First segment
        seg = result.segments[0]
        assert seg.id == 0
        assert seg.start_ms == 0
        assert seg.end_ms == 5000
        assert seg.text_zh == "你好世界"
        assert seg.text_en == "Hello world"
        assert seg.text_original == "你好世界"  # source!
        assert seg.text_translated == "Hello world"  # other
        # Second segment
        seg = result.segments[1]
        assert seg.text_zh == "这是测试"
        assert seg.text_en == "This is a test"
        assert seg.text_original == "这是测试"
        assert seg.text_translated == "This is a test"

    def test_fuzzy_timestamp_match(self):
        zh = _zh([
            Segment(id=0, start_ms=1000, end_ms=6000, text_original="你好"),
            Segment(id=1, start_ms=5000, end_ms=10000, text_original="世界"),
        ])
        en = _en([
            Segment(id=0, start_ms=0, end_ms=5000, text_original="Hello"),
            Segment(id=1, start_ms=4000, end_ms=9000, text_original="World"),
        ])

        result = merge_bilingual(zh, en, "zh")

        assert len(result.segments) == 2
        assert result.segments[0].text_zh == "你好"
        assert result.segments[0].text_en == "Hello"
        assert result.segments[0].text_original == "你好"
        assert result.segments[0].text_translated == "Hello"
        assert result.segments[1].text_zh == "世界"
        assert result.segments[1].text_en == "World"
        assert result.segments[1].text_original == "世界"
        assert result.segments[1].text_translated == "World"

    def test_fuzzy_match_threshold_exactly_3000ms(self):
        zh = _zh([
            Segment(id=0, start_ms=3000, end_ms=8000, text_original="三秒内"),
            Segment(id=1, start_ms=3001, end_ms=8001, text_original="超过三秒"),
        ])
        en = _en([
            Segment(id=0, start_ms=0, end_ms=5000, text_original="Within"),
            Segment(id=1, start_ms=10000, end_ms=15000, text_original="Beyond"),
        ])

        result = merge_bilingual(zh, en, "zh")

        # 3000ms diff matches
        assert result.segments[0].text_zh == "三秒内"
        assert result.segments[0].text_en == "Within"
        # 3001ms diff: no match -> en empty
        assert result.segments[1].text_zh == "超过三秒"
        assert result.segments[1].text_en == ""
        assert result.segments[1].text_original == "超过三秒"
        assert result.segments[1].text_translated == ""

    def test_no_match_within_tolerance(self):
        zh = _zh([
            Segment(id=0, start_ms=0, end_ms=5000, text_original="第一句"),
            Segment(id=1, start_ms=10000, end_ms=15000, text_original="第二句"),
        ])
        en = _en([
            Segment(id=0, start_ms=5000, end_ms=10000, text_original="Separated"),
        ])

        result = merge_bilingual(zh, en, "zh")

        assert len(result.segments) == 2
        for seg in result.segments:
            assert seg.text_en == ""  # no match
            assert seg.text_translated == ""
        assert result.segments[0].text_zh == "第一句"
        assert result.segments[0].text_original == "第一句"
        assert result.segments[1].text_zh == "第二句"

    def test_metadata_and_ids_from_zh(self):
        zh = _zh([
            Segment(id=10, start_ms=0, end_ms=5000, text_original="中文一"),
            Segment(id=11, start_ms=5000, end_ms=10000, text_original="中文二"),
        ])
        en = _en([
            Segment(id=0, start_ms=0, end_ms=5000, text_original="English one"),
            Segment(id=1, start_ms=5000, end_ms=10000, text_original="English two"),
        ])

        result = merge_bilingual(zh, en, "zh")

        assert result.episode_id == ""
        assert result.language == "zh"
        assert result.segments[0].id == 10
        assert result.segments[0].start_ms == 0
        assert result.segments[0].end_ms == 5000
        assert result.segments[1].id == 11
        assert result.segments[1].start_ms == 5000
        assert result.segments[1].end_ms == 10000

    def test_empty_english_transcript(self):
        zh = _zh([
            Segment(id=0, start_ms=0, end_ms=5000, text_original="你好"),
            Segment(id=1, start_ms=5000, end_ms=10000, text_original="世界"),
        ])
        en = _en([])

        result = merge_bilingual(zh, en, "zh")

        assert len(result.segments) == 2
        for seg in result.segments:
            assert seg.text_en == ""
            assert seg.text_translated == ""
        assert result.segments[0].text_zh == "你好"
        assert result.segments[0].text_original == "你好"

    def test_empty_chinese_transcript(self):
        zh = _zh([])
        en = _en([Segment(id=0, start_ms=0, end_ms=5000, text_original="Hello")])

        result = merge_bilingual(zh, en, "zh")

        assert len(result.segments) == 0
        assert result.episode_id == ""
        assert result.language == "zh"

    def test_first_match_within_tolerance_wins(self):
        zh = _zh([Segment(id=0, start_ms=2000, end_ms=7000, text_original="你好")])
        en = _en([
            Segment(id=0, start_ms=0, end_ms=5000, text_original="First"),
            Segment(id=1, start_ms=1000, end_ms=6000, text_original="Second"),
            Segment(id=2, start_ms=3000, end_ms=8000, text_original="Third"),
        ])

        result = merge_bilingual(zh, en, "zh")

        assert len(result.segments) == 1
        assert result.segments[0].text_en == "First"
        assert result.segments[0].text_zh == "你好"


class TestMergeBilingualEnSource:
    """source_lang="en": EN dictates timeline + is the source of truth."""

    def test_exact_timestamp_match(self):
        zh = _zh([
            Segment(id=0, start_ms=0, end_ms=5000, text_original="你好世界"),
            Segment(id=1, start_ms=5000, end_ms=10000, text_original="这是测试"),
        ])
        en = _en([
            Segment(id=0, start_ms=0, end_ms=5000, text_original="Hello world"),
            Segment(id=1, start_ms=5000, end_ms=10000, text_original="This is a test"),
        ])

        result = merge_bilingual(zh, en, "en")

        assert len(result.segments) == 2
        assert result.language == "en"
        # IDs/timestamps come from EN now
        assert result.segments[0].id == 0
        assert result.segments[0].start_ms == 0
        assert result.segments[0].end_ms == 5000
        # Field assignments
        seg = result.segments[0]
        assert seg.text_en == "Hello world"
        assert seg.text_zh == "你好世界"
        assert seg.text_original == "Hello world"  # source!
        assert seg.text_translated == "你好世界"  # other
        seg = result.segments[1]
        assert seg.text_en == "This is a test"
        assert seg.text_zh == "这是测试"
        assert seg.text_original == "This is a test"
        assert seg.text_translated == "这是测试"

    def test_ids_and_timestamps_from_en(self):
        zh = _zh([
            Segment(id=10, start_ms=0, end_ms=5000, text_original="中文一"),
            Segment(id=11, start_ms=5000, end_ms=10000, text_original="中文二"),
        ])
        en = _en([
            Segment(id=0, start_ms=100, end_ms=5100, text_original="English one"),
            Segment(id=1, start_ms=5000, end_ms=10000, text_original="English two"),
        ])

        result = merge_bilingual(zh, en, "en")

        # EN drives the timeline
        assert result.segments[0].id == 0
        assert result.segments[0].start_ms == 100
        assert result.segments[0].end_ms == 5100
        assert result.segments[1].id == 1
        assert result.language == "en"

    def test_no_zh_match(self):
        en = _en([
            Segment(id=0, start_ms=0, end_ms=5000, text_original="Hello"),
            Segment(id=1, start_ms=10000, end_ms=15000, text_original="World"),
        ])
        zh = _zh([Segment(id=0, start_ms=5000, end_ms=10000, text_original="中间")])

        result = merge_bilingual(zh, en, "en")

        assert len(result.segments) == 2
        for seg in result.segments:
            assert seg.text_zh == ""
            assert seg.text_translated == ""
        assert result.segments[0].text_en == "Hello"
        assert result.segments[0].text_original == "Hello"


class TestPickSourceAndMerge:
    """_pick_source_and_merge: detection drives the merge source_lang."""

    def _zh(self):
        return _zh([Segment(id=0, start_ms=0, end_ms=5000, text_original="你好")])

    def _en(self):
        return _en([Segment(id=0, start_ms=0, end_ms=5000, text_original="Hello")])

    def test_manual_cc_zh_resolves_zh_source(self):
        """info_json with manual zh subtitle -> source_lang="zh" -> ZH is source."""
        info_json = {"subtitles": {"zh-Hans": [{"ext": "vtt"}]}}

        result = asyncio.run(_pick_source_and_merge(self._zh(), self._en(), info_json))

        assert result.language == "zh"
        assert result.segments[0].text_original == "你好"
        assert result.segments[0].text_zh == "你好"
        assert result.segments[0].text_en == "Hello"
        assert result.segments[0].text_translated == "Hello"

    def test_manual_cc_en_resolves_en_source(self):
        """info_json with manual en subtitle -> source_lang="en" -> EN is source."""
        info_json = {"subtitles": {"en": [{"ext": "vtt"}]}}

        result = asyncio.run(_pick_source_and_merge(self._zh(), self._en(), info_json))

        assert result.language == "en"
        assert result.segments[0].text_original == "Hello"
        assert result.segments[0].text_en == "Hello"
        assert result.segments[0].text_zh == "你好"
        assert result.segments[0].text_translated == "你好"

    def test_none_info_json_defaults_to_en(self):
        """No info_json -> cascade falls back to default "en"."""
        result = asyncio.run(_pick_source_and_merge(self._zh(), self._en(), None))

        assert result.language == "en"
        assert result.segments[0].text_original == "Hello"

    def test_metadata_level_resolves_en(self):
        """No manual CC, but metadata language=en -> source_lang="en"."""
        info_json = {"language": "en-US"}

        result = asyncio.run(_pick_source_and_merge(self._zh(), self._en(), info_json))

        assert result.language == "en"
        assert result.segments[0].text_original == "Hello"


class TestFailFastNoSubtitles:
    """无字幕视频应在 CC 抓取链入口 fail-fast, 直接回退 ASR。

    背景: ep_1783401350118 (XEhf371Aeso) 实测 'has no subtitles' + 'has no
    automatic captions', 但 fetch_youtube_subtitles 仍逐条策略重试 (每条 ~4min
    超时), 烧 ~30-45min 才回退 ASR。应在入口用 --list-subs (~10s) 判定存在性。
    """

    def test_signal_false_when_manual_and_auto_both_absent(self):
        """XEhf371Aeso 实测输出 → 明确无字幕, signal=False (应 fail-fast)。"""
        from app.sources.ytdlp_runner import _has_subtitles_signal
        output = (
            "[youtube] XEhf371Aeso: Downloading webpage\n"
            "[youtube] XEhf371Aeso: Downloading android vr player API JSON\n"
            "XEhf371Aeso has no automatic captions\n"
            "XEhf371Aeso has no subtitles\n"
        )
        assert _has_subtitles_signal(output) is False

    def test_signal_true_when_subs_listed(self):
        """有字幕清单 → signal=True (继续策略链)。"""
        from app.sources.ytdlp_runner import _has_subtitles_signal
        output = (
            "Available subtitles for XEhf371Aeso:\n"
            "Language formats\n"
            "en       vtt, ttml\n"
            "zh-Hans  vtt\n"
        )
        assert _has_subtitles_signal(output) is True

    def test_signal_conservative_when_only_one_absent(self):
        """只有 'no subtitles' 但没提 auto captions (或反之) → 不确定, 保守 True。"""
        from app.sources.ytdlp_runner import _has_subtitles_signal
        assert _has_subtitles_signal("XEhf371Aeso has no subtitles\n") is True
        assert _has_subtitles_signal("XEhf371Aeso has no automatic captions\n") is True

    def test_signal_conservative_on_empty_output(self):
        """空输出 → 不确定, 保守 True (不阻断)。"""
        from app.sources.ytdlp_runner import _has_subtitles_signal
        assert _has_subtitles_signal("") is True

    def test_fetch_short_circuits_when_probe_says_no_subtitles(self, monkeypatch):
        """探测返回 '无字幕' 时, fetch_youtube_subtitles 立即返回 None,
        且绝不进入策略链 (_try_subtitle_fetch 零调用)。

        用 call-counter 而非异常: fetch 的 except 会吞掉 _try_subtitle_fetch
        抛出的异常 → 抛异常的 mock 会让测试假绿。
        """
        import app.sources.ytdlp_runner as Y

        async def fake_probe(url, cookies_txt=None):
            return False

        strategy_calls = []

        async def fake_try(*args, **kwargs):
            strategy_calls.append(1)
            return False, None, "no_valid_subtitle"

        monkeypatch.setattr(Y, "_video_has_any_subtitles", fake_probe)
        monkeypatch.setattr(Y, "_try_subtitle_fetch", fake_try)

        result = asyncio.run(
            Y.fetch_youtube_subtitles("https://www.youtube.com/watch?v=noneCC1")
        )

        assert result is None, "无字幕应直接返回 None 回退 ASR"
        assert strategy_calls == [], "fail-fast 下不应进入任何 CC 策略"

    def test_probe_retries_on_transient_timeout(self, monkeypatch):
        """probe 首次因瞬时限流超时, 重试拿到明确 '无字幕' → 返回 False。

        背景: ep_1783401350118 首跑时 probe 在 YouTube 限流下 40s 超时, 单次失败
        → 保守 True → 退回 30-45min grind。数分钟后复测仅 3.7s 成功 → 证明是瞬态。
        应重试而非一次失败就放弃。
        """
        import asyncio as _aio
        import app.sources.ytdlp_runner as Y

        calls = {"n": 0}

        class _FakeProc:
            def __init__(self, comm):
                self._comm = comm

            async def communicate(self):
                if isinstance(self._comm, BaseException):
                    raise self._comm
                return self._comm

        async def fake_exec(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return _FakeProc(_aio.TimeoutError())  # 首次瞬时限流超时
            return _FakeProc(
                (b"X has no automatic captions\nX has no subtitles", b"")
            )

        async def fake_sleep(_n):
            return None

        monkeypatch.setattr(_aio, "create_subprocess_exec", fake_exec)
        monkeypatch.setattr(_aio, "sleep", fake_sleep)

        result = asyncio.run(Y._video_has_any_subtitles("https://x", None))
        assert result is False, "重试后应拿到明确 '无字幕' 结论 (False), 不保守 True"
        assert calls["n"] >= 2, "首次超时应触发重试"

    def test_probe_conservative_when_all_attempts_timeout(self, monkeypatch):
        """全部重试均超时 → 仍保守返回 True (宁可 grind 也不误杀有字幕视频)。"""
        import asyncio as _aio
        import app.sources.ytdlp_runner as Y

        class _FakeProc:
            async def communicate(self):
                raise _aio.TimeoutError()

        async def fake_exec(*args, **kwargs):
            return _FakeProc()

        async def fake_sleep(_n):
            return None

        monkeypatch.setattr(_aio, "create_subprocess_exec", fake_exec)
        monkeypatch.setattr(_aio, "sleep", fake_sleep)

        result = asyncio.run(Y._video_has_any_subtitles("https://x", None))
        assert result is True, "全部重试超时 → 保守放行 True"
