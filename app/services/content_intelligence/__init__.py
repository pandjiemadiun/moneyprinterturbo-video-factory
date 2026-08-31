"""Content Intelligence Module.

Transforms current/relevant content signals into actionable content opportunities
and structured content hypotheses.

Capabilities:
    1. Trend Radar - collect, normalize, deduplicate trend signals
    2. Opportunity Mining - transform trends into content opportunities
    3. Viral Pattern Analysis - identify viral patterns in content signals
    4. Opportunity Scoring - deterministic, explainable opportunity scoring
    5. Trend -> Content Hypothesis - structured hypotheses for content generation

Data flow:
    Raw Signals -> Normalization -> Trend Detection -> Opportunity Mining
        -> Viral Pattern Analysis -> Opportunity Scoring -> Content Hypothesis
        -> Structured Output -> Content Factory
"""

from app.services.content_intelligence.models import (
    RawSignal,
    NormalizedSignal,
    Trend,
    TrendSource,
    ContentOpportunity,
    ViralPattern,
    ViralPatternType,
    PatternEvidence,
    ScoreDimension,
    OpportunityScore,
    ContentHypothesis,
)
from app.services.content_intelligence.pipeline import ContentIntelligencePipeline
from app.services.content_intelligence.trend_radar import TrendRadar
from app.services.content_intelligence.opportunity_miner import OpportunityMiner
from app.services.content_intelligence.viral_analyzer import ViralAnalyzer
from app.services.content_intelligence.scorer import OpportunityScorer
from app.services.content_intelligence.hypothesis import HypothesisGenerator
from app.services.content_intelligence.provider_base import (
    ContentProvider,
    ProviderCapability,
    ProviderHealth,
    ProviderStatus,
    Freshness,
)
from app.services.content_intelligence.providers import (
    ProviderRegistry,
    create_provider_registry,
)

__all__ = [
    "RawSignal",
    "NormalizedSignal",
    "Trend",
    "TrendSource",
    "ContentOpportunity",
    "ViralPattern",
    "ViralPatternType",
    "PatternEvidence",
    "ScoreDimension",
    "OpportunityScore",
    "ContentHypothesis",
    "ContentIntelligencePipeline",
    "TrendRadar",
    "OpportunityMiner",
    "ViralAnalyzer",
    "OpportunityScorer",
    "HypothesisGenerator",
    "ContentProvider",
    "ProviderCapability",
    "ProviderHealth",
    "ProviderStatus",
    "Freshness",
    "ProviderRegistry",
    "create_provider_registry",
]
