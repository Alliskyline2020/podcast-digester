"""
Existing-data language-field migration tool (Phase 6, pulled forward).

Content-based self-healing for legacy `text_original`/`text_translated` data:
- ADDITIVELY routes each segment's two candidate texts into `text_zh`/`text_en`
  based on CJK character ratio (never modifies the original two fields).
- Proposes a corrected episode `language` label via an audio-language probe
  (reuses `app.sources.lang_detect.detect_source_language` cascade, whose
  audio_probe level calls `app.asr_afm3._probe_audio_language`). When the probe
  cannot run, falls back to the existing label and flags the episode as
  `probe_fell_back`.

DEFAULT mode is `--dry-run`: it writes NOTHING to data/ and prints + saves a
JSON report. `--apply` is the user-gated separate task; it additionally
requires `--yes-i-backed-up` and backs up DB + transcript.json first.

Out of scope (NOT touched): paragraph_mappings, text_with_punct, removal of
the legacy text_original/text_translated fields, and orphan episode dirs are
reported only (never written even in apply mode).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import shutil
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable, Optional

from app.config import DB_PATH, DATA_DIR

logger = logging.getLogger(__name__)

# CJK ratio at/above which a single-candidate segment is routed to text_zh.
CJK_RATIO_THRESHOLD: float = 0.3

# Hanzi Unicode block. CJK punctuation (、。「」 etc.) lives outside this range
# and is intentionally NOT counted as CJK content.
_CJK_LO = "一"
_CJK_HI = "鿿"

# Minimum non-space length for a candidate text to be considered "present".
_EMPTY_TEXTS = (None, "", " ", "\t", "\n")


# ============================================================================
# Pure helpers (unit-tested)
# ============================================================================

def cjk_ratio(text: Optional[str]) -> float:
    """Return the ratio of CJK hanzi characters to non-space characters.

    Hanzi = U+4E00..U+9FFF (CJK Unified Ideographs). CJK punctuation
    (、。「」 etc.) lives outside this range and does NOT count, so a
    punctuation-only string has ratio 0.

    Args:
        text: Input string, or None.

    Returns:
        Ratio in [0.0, 1.0]. Empty/whitespace/None/numbers-only -> 0.0.
    """
    if not text:
        return 0.0
    non_space = sum(1 for c in text if not c.isspace())
    if non_space == 0:
        return 0.0
    cjk_count = sum(1 for c in text if _CJK_LO <= c <= _CJK_HI)
    return cjk_count / non_space


@dataclass(frozen=True)
class RouteResult:
    """Result of routing one segment's two candidate texts to zh/en.

    `text_zh`/`text_en` are the routed values (the content), or None if that
    language has no candidate for this segment. The original candidate texts
    are NEVER mutated — this is purely additive.
    """
    text_zh: Optional[str]
    text_en: Optional[str]


def _is_present(text: Optional[str]) -> bool:
    """True if the candidate text is non-None and non-whitespace."""
    return text not in _EMPTY_TEXTS and bool(text) and not text.isspace()


def route_segment(text_original: Optional[str], text_translated: Optional[str]) -> RouteResult:
    """Route the two candidate texts of a segment into zh/en by CJK ratio.

    Rules (brief task-5):
    - Both candidates present: higher CJK ratio -> text_zh, lower -> text_en.
      On exact tie (e.g. both pure Chinese) the translated candidate is routed
      to text_zh (deterministic) and original to text_en.
    - Single candidate present: ratio >= CJK_RATIO_THRESHOLD -> text_zh,
      else -> text_en. The other field stays None.
    - Neither present: both None.

    Args:
        text_original: The legacy text_original field value.
        text_translated: The legacy text_translated field value.

    Returns:
        RouteResult with text_zh / text_en (None where no candidate routed).
    """
    orig_present = _is_present(text_original)
    trans_present = _is_present(text_translated)

    if not orig_present and not trans_present:
        return RouteResult(text_zh=None, text_en=None)

    if orig_present and not trans_present:
        return _route_single(text_original)

    if trans_present and not orig_present:
        return _route_single(text_translated)

    # Both present: route by ratio.
    orig_ratio = cjk_ratio(text_original)
    trans_ratio = cjk_ratio(text_translated)

    if trans_ratio > orig_ratio:
        return RouteResult(text_zh=text_translated, text_en=text_original)
    if orig_ratio > trans_ratio:
        return RouteResult(text_zh=text_original, text_en=text_translated)
    # Tie: translated -> zh (deterministic; covers the both-pure-Chinese case).
    return RouteResult(text_zh=text_translated, text_en=text_original)


def _route_single(text: str) -> RouteResult:
    """Route a single present candidate."""
    if cjk_ratio(text) >= CJK_RATIO_THRESHOLD:
        return RouteResult(text_zh=text, text_en=None)
    return RouteResult(text_zh=None, text_en=text)


@dataclass
class EpisodeAggregation:
    """Aggregated routing stats for one episode."""
    segments_total: int = 0
    segments_with_both_langs: int = 0
    segments_zh_only: int = 0
    segments_en_only: int = 0
    segments_neither: int = 0
    zh_chars: int = 0
    en_chars: int = 0

    @property
    def majority_lang(self) -> Optional[str]:
        """Which language dominates by character count, or None if tied/empty."""
        if self.zh_chars == self.en_chars:
            return None
        return "zh" if self.zh_chars > self.en_chars else "en"


def aggregate_episode(routed_segments: list[RouteResult]) -> EpisodeAggregation:
    """Aggregate routing stats over all segments of an episode."""
    agg = EpisodeAggregation()
    for r in routed_segments:
        agg.segments_total += 1
        has_zh = r.text_zh is not None
        has_en = r.text_en is not None
        if has_zh and has_en:
            agg.segments_with_both_langs += 1
        elif has_zh:
            agg.segments_zh_only += 1
        elif has_en:
            agg.segments_en_only += 1
        else:
            agg.segments_neither += 1
        agg.zh_chars += len(r.text_zh or "")
        agg.en_chars += len(r.text_en or "")
    return agg


def is_ambiguous(
    existing_language: Optional[str],
    proposed_language: Optional[str],
    agg: EpisodeAggregation,
) -> bool:
    """True when both languages are substantially present AND label disagrees.

    These are the Yao-type cases (bilingual content, label disagrees with the
    audio probe) that the user must review before any apply. A monolingual
    episode whose label simply differs is NOT ambiguous (just relabel).
    """
    if not proposed_language:
        return False
    if existing_language is not None and proposed_language == existing_language:
        return False
    # "Both languages substantially present": require at least one segment
    # with both langs, and non-trivial content in the minority side too.
    if agg.segments_with_both_langs == 0:
        return False
    # Require minority side to carry some real content (not 1 stray char).
    minority = min(agg.zh_chars, agg.en_chars)
    if minority < 10:
        return False
    return True


# ============================================================================
# Probe abstraction
# ============================================================================

# A probe callable takes an audio Path and returns the proposed language
# ("zh" / "en") or None if unavailable. It is injected so unit tests can mock
# it without touching real audio or ASR.
ProbeFn = Callable[[Path], Awaitable[Optional[str]]]


async def _default_audio_probe(audio_path: Path) -> Optional[str]:
    """Default probe: build an AppleASR client and run detect_source_language.

    Returns "zh"/"en" on success, or None on any failure (headless-unavailable,
    ASR error, probe exception). The caller (build_episode_report) is
    responsible for falling back to the existing label when this returns None
    or raises.
    """
    try:
        from app.asr_afm3 import get_apple_asr
        from app.sources.lang_detect import detect_source_language

        # get_apple_asr() raises if ASR is unavailable on this host.
        asr = get_apple_asr()
        result = await detect_source_language(
            available_langs=["zh", "en"],
            info_json=None,           # we have no info_json for existing data
            audio_path=audio_path,
            asr=asr,
        )
        # detect_source_language always returns a result (default fallback "en").
        # We only treat audio_probe basis as a verified probe; metadata/manual
        # are not applicable here (no info_json), so default-fallback and
        # metadata basis both count as "unverified" -> None signals fallback.
        if result.basis == "audio_probe":
            return result.lang
        return None
    except Exception as e:  # noqa: BLE001 — probe must never abort the run
        logger.warning("Audio probe unavailable for %s: %s", audio_path, e)
        return None


# ============================================================================
# Episode report builder (unit-tested; pure given a probe_fn)
# ============================================================================

def _truncate(text: Optional[str], n: int = 40) -> Optional[str]:
    if text is None:
        return None
    return text[:n]


def build_episode_report(
    ep_id: str,
    in_db: bool,
    is_orphan: bool,
    current_db_language: Optional[str],
    transcript_language: Optional[str],
    segments: list[dict],
    audio_path: Optional[Path],
    probe_fn: Optional[ProbeFn],
) -> dict:
    """Sync per-episode report builder for unit tests.

    Runs the (async) probe by driving a fresh event loop, so a unittest
    AsyncMock works without an existing loop. Production code calls the
    async variant `build_episode_report_async` instead.
    """
    routed = [route_segment(s.get("text_original"), s.get("text_translated")) for s in segments]
    agg = aggregate_episode(routed)
    existing_label = current_db_language or transcript_language

    probe_fell_back = False
    if audio_path is not None and probe_fn is not None:
        probe_result = _drive_async(_run_probe(probe_fn, audio_path))
        if probe_result is not None:
            proposed_language = probe_result
            language_method = "audio_probe"
        else:
            proposed_language = existing_label
            language_method = "kept_existing"
            probe_fell_back = True
    else:
        proposed_language = existing_label
        language_method = "kept_existing"
        # Distinguish "no audio file" from "probe callable not supplied".
        probe_fell_back = audio_path is None and probe_fn is not None

    ambiguous = is_ambiguous(existing_label, proposed_language, agg)

    return {
        "ep_id": ep_id,
        "in_db": in_db,
        "is_orphan": is_orphan,
        "current_language_db": current_db_language,
        "current_language_transcript": transcript_language,
        "proposed_language": proposed_language,
        "language_method": language_method,
        "probe_fell_back": probe_fell_back,
        "zh_chars": agg.zh_chars,
        "en_chars": agg.en_chars,
        "segments_total": agg.segments_total,
        "segments_with_both_langs": agg.segments_with_both_langs,
        "segments_zh_only": agg.segments_zh_only,
        "segments_en_only": agg.segments_en_only,
        "segments_neither": agg.segments_neither,
        "majority_lang": agg.majority_lang,
        "ambiguous": ambiguous,
        "sample": _build_sample(segments, routed),
    }


def _drive_async(coro) -> any:
    """Run a coroutine to completion on a throwaway event loop (sync helper)."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("loop closed")
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


