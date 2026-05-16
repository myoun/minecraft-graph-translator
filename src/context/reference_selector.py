"""Select compact mod translation references for prompt context."""

from __future__ import annotations

import re

from ..models import TranslationTask
from .models import ReferenceBucket, ReferenceEntry, SelectedReferenceEntry
from .reference_store import ModTranslationReferenceStore

TOKEN_RE = re.compile(r"[a-z0-9]+")
CATEGORY_KEYS = {"advancement", "block", "entity", "gui", "item", "tooltip"}


class ReferenceSelector:
    """Select stable, compact reference translations from related mods."""

    def select(
        self,
        task: TranslationTask,
        reference_mod_ids: list[str],
        reference_store: ModTranslationReferenceStore,
        *,
        max_entries: int = 8,
    ) -> list[SelectedReferenceEntry]:
        """Select reference entries for a task."""
        if max_entries <= 0 or not reference_mod_ids:
            return []

        task_keys = list(task.entries.keys())
        task_source_texts = [entry.source_text for entry in task.entries.values()]
        task_key_prefixes = {_key_prefix(key) for key in task_keys}
        task_key_tokens = _tokens(" ".join(task_keys))
        task_text_tokens = _tokens(" ".join(task_source_texts))
        task_categories = {_category(key) for key in task_keys if _category(key)}

        selected_by_identity: dict[tuple[str, str], SelectedReferenceEntry] = {}
        for entry in reference_store.get_entries(reference_mod_ids):
            selected = self._classify_entry(
                entry,
                task_source_texts=task_source_texts,
                task_key_prefixes=task_key_prefixes,
                task_key_tokens=task_key_tokens,
                task_text_tokens=task_text_tokens,
                task_categories=task_categories,
            )
            if selected is None:
                continue

            identity = (entry.mod_id, entry.key)
            existing = selected_by_identity.get(identity)
            if existing is None or _bucket_order(selected.bucket) < _bucket_order(
                existing.bucket
            ):
                selected_by_identity[identity] = selected

        ordered = sorted(
            selected_by_identity.values(),
            key=lambda selected: (
                _bucket_order(selected.bucket),
                -selected.overlap_count,
                selected.entry.mod_id,
                selected.entry.key,
            ),
        )
        return ordered[:max_entries]

    def _classify_entry(
        self,
        entry: ReferenceEntry,
        *,
        task_source_texts: list[str],
        task_key_prefixes: set[str],
        task_key_tokens: set[str],
        task_text_tokens: set[str],
        task_categories: set[str],
    ) -> SelectedReferenceEntry | None:
        if entry.source_text in task_source_texts:
            return SelectedReferenceEntry(
                entry=entry,
                bucket=ReferenceBucket.EXACT_SOURCE,
                overlap_count=1,
                reasons=["source text exactly matches translation target"],
            )

        entry_prefix = _key_prefix(entry.key)
        if entry_prefix in task_key_prefixes:
            return SelectedReferenceEntry(
                entry=entry,
                bucket=ReferenceBucket.SAME_KEY_PREFIX,
                overlap_count=1,
                reasons=[f"same key prefix: {entry_prefix}"],
            )

        entry_key_tokens = _tokens(entry.key)
        key_overlap = task_key_tokens & entry_key_tokens
        if key_overlap:
            return SelectedReferenceEntry(
                entry=entry,
                bucket=ReferenceBucket.KEY_TOKEN_OVERLAP,
                overlap_count=len(key_overlap),
                reasons=[f"key token overlap: {', '.join(sorted(key_overlap))}"],
            )

        entry_text_tokens = _tokens(entry.source_text)
        text_overlap = task_text_tokens & entry_text_tokens
        if text_overlap:
            return SelectedReferenceEntry(
                entry=entry,
                bucket=ReferenceBucket.TEXT_TOKEN_OVERLAP,
                overlap_count=len(text_overlap),
                reasons=[f"text token overlap: {', '.join(sorted(text_overlap))}"],
            )

        entry_category = _category(entry.key)
        if entry_category and entry_category in task_categories:
            return SelectedReferenceEntry(
                entry=entry,
                bucket=ReferenceBucket.SAME_CATEGORY,
                overlap_count=1,
                reasons=[f"same key category: {entry_category}"],
            )

        if entry.namespace == entry.mod_id:
            return SelectedReferenceEntry(
                entry=entry,
                bucket=ReferenceBucket.NAMESPACE_REFERENCE,
                overlap_count=0,
                reasons=[f"namespace reference for {entry.namespace}"],
            )

        return None


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in TOKEN_RE.findall(text.lower())
        if len(token) > 1 and not token.isdigit()
    }


def _key_prefix(key: str) -> str:
    parts = key.lower().split(".")
    if len(parts) >= 3:
        return ".".join(parts[:3])
    return key.lower()


def _category(key: str) -> str:
    category = key.lower().split(".", 1)[0]
    return category if category in CATEGORY_KEYS else ""


def _bucket_order(bucket: ReferenceBucket) -> int:
    order = {
        ReferenceBucket.EXACT_SOURCE: 0,
        ReferenceBucket.SAME_KEY_PREFIX: 1,
        ReferenceBucket.KEY_TOKEN_OVERLAP: 2,
        ReferenceBucket.TEXT_TOKEN_OVERLAP: 3,
        ReferenceBucket.SAME_CATEGORY: 4,
        ReferenceBucket.NAMESPACE_REFERENCE: 5,
    }
    return order[bucket]
