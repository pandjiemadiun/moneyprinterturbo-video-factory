"""Content Intelligence Pipeline — end-to-end orchestration.

Orchestrates the complete flow:
    Raw Signals -> Normalization -> Trend Detection -> Opportunity Mining
        -> Viral Pattern Analysis -> Opportunity Scoring -> Content Hypothesis
        -> Structured Output -> Ready for Content Factory
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from loguru import logger

from app.services.content_intelligence.models import (
    ContentHypothesis,
    ContentOpportunity,
    RawSignal,
    Trend,
    TrendSource,
    ViralPattern,
)
from app.services.content_intelligence.trend_radar import TrendRadar
from app.services.content_intelligence.opportunity_miner import OpportunityMiner
from app.services.content_intelligence.viral_analyzer import ViralAnalyzer
from app.services.content_intelligence.scorer import OpportunityScorer
from app.services.content_intelligence.hypothesis import HypothesisGenerator


@dataclass
class PipelineResult:
    """Result of a complete pipeline run.

    Contains all intermediate and final outputs for full traceability.
    """
    trends: list[Trend] = field(default_factory=list)
    opportunities: list[ContentOpportunity] = field(default_factory=list)
    patterns: list[ViralPattern] = field(default_factory=list)
    hypotheses: list[ContentHypothesis] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    success: bool = True

    @property
    def top_hypothesis(self) -> Optional[ContentHypothesis]:
        """Return the highest-confidence hypothesis."""
        if not self.hypotheses:
            return None
        return max(self.hypotheses, key=lambda h: h.confidence)


class ContentIntelligencePipeline:
    """End-to-end Content Intelligence pipeline.

    Coordinates the five capabilities:
    1. Trend Radar
    2. Opportunity Mining
    3. Viral Pattern Analysis
    4. Opportunity Scoring
    5. Trend -> Content Hypothesis
    """

    def __init__(
        self,
        trend_radar: Optional[TrendRadar] = None,
        opportunity_miner: Optional[OpportunityMiner] = None,
        viral_analyzer: Optional[ViralAnalyzer] = None,
        scorer: Optional[OpportunityScorer] = None,
        hypothesis_generator: Optional[HypothesisGenerator] = None,
        llm_client=None,
    ):
        """Initialize the pipeline with optional component overrides.

        If a component is not provided, a default is created. The
        ``llm_client`` is passed to components that can use it for
        semantic enhancement.
        """
        self._radar = trend_radar or TrendRadar()
        self._miner = opportunity_miner or OpportunityMiner(llm_client)
        self._analyzer = viral_analyzer or ViralAnalyzer(llm_client)
        self._scorer = scorer or OpportunityScorer()
        self._generator = hypothesis_generator or HypothesisGenerator(
            llm_client
        )

    def add_signal_provider(
        self, provider: Callable[[], list[RawSignal]]
    ) -> None:
        """Register a raw signal provider with the trend radar."""
        self._radar.add_provider(provider)

    def run(
        self,
        signals: Optional[list[RawSignal]] = None,
    ) -> PipelineResult:
        """Run the complete pipeline.

        If ``signals`` is provided, they are used as input. Otherwise,
        the trend radar collects from registered providers.

        Returns a ``PipelineResult`` with all intermediate and final outputs.
        """
        result = PipelineResult()
        try:
            trends = self._radar.detect_trends(signals)
            result.trends = trends
            if not trends:
                logger.info("pipeline: no trends detected")
                result.errors.append("no_trends_detected")
                return result
            patterns = self._analyzer.analyze_trends(trends)
            result.patterns = patterns
            opportunities = self._miner.mine_opportunities(trends, patterns)
            result.opportunities = opportunities
            if not opportunities:
                logger.info("pipeline: no opportunities mined")
                result.errors.append("no_opportunities_mined")
                return result
            self._scorer.score_opportunities(
                opportunities, trends, patterns
            )
            ranked = self._scorer.rank_opportunities(opportunities)
            hypotheses = self._generator.generate_hypotheses(
                ranked, trends, patterns
            )
            result.hypotheses = hypotheses
            if not hypotheses:
                result.errors.append("no_hypotheses_generated")
            logger.info(
                f"pipeline complete: {len(trends)} trends, "
                f"{len(opportunities)} opportunities, "
                f"{len(patterns)} patterns, "
                f"{len(hypotheses)} hypotheses"
            )
        except Exception as exc:
            logger.exception(f"pipeline failed: {exc}")
            result.success = False
            result.errors.append(str(exc))
        return result

    def run_from_texts(
        self,
        texts: list[str],
        source: TrendSource = TrendSource.MANUAL,
        provider: str = "manual",
    ) -> PipelineResult:
        """Convenience method: run the pipeline from a list of text topics.

        Each text becomes a RawSignal. Useful for testing and for
        user-provided topics.
        """
        signals = [
            RawSignal(
                source=source,
                topic=text,
                provider=provider,
                confidence=0.7,
            )
            for text in texts
            if text and text.strip()
        ]
        return self.run(signals)