async def _run_probe(probe_fn: ProbeFn, audio_path: Path) -> Optional[str]:
    """Run the (async) probe function, returning its result or None on error."""
    try:
        return await probe_fn(audio_path)
    except Exception as e:  # noqa: BLE001
        logger.warning("Probe raised for %s: %s", audio_path, e)
        return None


async def build_episode_report_async(
    ep_id: str,
    in_db: bool,
    is_orphan: bool,
    current_db_language: Optional[str],
    transcript_language: Optional[str],
    segments: list[dict],
    audio_path: Optional[Path],
    probe_fn: Optional[ProbeFn],
) -> dict:
    """Async variant: actually runs the audio probe.

    Pure routing logic is identical to build_episode_report; only the probe
    execution differs (real await). This is what the CLI uses.
    """
    routed = [route_segment(s.get("text_original"), s.get("text_translated")) for s in segments]
    agg = aggregate_episode(routed)

    existing_label = current_db_language or transcript_language

    probe_fell_back = False
    if audio_path is not None and probe_fn is not None:
        probe_result = await _run_probe(probe_fn, audio_path)
        if probe_result is not None:
            proposed_language = probe_result
            language_method = "audio_probe"
        else:
            proposed_language = existing_label
            language_method = "kept_existing"
            probe_fell_back = True
    else:
        proposed_language = existing_label
        language_method = "kept_existing"
        probe_fell_back = audio_path is None and probe_fn is not None

    ambiguous = is_ambiguous(existing_label, proposed_language, agg)

    return {
        "ep_id": ep_id,
        "in_db": in_db,
        "is_orphan": is_orphan,
        "current_language_db": current_db_language,
        "current_language_transcript": transcript_language,
        "proposed_language": proposed_language,
        "language_method": language_method,
        "probe_fell_back": probe_fell_back,
        "zh_chars": agg.zh_chars,
        "en_chars": agg.en_chars,
        "segments_total": agg.segments_total,
        "segments_with_both_langs": agg.segments_with_both_langs,
        "segments_zh_only": agg.segments_zh_only,
        "segments_en_only": agg.segments_en_only,
        "segments_neither": agg.segments_neither,
        "majority_lang": agg.majority_lang,
        "ambiguous": ambiguous,
        "sample": _build_sample(segments, routed),
    }


