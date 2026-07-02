"""
Tests for lang_detect module - Phase 1 of language-naming refactor.

Tests follow TDD: write failing tests first, then implement.

The cascade (FIRST signal wins):
1. manual_cc (strongest) - manual subtitles from info_json["subtitles"]
2. metadata - info_json["language"] (yt-dlp declared audio language)
3. audio_probe - reuse _probe_audio_language (async, returns "en-US"/"zh-CN")
4. default - "en" with warning

All tests use synthetic info_json dicts and monkeypatching - no real audio/ASR.
"""
import pytest
from pathlib import Path
from app.sources.lang_detect import (
    detect_source_language,
    SourceLangResult,
    _normalize_lang,
)


class TestNormalizeLang:
    """Tests for _normalize_lang helper."""

    def test_zh_variants(self):
        """Test zh variants normalize to 'zh'."""
        assert _normalize_lang("zh") == "zh"
        assert _normalize_lang("zh-Hans") == "zh"
        assert _normalize_lang("zh-Hant") == "zh"
        assert _normalize_lang("zh-CN") == "zh"
        assert _normalize_lang("zh-TW") == "zh"
        assert _normalize_lang("zh-Hans-en") == "zh"  # First segment wins
        assert _normalize_lang("zh-Hant-en") == "zh"

    def test_en_variants(self):
        """Test en variants normalize to 'en'."""
        assert _normalize_lang("en") == "en"
        assert _normalize_lang("en-US") == "en"
        assert _normalize_lang("en-GB") == "en"
        assert _normalize_lang("en-zh-Hans") == "en"  # First segment wins
        assert _normalize_lang("en-en") == "en"

    def test_unsupported_languages(self):
        """Test unsupported languages return None."""
        assert _normalize_lang("fr") is None
        assert _normalize_lang("de") is None
        assert _normalize_lang("ja") is None
        assert _normalize_lang("ko") is None
        assert _normalize_lang("") is None
        assert _normalize_lang("xx-YY") is None

    def test_case_insensitive(self):
        """Test normalization is case-insensitive for zh/en prefix."""
        assert _normalize_lang("ZH") == "zh"
        assert _normalize_lang("EN") == "en"
        assert _normalize_lang("Zh-Hans") == "zh"
        assert _normalize_lang("En-US") == "en"


class TestManualCcLevel:
    """Tests for manual_cc cascade level (strongest signal)."""

    @pytest.mark.asyncio
    async def test_manual_cc_zh_wins(self):
        """Test manual Chinese CC detected when both zh and en available."""
        # info_json with manual zh subtitles and auto en captions
        info_json = {
            "subtitles": {
                "zh-Hans": [{"ext": "vtt"}],  # Manual
            },
            "automatic_captions": {
                "en": [{"ext": "vtt"}],  # Auto
            },
        }
        available_langs = ["zh", "en"]

        result = await detect_source_language(
            available_langs=available_langs,
            info_json=info_json,
        )

        assert result.lang == "zh"
        assert result.basis == "manual_cc"
        assert "manual" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_manual_cc_en_wins(self):
        """Test manual English CC detected when only en is manual."""
        info_json = {
            "subtitles": {
                "en": [{"ext": "vtt"}],  # Manual
            },
            "automatic_captions": {
                "zh-Hans": [{"ext": "vtt"}],  # Auto
            },
        }
        available_langs = ["zh", "en"]

        result = await detect_source_language(
            available_langs=available_langs,
            info_json=info_json,
        )

        assert result.lang == "en"
        assert result.basis == "manual_cc"

    @pytest.mark.asyncio
    async def test_manual_cc_both_manual_zh_first(self):
        """Test when both are manual, first in available_langs wins."""
        info_json = {
            "subtitles": {
                "en": [{"ext": "vtt"}],
                "zh-Hans": [{"ext": "vtt"}],
            },
            "automatic_captions": {},
        }
        available_langs = ["zh", "en"]

        result = await detect_source_language(
            available_langs=available_langs,
            info_json=info_json,
        )

        # First matching manual lang in available_langs wins
        assert result.lang == "zh"
        assert result.basis == "manual_cc"

    @pytest.mark.asyncio
    async def test_manual_cc_no_subtitles_key(self):
        """Test when info_json has no subtitles key, manual_cc fails."""
        info_json = {
            "automatic_captions": {
                "en": [{"ext": "vtt"}],
            },
        }
        available_langs = ["zh", "en"]

        result = await detect_source_language(
            available_langs=available_langs,
            info_json=info_json,
        )

        # Should fall through to metadata or lower
        assert result.basis != "manual_cc"

    @pytest.mark.asyncio
    async def test_manual_cc_no_match_in_available(self):
        """Test when manual CC lang not in available_langs, manual_cc fails."""
        info_json = {
            "subtitles": {
                "fr": [{"ext": "vtt"}],  # Manual but not in available_langs
            },
            "automatic_captions": {
                "en": [{"ext": "vtt"}],
            },
        }
        available_langs = ["zh", "en"]

        result = await detect_source_language(
            available_langs=available_langs,
            info_json=info_json,
        )

        # Should fall through - fr not in available_langs
        assert result.basis != "manual_cc"


