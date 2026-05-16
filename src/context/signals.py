"""Signal extraction for translation context assembly."""

from __future__ import annotations

import re
from pathlib import Path

from ..models import TranslationTask
from .models import RegistryId, TranslationContextSignal

REGISTRY_ID_RE = re.compile(r"\b([a-z0-9_.-]+):([a-z0-9_./-]+)\b")
TOKEN_RE = re.compile(r"[a-z0-9_.-]+")
COMPAT_TOKENS = {"compat", "integration", "addon", "bridge", "plugin"}


def extract_mod_translation_signal(task: TranslationTask) -> TranslationContextSignal:
    """Extract signals from a mod language translation task only."""
    file_pair = task.file_pair
    keys = list(task.entries.keys())
    source_texts = [entry.source_text for entry in task.entries.values()]
    source_path = file_pair.source_path

    registry_ids = _extract_registry_ids(keys, source_texts)
    path_tokens = _path_tokens(source_path)
    mentioned_namespaces = {
        registry_id.namespace for registry_id in registry_ids
    }
    mentioned_namespaces.update(_namespaces_from_keys(keys))

    return TranslationContextSignal(
        mod_id=file_pair.mod_id,
        namespace=file_pair.namespace,
        source_type=file_pair.source_type,
        source_path=source_path,
        keys=keys,
        source_texts=source_texts,
        registry_ids=registry_ids,
        mentioned_namespaces=mentioned_namespaces,
        path_tokens=path_tokens,
        compat_path_hint=bool(path_tokens & COMPAT_TOKENS),
    )


def _extract_registry_ids(
    keys: list[str],
    source_texts: list[str],
) -> list[RegistryId]:
    seen: set[str] = set()
    registry_ids: list[RegistryId] = []

    for text in [*keys, *source_texts]:
        for match in REGISTRY_ID_RE.finditer(text.lower()):
            namespace = match.group(1)
            path = match.group(2)
            value = f"{namespace}:{path}"
            if value in seen:
                continue
            seen.add(value)
            registry_ids.append(RegistryId(namespace=namespace, path=path))

    return registry_ids


def _path_tokens(source_path: Path) -> set[str]:
    normalized = source_path.as_posix().lower()
    return set(TOKEN_RE.findall(normalized))


def _namespaces_from_keys(keys: list[str]) -> set[str]:
    namespaces: set[str] = set()
    for key in keys:
        parts = key.lower().split(".")
        if len(parts) >= 2 and parts[0] in {"item", "block", "entity", "tooltip"}:
            namespaces.add(parts[1])
    return namespaces
