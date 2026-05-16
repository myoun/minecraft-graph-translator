"""Rule-based context assembly for mod language translation."""

from __future__ import annotations

from ..graph import DependencyKind, GraphContext, ModDependency
from ..models import TranslationTask
from .models import (
    ContextCandidate,
    ContextPriority,
    ContextRelation,
    TranslationContext,
)
from .reference_selector import ReferenceSelector
from .reference_store import ModTranslationReferenceStore
from .signals import extract_mod_translation_signal

CORE_MOD_IDS = {"minecraft", "forge", "neoforge", "fabricloader", "fabric", "java"}
INCLUDED_CORE_MOD_IDS = {"minecraft"}
LOW_VALUE_INFRASTRUCTURE_MOD_IDS = {
    "architectury",
    "catalogue",
    "cloth-config",
    "configured",
    "curios",
    "emi",
    "jade",
    "jei",
    "modmenu",
    "rei",
    "wthit",
}


class ModTranslationContextAssembler:
    """Assemble context for mod lang translation.

    This assembler intentionally ignores quest/task/reward/chapter signals.
    Quest context must be assembled by a separate quest-specific pipeline after
    mod translation memory exists.
    """

    def assemble(
        self,
        task: TranslationTask,
        graph_context: GraphContext,
        reference_store: ModTranslationReferenceStore | None = None,
        *,
        max_reference_entries: int = 8,
    ) -> TranslationContext:
        """Assemble context for a single mod language translation task."""
        signal = extract_mod_translation_signal(task)
        target_mod_id = signal.mod_id

        if signal.source_type != "language":
            candidate = ContextCandidate(
                mod_id=target_mod_id or signal.namespace or signal.source_type,
                installed=target_mod_id in graph_context.mods,
                included=False,
                priority=ContextPriority.EXCLUDED,
                relations=[ContextRelation.UNSUPPORTED_SOURCE_TYPE],
                reasons=[
                    "mod translation context only supports language source_type"
                ],
            )
            return TranslationContext(
                target_mod_id=target_mod_id,
                source_type=signal.source_type,
                candidates=[candidate],
                signals=signal,
            )

        candidates: dict[str, ContextCandidate] = {}

        if target_mod_id:
            self._add_relation(
                candidates,
                target_mod_id,
                graph_context,
                ContextRelation.TARGET,
                f"target mod {target_mod_id}",
            )

        for dependency in graph_context.get_dependencies(
            target_mod_id,
            include_optional=True,
            include_incompatible=False,
        ):
            self._add_dependency_candidate(candidates, graph_context, dependency)

        for namespace in sorted(signal.mentioned_namespaces):
            mod_id = graph_context.get_mod_id_for_namespace(namespace) or namespace
            if mod_id == target_mod_id:
                continue
            self._add_relation(
                candidates,
                mod_id,
                graph_context,
                ContextRelation.MENTIONED_NAMESPACE,
                f"namespace mentioned in translation target: {namespace}",
            )

        self._apply_rules(candidates, signal_mod_id=target_mod_id)
        ordered_candidates = sorted(
            candidates.values(),
            key=self._candidate_sort_key,
        )
        reference_mod_ids = [
            candidate.mod_id
            for candidate in ordered_candidates
            if candidate.included and candidate.mod_id != target_mod_id
        ]
        reference_entries = []
        if reference_store is not None:
            reference_entries = ReferenceSelector().select(
                task,
                reference_mod_ids,
                reference_store,
                max_entries=max_reference_entries,
            )

        return TranslationContext(
            target_mod_id=target_mod_id,
            source_type=signal.source_type,
            reference_mod_ids=reference_mod_ids,
            reference_entries=reference_entries,
            candidates=ordered_candidates,
            signals=signal,
        )

    def _add_dependency_candidate(
        self,
        candidates: dict[str, ContextCandidate],
        graph_context: GraphContext,
        dependency: ModDependency,
    ) -> None:
        relation = (
            ContextRelation.REQUIRED_DEPENDENCY
            if dependency.kind == DependencyKind.REQUIRED
            else ContextRelation.OPTIONAL_DEPENDENCY
        )
        if dependency.target_mod_id in CORE_MOD_IDS:
            relation = ContextRelation.CORE_DEPENDENCY

        self._add_relation(
            candidates,
            dependency.target_mod_id,
            graph_context,
            relation,
            (
                f"{dependency.source_mod_id} declares {dependency.kind.value} "
                f"dependency on {dependency.target_mod_id}"
            ),
        )

    def _add_relation(
        self,
        candidates: dict[str, ContextCandidate],
        mod_id: str,
        graph_context: GraphContext,
        relation: ContextRelation,
        reason: str,
    ) -> None:
        candidate = candidates.get(mod_id)
        if candidate is None:
            candidate = ContextCandidate(
                mod_id=mod_id,
                installed=mod_id in graph_context.mods,
            )
            candidates[mod_id] = candidate

        if relation not in candidate.relations:
            candidate.relations.append(relation)
        if reason not in candidate.reasons:
            candidate.reasons.append(reason)

        if mod_id in LOW_VALUE_INFRASTRUCTURE_MOD_IDS:
            if ContextRelation.LOW_VALUE_INFRASTRUCTURE not in candidate.relations:
                candidate.relations.append(ContextRelation.LOW_VALUE_INFRASTRUCTURE)
            reason = f"{mod_id} is low-value infrastructure for terminology context"
            if reason not in candidate.reasons:
                candidate.reasons.append(reason)

    def _apply_rules(
        self,
        candidates: dict[str, ContextCandidate],
        *,
        signal_mod_id: str,
    ) -> None:
        for candidate in candidates.values():
            relations = set(candidate.relations)

            if ContextRelation.TARGET in relations:
                candidate.included = True
                candidate.priority = ContextPriority.TARGET
            elif candidate.mod_id == "minecraft":
                candidate.included = True
                candidate.priority = ContextPriority.MINECRAFT
            elif ContextRelation.LOW_VALUE_INFRASTRUCTURE in relations:
                candidate.included = False
                candidate.priority = ContextPriority.EXCLUDED
            elif ContextRelation.REQUIRED_DEPENDENCY in relations:
                candidate.included = True
                candidate.priority = ContextPriority.REQUIRED
            elif (
                ContextRelation.OPTIONAL_DEPENDENCY in relations
                and candidate.installed
                and (
                    ContextRelation.MENTIONED_NAMESPACE in relations
                    or ContextRelation.REGISTRY_NAMESPACE in relations
                    or ContextRelation.PATH_HINT in relations
                )
            ):
                candidate.included = True
                candidate.priority = ContextPriority.PROMOTED_OPTIONAL
            elif (
                ContextRelation.MENTIONED_NAMESPACE in relations
                and candidate.installed
                and candidate.mod_id != signal_mod_id
            ):
                candidate.included = True
                candidate.priority = ContextPriority.MENTIONED
            elif ContextRelation.CORE_DEPENDENCY in relations:
                candidate.included = candidate.mod_id in INCLUDED_CORE_MOD_IDS
                candidate.priority = (
                    ContextPriority.MINECRAFT
                    if candidate.included
                    else ContextPriority.CORE
                )
            else:
                candidate.included = False
                candidate.priority = ContextPriority.EXCLUDED

    def _candidate_sort_key(
        self,
        candidate: ContextCandidate,
    ) -> tuple[int, str]:
        priority_order = {
            ContextPriority.TARGET: 0,
            ContextPriority.REQUIRED: 1,
            ContextPriority.MINECRAFT: 2,
            ContextPriority.CORE: 3,
            ContextPriority.PROMOTED_OPTIONAL: 4,
            ContextPriority.MENTIONED: 5,
            ContextPriority.EXCLUDED: 6,
        }
        return (priority_order[candidate.priority], candidate.mod_id)
