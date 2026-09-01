"""Tests for the Visual Opportunity Engine.

Covers:
A. Visual query generation (deterministic, dedup, LLM-inferred marking)
B. Provider availability normalization
C. Portrait detection and landscape reframing eligibility
D. Visual feasibility scoring (deterministic, bounded, explainable)
E. Production gate (PRODUCIBLE/LIMITED/NOT_PRODUCIBLE/CHECK_FAILED)
F. Provider failure isolation
G. Cache behavior and provenance
H. No fabricated data
"""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.visual_opportunity.models import (
    CandidateRejectionReason,
    ProviderAvailability,
    VisualCandidate,
    VisualConcept,
    VisualFeasibilityScore,
    VisualFeasibilityStatus,
    VisualOpportunityAssessment,
)
from app.services.visual_opportunity.query_generator import (
    _extract_meaningful_terms,
    _canonicalize,
    generate_visual_queries,
)
from app.services.visual_opportunity.scorer import (
    DEFAULT_WEIGHTS,
    apply_production_gate,
    compute_provider_diversity_score,
    compute_portrait_readiness_score,
    compute_quantity_score,
    compute_scene_diversity_score,
    compute_visual_feasibility,
)
from app.services.visual_opportunity.provider_probe import (
    _classify_candidate,
    _extract_dimensions,
)
from app.services.visual_opportunity.engine import (
    VisualOpportunityEngine,
    create_visual_opportunity_engine,
)
from app.models.schema import MaterialInfo


# ===========================================================================
# A. VISUAL QUERY GENERATION
# ===========================================================================

class TestVisualQueryGeneration(unittest.TestCase):
    """Test deterministic visual query generation."""

    def test_original_topic_retained(self):
        """Original topic must always be the first query."""
        concepts = generate_visual_queries("Top 5 Mountains", category="general", max_queries=5)
        self.assertTrue(len(concepts) > 0)
        self.assertEqual(concepts[0].term, "top 5 mountains")
        self.assertEqual(concepts[0].source, "topic")

    def test_deduplication(self):
        """Duplicate terms must be removed."""
        concepts = generate_visual_queries("mountain mountain mountain", category="general", max_queries=10)
        terms = [c.term for c in concepts]
        self.assertEqual(len(terms), len(set(terms)))

    def test_stopwords_dropped(self):
        """Stopwords should not appear as standalone terms."""
        concepts = generate_visual_queries("the a an", category="general", max_queries=10)
        for c in concepts:
            self.assertNotIn(c.term, {"the", "a", "an"})

    def test_max_queries_respected(self):
        """Number of queries must not exceed max_queries."""
        concepts = generate_visual_queries("technology AI robot", category="technology", max_queries=4)
        self.assertLessEqual(len(concepts), 4)

    def test_category_expansion(self):
        """Category-based visual terms should be included."""
        concepts = generate_visual_queries("AI Health", category="technology", max_queries=10)
        terms = [c.term for c in concepts]
        # At least one category term should appear
        category_terms = {"technology", "computer", "smartphone", "robot", "digital"}
        self.assertTrue(any(t in category_terms for t in terms))

    def test_deterministic(self):
        """Same input must produce same output."""
        c1 = generate_visual_queries("Morning Running", category="health", max_queries=6)
        c2 = generate_visual_queries("Morning Running", category="health", max_queries=6)
        self.assertEqual([c.term for c in c1], [c.term for c in c2])
        self.assertEqual([c.source for c in c1], [c.source for c in c2])

    def test_llm_expansion_marked_inferred(self):
        """LLM-expanded terms must be marked as inferred."""
        mock_llm = MagicMock()
        mock_llm.generate.return_value = "forest trail\nhiking boots\nsummit view"
        # Use a large max_queries so deterministic expansion doesn't fill all slots
        concepts = generate_visual_queries(
            "Mountain", category="general", max_queries=20, llm_client=mock_llm
        )
        inferred = [c for c in concepts if c.source == "inferred"]
        self.assertTrue(len(inferred) > 0)

    def test_llm_failure_graceful(self):
        """LLM failure should not break query generation."""
        mock_llm = MagicMock()
        mock_llm.generate.side_effect = Exception("LLM unavailable")
        concepts = generate_visual_queries(
            "Mountain Hiking", category="general", max_queries=5, llm_client=mock_llm
        )
        # Should still have deterministic queries
        self.assertTrue(len(concepts) > 0)
        self.assertEqual(concepts[0].source, "topic")

    def test_empty_topic(self):
        """Empty topic should return minimal/no concepts."""
        concepts = generate_visual_queries("", category="general", max_queries=5)
        # Should not crash, may return category defaults
        self.assertIsInstance(concepts, list)


