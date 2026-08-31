"""Comprehensive tests for the Content Intelligence module.

Covers:
A. Trend Radar - valid/empty/failure/duplicate/stale/timestamp/source
B. Opportunity Mining - valid/multiple/weak/duplicate/evidence
C. Viral Pattern Analysis - valid/empty/insufficient/malformed/observed-vs-inference
D. Opportunity Scoring - deterministic/boundary/missing/invalid/ranking/explainability
E. Hypothesis Generation - valid/invalid/missing/provider-failure/evidence/schema
F. Integration - complete flow/downstream-compatibility/failure-propagation
G. Regression tests for discovered bugs
"""

import json
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.services.content_intelligence.models import (
    ContentHypothesis,
    ContentOpportunity,
    DimensionScore,
    NormalizedSignal,
    OpportunityScore,
    PatternEvidence,
    RawSignal,
    ScoreDimension,
    Trend,
    TrendSource,
    ViralPattern,
    ViralPatternType,
)
from app.services.content_intelligence.trend_radar import (
    TrendRadar,
    _canonicalize,
    _compute_freshness,
)
from app.services.content_intelligence.opportunity_miner import OpportunityMiner
from app.services.content_intelligence.viral_analyzer import ViralAnalyzer
from app.services.content_intelligence.scorer import (
    DEFAULT_WEIGHTS,
    OpportunityScorer,
    _normalize_weights,
)
from app.services.content_intelligence.hypothesis import HypothesisGenerator
from app.services.content_intelligence.pipeline import (
    ContentIntelligencePipeline,
    PipelineResult,
)


# ===========================================================================
# A. TREND RADAR TESTS
# ===========================================================================

class TestTrendRadarValidProvider(unittest.TestCase):
    """Valid provider response produces trends."""

    def test_single_signal_produces_trend(self):
        radar = TrendRadar()
        signals = [
            RawSignal(
                source=TrendSource.MANUAL,
                topic="AI in healthcare",
                confidence=0.8,
            )
        ]
        trends = radar.detect_trends(signals)
        self.assertEqual(len(trends), 1)
        self.assertEqual(trends[0].topic, "AI in healthcare")
        self.assertEqual(trends[0].signal_count, 1)
        self.assertGreater(trends[0].strength, 0)

    def test_multiple_signals_same_topic_aggregate(self):
        radar = TrendRadar()
        now = datetime.now(timezone.utc)
        signals = [
            RawSignal(
                source=TrendSource.MANUAL,
                topic="AI in healthcare",
                observed_at=now,
                confidence=0.8,
            ),
            RawSignal(
                source=TrendSource.WEB_SEARCH,
                topic="AI in healthcare",
                observed_at=now,
                confidence=0.7,
            ),
        ]
        trends = radar.detect_trends(signals)
        self.assertEqual(len(trends), 1)
        self.assertEqual(trends[0].signal_count, 2)
        self.assertEqual(len(trends[0].sources), 2)

    def test_multiple_topics_produce_multiple_trends(self):
        radar = TrendRadar()
        signals = [
            RawSignal(
                source=TrendSource.MANUAL,
                topic="AI in healthcare",
            ),
            RawSignal(
                source=TrendSource.MANUAL,
                topic="Climate change solutions",
            ),
        ]
        trends = radar.detect_trends(signals)
        self.assertEqual(len(trends), 2)


class TestTrendRadarEmptyResponse(unittest.TestCase):
    """Empty provider response handled gracefully."""

    def test_no_signals_returns_empty(self):
        radar = TrendRadar()
        trends = radar.detect_trends([])
        self.assertEqual(trends, [])

    def test_no_providers_returns_empty(self):
        radar = TrendRadar()
        trends = radar.detect_trends()
        self.assertEqual(trends, [])

    def test_all_empty_topics_returns_empty(self):
        radar = TrendRadar()
        signals = [
            RawSignal(source=TrendSource.MANUAL, topic="   "),
        ]
        trends = radar.detect_trends(signals)
        self.assertEqual(trends, [])


