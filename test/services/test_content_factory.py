"""Tests for the Content Factory."""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.content_factory import (
    ContentFactory,
    ProductionResult,
    ProductionSpecification,
    VisualConceptSpec,
    Provenance,
    create_content_factory,
)
from app.services.visual_opportunity.models import (
    VisualConcept,
    VisualFeasibilityScore,
    VisualFeasibilityStatus,
    VisualOpportunityAssessment,
    ProviderAvailability,
)


def _make_assessment(
    topic: str = "mountain landscape",
    status: VisualFeasibilityStatus = VisualFeasibilityStatus.VISUALLY_PRODUCIBLE,
    relevance_confidence: float = 0.7,
    feasibility_score: float = 0.8,
) -> VisualOpportunityAssessment:
    """Create a mock assessment for testing."""
    assessment = VisualOpportunityAssessment(
        topic=topic,
        status=status,
        relevance_confidence=relevance_confidence,
    )
    assessment.feasibility_score = VisualFeasibilityScore(total=feasibility_score)
    assessment.concepts = [
        VisualConcept(concept_id="vc_001", term="mountain", source="topic", parent_topic=topic),
        VisualConcept(concept_id="vc_002", term="landscape", source="topic", parent_topic=topic),
    ]
    assessment.provider_availability = [
        ProviderAvailability(
            provider="pexels", query="mountain", status="OK",
            raw_count=20, usable_count=15,
            relevance_counts={"STRONG_RELEVANCE": 10, "PARTIAL_RELEVANCE": 5},
        ),
    ]
    return assessment


class TestProductionSpecification(unittest.TestCase):
    """Test ProductionSpecification."""

    def test_compute_spec_id_deterministic(self):
        """Same topic + concepts should always produce same spec ID."""
        spec1 = ProductionSpecification(topic="mountain landscape")
        spec1.visual_concepts = [VisualConceptSpec(concept="mountain"), VisualConceptSpec(concept="landscape")]
        spec1.spec_id = spec1.compute_spec_id()

        spec2 = ProductionSpecification(topic="mountain landscape")
        spec2.visual_concepts = [VisualConceptSpec(concept="landscape"), VisualConceptSpec(concept="mountain")]
        spec2.spec_id = spec2.compute_spec_id()

        self.assertEqual(spec1.spec_id, spec2.spec_id)

    def test_compute_spec_id_different_topics(self):
        """Different topics should produce different spec IDs."""
        spec1 = ProductionSpecification(topic="mountain")
        spec1.spec_id = spec1.compute_spec_id()

        spec2 = ProductionSpecification(topic="ocean")
        spec2.spec_id = spec2.compute_spec_id()

        self.assertNotEqual(spec1.spec_id, spec2.spec_id)

    def test_provenance_tracking(self):
        """Fields should track their provenance."""
        spec = ProductionSpecification()
        spec.set_field("topic", "mountain", Provenance.OBSERVED, "assessment.topic")

        prov = spec.get_provenance("topic")
        self.assertIsNotNone(prov)
        self.assertEqual(prov.provenance, Provenance.OBSERVED)
        self.assertEqual(prov.source, "assessment.topic")

    def test_to_dict(self):
        """Specification should serialize to dict."""
        spec = ProductionSpecification(topic="mountain landscape")
        spec.visual_concepts = [VisualConceptSpec(concept="mountain", relevant_count=10)]
        spec.spec_id = spec.compute_spec_id()

        d = spec.to_dict()
        self.assertEqual(d["topic"], "mountain landscape")
        self.assertIn("visual_concepts", d)
        self.assertIn("spec_id", d)