# ===========================================================================
# B. PROVIDER AVAILABILITY NORMALIZATION
# ===========================================================================

class TestProviderAvailabilityNormalization(unittest.TestCase):
    """Test provider availability data structures."""

    def test_provider_availability_defaults(self):
        """ProviderAvailability should have safe defaults."""
        pa = ProviderAvailability(provider="pexels", query="mountain")
        self.assertEqual(pa.status, "OK")
        self.assertEqual(pa.raw_count, 0)
        self.assertEqual(pa.usable_count, 0)
        self.assertEqual(pa.rejected_count, 0)
        self.assertIsNotNone(pa.checked_at)

    def test_provider_availability_with_evidence(self):
        """ProviderAvailability should record observed evidence."""
        pa = ProviderAvailability(
            provider="pexels",
            query="mountain",
            status="OK",
            raw_count=20,
            usable_count=15,
            native_portrait_count=5,
            reframable_landscape_count=8,
            rejected_count=5,
            rejection_reasons={"LOW_RESOLUTION": 3, "UNABLE_TO_REFRAME": 2},
        )
        self.assertEqual(pa.usable_count, 15)
        self.assertEqual(pa.rejection_reasons["LOW_RESOLUTION"], 3)


# ===========================================================================
# C. PORTRAIT DETECTION & LANDSCAPE REFRAMING
# ===========================================================================

class TestCandidateClassification(unittest.TestCase):
    """Test candidate orientation detection and reframing eligibility."""

    def _make_info(self, provider, w, h, duration=10):
        return MaterialInfo(
            provider=provider,
            url=f"https://example.com/{provider}/vid.mp4",
            duration=duration,
            source_info={
                "asset_id": "123",
                "source_page": f"https://example.com/{provider}",
                "rendition": {"id": "r1", "width": w, "height": h},
            },
        )

    def test_native_portrait_detected(self):
        """Portrait video (h > w) should be classified as portrait."""
        info = self._make_info("pexels", 1080, 1920)
        candidate = _classify_candidate(info)
        self.assertTrue(candidate.is_portrait)
        self.assertFalse(candidate.is_landscape)
        self.assertIsNone(candidate.rejection_reason)

    def test_landscape_reframable(self):
        """Large landscape video should be eligible for reframing."""
        info = self._make_info("pexels", 1920, 1080)
        candidate = _classify_candidate(info)
        self.assertTrue(candidate.is_landscape)
        self.assertTrue(candidate.is_reframable)
        self.assertIsNone(candidate.rejection_reason)

    def test_landscape_too_small_to_reframe(self):
        """Small landscape video should be rejected."""
        info = self._make_info("pexels", 1280, 720)
        candidate = _classify_candidate(info)
        self.assertTrue(candidate.is_landscape)
        self.assertFalse(candidate.is_reframable)
        self.assertEqual(candidate.rejection_reason, CandidateRejectionReason.UNABLE_TO_REFRAME)

    def test_low_resolution_rejected(self):
        """Low resolution video should be rejected."""
        info = self._make_info("pexels", 320, 240)
        candidate = _classify_candidate(info)
        self.assertEqual(candidate.rejection_reason, CandidateRejectionReason.LOW_RESOLUTION)

    def test_square_accepted(self):
        """Square video should be accepted."""
        info = self._make_info("pexels", 1080, 1080)
        candidate = _classify_candidate(info)
        self.assertTrue(candidate.is_square)
        self.assertIsNone(candidate.rejection_reason)

    def test_extract_dimensions(self):
        """Dimensions should be extracted from source_info."""
        info = self._make_info("pexels", 1920, 1080)
        w, h = _extract_dimensions(info)
        self.assertEqual(w, 1920)
        self.assertEqual(h, 1080)

    def test_extract_dimensions_missing(self):
        """Missing dimensions should return (0, 0)."""
        info = MaterialInfo(provider="pexels", url="http://x.mp4", duration=5)
        w, h = _extract_dimensions(info)
        self.assertEqual(w, 0)
        self.assertEqual(h, 0)