class TestTrendRadarProviderFailure(unittest.TestCase):
    """Provider failure handled gracefully - no fabricated data."""

    def test_failing_provider_returns_empty(self):
        def failing_provider():
            raise ConnectionError("provider unavailable")

        radar = TrendRadar()
        radar.add_provider(failing_provider)
        trends = radar.detect_trends()
        self.assertEqual(trends, [])

    def test_one_failing_one_succeeding_provider(self):
        def failing_provider():
            raise ConnectionError("provider unavailable")

        def succeeding_provider():
            return [
                RawSignal(
                    source=TrendSource.MANUAL,
                    topic="AI trends",
                    confidence=0.8,
                )
            ]

        radar = TrendRadar()
        radar.add_provider(failing_provider)
        radar.add_provider(succeeding_provider)
        trends = radar.detect_trends()
        self.assertEqual(len(trends), 1)
        self.assertEqual(trends[0].topic, "AI trends")


class TestTrendRadarDuplicateTrends(unittest.TestCase):
    """Duplicate trends are deduplicated."""

    def test_equivalent_topics_deduplicated(self):
        radar = TrendRadar()
        signals = [
            RawSignal(
                source=TrendSource.MANUAL,
                topic="AI in Healthcare",
                confidence=0.8,
            ),
            RawSignal(
                source=TrendSource.WEB_SEARCH,
                topic="ai in healthcare",
                confidence=0.7,
            ),
            RawSignal(
                source=TrendSource.SOCIAL,
                topic="  AI in healthcare!  ",
                confidence=0.6,
            ),
        ]
        trends = radar.detect_trends(signals)
        self.assertEqual(len(trends), 1)
        self.assertEqual(trends[0].signal_count, 3)

    def test_different_topics_not_deduplicated(self):
        radar = TrendRadar()
        signals = [
            RawSignal(source=TrendSource.MANUAL, topic="AI healthcare"),
            RawSignal(source=TrendSource.MANUAL, topic="Climate change"),
        ]
        trends = radar.detect_trends(signals)
        self.assertEqual(len(trends), 2)


class TestTrendRadarStaleSignals(unittest.TestCase):
    """Stale signals have lower freshness."""

    def test_recent_signal_higher_freshness(self):
        now = datetime.now(timezone.utc)
        recent = now - timedelta(hours=1)
        stale = now - timedelta(days=7)
        freshness_recent = _compute_freshness(recent, now)
        freshness_stale = _compute_freshness(stale, now)
        self.assertGreater(freshness_recent, freshness_stale)

    def test_very_old_signal_near_zero_freshness(self):
        now = datetime.now(timezone.utc)
        very_old = now - timedelta(days=30)
        freshness = _compute_freshness(very_old, now)
        self.assertLess(freshness, 0.01)


class TestTrendRadarTimestampHandling(unittest.TestCase):
    """Timestamps are preserved correctly."""

    def test_first_and_latest_observed_preserved(self):
        radar = TrendRadar()
        now = datetime.now(timezone.utc)
        earlier = now - timedelta(hours=2)
        signals = [
            RawSignal(
                source=TrendSource.MANUAL,
                topic="AI trends",
                observed_at=earlier,
            ),
            RawSignal(
                source=TrendSource.MANUAL,
                topic="AI trends",
                observed_at=now,
            ),
        ]
        trends = radar.detect_trends(signals)
        self.assertEqual(len(trends), 1)
        self.assertEqual(trends[0].first_observed, earlier)
        self.assertEqual(trends[0].latest_observed, now)


class TestTrendRadarSourceAttribution(unittest.TestCase):
    """Source attribution is preserved."""

    def test_sources_preserved(self):
        radar = TrendRadar()
        signals = [
            RawSignal(
                source=TrendSource.MANUAL,
                topic="AI trends",
                provider="user_input",
            ),
            RawSignal(
                source=TrendSource.WEB_SEARCH,
                topic="AI trends",
                provider="google",
            ),
        ]
        trends = radar.detect_trends(signals)
        self.assertEqual(len(trends), 1)
        self.assertIn(TrendSource.MANUAL, trends[0].sources)
        self.assertIn(TrendSource.WEB_SEARCH, trends[0].sources)
        self.assertIn("user_input", trends[0].providers)
        self.assertIn("google", trends[0].providers)


class TestCanonicalize(unittest.TestCase):
    """Test the canonicalize function."""

    def test_lowercase(self):
        self.assertEqual(_canonicalize("AI TRENDS"), "ai trends")

    def test_punctuation_removed(self):
        self.assertEqual(_canonicalize("ai, trends!"), "ai trends")

    def test_filler_words_removed(self):
        self.assertEqual(
            _canonicalize("the truth about ai"), "truth ai"
        )

    def test_empty_string(self):
        self.assertEqual(_canonicalize(""), "")

    def test_whitespace_only(self):
        self.assertEqual(_canonicalize("   "), "")


