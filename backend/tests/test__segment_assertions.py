"""
Tests for _segment_assertions helper.

Tests the assert_segment_coverage helper function.
"""
import pytest
from tests._segment_assertions import assert_segment_coverage


def test_segment_coverage_clean_passing_mapping():
    """Test that a clean mapping covering all indices passes."""
    paragraph_mappings = [
        {"segment_indices": [0, 1, 2], "id": "para1"},
        {"segment_indices": [3, 4, 5], "id": "para2"},
    ]
    # Should pass - covers 0-5 exactly once each
    assert_segment_coverage(paragraph_mappings, n_source_segments=6)


def test_segment_coverage_missing_index_fails():
    """Test that a mapping missing index 3 fails."""
    paragraph_mappings = [
        {"segment_indices": [0, 1, 2], "id": "para1"},
        {"segment_indices": [4, 5], "id": "para2"},  # Missing 3
    ]
    with pytest.raises(AssertionError) as excinfo:
        assert_segment_coverage(paragraph_mappings, n_source_segments=6)
    assert "Missing segment_indices: [3]" in str(excinfo.value)


def test_segment_coverage_duplicate_index_fails():
    """Test that a mapping with duplicate index 2 fails."""
    paragraph_mappings = [
        {"segment_indices": [0, 1, 2], "id": "para1"},
        {"segment_indices": [2, 3, 4, 5], "id": "para2"},  # 2 appears twice
    ]
    with pytest.raises(AssertionError) as excinfo:
        assert_segment_coverage(paragraph_mappings, n_source_segments=6)
    assert "Duplicate segment_indices" in str(excinfo.value)
    assert "2(2x)" in str(excinfo.value)


def test_segment_coverage_extra_index_fails():
    """Test that a mapping with index beyond range fails.

    Note: If there's both a missing index AND an extra index, the missing
    error is reported first. This test uses a mapping that has no gaps
    but has an extra index.
    """
    paragraph_mappings = [
        {"segment_indices": [0, 1, 2], "id": "para1"},
        {"segment_indices": [3, 4, 5, 10], "id": "para2"},  # 10 is out of range
    ]
    with pytest.raises(AssertionError) as excinfo:
        assert_segment_coverage(paragraph_mappings, n_source_segments=6)
    assert "Extra segment_indices" in str(excinfo.value)
    assert "10" in str(excinfo.value)


def test_segment_coverage_allow_gaps():
    """Test allow_gaps=True permits missing indices."""
    paragraph_mappings = [
        {"segment_indices": [0, 1], "id": "para1"},
        {"segment_indices": [4, 5], "id": "para2"},  # Gap: 2,3 missing
    ]
    # Should pass when gaps allowed
    assert_segment_coverage(paragraph_mappings, n_source_segments=6, allow_gaps=True)


def test_segment_coverage_allow_gaps_still_rejects_duplicates():
    """Test that allow_gaps=True still rejects duplicates."""
    paragraph_mappings = [
        {"segment_indices": [0, 1, 1], "id": "para1"},  # Duplicate 1
    ]
    with pytest.raises(AssertionError) as excinfo:
        assert_segment_coverage(paragraph_mappings, n_source_segments=6, allow_gaps=True)
    assert "Duplicate segment_indices" in str(excinfo.value)


def test_segment_coverage_allow_gaps_still_rejects_out_of_range():
    """Test that allow_gaps=True still rejects out-of-range indices."""
    paragraph_mappings = [
        {"segment_indices": [0, 1, 10], "id": "para1"},  # 10 is out of range
    ]
    with pytest.raises(AssertionError) as excinfo:
        assert_segment_coverage(paragraph_mappings, n_source_segments=6, allow_gaps=True)
    assert "out of range" in str(excinfo.value)


def test_segment_coverage_empty_mappings():
    """Test empty mappings with n=0 passes."""
    assert_segment_coverage([], n_source_segments=0)


def test_segment_coverage_empty_mappings_with_n_fails():
    """Test empty mappings with n>0 fails."""
    with pytest.raises(AssertionError) as excinfo:
        assert_segment_coverage([], n_source_segments=3)
    assert "Missing segment_indices: [0, 1, 2]" in str(excinfo.value)


def test_segment_coverage_non_list_indices_fails():
    """Test that non-list segment_indices raises AssertionError."""
    paragraph_mappings = [
        {"segment_indices": "not-a-list", "id": "para1"},
    ]
    with pytest.raises(AssertionError) as excinfo:
        assert_segment_coverage(paragraph_mappings, n_source_segments=3)
    assert "non-list segment_indices" in str(excinfo.value)


def test_segment_coverage_non_integer_index_fails():
    """Test that non-integer in segment_indices raises AssertionError."""
    paragraph_mappings = [
        {"segment_indices": [0, 1, "two"], "id": "para1"},
    ]
    with pytest.raises(AssertionError) as excinfo:
        assert_segment_coverage(paragraph_mappings, n_source_segments=3)
    assert "non-integer" in str(excinfo.value)
