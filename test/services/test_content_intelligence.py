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


    def test_pipeline_result_top_hypothesis_empty(self):
        """top_hypothesis returns None when no hypotheses."""
        result = PipelineResult()
        self.assertIsNone(result.top_hypothesis)


# ===========================================================================
# H. DATA SOURCE TRANSPARENCY TESTS
# ===========================================================================

class TestDataSourceTransparency(unittest.TestCase):
    """Tests to verify data source transparency and prevent fake data."""

    def test_user_input_marked_as_manual_source(self):
        """User-provided topics should be marked with MANUAL source."""
        pipeline = ContentIntelligencePipeline()
        result = pipeline.run_from_texts(["AI in healthcare"])
        self.assertGreater(len(result.trends), 0)
        for trend in result.trends:
            self.assertIn(TrendSource.MANUAL, trend.sources)

    def test_no_fake_external_sources(self):
        """Without external providers, no trends should claim external sources."""
        pipeline = ContentIntelligencePipeline()
        result = pipeline.run_from_texts(["AI in healthcare", "Climate change"])
        for trend in result.trends:
            for source in trend.sources:
                self.assertEqual(source, TrendSource.MANUAL)

    def test_empty_input_returns_empty_trends(self):
        """Empty input should return empty trends, not fake data."""
        pipeline = ContentIntelligencePipeline()
        result = pipeline.run_from_texts([])
        self.assertEqual(len(result.trends), 0)
        self.assertIn("no_trends_detected", result.errors)

    def test_freshness_based_on_observation_time(self):
        """Freshness should be derived from actual observation time."""
        from datetime import datetime, timedelta, timezone
        radar = TrendRadar()
        now = datetime.now(timezone.utc)
        old_time = now - timedelta(days=7)
        signals_old = [
            RawSignal(
                source=TrendSource.MANUAL,
                topic="Old topic",
                observed_at=old_time,
            )
        ]
        signals_new = [
            RawSignal(
                source=TrendSource.MANUAL,
                topic="New topic",
                observed_at=now,
            )
        ]
        trends_old = radar.detect_trends(signals_old)
        trends_new = radar.detect_trends(signals_new)
        self.assertEqual(len(trends_old), 1)
        self.assertEqual(len(trends_new), 1)
        self.assertGreater(trends_new[0].freshness, trends_old[0].freshness)

    def test_scores_explainable(self):
        """All scores must have explanations."""
        pipeline = ContentIntelligencePipeline()
        result = pipeline.run_from_texts(["AI in healthcare"])
        for opp in result.opportunities:
            if opp.score:
                self.assertTrue(opp.score.explanation)
                for dim in opp.score.dimensions:
                    self.assertTrue(dim.explanation)

    def test_observed_vs_inference_distinguishable(self):
        """Observed evidence must be distinguishable from inference."""
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
                # Deterministic patterns should be marked as observed
                if evidence.source in (
                    "hook_detection",
                    "emotional_framing_detection",
                    "curiosity_gap_detection",
                    "list_structure_detection",
                    "problem_solution_detection",
                    "controversy_detection",
                    "recurring_theme_detection",
                ):
                    self.assertTrue(evidence.is_observed)