# ===========================================================================
# B. OPPORTUNITY MINING TESTS
# ===========================================================================

class TestOpportunityMiningValid(unittest.TestCase):
    """Valid trend produces opportunity."""

    def test_valid_trend_produces_opportunity(self):
        miner = OpportunityMiner()
        trend = Trend(
            trend_id="t1",
            topic="AI in healthcare",
            canonical_key="ai healthcare",
            strength=0.7,
            freshness=0.8,
            confidence=0.8,
            signal_count=3,
            evidence=["signal_count=3"],
        )
        opportunities = miner.mine_opportunities([trend])
        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0].topic, "AI in healthcare")
        self.assertTrue(opportunities[0].audience)
        self.assertTrue(opportunities[0].angle)
        self.assertTrue(opportunities[0].rationale)

    def test_opportunity_not_just_topic_copy(self):
        miner = OpportunityMiner()
        trend = Trend(
            trend_id="t1",
            topic="AI in healthcare",
            canonical_key="ai healthcare",
            strength=0.7,
            freshness=0.8,
            confidence=0.8,
        )
        opportunities = miner.mine_opportunities([trend])
        self.assertNotEqual(opportunities[0].angle, "AI in healthcare")


class TestOpportunityMiningMultiple(unittest.TestCase):
    """Multiple trends produce multiple opportunities."""

    def test_multiple_trends(self):
        miner = OpportunityMiner()
        trends = [
            Trend(
                trend_id="t1",
                topic="AI in healthcare",
                canonical_key="ai healthcare",
                strength=0.7,
                freshness=0.8,
                confidence=0.8,
            ),
            Trend(
                trend_id="t2",
                topic="Climate change",
                canonical_key="climate change",
                strength=0.6,
                freshness=0.7,
                confidence=0.7,
            ),
        ]
        opportunities = miner.mine_opportunities(trends)
        self.assertEqual(len(opportunities), 2)


class TestOpportunityMiningWeakRejection(unittest.TestCase):
    """Weak trends are rejected."""

    def test_very_weak_trend_rejected(self):
        miner = OpportunityMiner()
        trend = Trend(
            trend_id="t1",
            topic="Obscure topic",
            canonical_key="obscure topic",
            strength=0.01,
            freshness=0.01,
            confidence=0.1,
            signal_count=1,
        )
        opportunities = miner.mine_opportunities([trend])
        self.assertEqual(len(opportunities), 0)


class TestOpportunityMiningDuplicate(unittest.TestCase):
    """Duplicate opportunities are avoided."""

    def test_same_topic_not_duplicated(self):
        miner = OpportunityMiner()
        trends = [
            Trend(
                trend_id="t1",
                topic="AI in healthcare",
                canonical_key="ai healthcare",
                strength=0.7,
                freshness=0.8,
                confidence=0.8,
            ),
            Trend(
                trend_id="t2",
                topic="AI in healthcare",
                canonical_key="ai healthcare",
                strength=0.6,
                freshness=0.7,
                confidence=0.7,
            ),
        ]
        opportunities = miner.mine_opportunities(trends)
        self.assertEqual(len(opportunities), 1)


class TestOpportunityMiningEvidence(unittest.TestCase):
    """Evidence is preserved."""

    def test_evidence_preserved(self):
        miner = OpportunityMiner()
        trend = Trend(
            trend_id="t1",
            topic="AI in healthcare",
            canonical_key="ai healthcare",
            strength=0.7,
            freshness=0.8,
            confidence=0.8,
            signal_count=5,
            evidence=["source=web_search", "region=US"],
        )
        opportunities = miner.mine_opportunities([trend])
        self.assertEqual(len(opportunities), 1)
        self.assertIn("source=web_search", opportunities[0].evidence)
        self.assertIn("region=US", opportunities[0].evidence)


# ===========================================================================
# C. VIRAL PATTERN ANALYSIS TESTS
# ===========================================================================