def _build_sample(segments: list[dict], routed: list[RouteResult]) -> dict:
    """First-segment sample for the report, truncated to 40 chars per field."""
    if not segments:
        return {"text_original": None, "text_translated": None, "text_zh": None, "text_en": None}
    s0 = segments[0]
    r0 = routed[0] if routed else RouteResult(None, None)
    return {
        "text_original": _truncate(s0.get("text_original")),
        "text_translated": _truncate(s0.get("text_translated")),
        "text_zh": _truncate(r0.text_zh),
        "text_en": _truncate(r0.text_en),
    }


# ============================================================================
# I/O helpers (not unit-tested; thin wrappers over sqlite/json/filesystem)
# ============================================================================

def _load_db_episodes() -> dict[str, dict]:
    """Return {ep_id: {language, has_transcript}} for all DB rows."""
    episodes: dict[str, dict] = {}
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        for row in conn.execute("SELECT id, language, transcript FROM episode"):
            episodes[row["id"]] = {
                "language": row["language"] or None,
                "has_transcript_json": bool(row["transcript"]),
            }
    return episodes


def _load_transcript_json(ep_id: str, media_dir: Path) -> Optional[dict]:
    path = media_dir / ep_id / "transcript.json"
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Could not read %s: %s", path, e)
        return None