# ===========================================================================
# D. VISUAL FEASIBILITY SCORING
# ===========================================================================

class TestVisualFeasibilityScoring(unittest.TestCase):
    """Test deterministic, bounded, explainable scoring."""

    def _make_concepts(self, terms):
        return [VisualConcept(concept_id=f"vc_{i}", term=t, source="topic", parent_topic="test")
                for i, t in enumerate(terms)]

    def _make_pa(self, provider, query, usable, portrait=0, reframe=0, raw=None, status="OK"):
        raw = raw if raw is not None else usable
        return ProviderAvailability(
            provider=provider, query=query, status=status,
            raw_count=raw, usable_count=usable,
            native_portrait_count=portrait,
            reframable_landscape_count=reframe,
            rejected_count=max(0, raw - usable),
        )

    def test_score_bounded_zero_to_one(self):
        """Score must always be between 0 and 1."""
        concepts = self._make_concepts(["mountain"])
        pa = self._make_pa("pexels", "mountain", usable=100, portrait=50, reframe=50, raw=200)
        score = compute_visual_feasibility(concepts, [pa])
        self.assertGreaterEqual(score.total, 0.0)
        self.assertLessEqual(score.total, 1.0)

    def test_score_deterministic(self):
        """Same inputs must produce same score."""
        concepts = self._make_concepts(["mountain"])
        pa = self._make_pa("pexels", "mountain", usable=10, portrait=3, reframe=5, raw=20)
        s1 = compute_visual_feasibility(concepts, [pa])
        s2 = compute_visual_feasibility(concepts, [pa])
        self.assertAlmostEqual(s1.total, s2.total, places=6)

    def test_higher_evidence_higher_score(self):
        """More evidence should produce higher score."""
        concepts = self._make_concepts(["mountain"])
        pa_low = self._make_pa("pexels", "mountain", usable=2, portrait=0, reframe=1, raw=5)
        pa_high = self._make_pa("pexels", "mountain", usable=20, portrait=8, reframe=10, raw=30)
        s_low = compute_visual_feasibility(concepts, [pa_low])
        s_high = compute_visual_feasibility(concepts, [pa_high])
        self.assertGreater(s_high.total, s_low.total)

    def test_zero_evidence_zero_score(self):
        """No evidence should produce zero score."""
        concepts = self._make_concepts(["mountain"])
        score = compute_visual_feasibility(concepts, [])
        self.assertEqual(score.total, 0.0)

    def test_quantity_score_saturates(self):
        """Quantity score should saturate at high candidate counts."""
        s1 = compute_quantity_score(30)
        s2 = compute_quantity_score(100)
        self.assertAlmostEqual(s1, s2, places=2)
        self.assertLessEqual(s1, 1.0)

    def test_provider_diversity(self):
        """More providers with usable results = higher diversity."""
        pa1 = self._make_pa("pexels", "x", usable=5)
        pa2 = self._make_pa("pixabay", "x", usable=5)
        pa3 = self._make_pa("coverr", "x", usable=5)
        s = compute_provider_diversity_score([pa1, pa2, pa3])
        self.assertAlmostEqual(s, 1.0, places=2)

    def test_explanation_provided(self):
        """Score must include a human-readable explanation."""
        concepts = self._make_concepts(["mountain"])
        pa = self._make_pa("pexels", "mountain", usable=10, portrait=3, reframe=5, raw=20)
        score = compute_visual_feasibility(concepts, [pa])
        self.assertTrue(len(score.explanation) > 0)

    def test_weights_sum_to_one(self):
        """Default weights must sum to 1.0."""
        total = sum(DEFAULT_WEIGHTS.values())
        self.assertAlmostEqual(total, 1.0, places=2)

    def test_components_bounded(self):
        """All component scores must be bounded [0, 1]."""
        concepts = self._make_concepts(["a", "b", "c"])
        pa = self._make_pa("pexels", "a", usable=10, portrait=3, reframe=5, raw=20)
        score = compute_visual_feasibility(concepts, [pa])
        for field in ["quantity_score", "provider_diversity_score",
                       "portrait_readiness_score", "resolution_sufficiency_score",
                       "scene_diversity_score", "provider_health_score"]:
            val = getattr(score, field)
            self.assertGreaterEqual(val, 0.0, f"{field} below 0")
            self.assertLessEqual(val, 1.0, f"{field} above 1")