class TestViralPatternValid(unittest.TestCase):
    """Valid analysis produces patterns."""

    def test_question_hook_detected(self):
        analyzer = ViralAnalyzer()
        trends = [
            Trend(
                trend_id="t1",
                topic="Why AI is changing everything",
                canonical_key="ai changing everything",
            )
        ]
        patterns = analyzer.analyze_trends(trends)
        hook_patterns = [
            p for p in patterns
            if p.pattern_type == ViralPatternType.HOOK_STRUCTURE
        ]
        self.assertGreater(len(hook_patterns), 0)

    def test_list_structure_detected(self):
        analyzer = ViralAnalyzer()
        trends = [
            Trend(
                trend_id="t1",
                topic="7 ways to improve productivity",
                canonical_key="7 ways improve productivity",
            )
        ]
        patterns = analyzer.analyze_trends(trends)
        list_patterns = [
            p for p in patterns
            if p.pattern_type == ViralPatternType.LIST_STRUCTURE
        ]
        self.assertGreater(len(list_patterns), 0)

    def test_emotional_framing_detected(self):
        analyzer = ViralAnalyzer()
        trends = [
            Trend(
                trend_id="t1",
                topic="The shocking truth about social media",
                canonical_key="shocking truth social media",
            )
        ]
        patterns = analyzer.analyze_trends(trends)
        emotional_patterns = [
            p for p in patterns
            if p.pattern_type == ViralPatternType.EMOTIONAL_FRAMING
        ]
        self.assertGreater(len(emotional_patterns), 0)


class TestViralPatternEmpty(unittest.TestCase):
    """Empty input handled gracefully."""

    def test_empty_trends(self):
        analyzer = ViralAnalyzer()
        patterns = analyzer.analyze_trends([])
        self.assertEqual(patterns, [])


class TestViralPatternObservedVsInference(unittest.TestCase):
    """Distinction between observed data and inference."""

    def test_observed_evidence_flagged(self):
        analyzer = ViralAnalyzer()
        trends = [
            Trend(
                trend_id="t1",
                topic="Why AI is changing everything",
                canonical_key="ai changing everything",
            )
        ]
        patterns = analyzer.analyze_trends(trends)
        for pattern in patterns:
            for evidence in pattern.evidence:
                self.assertTrue(evidence.is_observed)

    def test_llm_inference_flagged(self):
        """LLM-generated patterns are marked as inference."""

        class FakeLLMClient:
            def generate(self, prompt):
                return json.dumps([
                    {
                        "type": "storytelling",
                        "name": "narrative_arc",
                        "description": "Topic uses narrative arc",
                        "confidence": 0.7,
                    }
                ])

        analyzer = ViralAnalyzer(FakeLLMClient())
        trends = [
            Trend(
                trend_id="t1",
                topic="AI in healthcare",
                canonical_key="ai healthcare",
            )
        ]
        patterns = analyzer.analyze_trends(trends)
        llm_patterns = [
            p for p in patterns
            if p.pattern_type == ViralPatternType.STORYTELLING
        ]
        if llm_patterns:
            for evidence in llm_patterns[0].evidence:
                self.assertFalse(evidence.is_observed)


class TestViralPatternMalformed(unittest.TestCase):
    """Malformed LLM response handled gracefully."""

    def test_invalid_json_response(self):
        class FakeLLMClient:
            def generate(self, prompt):
                return "not valid json"

        analyzer = ViralAnalyzer(FakeLLMClient())
        trends = [
            Trend(
                trend_id="t1",
                topic="AI in healthcare",
                canonical_key="ai healthcare",
            )
        ]
        patterns = analyzer.analyze_trends(trends)
        # Should not crash; LLM patterns should be empty
        llm_patterns = [
            p for p in patterns
            if p.pattern_type == ViralPatternType.STORYTELLING
        ]
        self.assertEqual(len(llm_patterns), 0)

    def test_empty_llm_response(self):
        class FakeLLMClient:
            def generate(self, prompt):
                return ""

        analyzer = ViralAnalyzer(FakeLLMClient())
        trends = [
            Trend(
                trend_id="t1",
                topic="AI in healthcare",
                canonical_key="ai healthcare",
            )
        ]
        patterns = analyzer.analyze_trends(trends)
        self.assertIsInstance(patterns, list)

    def test_invalid_pattern_type(self):
        class FakeLLMClient:
            def generate(self, prompt):
                return json.dumps([
                    {
                        "type": "invalid_type",
                        "name": "bad",
                        "description": "bad pattern",
                        "confidence": 0.5,
                    }
                ])

        analyzer = ViralAnalyzer(FakeLLMClient())
        trends = [
            Trend(
                trend_id="t1",
                topic="AI in healthcare",
                canonical_key="ai healthcare",
            )
        ]
        patterns = analyzer.analyze_trends(trends)
        invalid_patterns = [
            p for p in patterns
            if p.pattern_type == "invalid_type"
        ]
        self.assertEqual(len(invalid_patterns), 0)