def _audio_path_for(ep_id: str, media_dir: Path) -> Optional[Path]:
    audio = media_dir / ep_id / "audio.m4a"
    return audio if audio.exists() else None


def _discover_disk_episode_ids(media_dir: Path) -> list[str]:
    """All ep_* dirs on disk that have a transcript.json."""
    if not media_dir.exists():
        return []
    out = []
    for child in sorted(media_dir.iterdir()):
        if child.is_dir() and (child / "transcript.json").exists():
            out.append(child.name)
    return out


# ============================================================================
# Dry-run entry point
# ============================================================================

async def run_dry_run(
    episode_filter: Optional[str] = None,
    probe_fn: Optional[ProbeFn] = _default_audio_probe,
) -> dict:
    """Run the full dry-run scan and return the report dict.

    Writes NOTHING to data/. Returns a dict with per-episode reports + summary.
    """
    start = time.monotonic()
    media_dir = DATA_DIR / "media"
    db_episodes = _load_db_episodes()
    disk_ids = _discover_disk_episode_ids(media_dir)

    # Union: all DB ids + all disk ids (orphans included).
    all_ids = sorted(set(db_episodes.keys()) | set(disk_ids))

    if episode_filter:
        all_ids = [i for i in all_ids if i == episode_filter]
        if not all_ids:
            print(f"[dry-run] no episode matched --episode {episode_filter!r}")
            return {"episodes": [], "summary": _empty_summary()}

    reports = []
    for ep_id in all_ids:
        in_db = ep_id in db_episodes
        is_orphan = ep_id not in db_episodes
        db_lang = db_episodes.get(ep_id, {}).get("language")
        tj = _load_transcript_json(ep_id, media_dir)
        tj_lang = (tj.get("language") if tj else None) or None
        segments = tj.get("segments", []) if tj else []
        audio = _audio_path_for(ep_id, media_dir)

        report = await build_episode_report_async(
            ep_id=ep_id,
            in_db=in_db,
            is_orphan=is_orphan,
            current_db_language=db_lang,
            transcript_language=tj_lang,
            segments=segments,
            audio_path=audio,
            probe_fn=probe_fn,
        )
        reports.append(report)
        _print_episode_line(report)

    summary = _summarize(reports, time.monotonic() - start)
    return {"episodes": reports, "summary": summary}


