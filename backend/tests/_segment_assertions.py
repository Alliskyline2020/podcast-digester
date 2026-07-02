"""
Segment coverage assertions for testing.

Provides reusable test helpers for verifying that paragraph_mappings
cover all source segments without silent drops.
"""
from typing import List, Dict, Any


def assert_segment_coverage(
    paragraph_mappings: List[Dict[str, Any]],
    n_source_segments: int,
    *,
    allow_gaps: bool = False
) -> None:
    """Assert paragraph_mappings' segment_indices union covers 0..n-1.

    Every source segment index should appear exactly once across all paragraphs.
    This ensures no silent drops during segmentation/transcription operations.

    Args:
        paragraph_mappings: List of paragraph dicts, each containing a
            "segment_indices" key with a list of integers.
        n_source_segments: Expected total number of source segments.
        allow_gaps: If False (default), every index 0..n-1 must appear exactly once.
            If True, gaps are allowed (useful for testing partial processing).

    Raises:
        AssertionError: With detailed message listing missing and/or duplicate indices.
    """
    # Collect all indices from all paragraphs
    seen_indices: List[int] = []
    for para in paragraph_mappings:
        indices = para.get("segment_indices", [])
        if not isinstance(indices, list):
            raise AssertionError(
                f"paragraph has non-list segment_indices: {type(indices).__name__}"
            )
        seen_indices.extend(indices)

    # Check for duplicates
    index_counts: Dict[int, int] = {}
    for idx in seen_indices:
        if not isinstance(idx, int):
            raise AssertionError(
                f"segment_indices contains non-integer: {idx} (type: {type(idx).__name__})"
            )
        index_counts[idx] = index_counts.get(idx, 0) + 1

    duplicates = {idx: count for idx, count in index_counts.items() if count > 1}
    if duplicates:
        dup_str = ", ".join(f"{idx}({count}x)" for idx, count in sorted(duplicates.items()))
        raise AssertionError(f"Duplicate segment_indices found: {dup_str}")

    # Check for missing indices
    expected_set = set(range(n_source_segments))
    actual_set = set(seen_indices)

    if allow_gaps:
        # When gaps allowed, just check that all seen indices are within range
        out_of_range = [idx for idx in seen_indices if idx < 0 or idx >= n_source_segments]
        if out_of_range:
            raise AssertionError(
                f"segment_indices out of range [0, {n_source_segments}): {out_of_range}"
            )
    else:
        # When gaps not allowed, every index must appear exactly once
        missing = sorted(expected_set - actual_set)
        if missing:
            raise AssertionError(
                f"Missing segment_indices: {missing}. "
                f"Expected {n_source_segments} segments, found {len(actual_set)}."
            )
        # Also check for extra indices beyond range
        extra = sorted(actual_set - expected_set)
        if extra:
            raise AssertionError(
                f"Extra segment_indices beyond range [0, {n_source_segments}): {extra}"
            )