# ===========================================================================
# D. OPPORTUNITY SCORING TESTS
# ===========================================================================

class TestScoringDeterministic(unittest.TestCase):
    """Scoring is deterministic."""

    def test_same_input_same_output(self):
        scorer = OpportunityScorer()
        opp = ContentOpportunity(
            opportunity_id="o1",
            topic="AI in healthcare",
            rationale="test",
            audience="tech enthusiasts",
            angle="how ai changes healthcare",
            timeliness="trending now",
            evidence=["test"],
            metadata={"category": "technology", "trend_strength": 0.7},
        )
        score1 = scorer.score_opportunity(opp)
        score2 = scorer.score_opportunity(opp)
        self.assertEqual(score1.total, score2.total)
        self.assertEqual(len(score1.dimensions), len(score2.dimensions))

    def test_all_dimensions_present(self):
        scorer = OpportunityScorer()
        opp = ContentOpportunity(
            opportunity_id="o1",
            topic="AI in healthcare",
            rationale="test",
            audience="tech enthusiasts",
            angle="how ai changes healthcare",
            timeliness="trending now",
            evidence=["test"],
            metadata={"category": "technology", "trend_strength": 0.7},
        )
        score = scorer.score_opportunity(opp)
        dim_names = {d.dimension for d in score.dimensions}
        for expected in ScoreDimension:
            self.assertIn(expected, dim_names)


class TestScoringBoundary(unittest.TestCase):
    """Boundary values handled correctly."""

    def test_score_between_0_and_1(self):
        scorer = OpportunityScorer()
        opp = ContentOpportunity(
            opportunity_id="o1",
            topic="AI in healthcare",
            rationale="test",
            audience="tech enthusiasts",
            angle="how ai changes healthcare",
            timeliness="trending now",
            evidence=["test"],
            metadata={"category": "technology", "trend_strength": 0.7},
        )
        score = scorer.score_opportunity(opp)
        self.assertGreaterEqual(score.total, 0.0)
        self.assertLessEqual(score.total, 1.0)
        for dim in score.dimensions:
            self.assertGreaterEqual(dim.score, 0.0)
            self.assertLessEqual(dim.score, 1.0)

    def test_zero_strength_scores_low(self):
        scorer = OpportunityScorer()
        opp = ContentOpportunity(
            opportunity_id="o1",
            topic="Obscure topic",
            rationale="test",
            audience="general audience",
            angle="test angle",
            timeliness="old",
            evidence=[],
            metadata={"category": "general", "trend_strength": 0.0},
        )
        score = scorer.score_opportunity(opp)
        self.assertLess(score.total, 0.5)


class TestScoringMissingDimensions(unittest.TestCase):
    """Missing dimensions handled gracefully."""

    def test_no_trend_data(self):
        scorer = OpportunityScorer()
        opp = ContentOpportunity(
            opportunity_id="o1",
            topic="AI in healthcare",
            rationale="test",
            audience="tech enthusiasts",
            angle="how ai changes healthcare",
            timeliness="trending now",
            evidence=["test"],
            metadata={"category": "technology"},
        )
        score = scorer.score_opportunity(opp, trend=None)
        self.assertIsNotNone(score)
        self.assertGreaterEqual(score.total, 0.0)


class TestScoringInvalidDimensions(unittest.TestCase):
    """Invalid dimensions rejected."""

    def test_invalid_dimension_score_rejected(self):
        with self.assertRaises(ValueError):
            DimensionScore(
                dimension=ScoreDimension.TREND_STRENGTH,
                score=1.5,
                weight=0.2,
                explanation="test",
            )

    def test_invalid_dimension_weight_rejected(self):
        with self.assertRaises(ValueError):
            DimensionScore(
                dimension=ScoreDimension.TREND_STRENGTH,
                score=0.5,
                weight=1.5,
                explanation="test",
            )


