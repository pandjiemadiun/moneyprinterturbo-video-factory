"""Content Factory — production orchestration layer.

Turns validated visual opportunities into actual MPT production jobs.

The factory does NOT duplicate any MPT infrastructure.
It builds a ProductionSpecification from a Phase 12 assessment,
then submits it through the existing MPT task creation pipeline.

Idempotency: the same opportunity always produces the same deterministic
task identity, preventing duplicate production.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.services.content_factory.spec import (
    ProductionSpecification,
    Provenance,
    VisualConceptSpec,
)


# Namespace for deterministic UUID5 task IDs.
_FACTORY_NAMESPACE = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")


@dataclass
class ProductionResult:
    """Result of a production attempt."""

    success: bool = False
    task_id: str = ""
    spec_id: str = ""
    status: str = ""  # created | exists | rejected | failed
    message: str = ""
    errors: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ContentFactory:
    """Orchestrates video production from validated visual opportunities.

    The factory consumes a VisualOpportunityAssessment (from Phase 12)
    and produces an MPT task through the existing pipeline.
    """

    def __init__(self, llm_client: Any = None):
        self.llm_client = llm_client

    def produce(
        self,
        assessment: Any,
        language: str = "id",
        video_aspect: str = "portrait",
        preferred_providers: list[str] | None = None,
    ) -> ProductionResult:
        """Produce a video from a validated visual opportunity.

        Args:
            assessment: VisualOpportunityAssessment from Phase 12.
            language: Target language for the video.
            video_aspect: Target aspect ratio.
            preferred_providers: Override provider preference.

        Returns:
            ProductionResult with task_id and status.
        """
        result = ProductionResult()

        # 1. Validate visual gate (server-side enforcement).
        gate_error = self._validate_visual_gate(assessment)
        if gate_error:
            result.status = "rejected"
            result.message = gate_error
            result.errors.append(gate_error)
            return result

        # 2. Build production specification.
        spec = self._build_specification(
            assessment, language, video_aspect, preferred_providers
        )
        result.spec_id = spec.spec_id

        # 3. Check for existing task (idempotency).
        existing_task_id = self._find_existing_task(spec)
        if existing_task_id:
            result.success = True
            result.task_id = existing_task_id
            result.status = "exists"
            result.message = f"Task already exists: {existing_task_id}"
            return result

        # 4. Create MPT task.
        try:
            task_id = self._create_task(spec)
            result.success = True
            result.task_id = task_id
            result.status = "created"
            result.message = f"Task created: {task_id}"
        except Exception as e:
            result.status = "failed"
            result.message = f"Task creation failed: {e}"
            result.errors.append(str(e))

        return result

    def _validate_visual_gate(self, assessment: Any) -> str | None:
        """Validate that the assessment passed the visual production gate.

        Returns error message if rejected, None if passed.
        """
        from app.services.visual_opportunity.models import VisualFeasibilityStatus

        status = getattr(assessment, "status", None)
        if status is None:
            return "assessment has no status"

        if status == VisualFeasibilityStatus.VISUALLY_PRODUCIBLE:
            return None  # Pass

        # All other statuses are rejected for automatic production.
        if status == VisualFeasibilityStatus.VISUALLY_LIMITED:
            return (
                "topic is VISUALLY_LIMITED: insufficient relevant footage "
                "for automatic production"
            )
        if status == VisualFeasibilityStatus.NOT_VISUALLY_PRODUCIBLE:
            return (
                "topic is NOT_VISUALLY_PRODUCIBLE: no relevant footage found"
            )
        if status == VisualFeasibilityStatus.CHECK_FAILED:
            return "topic CHECK_FAILED: provider/system failure prevented assessment"

        return f"unknown visual gate status: {status}"

    def _build_specification(
        self,
        assessment: Any,
        language: str,
        video_aspect: str,
        preferred_providers: list[str] | None,
    ) -> ProductionSpecification:
        """Build a ProductionSpecification from a visual opportunity assessment."""
        spec = ProductionSpecification()

        topic = getattr(assessment, "topic", "")
        spec.set_field("topic", topic, Provenance.OBSERVED, "assessment.topic")
        spec.set_field(
            "language", language, Provenance.STATIC, "factory.default"
        )
        spec.set_field(
            "visual_aspect", video_aspect, Provenance.STATIC, "factory.default"
        )

        # Visual concepts from assessment.
        concepts = getattr(assessment, "concepts", [])
        visual_concepts: list[VisualConceptSpec] = []
        for c in concepts:
            vc = VisualConceptSpec(
                concept=getattr(c, "term", ""),
                query=getattr(c, "term", ""),
                source=getattr(c, "source", ""),
            )
            visual_concepts.append(vc)
        spec.set_field(
            "visual_concepts", visual_concepts, Provenance.DERIVED, "assessment.concepts"
        )

        # Provider evidence from assessment.
        provider_avail = getattr(assessment, "provider_availability", [])
        for pa in provider_avail:
            provider_name = getattr(pa, "provider", "")
            query = getattr(pa, "query", "")
            rel_counts = getattr(pa, "relevance_counts", {})
            strong = rel_counts.get("STRONG_RELEVANCE", 0)
            partial = rel_counts.get("PARTIAL_RELEVANCE", 0)
            relevant = strong + partial
            # Find matching visual concept and update counts.
            for vc in visual_concepts:
                if vc.concept == query:
                    vc.provider = provider_name
                    vc.relevant_count = relevant
                    vc.strong_count = strong
                    break

        # Scores.
        feasibility_score = getattr(assessment, "feasibility_score", None)
        if feasibility_score:
            spec.set_field(
                "visual_feasibility_score",
                getattr(feasibility_score, "total", 0.0),
                Provenance.DERIVED,
                "assessment.feasibility_score.total",
            )

        spec.set_field(
            "relevance_confidence",
            getattr(assessment, "relevance_confidence", 0.0),
            Provenance.DERIVED,
            "assessment.relevance_confidence",
        )

        # Keywords from visual concepts.
        keywords = [vc.concept for vc in visual_concepts if vc.concept]
        spec.set_field("keywords", keywords, Provenance.DERIVED, "visual_concepts")

        # Script guidance from topic + concepts.
        script_guidance = self._build_script_guidance(topic, visual_concepts)
        spec.set_field(
            "script_guidance", script_guidance, Provenance.DERIVED, "topic+concepts"
        )

        # Scene guidance from visual concepts.
        scene_guidance = self._build_scene_guidance(visual_concepts)
        spec.set_field(
            "scene_guidance", scene_guidance, Provenance.DERIVED, "visual_concepts"
        )

        # Providers.
        if preferred_providers:
            spec.set_field(
                "preferred_providers",
                preferred_providers,
                Provenance.STATIC,
                "user_override",
            )

        # Compute deterministic spec ID.
        spec.spec_id = spec.compute_spec_id()
        spec.set_field("spec_id", spec.spec_id, Provenance.DERIVED, "sha256(topic+concepts)")

        return spec

    def _build_script_guidance(
        self, topic: str, visual_concepts: list[VisualConceptSpec]
    ) -> str:
        """Build script guidance from topic and visual concepts."""
        concept_names = [vc.concept for vc in visual_concepts if vc.concept]
        if concept_names:
            return (
                f"Create a short-form video about '{topic}'. "
                f"Visual concepts to cover: {', '.join(concept_names)}. "
                f"Use these concepts to guide scene selection and narration."
            )
        return f"Create a short-form video about '{topic}'."

    def _build_scene_guidance(
        self, visual_concepts: list[VisualConceptSpec]
    ) -> str:
        """Build scene guidance from visual concepts."""
        lines = []
        for i, vc in enumerate(visual_concepts):
            if vc.concept:
                lines.append(f"Scene {i + 1}: {vc.concept}")
        return "; ".join(lines) if lines else "Use relevant footage for each scene."

    def _find_existing_task(self, spec: ProductionSpecification) -> str | None:
        """Check if a task for this specification already exists.

        Uses the deterministic spec ID to find existing tasks.
        """
        from app.models import const
        from app.services.state import sm

        # Search recent tasks for matching spec ID in params.
        try:
            tasks, _ = sm.state.get_all_tasks(page=1, page_size=200)
            for task in tasks:
                task_params = task.get("params", {})
                # Check if this task was created by the factory with the same spec.
                factory_spec_id = task_params.get("_content_factory_spec_id")
                if factory_spec_id == spec.spec_id:
                    task_state = task.get("state")
                    # Return existing task if it's not failed/cancelled.
                    if task_state not in (
                        const.TASK_STATE_FAILED,
                        const.TASK_STATE_CANCELLED,
                    ):
                        return task.get("task_id")
        except Exception:
            pass
        return None

    def _create_task(self, spec: ProductionSpecification) -> str:
        """Create an MPT task from the production specification.

        Uses the existing MPT task creation infrastructure.
        """
        from app import models
        from app.config import config
        from app.services import utils as service_utils
        from app.services.state import sm
        from app.services.task import start

        # Build VideoParams from specification.
        params = self._build_video_params(spec)

        # Generate deterministic task ID.
        task_id = str(uuid.uuid5(_FACTORY_NAMESPACE, spec.spec_id))

        # Create task state.
        task_params = params.model_dump()
        # Embed spec ID for idempotency tracking.
        task_params["_content_factory_spec_id"] = spec.spec_id
        task_params["_content_factory_topic"] = spec.topic

        sm.state.update_task(
            task_id,
            state=models.const.TASK_STATE_QUEUED,
            params=task_params,
        )

        # Submit to task manager.
        from app.controllers.v1.video import task_manager

        task_manager.add_task(
            start,
            task_id=task_id,
            params=params,
            stop_at="video",
        )

        return task_id

    def _build_video_params(self, spec: ProductionSpecification) -> Any:
        """Build VideoParams from the production specification."""
        from app.models.schema import VideoParams, VideoAspect, VideoConcatMode

        # Map aspect ratio.
        aspect_map = {
            "portrait": VideoAspect.portrait,
            "landscape": VideoAspect.landscape,
            "square": VideoAspect.square,
        }
        aspect = aspect_map.get(spec.visual_aspect, VideoAspect.portrait)

        # Build keywords string.
        keywords_str = ", ".join(spec.keywords) if spec.keywords else spec.topic

        params = VideoParams(
            video_subject=spec.topic,
            video_script="",  # Will be generated by LLM in the pipeline
            video_terms=keywords_str,
            video_aspect=aspect.value,
            video_concat_mode=VideoConcatMode.random.value,
            video_clip_duration=spec.clip_duration,
            video_source=spec.preferred_providers[0] if spec.preferred_providers else "pexels",
            video_sources=spec.preferred_providers,
            video_language=spec.language,
            voice_name="",
            voice_volume=1.0,
            voice_rate=1.0,
            bgm_type="random",
            bgm_volume=0.2,
            subtitle_enabled=True,
            n_threads=2,
            paragraph_number=1,
            video_script_prompt=spec.script_guidance,
            custom_system_prompt=spec.scene_guidance,
        )

        return params


def create_content_factory(llm_client: Any = None) -> ContentFactory:
    """Factory function."""
    return ContentFactory(llm_client=llm_client)
