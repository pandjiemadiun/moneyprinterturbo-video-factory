"""Visual Opportunity Engine.

Bridges Content Intelligence with real provider probing to produce
visual-feasibility-aware opportunity assessments.
"""

from app.services.visual_opportunity.engine import (
    VisualOpportunityEngine,
    create_visual_opportunity_engine,
)
from app.services.visual_opportunity.models import (
    CandidateRejectionReason,
    ProviderAvailability,
    VisualCandidate,
    VisualConcept,
    VisualFeasibilityScore,
    VisualFeasibilityStatus,
    VisualOpportunityAssessment,
)
from app.services.visual_opportunity.query_generator import generate_visual_queries
from app.services.visual_opportunity.scorer import (
    apply_production_gate,
    compute_visual_feasibility,
)

__all__ = [
    "VisualOpportunityEngine",
    "create_visual_opportunity_engine",
    "generate_visual_queries",
    "compute_visual_feasibility",
    "apply_production_gate",
    "VisualOpportunityAssessment",
    "VisualFeasibilityScore",
    "VisualFeasibilityStatus",
    "VisualCandidate",
    "VisualConcept",
    "ProviderAvailability",
    "CandidateRejectionReason",
]