class TestScoringRanking(unittest.TestCase):
    """Opportunities are ranked correctly."""

    def test_higher_strength_ranks_higher(self):
        scorer = OpportunityScorer()
        opp1 = ContentOpportunity(
            opportunity_id="o1",
            topic="Strong trend",
            rationale="test",
            audience="tech enthusiasts",
            angle="test",
            timeliness="trending",
            evidence=[],
            metadata={"category": "technology", "trend_strength": 0.9},
        )
        opp2 = ContentOpportunity(
            opportunity_id="o2",
            topic="Weak trend",
            rationale="test",
            audience="general audience",
            angle="test",
            timeliness="old",
            evidence=[],
            metadata={"category": "general", "trend_strength": 0.1},
        )
        scorer.score_opportunities([opp1, opp2])
        ranked = scorer.rank_opportunities([opp1, opp2])
        self.assertEqual(ranked[0].opportunity_id, "o1")


class TestScoringExplainability(unittest.TestCase):
    """Scores are explainable."""

    def test_explanation_present(self):
        scorer = OpportunityScorer()
        opp = ContentOpportunity(
            opportunity_id="o1",
            topic="AI in healthcare",
            rationale="test",
            audience="tech enthusiasts",
            angle="how ai changes healthcare",
            timeliness="trending now",
            evidence=["test"],
            metadata={"category": "technology", "trend_strength": 0.7},
        )
        score = scorer.score_opportunity(opp)
        self.assertTrue(score.explanation)
        self.assertIn("Total score=", score.explanation)

    def test_dimension_explanations_present(self):
        scorer = OpportunityScorer()
        opp = ContentOpportunity(
            opportunity_id="o1",
            topic="AI in healthcare",
            rationale="test",
            audience="tech enthusiasts",
            angle="how ai changes healthcare",
            timeliness="trending now",
            evidence=["test"],
            metadata={"category": "technology", "trend_strength": 0.7},
        )
        score = scorer.score_opportunity(opp)
        for dim in score.dimensions:
            self.assertTrue(dim.explanation)


class TestNormalizeWeights(unittest.TestCase):
    """Weight normalization works correctly."""

    def test_weights_sum_to_1(self):
        weights = {
            ScoreDimension.TREND_STRENGTH: 0.2,
            ScoreDimension.FRESHNESS: 0.3,
        }
        normalized = _normalize_weights(weights)
        self.assertAlmostEqual(sum(normalized.values()), 1.0)

    def test_zero_weights_default(self):
        weights = {
            ScoreDimension.TREND_STRENGTH: 0.0,
            ScoreDimension.FRESHNESS: 0.0,
        }
        normalized = _normalize_weights(weights)
        self.assertAlmostEqual(sum(normalized.values()), 1.0)


# ===========================================================================
# E. HYPOTHESIS GENERATION TESTS
# ===========================================================================

class TestHypothesisValid(unittest.TestCase):
    """Valid opportunity produces hypothesis."""

    def test_valid_opportunity_produces_hypothesis(self):
        generator = HypothesisGenerator()
        opp = ContentOpportunity(
            opportunity_id="o1",
            topic="AI in healthcare",
            rationale="AI is trending",
            audience="tech enthusiasts",
            angle="how ai changes healthcare",
            timeliness="trending now",
            evidence=["source=web_search"],
            score=OpportunityScore(total=0.7, explanation="good"),
            metadata={"category": "technology"},
        )
        hypothesis = generator.generate_hypothesis(opp)
        self.assertIsNotNone(hypothesis)
        self.assertEqual(hypothesis.topic, "AI in healthcare")
        self.assertTrue(hypothesis.proposed_hook)
        self.assertTrue(hypothesis.content_promise)
        self.assertTrue(hypothesis.format)
        self.assertGreater(hypothesis.confidence, 0)

    def test_hypothesis_has_required_fields(self):
        generator = HypothesisGenerator()
        opp = ContentOpportunity(
            opportunity_id="o1",
            topic="AI in healthcare",
            rationale="AI is trending",
            audience="tech enthusiasts",
            angle="how ai changes healthcare",
            timeliness="trending now",
            evidence=["source=web_search"],
            score=OpportunityScore(total=0.7, explanation="good"),
            metadata={"category": "technology"},
        )
        hypothesis = generator.generate_hypothesis(opp)
        self.assertTrue(hypothesis.topic)
        self.assertTrue(hypothesis.audience)
        self.assertTrue(hypothesis.angle)
        self.assertTrue(hypothesis.proposed_hook)
        self.assertTrue(hypothesis.content_promise)
        self.assertTrue(hypothesis.format)
        self.assertTrue(hypothesis.rationale)


