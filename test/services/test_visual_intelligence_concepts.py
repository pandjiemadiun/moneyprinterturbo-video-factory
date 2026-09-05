"""Regression tests for visual_intelligence.py canonical concept fixes.

These tests protect against:
- Duplicate dictionary keys in VISUAL_CONCEPTS_ID
- Missing required synonyms in the canonical concept entries
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services import visual_intelligence


class TestVisualIntelligenceConcepts:
    """Validate the effective runtime VISUAL_CONCEPTS_ID dictionary."""

    def test_no_duplicate_mengapa_key(self):
        """VISUAL_CONCEPTS_ID must contain exactly one 'mengapa' key."""
        keys = list(visual_intelligence.VISUAL_CONCEPTS_ID.keys())
        assert keys.count("mengapa") == 1, (
            f"Duplicate 'mengapa' key found: {keys.count('mengapa')} occurrences"
        )

    def test_mengapa_includes_because(self):
        """The effective 'mengapa' synonym list must include 'because'."""
        synonyms = visual_intelligence.VISUAL_CONCEPTS_ID["mengapa"]
        assert "because" in synonyms, (
            f"'because' missing from 'mengapa' synonyms: {synonyms}"
        )

    def test_mengapa_surviving_entry_has_expected_synonyms(self):
        """The surviving 'mengapa' entry should contain expected synonyms."""
        synonyms = visual_intelligence.VISUAL_CONCEPTS_ID["mengapa"]
        expected = ["why", "reason", "explanation", "person curious", "because"]
        for term in expected:
            assert term in synonyms, (
                f"Expected synonym '{term}' missing from 'mengapa': {synonyms}"
            )