# ===========================================================================
# E. PRODUCTION GATE
# ===========================================================================

class TestProductionGate(unittest.TestCase):
    """Test the hard production feasibility gate."""

    def _make_score(self, total):
        return VisualFeasibilityScore(total=total)

    def _make_pa(self, provider, query, usable, portrait=0, reframe=0, raw=None, status="OK"):
        raw = raw if raw is not None else usable
        return ProviderAvailability(
            provider=provider, query=query, status=status,
            raw_count=raw, usable_count=usable,
            native_portrait_count=portrait,
            reframable_landscape_count=reframe,
            rejected_count=max(0, raw - usable),
        )

    def test_visually_producible(self):
        """Strong evidence should pass as PRODUCIBLE."""
        score = self._make_score(0.8)
        pa = self._make_pa("pexels", "x", usable=15, portrait=5, reframe=8, raw=20)
        status = apply_production_gate(score, 15, 5, 8, [pa])
        self.assertEqual(status, VisualFeasibilityStatus.VISUALLY_PRODUCIBLE)

    def test_not_producible_low_evidence(self):
        """Low evidence should be NOT_PRODUCIBLE."""
        score = self._make_score(0.1)
        pa = self._make_pa("pexels", "x", usable=1, portrait=0, reframe=0, raw=5)
        status = apply_production_gate(score, 1, 0, 0, [pa])
        self.assertEqual(status, VisualFeasibilityStatus.NOT_VISUALLY_PRODUCIBLE)

    def test_check_failed_all_providers_error(self):
        """All providers failing should be CHECK_FAILED."""
        score = self._make_score(0.0)
        pa = ProviderAvailability(provider="pexels", query="x", status="ERROR", error_message="timeout")
        status = apply_production_gate(score, 0, 0, 0, [pa])
        self.assertEqual(status, VisualFeasibilityStatus.CHECK_FAILED)

    def test_visually_limited(self):
        """Medium evidence should be LIMITED."""
        score = self._make_score(0.4)
        pa = self._make_pa("pexels", "x", usable=5, portrait=1, reframe=2, raw=10)
        status = apply_production_gate(score, 5, 1, 2, [pa])
        self.assertEqual(status, VisualFeasibilityStatus.VISUALLY_LIMITED)

    def test_reframable_landscape_can_produce(self):
        """Enough reframable landscape can make topic producible even with few portrait."""
        score = self._make_score(0.7)
        pa = self._make_pa("pexels", "x", usable=12, portrait=0, reframe=10, raw=20)
        status = apply_production_gate(score, 12, 0, 10, [pa])
        self.assertEqual(status, VisualFeasibilityStatus.VISUALLY_PRODUCIBLE)

    def test_no_providers_not_check_failed(self):
        """No providers queried (empty list) should NOT be CHECK_FAILED."""
        score = self._make_score(0.0)
        status = apply_production_gate(score, 0, 0, 0, [])
        self.assertEqual(status, VisualFeasibilityStatus.NOT_VISUALLY_PRODUCIBLE)