class TestMetadataLevel:
    """Tests for metadata cascade level."""

    @pytest.mark.asyncio
    async def test_metadata_zh(self):
        """Test metadata 'zh' detected when no manual CC."""
        info_json = {
            "automatic_captions": {
                "en": [{"ext": "vtt"}],  # Only auto, no manual
            },
            "language": "zh",  # Declared audio language
        }
        available_langs = ["zh", "en"]

        result = await detect_source_language(
            available_langs=available_langs,
            info_json=info_json,
        )

        assert result.lang == "zh"
        assert result.basis == "metadata"

    @pytest.mark.asyncio
    async def test_metadata_en(self):
        """Test metadata 'en' detected when no manual CC."""
        info_json = {
            "automatic_captions": {
                "zh-Hans": [{"ext": "vtt"}],
            },
            "language": "en",
        }
        available_langs = ["zh", "en"]

        result = await detect_source_language(
            available_langs=available_langs,
            info_json=info_json,
        )

        assert result.lang == "en"
        assert result.basis == "metadata"

    @pytest.mark.asyncio
    async def test_metadata_with_manual_cc_present(self):
        """Test metadata ignored when manual CC exists (precedence)."""
        info_json = {
            "subtitles": {
                "zh-Hans": [{"ext": "vtt"}],  # Manual CC
            },
            "automatic_captions": {
                "en": [{"ext": "vtt"}],
            },
            "language": "en",  # Metadata disagrees with manual CC
        }
        available_langs = ["zh", "en"]

        result = await detect_source_language(
            available_langs=available_langs,
            info_json=info_json,
        )

        # Manual CC should win over metadata
        assert result.lang == "zh"
        assert result.basis == "manual_cc"

    @pytest.mark.asyncio
    async def test_metadata_missing(self):
        """Test when metadata key missing, falls through to audio_probe."""
        info_json = {
            "automatic_captions": {
                "en": [{"ext": "vtt"}],
            },
            # No "language" key
        }
        available_langs = ["zh", "en"]

        result = await detect_source_language(
            available_langs=available_langs,
            info_json=info_json,
            audio_path=Path("/fake/audio.m4a"),
        )

        # Should fall through to audio_probe or default
        assert result.basis not in ("manual_cc", "metadata")

    @pytest.mark.asyncio
    async def test_metadata_unsupported_lang(self):
        """Test when metadata is unsupported lang (fr), falls through."""
        info_json = {
            "automatic_captions": {
                "en": [{"ext": "vtt"}],
            },
            "language": "fr",  # Unsupported
        }
        available_langs = ["zh", "en"]

        result = await detect_source_language(
            available_langs=available_langs,
            info_json=info_json,
            audio_path=Path("/fake/audio.m4a"),
        )

        # Should fall through - fr not supported
        assert result.basis not in ("manual_cc", "metadata")


