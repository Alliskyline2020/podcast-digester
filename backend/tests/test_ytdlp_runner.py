"""
Characterization tests for _merge_bilingual_transcripts.

IMPORTANT: These tests lock the CURRENT (buggy) behavior of
_merge_bilingual_transcripts as change-detectors for the language-naming refactor.

Several assertions below intentionally lock the buggy behavior that WILL be updated
in Phase 3 of the refactor:
- English is hardcoded as text_original (the "original" language)
- Chinese is always text_translated
- language="en" is hardcoded in the output Transcript

These tests MUST pass against current code and serve as guards to ensure
behavior changes are explicit during the refactor.
"""
import pytest
from app.models import Segment, Transcript
from app.sources.ytdlp_runner import _merge_bilingual_transcripts


class TestMergeBilingualTranscripts:
    """Characterization tests for bilingual transcript merging.

    Tests lock the CURRENT behavior exactly - they are change-detectors,
    NOT correctness specifications.
    """

    def test_exact_timestamp_match(self):
        """Test exact timestamp match: zh_seg (start_ms,end_ms) == en_seg (start_ms,end_ms).

        Expected CURRENT behavior:
        - English text lands in text_original
        - Chinese text lands in text_translated
        """
        # Arrange
        zh_transcript = Transcript(
            episode_id="test_ep",
            language="zh",
            segments=[
                Segment(id=0, start_ms=0, end_ms=5000, text_original="你好世界"),
                Segment(id=1, start_ms=5000, end_ms=10000, text_original="这是测试"),
            ]
        )
        en_transcript = Transcript(
            episode_id="test_ep",
            language="en",
            segments=[
                Segment(id=0, start_ms=0, end_ms=5000, text_original="Hello world"),
                Segment(id=1, start_ms=5000, end_ms=10000, text_original="This is a test"),
            ]
        )

        # Act
        result = _merge_bilingual_transcripts(zh_transcript, en_transcript)

        # Assert - locks CURRENT buggy behavior
        assert len(result.segments) == 2
        # First segment: exact match
        assert result.segments[0].id == 0
        assert result.segments[0].start_ms == 0
        assert result.segments[0].end_ms == 5000
        assert result.segments[0].text_original == "Hello world"  # EN as "original" (buggy)
        assert result.segments[0].text_translated == "你好世界"  # ZH as "translated"
        # Second segment: exact match
        assert result.segments[1].id == 1
        assert result.segments[1].start_ms == 5000
        assert result.segments[1].end_ms == 10000
        assert result.segments[1].text_original == "This is a test"
        assert result.segments[1].text_translated == "这是测试"

    def test_fuzzy_timestamp_match(self):
        """Test fuzzy match: zh_seg start within 3000ms of en_seg start.

        Expected CURRENT behavior:
        - Still paired with that en text even when timestamps differ slightly
        - Uses first match within 3s tolerance
        """
        # Arrange - timestamps differ but within 3s
        zh_transcript = Transcript(
            episode_id="test_ep",
            language="zh",
            segments=[
                Segment(id=0, start_ms=1000, end_ms=6000, text_original="你好"),
                Segment(id=1, start_ms=5000, end_ms=10000, text_original="世界"),
            ]
        )
        en_transcript = Transcript(
            episode_id="test_ep",
            language="en",
            segments=[
                Segment(id=0, start_ms=0, end_ms=5000, text_original="Hello"),
                Segment(id=1, start_ms=4000, end_ms=9000, text_original="World"),
            ]
        )

        # Act
        result = _merge_bilingual_transcripts(zh_transcript, en_transcript)

        # Assert - locks CURRENT fuzzy matching behavior
        assert len(result.segments) == 2
        # First zh_seg (1000ms) should match en_seg starting at 0ms (1000ms diff <= 3000ms)
        assert result.segments[0].text_original == "Hello"
        assert result.segments[0].text_translated == "你好"
        # Second zh_seg (5000ms) should match en_seg starting at 4000ms (1000ms diff)
        assert result.segments[1].text_original == "World"
        assert result.segments[1].text_translated == "世界"

    def test_fuzzy_match_threshold_exactly_3000ms(self):
        """Test fuzzy match at exactly 3000ms threshold.

        Expected CURRENT behavior:
        - 3000ms diff should match (<= condition)
        - 3001ms diff should not match
        """
        # Arrange
        zh_transcript = Transcript(
            episode_id="test_ep",
            language="zh",
            segments=[
                Segment(id=0, start_ms=3000, end_ms=8000, text_original="三秒内"),
                Segment(id=1, start_ms=3001, end_ms=8001, text_original="超过三秒"),
            ]
        )
        en_transcript = Transcript(
            episode_id="test_ep",
            language="en",
            segments=[
                Segment(id=0, start_ms=0, end_ms=5000, text_original="Within"),
                Segment(id=1, start_ms=10000, end_ms=15000, text_original="Beyond"),
            ]
        )

        # Act
        result = _merge_bilingual_transcripts(zh_transcript, en_transcript)

        # Assert - locks CURRENT 3s threshold behavior
        # First zh at 3000ms matches en at 0ms (diff == 3000ms)
        assert result.segments[0].text_original == "Within"
        assert result.segments[0].text_translated == "三秒内"
        # Second zh at 3001ms has no match (closest en at 0ms is 3001ms away, > 3000ms)
        assert result.segments[1].text_original == ""  # Empty when no match
        assert result.segments[1].text_translated == "超过三秒"

    def test_no_match_within_tolerance(self):
        """Test no match: zh_seg has no en within 3s.

        Expected CURRENT behavior:
        - text_original == "" (empty string, not None)
        - text_translated still contains Chinese text
        """
        # Arrange - timestamps differ by more than 3s
        zh_transcript = Transcript(
            episode_id="test_ep",
            language="zh",
            segments=[
                Segment(id=0, start_ms=0, end_ms=5000, text_original="第一句"),
                Segment(id=1, start_ms=10000, end_ms=15000, text_original="第二句"),
            ]
        )
        en_transcript = Transcript(
            episode_id="test_ep",
            language="en",
            segments=[
                Segment(id=0, start_ms=5000, end_ms=10000, text_original="Separated"),
            ]
        )

        # Act
        result = _merge_bilingual_transcripts(zh_transcript, en_transcript)

        # Assert - locks CURRENT behavior for unmatched segments
        assert len(result.segments) == 2
        # First zh_seg (0ms) to en_seg (5000ms) is 5000ms diff > 3000ms: no match
        assert result.segments[0].text_original == ""  # Empty string when no match
        assert result.segments[0].text_translated == "第一句"
        # Second zh_seg (10000ms) to en_seg (5000ms) is 5000ms diff > 3000ms: no match
        assert result.segments[1].text_original == ""
        assert result.segments[1].text_translated == "第二句"

    def test_output_transcript_metadata(self):
        """Test output Transcript metadata.

        Expected CURRENT behavior:
        - episode_id == "" (empty, not None)
        - language == "en" (hardcoded - THIS IS THE BUG)
        """
        # Arrange
        zh_transcript = Transcript(
            episode_id="any_zh_id",
            language="zh",
            segments=[Segment(id=0, start_ms=0, end_ms=5000, text_original="你好")]
        )
        en_transcript = Transcript(
            episode_id="any_en_id",
            language="en",
            segments=[Segment(id=0, start_ms=0, end_ms=5000, text_original="Hello")]
        )

        # Act
        result = _merge_bilingual_transcripts(zh_transcript, en_transcript)

        # Assert - locks CURRENT buggy metadata behavior
        assert result.episode_id == "", "episode_id should be empty string"
        # BUG: language is hardcoded to "en" regardless of actual source language
        assert result.language == "en", "language hardcoded to 'en' (bug being locked)"

    def test_output_segment_ids_and_timestamps_from_zh(self):
        """Test output Segment ids/timestamps come from ZH transcript.

        Expected CURRENT behavior:
        - Output ids are zh_seg.id
        - Output timestamps are zh_seg.start_ms, zh_seg.end_ms
        """
        # Arrange - different IDs between zh/en
        zh_transcript = Transcript(
            episode_id="test_ep",
            language="zh",
            segments=[
                Segment(id=10, start_ms=0, end_ms=5000, text_original="中文一"),
                Segment(id=11, start_ms=5000, end_ms=10000, text_original="中文二"),
            ]
        )
        en_transcript = Transcript(
            episode_id="test_ep",
            language="en",
            segments=[
                Segment(id=0, start_ms=0, end_ms=5000, text_original="English one"),
                Segment(id=1, start_ms=5000, end_ms=10000, text_original="English two"),
            ]
        )

        # Act
        result = _merge_bilingual_transcripts(zh_transcript, en_transcript)

        # Assert - output carries zh metadata
        assert len(result.segments) == 2
        assert result.segments[0].id == 10, "ID from zh transcript"
        assert result.segments[0].start_ms == 0, "start_ms from zh transcript"
        assert result.segments[0].end_ms == 5000, "end_ms from zh transcript"
        assert result.segments[1].id == 11, "ID from zh transcript"
        assert result.segments[1].start_ms == 5000, "start_ms from zh transcript"
        assert result.segments[1].end_ms == 10000, "end_ms from zh transcript"

    def test_empty_english_transcript(self):
        """Test behavior when English transcript is empty.

        Expected CURRENT behavior:
        - All segments have empty text_original
        - Chinese text still preserved in text_translated
        """
        # Arrange
        zh_transcript = Transcript(
            episode_id="test_ep",
            language="zh",
            segments=[
                Segment(id=0, start_ms=0, end_ms=5000, text_original="你好"),
                Segment(id=1, start_ms=5000, end_ms=10000, text_original="世界"),
            ]
        )
        en_transcript = Transcript(
            episode_id="test_ep",
            language="en",
            segments=[]  # Empty English
        )

        # Act
        result = _merge_bilingual_transcripts(zh_transcript, en_transcript)

        # Assert
        assert len(result.segments) == 2
        assert result.segments[0].text_original == ""
        assert result.segments[0].text_translated == "你好"
        assert result.segments[1].text_original == ""
        assert result.segments[1].text_translated == "世界"

    def test_empty_chinese_transcript(self):
        """Test behavior when Chinese transcript is empty.

        Expected CURRENT behavior:
        - Returns empty segments list
        - episode_id and language still set
        """
        # Arrange
        zh_transcript = Transcript(
            episode_id="test_ep",
            language="zh",
            segments=[]  # Empty Chinese
        )
        en_transcript = Transcript(
            episode_id="test_ep",
            language="en",
            segments=[
                Segment(id=0, start_ms=0, end_ms=5000, text_original="Hello"),
            ]
        )

        # Act
        result = _merge_bilingual_transcripts(zh_transcript, en_transcript)

        # Assert
        assert len(result.segments) == 0
        assert result.episode_id == ""
        assert result.language == "en"

    def test_multiple_english_segments_within_tolerance(self):
        """Test behavior when multiple EN segments are within 3s tolerance.

        Expected CURRENT behavior:
        - Uses FIRST match within tolerance (breaks after first match)
        """
        # Arrange - multiple EN candidates within 3s of zh_seg
        zh_transcript = Transcript(
            episode_id="test_ep",
            language="zh",
            segments=[
                Segment(id=0, start_ms=2000, end_ms=7000, text_original="你好"),
            ]
        )
        en_transcript = Transcript(
            episode_id="test_ep",
            language="en",
            segments=[
                Segment(id=0, start_ms=0, end_ms=5000, text_original="First"),
                Segment(id=1, start_ms=1000, end_ms=6000, text_original="Second"),
                Segment(id=2, start_ms=3000, end_ms=8000, text_original="Third"),
            ]
        )

        # Act
        result = _merge_bilingual_transcripts(zh_transcript, en_transcript)

        # Assert - should match FIRST within tolerance (0ms: 2000ms diff)
        assert len(result.segments) == 1
        assert result.segments[0].text_original == "First"
        assert result.segments[0].text_translated == "你好"