# ===========================================================================
# F. PROVIDER FAILURE ISOLATION
# ===========================================================================

class TestProviderFailureIsolation(unittest.TestCase):
    """Test that one provider failing doesn't kill the whole assessment."""

    def test_partial_provider_failure(self):
        """One provider failing, others succeeding — still usable."""
        ok_pa = ProviderAvailability(
            provider="pexels", query="x", status="OK",
            raw_count=20, usable_count=10, native_portrait_count=3,
            reframable_landscape_count=5,
        )
        fail_pa = ProviderAvailability(
            provider="pixabay", query="x", status="TIMEOUT",
            error_message="request timed out",
        )
        concepts = [VisualConcept(term="x", source="topic", parent_topic="test")]
        score = compute_visual_feasibility(concepts, [ok_pa, fail_pa])
        # Should still have usable candidates from pexels
        self.assertGreater(score.total, 0.0)

    def test_timeout_isolated(self):
        """Timeout on one provider should not affect others."""
        pa1 = ProviderAvailability(provider="pexels", query="x", status="OK",
                                   raw_count=10, usable_count=5, native_portrait_count=2, reframable_landscape_count=3)
        pa2 = ProviderAvailability(provider="pixabay", query="x", status="TIMEOUT", error_message="timeout")
        pa3 = ProviderAvailability(provider="coverr", query="x", status="OK",
                                   raw_count=5, usable_count=2, native_portrait_count=1, reframable_landscape_count=1)
        concepts = [VisualConcept(term="x", source="topic", parent_topic="test")]
        score = compute_visual_feasibility(concepts, [pa1, pa2, pa3])
        # 2 of 3 providers healthy
        self.assertAlmostEqual(score.provider_health_score, 2.0 / 3.0, places=2)


# ===========================================================================
# G. ENGINE INTEGRATION
# ===========================================================================