class TestAudioProbeLevel:
    """Tests for audio_probe cascade level."""

    @pytest.mark.asyncio
    async def test_audio_probe_zh(self, monkeypatch):
        """Test audio probe returns zh-CN mapped to zh."""
        async def fake_probe(audio_path, asr):
            return "zh-CN"

        # Patch at the module where it's defined (asr_afm3)
        monkeypatch.setattr(
            "app.asr_afm3._probe_audio_language",
            fake_probe,
        )

        info_json = {
            "automatic_captions": {
                "en": [{"ext": "vtt"}],
            },
        }
        available_langs = ["zh", "en"]

        result = await detect_source_language(
            available_langs=available_langs,
            info_json=info_json,
            audio_path=Path("/fake/audio.m4a"),
        )

        assert result.lang == "zh"
        assert result.basis == "audio_probe"

    @pytest.mark.asyncio
    async def test_audio_probe_en(self, monkeypatch):
        """Test audio probe returns en-US mapped to en."""
        async def fake_probe(audio_path, asr):
            return "en-US"

        monkeypatch.setattr(
            "app.asr_afm3._probe_audio_language",
            fake_probe,
        )

        info_json = {}
        available_langs = ["zh", "en"]

        result = await detect_source_language(
            available_langs=available_langs,
            info_json=info_json,
            audio_path=Path("/fake/audio.m4a"),
        )

        assert result.lang == "en"
        assert result.basis == "audio_probe"

    @pytest.mark.asyncio
    async def test_audio_probe_no_audio_path(self):
        """Test when audio_path is None, falls through to default."""
        info_json = {}
        available_langs = ["zh", "en"]

        result = await detect_source_language(
            available_langs=available_langs,
            info_json=info_json,
            audio_path=None,
        )

        # Should fall through to default
        assert result.basis == "default"

    @pytest.mark.asyncio
    async def test_audio_probe_precedence_over_default(self, monkeypatch):
        """Test audio_probe runs before default when available."""
        async def fake_probe(audio_path, asr):
            return "zh-CN"

        monkeypatch.setattr(
            "app.asr_afm3._probe_audio_language",
            fake_probe,
        )

        result = await detect_source_language(
            available_langs=["zh", "en"],
            info_json={},  # No manual, no metadata
            audio_path=Path("/fake/audio.m4a"),
        )

        assert result.basis == "audio_probe"
        assert result.lang == "zh"


class TestDefaultLevel:
    """Tests for default cascade level (fallback)."""

    @pytest.mark.asyncio
    async def test_default_fallback(self):
        """Test default returns 'en' when all other levels fail."""
        result = await detect_source_language(
            available_langs=["zh", "en"],
            info_json=None,  # No info_json at all
            audio_path=None,  # No audio to probe
        )

        assert result.lang == "en"
        assert result.basis == "default"
        assert "warning" in result.reason.lower() or "fallback" in result.reason.lower()


