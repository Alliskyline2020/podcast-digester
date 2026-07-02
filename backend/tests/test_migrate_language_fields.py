"""
Unit tests for migrate_language_fields tool.

Tests ONLY pure routing/aggregation logic and the dry-run report builder.
The audio probe (detect_source_language / _probe_audio_language) is MOCKED —
unit tests never hit real audio.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.migrations.migrate_language_fields import (
    cjk_ratio,
    route_segment,
    RouteResult,
    aggregate_episode,
    is_ambiguous,
    build_episode_report,
    CJK_RATIO_THRESHOLD,
)


# ============================ cjk_ratio ============================

class TestCjkRatio:
    def test_pure_chinese_is_near_one(self):
        assert cjk_ratio("大家好我是一个中文句子") == pytest.approx(1.0, abs=1e-6)

    def test_pure_english_is_near_zero(self):
        assert cjk_ratio("Hello world, this is English.") == pytest.approx(0.0, abs=1e-6)

    def test_mixed_is_between(self):
        ratio = cjk_ratio("Hello 大家好 world")
        # 3 CJK, 14 non-space chars (Hello=5,space excluded,3 CJK,1 space,world=5
        # + ... ) — just assert it is strictly between 0 and 1.
        assert 0.0 < ratio < 1.0
        assert ratio == pytest.approx(3 / 13, abs=1e-6)

    def test_empty_is_zero(self):
        assert cjk_ratio("") == 0.0

    def test_whitespace_only_is_zero(self):
        assert cjk_ratio("   \t\n  ") == 0.0

    def test_numbers_and_punct_only_is_zero(self):
        assert cjk_ratio("12345... !!!") == 0.0

    def test_none_is_zero(self):
        assert cjk_ratio(None) == 0.0

    def test_does_not_count_punctuation_as_cjk(self):
        # CJK punctuation (、。「」) outside U+4E00–U+9FFF range must NOT count
        assert cjk_ratio("、。「」") == 0.0

    def test_chinese_with_punctuation_ratio(self):
        # 你好，世界 = 4 hanzi + 1 fullwidth comma (non-CJK-range, non-space)
        # -> 4/5 = 0.8
        assert cjk_ratio("你好，世界") == pytest.approx(4 / 5, abs=1e-6)


# ============================ route_segment ============================

class TestRouteSegment:
    def test_both_present_zh_higher(self):
        r = route_segment("大家好这是中文", "Hello this is English")
        assert r.text_zh == "大家好这是中文"
        assert r.text_en == "Hello this is English"

    def test_both_present_en_higher_in_original(self):
        # original is English, translated is Chinese
        r = route_segment("Hello world English text", "你好世界中文文本")
        assert r.text_zh == "你好世界中文文本"
        assert r.text_en == "Hello world English text"

    def test_both_present_equal_ratios_picks_translated_as_zh(self):
        # Equal CJK ratio (both pure Chinese): deterministic — translated -> zh
        r = route_segment("你好世界", "你好中国")
        assert r.text_zh == "你好中国"
        assert r.text_en == "你好世界"

    def test_only_original_zh(self):
        r = route_segment("大家好中文", None)
        assert r.text_zh == "大家好中文"
        assert r.text_en is None

    def test_only_original_en(self):
        r = route_segment("Hello English text", None)
        assert r.text_zh is None
        assert r.text_en == "Hello English text"

    def test_only_translated_zh(self):
        r = route_segment(None, "你好世界中文")
        assert r.text_zh == "你好世界中文"
        assert r.text_en is None

    def test_only_translated_en(self):
        r = route_segment(None, "English text only here")
        assert r.text_zh is None
        assert r.text_en == "English text only here"

    def test_neither_present(self):
        r = route_segment(None, None)
        assert r.text_zh is None
        assert r.text_en is None

    def test_both_empty_strings(self):
        r = route_segment("", "")
        assert r.text_zh is None
        assert r.text_en is None

    def test_original_empty_translated_present(self):
        r = route_segment("", "Hello world")
        assert r.text_zh is None
        assert r.text_en == "Hello world"

    def test_threshold_boundary_single_candidate(self):
        # single candidate with ratio exactly at threshold -> goes to zh (>=)
        # CJK_RATIO_THRESHOLD = 0.3; 3 hanzi + 7 ascii letters -> 3/10 = 0.3
        text = "你好世abcdefg"
        assert cjk_ratio(text) == pytest.approx(CJK_RATIO_THRESHOLD, abs=1e-6)
        r = route_segment(text, None)
        assert r.text_zh == text
        assert r.text_en is None

    def test_below_threshold_single_candidate(self):
        # 2 hanzi + 8 ascii -> 0.2 < 0.3 -> en
        text = "你好abcdefgh"
        assert cjk_ratio(text) < CJK_RATIO_THRESHOLD
        r = route_segment(text, None)
        assert r.text_zh is None
        assert r.text_en == text

    def test_whitespace_only_treated_as_absent(self):
        r = route_segment("   ", "Hello world")
        # original is whitespace -> counts as absent -> only translated
        assert r.text_zh is None
        assert r.text_en == "Hello world"

    def test_never_mutates_inputs(self):
        orig = "你好世界"
        trans = "Hello world"
        route_segment(orig, trans)
        assert orig == "你好世界"
        assert trans == "Hello world"


# ============================ aggregate_episode ============================

class TestAggregateEpisode:
    def _routed_segs(self, pairs):
        return [route_segment(o, t) for o, t in pairs]

    def test_aggregation_counts(self):
        routed = self._routed_segs([
            ("你好世界", "Hello world"),       # both
            ("大家好", None),                  # zh only
            (None, "English only here"),       # en only
            ("", ""),                          # neither
            ("中文文本", "English text"),      # both
        ])
        agg = aggregate_episode(routed)
        assert agg.segments_total == 5
        assert agg.segments_with_both_langs == 2
        assert agg.segments_zh_only == 1
        assert agg.segments_en_only == 1
        assert agg.segments_neither == 1
        assert agg.zh_chars > 0
        assert agg.en_chars > 0

    def test_aggregation_char_totals(self):
        routed = self._routed_segs([
            ("你好世界", "Hello world"),
        ])
        agg = aggregate_episode(routed)
        # zh_chars = len of "你好世界" = 4
        assert agg.zh_chars == 4
        # en_chars = len of "Hello world" = 11
        assert agg.en_chars == 11

    def test_empty_segments(self):
        agg = aggregate_episode([])
        assert agg.segments_total == 0
        assert agg.zh_chars == 0
        assert agg.en_chars == 0
        assert agg.segments_with_both_langs == 0

    def test_majority_zh(self):
        routed = self._routed_segs([
            ("你好世界大家好", None),   # 7 zh chars
            (None, "English"),         # 7 en chars -> tied, then next breaks it
            ("更多中文", None),          # +4 zh
        ])
        agg = aggregate_episode(routed)
        assert agg.majority_lang == "zh"

    def test_majority_en(self):
        routed = self._routed_segs([
            (None, "English one two"),    # 14 en chars
            (None, "More English text"),  # +16
            ("你好", None),               # 2 zh
        ])
        agg = aggregate_episode(routed)
        assert agg.majority_lang == "en"

    def test_majority_none_when_empty(self):
        agg = aggregate_episode([])
        assert agg.majority_lang is None

    def test_majority_none_when_balanced(self):
        routed = self._routed_segs([
            ("你好", "ab"),   # 2 zh, 2 en -> tied
        ])
        agg = aggregate_episode(routed)
        assert agg.majority_lang is None


# ============================ is_ambiguous ============================

class TestIsAmbiguous:
    def test_both_langs_present_and_probe_disagrees_is_ambiguous(self):
        # Substantial bilingual content (minority side well above the
        # is_ambiguous 10-char threshold).
        zh = "你好世界这是一段长度足够的中文文本内容"
        en = "Hello world this is a long enough english text content"
        agg = aggregate_episode([route_segment(zh, en), route_segment(zh, en)])
        # existing label "en", probe "zh", both langs present -> ambiguous
        assert is_ambiguous(
            existing_language="en",
            proposed_language="zh",
            agg=agg,
        ) is True

    def test_both_langs_present_but_probe_agrees_not_ambiguous(self):
        zh = "你好世界这是一段长度足够的中文文本内容"
        en = "Hello world this is a long enough english text content"
        agg = aggregate_episode([route_segment(zh, en)])
        assert is_ambiguous("zh", "zh", agg) is False
        assert is_ambiguous("en", "en", agg) is False

    def test_single_lang_not_ambiguous_even_if_label_differs(self):
        agg = aggregate_episode([
            route_segment("你好世界这是一段长度足够的中文文本内容", None),
            route_segment("大家好这里也是中文内容", None),
        ])
        # only zh present, label en disagrees, but not bilingual -> not ambiguous
        assert is_ambiguous("en", "zh", agg) is False

    def test_probe_fallback_same_label_not_ambiguous(self):
        zh = "你好世界这是一段长度足够的中文文本内容"
        en = "Hello world this is a long enough english text content"
        agg = aggregate_episode([route_segment(zh, en)])
        # proposed == existing (kept_existing fallback) -> not ambiguous
        assert is_ambiguous("en", "en", agg) is False

    def test_existing_none_with_both_langs_is_ambiguous(self):
        zh = "你好世界这是一段长度足够的中文文本内容"
        en = "Hello world this is a long enough english text content"
        agg = aggregate_episode([route_segment(zh, en)])
        # no existing label, probe says zh, both present -> ambiguous (needs review)
        assert is_ambiguous(None, "zh", agg) is True

    def test_trace_minority_below_threshold_not_ambiguous(self):
        # Bilingual but minority side < 10 chars -> not loud-ambiguous.
        agg = aggregate_episode([route_segment("你好", "Hello world long english text")])
        assert is_ambiguous("en", "zh", agg) is False


# ============================ build_episode_report (dry-run) ============================

class TestBuildEpisodeReport:
    def test_report_structure_audio_probe(self):
        zh = "你好世界这是一段长度足够的中文文本内容"
        en = "Hello world this is a long enough english text content"
        segments = [
            {"id": 0, "text_original": zh, "text_translated": en},
            {"id": 1, "text_original": "大家好", "text_translated": None},
        ]
        probe_fn = AsyncMock(return_value="zh")  # proposed language via probe
        report = build_episode_report(
            ep_id="ep_test1",
            in_db=True,
            is_orphan=False,
            current_db_language="en",
            transcript_language="en",
            segments=segments,
            audio_path=Path("/fake/audio.m4a"),
            probe_fn=probe_fn,
        )
        assert report["ep_id"] == "ep_test1"
        assert report["in_db"] is True
        assert report["is_orphan"] is False
        assert report["current_language_db"] == "en"
        assert report["current_language_transcript"] == "en"
        assert report["proposed_language"] == "zh"
        assert report["language_method"] == "audio_probe"
        assert report["segments_total"] == 2
        assert report["segments_with_both_langs"] == 1
        assert report["segments_zh_only"] == 1
        assert report["segments_en_only"] == 0
        assert report["zh_chars"] > 0
        assert report["en_chars"] > 0
        assert "sample" in report
        assert report["ambiguous"] is True  # both langs + en->zh disagreement

    def test_report_falls_back_to_existing_when_probe_returns_none(self):
        segments = [{"id": 0, "text_original": "Hello", "text_translated": None}]
        probe_fn = AsyncMock(return_value=None)  # probe unavailable
        report = build_episode_report(
            ep_id="ep_test2",
            in_db=True,
            is_orphan=False,
            current_db_language="en",
            transcript_language="en",
            segments=segments,
            audio_path=Path("/fake/audio.m4a"),
            probe_fn=probe_fn,
        )
        assert report["proposed_language"] == "en"
        assert report["language_method"] == "kept_existing"
        assert report["ambiguous"] is False
        assert report["probe_fell_back"] is True

    def test_report_falls_back_when_probe_raises(self):
        segments = [{"id": 0, "text_original": "Hello", "text_translated": None}]

        async def raising_probe(path):
            raise RuntimeError("ASR unavailable")

        report = build_episode_report(
            ep_id="ep_test3",
            in_db=True,
            is_orphan=False,
            current_db_language="en",
            transcript_language="en",
            segments=segments,
            audio_path=Path("/fake/audio.m4a"),
            probe_fn=raising_probe,
        )
        assert report["proposed_language"] == "en"
        assert report["language_method"] == "kept_existing"
        assert report["probe_fell_back"] is True

    def test_report_no_audio_path_keeps_existing(self):
        segments = [{"id": 0, "text_original": "你好", "text_translated": None}]
        probe_fn = AsyncMock(return_value="zh")
        report = build_episode_report(
            ep_id="ep_test4",
            in_db=True,
            is_orphan=False,
            current_db_language="zh",
            transcript_language="zh",
            segments=segments,
            audio_path=None,  # no audio
            probe_fn=probe_fn,
        )
        # no audio -> probe can't run -> kept_existing
        assert report["language_method"] == "kept_existing"
        assert report["proposed_language"] == "zh"
        probe_fn.assert_not_called()

    def test_report_orphan_flag(self):
        segments = [{"id": 0, "text_original": "Hello", "text_translated": None}]
        probe_fn = AsyncMock(return_value="en")
        report = build_episode_report(
            ep_id="ep_orphan",
            in_db=False,
            is_orphan=True,
            current_db_language=None,
            transcript_language="en",
            segments=segments,
            audio_path=Path("/fake/audio.m4a"),
            probe_fn=probe_fn,
        )
        assert report["is_orphan"] is True
        assert report["in_db"] is False

    def test_report_sample_truncation(self):
        long_zh = "中" * 100
        long_en = "E" * 100
        segments = [{"id": 0, "text_original": long_zh, "text_translated": long_en}]
        probe_fn = AsyncMock(return_value="zh")
        report = build_episode_report(
            ep_id="ep_test",
            in_db=True,
            is_orphan=False,
            current_db_language="zh",
            transcript_language="zh",
            segments=segments,
            audio_path=Path("/fake/audio.m4a"),
            probe_fn=probe_fn,
        )
        sample = report["sample"]
        assert len(sample["text_original"]) == 40
        assert len(sample["text_translated"]) == 40
        assert len(sample["text_zh"]) == 40
        assert len(sample["text_en"]) == 40

    def test_report_empty_segments_handled(self):
        probe_fn = AsyncMock(return_value="en")
        report = build_episode_report(
            ep_id="ep_empty",
            in_db=True,
            is_orphan=False,
            current_db_language="en",
            transcript_language="en",
            segments=[],
            audio_path=Path("/fake/audio.m4a"),
            probe_fn=probe_fn,
        )
        assert report["segments_total"] == 0
        assert report["zh_chars"] == 0
        assert report["en_chars"] == 0
        assert report["ambiguous"] is False