class TestHypothesisInvalidLLMResponse(unittest.TestCase):
    """Invalid LLM response handled gracefully."""

    def test_malformed_json_fallback(self):
        class FakeLLMClient:
            def generate(self, prompt):
                return "not json"

        generator = HypothesisGenerator(FakeLLMClient())
        opp = ContentOpportunity(
            opportunity_id="o1",
            topic="AI in healthcare",
            rationale="test",
            audience="tech enthusiasts",
            angle="how ai changes healthcare",
            timeliness="trending now",
            evidence=[],
            score=OpportunityScore(total=0.7, explanation="good"),
            metadata={"category": "technology"},
        )
        hypothesis = generator.generate_hypothesis(opp)
        self.assertIsNotNone(hypothesis)
        self.assertTrue(hypothesis.proposed_hook)

    def test_empty_llm_response_fallback(self):
        class FakeLLMClient:
            def generate(self, prompt):
                return ""

        generator = HypothesisGenerator(FakeLLMClient())
        opp = ContentOpportunity(
            opportunity_id="o1",
            topic="AI in healthcare",
            rationale="test",
            audience="tech enthusiasts",
            angle="how ai changes healthcare",
            timeliness="trending now",
            evidence=[],
            score=OpportunityScore(total=0.7, explanation="good"),
            metadata={"category": "technology"},
        )
        hypothesis = generator.generate_hypothesis(opp)
        self.assertIsNotNone(hypothesis)


class TestHypothesisMissingFields(unittest.TestCase):
    """Missing required fields handled."""

    def test_no_score_still_generates(self):
        generator = HypothesisGenerator()
        opp = ContentOpportunity(
            opportunity_id="o1",
            topic="AI in healthcare",
            rationale="test",
            audience="tech enthusiasts",
            angle="how ai changes healthcare",
            timeliness="trending now",
            evidence=[],
            score=None,
            metadata={"category": "technology"},
        )
        hypothesis = generator.generate_hypothesis(opp)
        self.assertIsNotNone(hypothesis)


class TestHypothesisProviderFailure(unittest.TestCase):
    """Provider failure handled gracefully."""

    def test_llm_exception_fallback(self):
        class FailingLLMClient:
            def generate(self, prompt):
                raise ConnectionError("LLM unavailable")

        generator = HypothesisGenerator(FailingLLMClient())
        opp = ContentOpportunity(
            opportunity_id="o1",
            topic="AI in healthcare",
            rationale="test",
            audience="tech enthusiasts",
            angle="how ai changes healthcare",
            timeliness="trending now",
            evidence=[],
            score=OpportunityScore(total=0.7, explanation="good"),
            metadata={"category": "technology"},
        )
        hypothesis = generator.generate_hypothesis(opp)
        self.assertIsNotNone(hypothesis)
        self.assertTrue(hypothesis.proposed_hook)


class TestHypothesisEvidence(unittest.TestCase):
    """Evidence is preserved."""

    def test_trend_evidence_preserved(self):
        generator = HypothesisGenerator()
        opp = ContentOpportunity(
            opportunity_id="o1",
            topic="AI in healthcare",
            rationale="test",
            audience="tech enthusiasts",
            angle="how ai changes healthcare",
            timeliness="trending now",
            evidence=["source=web_search", "region=US"],
            score=OpportunityScore(total=0.7, explanation="good"),
            metadata={"category": "technology"},
        )
        hypothesis = generator.generate_hypothesis(opp)
        self.assertIn("source=web_search", hypothesis.trend_evidence)
        self.assertIn("region=US", hypothesis.trend_evidence)


class TestHypothesisSchema(unittest.TestCase):
    """Hypothesis schema validation."""

    def test_confidence_in_valid_range(self):
        with self.assertRaises(ValueError):
            ContentHypothesis(
                hypothesis_id="h1",
                topic="test",
                audience="test",
                angle="test",
                proposed_hook="test",
                content_promise="test",
                format="test",
                confidence=1.5,
            )

    def test_to_script_prompt(self):
        hypothesis = ContentHypothesis(
            hypothesis_id="h1",
            topic="AI in healthcare",
            audience="tech enthusiasts",
            angle="how ai changes healthcare",
            proposed_hook="The truth about AI",
            content_promise="Discover how AI changes healthcare",
            format="explainer",
        )
        prompt = hypothesis.to_script_prompt()
        self.assertIn("AI in healthcare", prompt)
        self.assertIn("how ai changes healthcare", prompt)


# ===========================================================================
# F. INTEGRATION TESTS
# ===========================================================================