class TestCascadePrecedence:
    """Tests to verify cascade precedence order."""

    @pytest.mark.asyncio
    async def test_manual_cc_beats_metadata(self):
        """Verify manual_cc wins over metadata."""
        info_json = {
            "subtitles": {
                "zh-Hans": [{"ext": "vtt"}],  # Manual
            },
            "automatic_captions": {},
            "language": "en",  # Metadata disagrees
        }
        available_langs = ["zh", "en"]

        result = await detect_source_language(
            available_langs=available_langs,
            info_json=info_json,
        )

        assert result.lang == "zh"  # Manual wins
        assert result.basis == "manual_cc"

    @pytest.mark.asyncio
    async def test_metadata_beats_audio_probe(self, monkeypatch):
        """Verify metadata wins over audio_probe."""
        async def fake_probe(audio_path, asr):
            return "zh-CN"  # Probe says zh

        monkeypatch.setattr(
            "app.asr_afm3._probe_audio_language",
            fake_probe,
        )

        info_json = {
            "automatic_captions": {"en": [{"ext": "vtt"}]},
            "language": "en",  # Metadata says en
        }
        available_langs = ["zh", "en"]

        result = await detect_source_language(
            available_langs=available_langs,
            info_json=info_json,
            audio_path=Path("/fake/audio.m4a"),
        )

        assert result.lang == "en"  # Metadata wins
        assert result.basis == "metadata"

    @pytest.mark.asyncio
    async def test_audio_probe_beats_default(self, monkeypatch):
        """Verify audio_probe wins over default."""
        async def fake_probe(audio_path, asr):
            return "zh-CN"

        monkeypatch.setattr(
            "app.asr_afm3._probe_audio_language",
            fake_probe,
        )

        result = await detect_source_language(
            available_langs=["zh", "en"],
            info_json={},  # No manual, no metadata
            audio_path=Path("/fake/audio.m4a"),
        )

        assert result.lang == "zh"  # Probe wins over default
        assert result.basis == "audio_probe"

    @pytest.mark.asyncio
    async def test_full_cascade_manual_wins(self, monkeypatch):
        """Test full cascade: manual CC wins even with metadata and probe."""
        async def fake_probe(audio_path, asr):
            return "en-US"  # Probe says en

        monkeypatch.setattr(
            "app.asr_afm3._probe_audio_language",
            fake_probe,
        )

        info_json = {
            "subtitles": {
                "zh-Hans": [{"ext": "vtt"}],  # Manual says zh
            },
            "automatic_captions": {},
            "language": "en",  # Metadata says en
        }
        available_langs = ["zh", "en"]

        result = await detect_source_language(
            available_langs=available_langs,
            info_json=info_json,
            audio_path=Path("/fake/audio.m4a"),
        )

        assert result.lang == "zh"  # Manual CC wins overall
        assert result.basis == "manual_cc"


class TestSourceLangResult:
    """Tests for SourceLangResult dataclass."""

    def test_result_is_frozen(self):
        """Test that SourceLangResult is frozen (immutable)."""
        from dataclasses import FrozenInstanceError

        result = SourceLangResult(
            lang="zh",
            basis="manual_cc",
            reason="Manual Chinese CC found",
        )

        # Verify we can read attributes
        assert result.lang == "zh"
        assert result.basis == "manual_cc"
        assert result.reason == "Manual Chinese CC found"

        # Verify it's frozen (immutable)
        with pytest.raises(FrozenInstanceError):  # Frozen dataclass raises on modification
            result.lang = "en"

    def test_result_string_repr(self):
        """Test result has useful string representation."""
        result = SourceLangResult(
            lang="zh",
            basis="manual_cc",
            reason="Manual Chinese CC found",
        )

        # Should contain key info
        result_str = str(result)
        assert "zh" in result_str or "manual_cc" in result_str


class TestEdgeCases:
    """Edge case tests."""

    @pytest.mark.asyncio
    async def test_none_info_json(self):
        """Test with None info_json (e.g., not fetched)."""
        result = await detect_source_language(
            available_langs=["zh", "en"],
            info_json=None,
            audio_path=None,
        )

        assert result.lang == "en"
        assert result.basis == "default"

    @pytest.mark.asyncio
    async def test_empty_available_langs(self):
        """Test with empty available_langs list."""
        info_json = {
            "subtitles": {
                "zh-Hans": [{"ext": "vtt"}],
            },
        }

        result = await detect_source_language(
            available_langs=[],
            info_json=info_json,
        )

        # No langs available, should fall through
        assert result.basis != "manual_cc"

    @pytest.mark.asyncio
    async def test_complex_yt_lang_code(self):
        """Test with complex yt-dlp language codes."""
        info_json = {
            "subtitles": {
                "zh-Hans-en": [{"ext": "vtt"}],  # Translation format
            },
        }
        available_langs = ["zh", "en"]

        result = await detect_source_language(
            available_langs=available_langs,
            info_json=info_json,
        )

        # zh-Hans-en should normalize to zh
        assert result.lang == "zh"
        assert result.basis == "manual_cc"

    @pytest.mark.asyncio
    async def test_metadata_complex_code(self):
        """Test metadata with complex language code."""
        info_json = {
            "language": "zh-Hans",
        }

        result = await detect_source_language(
            available_langs=["zh", "en"],
            info_json=info_json,
        )

        assert result.lang == "zh"
        assert result.basis == "metadata"