class TestContentFactoryGateEnforcement(unittest.TestCase):
    """Test that the factory enforces the visual gate."""

    def setUp(self):
        self.factory = create_content_factory()

    def test_visually_producible_accepted(self):
        """VISUALLY_PRODUCIBLE should pass the gate."""
        assessment = _make_assessment(status=VisualFeasibilityStatus.VISUALLY_PRODUCIBLE)
        error = self.factory._validate_visual_gate(assessment)
        self.assertIsNone(error)

    def test_visually_limited_rejected(self):
        """VISUALLY_LIMITED should be rejected."""
        assessment = _make_assessment(status=VisualFeasibilityStatus.VISUALLY_LIMITED)
        error = self.factory._validate_visual_gate(assessment)
        self.assertIsNotNone(error)
        self.assertIn("LIMITED", error)

    def test_not_producible_rejected(self):
        """NOT_VISUALLY_PRODUCIBLE should be rejected."""
        assessment = _make_assessment(status=VisualFeasibilityStatus.NOT_VISUALLY_PRODUCIBLE)
        error = self.factory._validate_visual_gate(assessment)
        self.assertIsNotNone(error)
        self.assertIn("NOT_VISUALLY_PRODUCIBLE", error)

    def test_check_failed_rejected(self):
        """CHECK_FAILED should be rejected."""
        assessment = _make_assessment(status=VisualFeasibilityStatus.CHECK_FAILED)
        error = self.factory._validate_visual_gate(assessment)
        self.assertIsNotNone(error)
        self.assertIn("CHECK_FAILED", error)

    def test_produce_rejects_limited(self):
        """Produce should return rejected status for LIMITED."""
        assessment = _make_assessment(status=VisualFeasibilityStatus.VISUALLY_LIMITED)
        result = self.factory.produce(assessment)
        self.assertFalse(result.success)
        self.assertEqual(result.status, "rejected")

    def test_produce_rejects_not_producible(self):
        """Produce should return rejected status for NOT_PRODUCIBLE."""
        assessment = _make_assessment(status=VisualFeasibilityStatus.NOT_VISUALLY_PRODUCIBLE)
        result = self.factory.produce(assessment)
        self.assertFalse(result.success)
        self.assertEqual(result.status, "rejected")


class TestContentFactorySpecification(unittest.TestCase):
    """Test specification building."""

    def setUp(self):
        self.factory = create_content_factory()

    def test_build_specification(self):
        """Factory should build a valid specification from assessment."""
        assessment = _make_assessment()
        spec = self.factory._build_specification(assessment, "id", "portrait", None)

        self.assertEqual(spec.topic, "mountain landscape")
        self.assertEqual(spec.language, "id")
        self.assertEqual(spec.visual_aspect, "portrait")
        self.assertTrue(len(spec.visual_concepts) > 0)
        self.assertTrue(len(spec.keywords) > 0)
        self.assertGreater(spec.visual_feasibility_score, 0)
        self.assertGreater(spec.relevance_confidence, 0)

    def test_build_specification_with_providers(self):
        """Factory should respect provider overrides."""
        assessment = _make_assessment()
        spec = self.factory._build_specification(assessment, "id", "portrait", ["pexels"])

        self.assertEqual(spec.preferred_providers, ["pexels"])

    def test_spec_id_computed(self):
        """Specification should have a computed spec ID."""
        assessment = _make_assessment()
        spec = self.factory._build_specification(assessment, "id", "portrait", None)

        self.assertTrue(len(spec.spec_id) > 0)


class TestContentFactoryIdempotency(unittest.TestCase):
    """Test idempotent production."""

    def test_same_opportunity_same_spec_id(self):
        """Same opportunity should always produce same spec ID."""
        factory = create_content_factory()
        assessment = _make_assessment()

        spec1 = factory._build_specification(assessment, "id", "portrait", None)
        spec2 = factory._build_specification(assessment, "id", "portrait", None)

        self.assertEqual(spec1.spec_id, spec2.spec_id)


class TestContentFactoryVideoParams(unittest.TestCase):
    """Test VideoParams construction."""

    def setUp(self):
        self.factory = create_content_factory()

    def test_build_video_params(self):
        """Factory should build valid VideoParams."""
        assessment = _make_assessment()
        spec = self.factory._build_specification(assessment, "id", "portrait", None)
        params = self.factory._build_video_params(spec)

        self.assertEqual(params.video_subject, "mountain landscape")
        self.assertEqual(params.video_language, "id")
        self.assertIsNotNone(params.video_aspect)

    def test_build_video_params_landscape(self):
        """Factory should respect landscape aspect."""
        assessment = _make_assessment()
        spec = self.factory._build_specification(assessment, "id", "landscape", None)
        params = self.factory._build_video_params(spec)

        from app.models.schema import VideoAspect
        self.assertEqual(params.video_aspect, VideoAspect.landscape.value)


if __name__ == "__main__":
    unittest.main()
