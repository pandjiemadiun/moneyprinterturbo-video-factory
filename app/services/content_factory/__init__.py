"""Content Factory.

Turns validated visual opportunities into actual MPT production jobs.
"""

from app.services.content_factory.factory import (
    ContentFactory,
    ProductionResult,
    create_content_factory,
)
from app.services.content_factory.spec import (
    FieldProvenance,
    ProductionSpecification,
    Provenance,
    VisualConceptSpec,
)

__all__ = [
    "ContentFactory",
    "ProductionResult",
    "create_content_factory",
    "ProductionSpecification",
    "VisualConceptSpec",
    "Provenance",
    "FieldProvenance",
]