def _empty_summary() -> dict:
    return {
        "total_episodes": 0,
        "language_changes": 0,
        "ambiguous": 0,
        "orphans": 0,
        "probe_fell_back": 0,
        "runtime_seconds": 0.0,
    }


def _summarize(reports: list[dict], runtime: float) -> dict:
    language_changes = sum(
        1 for r in reports
        if r["proposed_language"] and r["current_language_db"] is not None
        and r["proposed_language"] != r["current_language_db"]
    )
    return {
        "total_episodes": len(reports),
        "language_changes": language_changes,
        "ambiguous": sum(1 for r in reports if r["ambiguous"]),
        "orphans": sum(1 for r in reports if r["is_orphan"]),
        "probe_fell_back": sum(1 for r in reports if r["probe_fell_back"]),
        "runtime_seconds": round(runtime, 2),
    }


def _print_episode_line(r: dict) -> None:
    flags = []
    if r["ambiguous"]:
        flags.append("AMBIGUOUS")
    if r["is_orphan"]:
        flags.append("ORPHAN")
    if r["probe_fell_back"]:
        flags.append("probe-fallback")
    flag_str = (" [" + ",".join(flags) + "]") if flags else ""
    print(
        f"  {r['ep_id']:24} db={str(r['current_language_db'] or '-'):<4} "
        f"tj={str(r['current_language_transcript'] or '-'):<4} "
        f"-> {str(r['proposed_language'] or '-'):<4} "
        f"({r['language_method']:<12}) "
        f"zh={r['zh_chars']:>7} en={r['en_chars']:>7} "
        f"both={r['segments_with_both_langs']:>5}/{r['segments_total']:<5}"
        f"{flag_str}"
    )


def _print_summary(s: dict) -> None:
    print()
    print("=" * 72)
    print("DRY-RUN SUMMARY")
    print("=" * 72)
    print(f"  Total episodes scanned : {s['total_episodes']}")
    print(f"  Language label changes : {s['language_changes']}")
    print(f"  Ambiguous (needs review): {s['ambiguous']}")
    print(f"  Orphan dirs (not in DB) : {s['orphans']}")
    print(f"  Probe fell back         : {s['probe_fell_back']}")
    print(f"  Runtime                 : {s['runtime_seconds']}s")
    print()
    print("NOTHING was written to data/ (dry-run only).")
    print("Apply is a separate, user-gated task (--apply --yes-i-backed-up).")


# ============================================================================
# Apply (NOT run in this task; implemented for the follow-up task)
# ============================================================================