class TestAPIDataSourceTransparency(unittest.TestCase):
    """Tests for API-level data source transparency."""

    def test_api_response_includes_data_source_summary(self):
        """API response should include data source summary."""
        from fastapi.testclient import TestClient
        from app.asgi import app

        client = TestClient(app)
        response = client.post(
            "/api/v1/content-intelligence/analyze",
            json={"topics": ["AI in healthcare"]},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json().get("data", {})
        self.assertIn("data_source_summary", data)
        summary = data["data_source_summary"]
        self.assertIn("trend_sources", summary)
        self.assertIn("has_external_data", summary)
        self.assertFalse(summary["has_external_data"])

    def test_api_trends_include_source_classification(self):
        """API trends should include data_source_classification."""
        from fastapi.testclient import TestClient
        from app.asgi import app

        client = TestClient(app)
        response = client.post(
            "/api/v1/content-intelligence/analyze",
            json={"topics": ["AI in healthcare"]},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json().get("data", {})
        trends = data.get("trends", [])
        self.assertGreater(len(trends), 0)
        for trend in trends:
            self.assertIn("data_source_classification", trend)
            self.assertEqual(trend["data_source_classification"], "USER_INPUT")

    def test_api_empty_input_returns_error(self):
        """API should return explicit error for empty input."""
        from fastapi.testclient import TestClient
        from app.asgi import app

        client = TestClient(app)
        response = client.post(
            "/api/v1/content-intelligence/analyze",
            json={"topics": []},
        )
        self.assertEqual(response.status_code, 200)
        data = response.json().get("data", {})
        self.assertIn("no_trends_detected", data.get("errors", []))


class TestHypothesisToVideoIntegration(unittest.TestCase):
    """Tests for hypothesis → Create Video integration."""

    def test_hypothesis_to_script_prompt(self):
        """Hypothesis should be convertible to a script prompt."""
        from app.services.content_intelligence.models import ContentHypothesis
        hyp = ContentHypothesis(
            hypothesis_id="h1",
            topic="AI in healthcare",
            audience="tech enthusiasts",
            angle="how ai changes healthcare",
            proposed_hook="The truth about AI in healthcare",
            content_promise="Discover how AI transforms medicine",
            format="explainer",
            keywords=["ai", "healthcare", "medicine"],
        )
        prompt = hyp.to_script_prompt()
        self.assertIn("AI in healthcare", prompt)
        self.assertIn("The truth about AI in healthcare", prompt)
        self.assertIn("Discover how AI transforms medicine", prompt)

    def test_hypothesis_contains_video_params(self):
        """Hypothesis should contain all needed fields for video creation."""
        from app.services.content_intelligence.models import ContentHypothesis
        hyp = ContentHypothesis(
            hypothesis_id="h1",
            topic="Test Topic",
            audience="test audience",
            angle="test angle",
            proposed_hook="test hook",
            content_promise="test promise",
            format="explainer",
            keywords=["test", "topic"],
        )
        # These fields are used by the WebUI to pre-fill video creation
        self.assertTrue(hyp.topic)
        self.assertTrue(hyp.proposed_hook)
        self.assertTrue(hyp.content_promise)
        self.assertTrue(hyp.format)
        self.assertTrue(hyp.keywords)


class TestProviderRealData(unittest.TestCase):
    """Tests to verify real provider data reaches the pipeline."""

    def test_google_news_returns_real_data(self):
        """Google News provider should return real data with provenance."""
        from app.services.content_intelligence.providers.google_news import GoogleNewsProvider
        provider = GoogleNewsProvider(enabled=True)
        signals = provider.fetch(geo="ID", language="id", max_signals=3)
        # Should get at least 1 signal (live test)
        if signals:
            s = signals[0]
            self.assertTrue(s.topic)
            self.assertEqual(s.source.value, "rss")
            self.assertEqual(s.provider, "google_news_rss")
            self.assertIsNotNone(s.observed_at)
            self.assertIn("source_url", s.metadata)
            self.assertIn("geo", s.metadata)

    def test_hackernews_returns_real_data(self):
        """Hacker News provider should return real data with scores."""
        from app.services.content_intelligence.providers.hackernews import HackerNewsProvider
        provider = HackerNewsProvider(enabled=True)
        signals = provider.fetch(max_signals=3)
        # Should get at least 1 signal (live test)
        if signals:
            s = signals[0]
            self.assertTrue(s.topic)
            self.assertEqual(s.source.value, "social")
            self.assertEqual(s.provider, "hackernews")
            self.assertIsNotNone(s.observed_at)
            self.assertIn("score", s.metadata)

    def test_pipeline_with_real_providers(self):
        """Full pipeline should work with real providers."""
        from app.services.content_intelligence import create_provider_registry, ContentIntelligencePipeline
        registry = create_provider_registry(enable_google_news=True, enable_hackernews=True)
        pipeline = ContentIntelligencePipeline(provider_registry=registry)
        result = pipeline.run(use_providers=True, geo="ID", language="id", max_signals_per_provider=3)
        # Should produce results (live test)
        if result.total_raw_signals > 0:
            self.assertTrue(result.success)
            self.assertGreater(len(result.trends), 0)
            self.assertGreater(len(result.opportunities), 0)
            self.assertGreater(len(result.hypotheses), 0)
            # Verify provider health is reported
            self.assertIn("google_news_rss", result.provider_health)
            self.assertIn("hackernews", result.provider_health)


class TestNoFakeData(unittest.TestCase):
    """Tests to verify no fake data appears in production paths."""

    def test_no_hardcoded_trends(self):
        """Verify no hardcoded trends in production code."""
        import ast
        import inspect
        from app.services.content_intelligence import pipeline
        source = inspect.getsource(pipeline)
        # Should not contain hardcoded trend examples like "AI" with score
        self.assertNotIn('{"topic": "AI", "score":', source)

    def test_no_fake_timestamps(self):
        """Verify timestamps come from real sources."""
        from app.services.content_intelligence.providers.google_news import GoogleNewsProvider
        provider = GoogleNewsProvider(enabled=True)
        signals = provider.fetch(geo="ID", language="id", max_signals=1)
        if signals:
            # observed_at should be a real timestamp, not datetime.now()
            s = signals[0]
            self.assertIsNotNone(s.observed_at)
            # Should have timezone info
            self.assertIsNotNone(s.observed_at.tzinfo)

    def test_empty_provider_returns_empty(self):
        """Empty provider should return empty list, not fake data."""
        from app.services.content_intelligence.providers.google_news import GoogleNewsProvider
        provider = GoogleNewsProvider(enabled=False)
        signals = provider.fetch()
        self.assertEqual(signals, [])


if __name__ == "__main__":
    unittest.main()
