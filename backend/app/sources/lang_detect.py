"""
Language detection module for podcast audio sources.

Phase 1 of language-naming refactor: Pure module that determines an audio's
spoken language via a 4-level cascade:

1. manual_cc (strongest): Manual/human subtitles from info_json["subtitles"]
2. metadata: info_json["language"] - yt-dlp's declared audio language
3. audio_probe: _probe_audio_language(audio_path, asr) - actual audio analysis
4. default (fallback): "en" with a warning

This module is NOT yet wired into the pipeline (Phase 3 does that).
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceLangResult:
    """Result of language detection with provenance.

    Attributes:
        lang: Detected language, "zh" or "en"
        basis: Which cascade level decided: "manual_cc" | "metadata" | "audio_probe" | "default"
        reason: Human-readable detail for logs
    """
    lang: str
    basis: str
    reason: str


def _normalize_lang(code: str) -> Optional[str]:
    """Normalize a language code to "zh" or "en", or return None.

    Handles various yt-dlp language code formats:
    - Simple: "zh", "en"
    - With region: "zh-CN", "zh-TW", "en-US", "en-GB"
    - Complex/translation: "zh-Hans-en", "zh-Hant-en", "en-zh-Hans", "en-en"

    For complex codes like "zh-Hans-en" (Chinese content, translated from English),
    we take the FIRST segment as the content language.

    Args:
        code: Language code string

    Returns:
        "zh" for Chinese variants, "en" for English variants, None otherwise
    """
    if not code:
        return None

    # Normalize to lowercase for comparison
    code_lower = code.lower()

    # Extract first segment before hyphen (handles "zh-Hans", "zh-CN", "zh-Hans-en")
    first_segment = code_lower.split("-")[0]

    if first_segment == "zh":
        return "zh"
    if first_segment == "en":
        return "en"

    # Not a supported language
    return None


def _check_manual_cc(
    available_langs: list[str],
    info_json: dict,
) -> Optional[SourceLangResult]:
    """Check level 1: manual closed captions.

    Determines which of the available_langs came from manual/human subtitles
    (info_json["subtitles"]) vs auto-generated (info_json["automatic_captions"]).

    A manual CC's language is considered the audio's spoken language.

    Args:
        available_langs: Languages we actually fetched CCs for (e.g., ["zh","en"])
        info_json: yt-dlp --write-info-json output

    Returns:
        SourceLangResult if a manual CC maps to zh/en, None otherwise
    """
    if not info_json:
        return None

    subtitles = info_json.get("subtitles", {})
    if not subtitles:
        return None

    # Find which available_langs have manual CCs
    manual_langs = []
    for available_lang in available_langs:
        # Check if any subtitle key normalizes to this available lang
        for subtitle_lang in subtitles.keys():
            normalized = _normalize_lang(subtitle_lang)
            if normalized == available_lang:
                manual_langs.append(available_lang)
                break

    if not manual_langs:
        return None

    # First matching manual lang wins
    detected_lang = manual_langs[0]

    return SourceLangResult(
        lang=detected_lang,
        basis="manual_cc",
        reason=f"Manual {detected_lang} subtitles found in info_json",
    )


def _check_metadata(
    available_langs: list[str],
    info_json: dict,
) -> Optional[SourceLangResult]:
    """Check level 2: yt-dlp metadata language.

    Args:
        available_langs: Languages we actually fetched CCs for
        info_json: yt-dlp --write-info-json output

    Returns:
        SourceLangResult if metadata maps to zh/en, None otherwise
    """
    if not info_json:
        return None

    declared_lang = info_json.get("language")
    if not declared_lang:
        return None

    normalized = _normalize_lang(declared_lang)
    if not normalized:
        return None

    # Check if normalized lang is in available_langs
    if normalized in available_langs:
        return SourceLangResult(
            lang=normalized,
            basis="metadata",
            reason=f"yt-dlp declared language: {declared_lang}",
        )

    return None


async def _check_audio_probe(
    available_langs: list[str],
    audio_path: Optional[Path],
    asr=None,
) -> Optional[SourceLangResult]:
    """Check level 3: probe actual audio with ASR.

    Reuses _probe_audio_language from asr_afm3 module.

    Args:
        available_langs: Languages we actually fetched CCs for
        audio_path: Path to audio file for probing
        asr: ASR object with .transcribe method

    Returns:
        SourceLangResult if probe succeeds and maps to zh/en, None otherwise
    """
    if not audio_path:
        return None

    # Import here to avoid circular dependency
    from ..asr_afm3 import _probe_audio_language

    try:
        probe_result = await _probe_audio_language(audio_path, asr)

        # _probe_audio_language returns "en-US" or "zh-CN"
        # Map to our normalized values
        if probe_result == "zh-CN":
            detected = "zh"
        elif probe_result == "en-US":
            detected = "en"
        else:
            # Unexpected result, normalize it
            detected = _normalize_lang(probe_result)

        if detected and detected in available_langs:
            return SourceLangResult(
                lang=detected,
                basis="audio_probe",
                reason=f"Audio probe returned {probe_result}",
            )
    except Exception as e:
        logger.warning(f"Audio probe failed: {e}")

    return None


def _check_default() -> SourceLangResult:
    """Check level 4: default fallback.

    Returns "en" as a safe default, matching the existing _probe_audio_language
    failure behavior.

    Returns:
        SourceLangResult with basis="default"
    """
    return SourceLangResult(
        lang="en",
        basis="default",
        reason="Default fallback (no language signal available)",
    )


async def detect_source_language(
    available_langs: list[str],
    info_json: Optional[dict] = None,
    audio_path: Optional[Path] = None,
    asr=None,
) -> SourceLangResult:
    """Detect the spoken language of audio source using a 4-level cascade.

    The cascade evaluates signals in priority order; FIRST signal that maps to
    zh/en wins. This ensures stronger signals override weaker ones:

    1. manual_cc (strongest): Manual/human subtitles indicate source language
    2. metadata: yt-dlp's declared audio language
    3. audio_probe: Actual audio analysis via ASR
    4. default (fallback): "en" with a warning

    Args:
        available_langs: Languages we actually fetched CCs for, e.g. ["zh","en"]
        info_json: yt-dlp --write-info-json output (may be None)
        audio_path: Path to audio file for probe fallback (optional)
        asr: ASR object with .transcribe method (only used for probe level)

    Returns:
        SourceLangResult with detected language and which level decided
    """
    # Level 1: Check manual closed captions
    result = _check_manual_cc(available_langs, info_json)
    if result:
        return result

    # Level 2: Check yt-dlp metadata
    result = _check_metadata(available_langs, info_json)
    if result:
        return result

    # Level 3: Probe actual audio
    result = await _check_audio_probe(available_langs, audio_path, asr)
    if result:
        return result

    # Level 4: Default fallback
    logger.warning(
        "Language detection: No signal found, using default 'en'. "
        "This may be incorrect for non-English content."
    )
    return _check_default()