async def run_apply(yes_i_backed_up: bool, episode_filter: Optional[str] = None) -> None:
    """Apply the migration. Refuses without --yes-i-backed-up.

    Backs up DB + each transcript.json BEFORE writing. Additive only: writes
    text_zh/text_en to segment dicts (never touches text_original /
    text_translated), updates episode.language only where the probe succeeded,
    and never writes to orphan dirs.
    """
    if not yes_i_backed_up:
        print("REFUSING to apply without --yes-i-backed-up.")
        print("Back up data/podcast_digester.db and data/media/*/transcript.json")
        print("first, then re-run with --apply --yes-i-backed-up.")
        sys.exit(2)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    db_backup = DB_PATH.with_name(f"{DB_PATH.name}.backup-pre-lang-migrate-{ts}")
    shutil.copy2(DB_PATH, db_backup)
    print(f"Backed up DB -> {db_backup}")

    media_dir = DATA_DIR / "media"
    db_episodes = _load_db_episodes()
    disk_ids = _discover_disk_episode_ids(media_dir)
    all_ids = sorted(set(db_episodes.keys()) | set(disk_ids))
    if episode_filter:
        all_ids = [i for i in all_ids if i == episode_filter]

    report = await run_dry_run(episode_filter=episode_filter)
    proposed_by_ep = {r["ep_id"]: r for r in report["episodes"]}

    for ep_id in all_ids:
        if ep_id not in db_episodes:
            print(f"  SKIP orphan {ep_id} (not in DB, never written)")
            continue
        tj_path = media_dir / ep_id / "transcript.json"
        if not tj_path.exists():
            continue
        # Backup transcript.json
        tj_backup = tj_path.with_name(f"{tj_path.name}.bak-pre-lang-migrate-{ts}")
        shutil.copy2(tj_path, tj_backup)

        with tj_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        changed = False
        for seg in data.get("segments", []):
            if "text_zh" in seg and "text_en" in seg:
                continue  # idempotent
            r = route_segment(seg.get("text_original"), seg.get("text_translated"))
            seg["text_zh"] = r.text_zh
            seg["text_en"] = r.text_en
            changed = True
        if changed:
            with tj_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

        # Update DB: episode.transcript JSON (if populated) + language (probe-verified only)
        ep_report = proposed_by_ep.get(ep_id, {})
        _update_db_episode(ep_id, data.get("segments", []), ep_report)
        print(f"  APPLY {ep_id} (transcript.json backup -> {tj_backup.name})")

    print("Apply complete.")


def _update_db_episode(ep_id: str, segments: list[dict], ep_report: dict) -> None:
    """Update the DB row's transcript JSON (text_zh/text_en) and language."""
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT transcript, language FROM episode WHERE id=?", (ep_id,)
        ).fetchone()
        if not row:
            return
        transcript_json, current_lang = row
        new_lang = ep_report.get("proposed_language") or current_lang
        # Only update language where probe verified (audio_probe method).
        lang_to_write = new_lang if ep_report.get("language_method") == "audio_probe" else current_lang

        if transcript_json:
            try:
                tj = json.loads(transcript_json)
            except json.JSONDecodeError:
                tj = None
            if tj is not None and "segments" in tj:
                for seg in tj["segments"]:
                    if "text_zh" not in seg or "text_en" not in seg:
                        r = route_segment(seg.get("text_original"), seg.get("text_translated"))
                        seg["text_zh"] = r.text_zh
                        seg["text_en"] = r.text_en
                conn.execute(
                    "UPDATE episode SET transcript=?, language=? WHERE id=?",
                    (json.dumps(tj, ensure_ascii=False), lang_to_write, ep_id),
                )
            else:
                conn.execute(
                    "UPDATE episode SET language=? WHERE id=?", (lang_to_write, ep_id)
                )
        else:
            conn.execute(
                "UPDATE episode SET language=? WHERE id=?", (lang_to_write, ep_id)
            )
        conn.commit()


# ============================================================================
# CLI
# ============================================================================

def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="app.migrations.migrate_language_fields",
        description="Existing-data language-field migration (content-route text_zh/text_en + audio-probe language).",
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True,
                      help="Scan + report only; write NOTHING (DEFAULT).")
    mode.add_argument("--apply", action="store_true",
                      help="Write text_zh/text_en + corrected language. Requires --yes-i-backed-up.")
    p.add_argument("--yes-i-backed-up", action="store_true",
                   help="Confirm you backed up data/ before --apply.")
    p.add_argument("--episode", default=None,
                   help="Restrict to a single episode id.")
    p.add_argument("--report-json", default=None,
                   help="Write the dry-run report JSON to this path.")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _build_arg_parser().parse_args(argv)

    if args.apply:
        asyncio.run(run_apply(yes_i_backed_up=args.yes_i_backed_up, episode_filter=args.episode))
        return 0

    report = asyncio.run(run_dry_run(episode_filter=args.episode))
    _print_summary(report["summary"])
    if args.report_json:
        out = Path(args.report_json)
        with out.open("w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"Report JSON written to {out}")
    else:
        # Default location: data/migration_dryrun_<ts>.json (still just a report,
        # not a mutation of episode data).
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        default_out = DATA_DIR / f"migration_dryrun_{ts}.json"
        with default_out.open("w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"Report JSON written to {default_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