class TestIntegrationCompleteFlow(unittest.TestCase):
    """Complete signal -> trend -> opportunity -> score -> hypothesis flow."""

    def test_full_pipeline(self):
        pipeline = ContentIntelligencePipeline()
        result = pipeline.run_from_texts([
            "AI in healthcare",
            "Climate change solutions",
            "Productivity hacks",
        ])
        self.assertTrue(result.success)
        self.assertGreater(len(result.trends), 0)
        self.assertGreater(len(result.opportunities), 0)
        self.assertGreater(len(result.hypotheses), 0)

    def test_pipeline_with_empty_input(self):
        pipeline = ContentIntelligencePipeline()
        result = pipeline.run_from_texts([])
        self.assertTrue(result.success)
        self.assertEqual(len(result.trends), 0)

    def test_pipeline_top_hypothesis(self):
        pipeline = ContentIntelligencePipeline()
        result = pipeline.run_from_texts([
            "AI in healthcare",
            "AI in healthcare",
            "AI in healthcare",
        ])
        if result.hypotheses:
            top = result.top_hypothesis
            self.assertIsNotNone(top)
            self.assertEqual(top.confidence, max(
                h.confidence for h in result.hypotheses
            ))


class TestIntegrationDownstreamCompatibility(unittest.TestCase):
    """Hypothesis output is compatible with downstream content generation."""

    def test_hypothesis_can_convert_to_script_prompt(self):
        pipeline = ContentIntelligencePipeline()
        result = pipeline.run_from_texts(["AI in healthcare"])
        if result.hypotheses:
            prompt = result.hypotheses[0].to_script_prompt()
            self.assertIn("AI in healthcare", prompt)

    def test_hypothesis_has_keywords(self):
        pipeline = ContentIntelligencePipeline()
        result = pipeline.run_from_texts(["AI in healthcare"])
        if result.hypotheses:
            self.assertIsInstance(result.hypotheses[0].keywords, list)


class TestIntegrationFailurePropagation(unittest.TestCase):
    """Failure propagation handled correctly."""

    def test_pipeline_handles_provider_failure(self):
        def failing_provider():
            raise ConnectionError("provider down")

        pipeline = ContentIntelligencePipeline()
        pipeline.add_signal_provider(failing_provider)
        result = pipeline.run()
        self.assertTrue(result.success)
        self.assertIn("no_trends_detected", result.errors)


# ===========================================================================
# G. REGRESSION TESTS
# ===========================================================================

class TestRegressionBugFixes(unittest.TestCase):
    """Regression tests for bugs discovered during implementation."""

    def test_fstring_syntax_in_hypothesis(self):
        """Ensure hypothesis module imports without SyntaxError."""
        from app.services.content_intelligence import hypothesis
        self.assertTrue(hasattr(hypothesis, "HypothesisGenerator"))

    def test_raw_signal_empty_topic_filtered_at_normalization(self):
        """Empty topic in RawSignal is filtered during normalization."""
        from app.services.content_intelligence.trend_radar import TrendRadar
        radar = TrendRadar()
        signal = RawSignal(
            source=TrendSource.MANUAL,
            topic="   ",
        )
        result = radar.normalize_signal(signal)
        self.assertIsNone(result)

    def test_raw_signal_invalid_confidence_rejected(self):
        """Invalid confidence in RawSignal raises ValueError."""
        with self.assertRaises(ValueError):
            RawSignal(
                source=TrendSource.MANUAL,
                topic="test",
                confidence=1.5,
            )

    def test_trend_invalid_confidence_rejected(self):
        """Invalid confidence in Trend raises ValueError."""
        with self.assertRaises(ValueError):
            Trend(
                trend_id="t1",
                topic="test",
                canonical_key="test",
                confidence=-0.1,
            )

    def test_viral_pattern_invalid_confidence_rejected(self):
        """Invalid confidence in ViralPattern raises ValueError."""
        with self.assertRaises(ValueError):
            ViralPattern(
                pattern_type=ViralPatternType.HOOK_STRUCTURE,
                name="test",
                description="test",
                confidence=2.0,
            )

    def test_pipeline_result_default_success(self):
        """PipelineResult defaults to success=True."""
        result = PipelineResult()
        self.assertTrue(result.success)

    def test_pipeline_result_top_hypothesis_empty(self):
        """top_hypothesis returns None when no hypotheses."""
        result = PipelineResult()
        self.assertIsNone(result.top_hypothesis)


if __name__ == "__main__":
    unittest.main()