class TestVisualOpportunityEngine(unittest.TestCase):
    """Test the engine orchestration with mocked providers."""

    def _make_mock_search(self, provider_results):
        """Create a mock search function returning MaterialInfo lists."""
        def mock_search(search_term, minimum_duration=3, video_aspect=None):
            key = search_term.lower().strip()
            return provider_results.get(key, [])
        return mock_search

    def test_engine_assess_topic_structure(self):
        """Engine should produce a well-structured assessment."""
        engine = create_visual_opportunity_engine(
            providers=["pexels"],
            max_opportunities=1,
        )
        engine.max_queries_per_topic = 3

        # Mock the provider search
        mock_results = {
            "mountain": [
                MaterialInfo(provider="pexels", url="http://p/1.mp4", duration=10,
                            source_info={"asset_id": "1", "source_page": "http://p", "rendition": {"width": 1920, "height": 1080}}),
                MaterialInfo(provider="pexels", url="http://p/2.mp4", duration=8,
                            source_info={"asset_id": "2", "source_page": "http://p", "rendition": {"width": 1080, "height": 1920}}),
            ],
        }

        with patch("app.services.visual_opportunity.provider_probe._call_provider_search") as mock_search, \
             patch("app.services.visual_opportunity.engine.get_configured_providers", return_value=["pexels"]):
            mock_search.side_effect = lambda prov, q, md: mock_results.get(q.lower().strip(), [])
            assessment = engine.assess_topic("Mountain Hiking", category="general")

        self.assertIsInstance(assessment, VisualOpportunityAssessment)
        self.assertEqual(assessment.topic, "Mountain Hiking")
        self.assertTrue(len(assessment.concepts) > 0)
        self.assertIsNotNone(assessment.feasibility_score)
        self.assertIn(assessment.status, list(VisualFeasibilityStatus))

    def test_engine_respects_no_fabrication(self):
        """Engine with no provider results should NOT fabricate data."""
        engine = create_visual_opportunity_engine(providers=["pexels"], max_opportunities=1)
        engine.max_queries_per_topic = 2

        with patch("app.services.visual_opportunity.provider_probe._call_provider_search") as mock_search, \
             patch("app.services.visual_opportunity.engine.get_configured_providers", return_value=["pexels"]):
            mock_search.return_value = []  # No results
            assessment = engine.assess_topic("Rare Indonesian Ghost Legend", category="general")

        # Should report zero usable, not fabricate
        self.assertEqual(assessment.total_usable, 0)
        # Score should be low (only provider_health contributes since provider is OK but no results)
        self.assertLess(assessment.feasibility_score.total, 0.3)
        self.assertEqual(assessment.status, VisualFeasibilityStatus.NOT_VISUALLY_PRODUCIBLE)

    def test_engine_provenance_preserved(self):
        """Provider evidence should preserve provenance."""
        engine = create_visual_opportunity_engine(providers=["pexels"], max_opportunities=1)
        engine.max_queries_per_topic = 1

        mock_results = {
            "ocean": [
                MaterialInfo(provider="pexels", url="http://p/ocean.mp4", duration=15,
                            source_info={"asset_id": "abc123", "source_page": "https://pexels.com/abc", "rendition": {"width": 3840, "height": 2160}}),
            ],
        }

        with patch("app.services.visual_opportunity.provider_probe._call_provider_search") as mock_search, \
             patch("app.services.visual_opportunity.engine.get_configured_providers", return_value=["pexels"]):
            mock_search.side_effect = lambda prov, q, md: mock_results.get(q.lower().strip(), [])
            assessment = engine.assess_topic("Ocean Waves", category="general")

        # Check provenance in sample candidates
        all_samples = []
        for pa in assessment.provider_availability:
            all_samples.extend(pa.sample_candidates)

        if all_samples:
            self.assertEqual(all_samples[0].provider, "pexels")
            self.assertEqual(all_samples[0].asset_id, "abc123")
            self.assertTrue(all_samples[0].source_url.startswith("http"))

    def test_engine_caching(self):
        """Engine should respect cache and not re-probe."""
        cache = {}
        engine = create_visual_opportunity_engine(providers=["pexels"], max_opportunities=1)
        engine.max_queries_per_topic = 1
        engine._cache = cache

        call_count = [0]
        def counting_search(prov, q, md):
            call_count[0] += 1
            return []

        with patch("app.services.visual_opportunity.provider_probe._call_provider_search") as mock_search, \
             patch("app.services.visual_opportunity.engine.get_configured_providers", return_value=["pexels"]):
            mock_search.side_effect = counting_search
            engine.assess_topic("Sunset Beach", category="general")
            engine.assess_topic("Sunset Beach", category="general")  # cached

        # Should only have probed once (second call hits cache)
        self.assertEqual(call_count[0], 1)

    def test_engine_force_refresh(self):
        """force_refresh should bypass cache."""
        cache = {}
        engine = create_visual_opportunity_engine(providers=["pexels"], max_opportunities=1)
        engine.max_queries_per_topic = 1
        engine._cache = cache

        call_count = [0]
        def counting_search(prov, q, md):
            call_count[0] += 1
            return []

        with patch("app.services.visual_opportunity.provider_probe._call_provider_search") as mock_search, \
             patch("app.services.visual_opportunity.engine.get_configured_providers", return_value=["pexels"]):
            mock_search.side_effect = counting_search
            engine.assess_topic("Forest Path", category="general")
            engine.assess_topic("Forest Path", category="general", force_refresh=True)

        # Should have probed twice
        self.assertEqual(call_count[0], 2)


if __name__ == "__main__":
    unittest.main()
