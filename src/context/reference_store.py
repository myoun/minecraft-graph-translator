"""Store existing mod language translations for reference context."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..handlers.base import HandlerRegistry
from ..scanner import ScanResult
from .models import ReferenceEntry

logger = logging.getLogger(__name__)


@dataclass
class ModTranslationReferenceStore:
    """Existing mod translations keyed by mod id."""

    references_by_mod: dict[str, list[ReferenceEntry]] = field(default_factory=dict)

    @classmethod
    async def build(
        cls,
        scan_result: ScanResult,
        handler_registry: HandlerRegistry,
    ) -> ModTranslationReferenceStore:
        """Build reference store from paired mod language files."""
        store = cls()

        for pair in scan_result.paired_files:
            if pair.source_type != "language" or pair.target_path is None:
                continue
            if not pair.mod_id:
                continue

            source_handler = handler_registry.get_handler(pair.source_path)
            target_handler = handler_registry.get_handler(pair.target_path)
            if source_handler is None or target_handler is None:
                continue

            try:
                source_data = await source_handler.extract(pair.source_path)
                target_data = await target_handler.extract(pair.target_path)
            except (OSError, ValueError, TypeError, KeyError) as e:
                logger.debug(
                    "Failed to load reference translations for %s: %s",
                    pair.source_path,
                    e,
                )
                continue

            entries: list[ReferenceEntry] = []
            for key, source_text in source_data.items():
                target_text = target_data.get(key)
                if not target_text or not source_text or source_text == target_text:
                    continue

                entries.append(
                    ReferenceEntry(
                        mod_id=pair.mod_id,
                        namespace=pair.namespace,
                        key=key,
                        source_text=source_text,
                        target_text=target_text,
                        source_path=pair.source_path,
                        target_path=pair.target_path,
                    )
                )

            if entries:
                store.references_by_mod.setdefault(pair.mod_id, []).extend(entries)

        logger.info(
            "Loaded %d mod translation reference entries from %d mods",
            sum(len(entries) for entries in store.references_by_mod.values()),
            len(store.references_by_mod),
        )
        return store

    def get_entries(self, mod_ids: list[str]) -> list[ReferenceEntry]:
        """Return reference entries for mod ids in requested order."""
        entries: list[ReferenceEntry] = []
        for mod_id in mod_ids:
            entries.extend(self.references_by_mod.get(mod_id, []))
        return entries

    def get_mod_entry_count(self, mod_id: str) -> int:
        """Return number of reference entries for a mod."""
        return len(self.references_by_mod.get(mod_id, []))
