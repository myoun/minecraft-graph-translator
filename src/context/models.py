"""Models for translation context assembly."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class ContextRelation(str, Enum):
    """Why a mod is considered as translation context."""

    TARGET = "target"
    REQUIRED_DEPENDENCY = "required_dependency"
    OPTIONAL_DEPENDENCY = "optional_dependency"
    CORE_DEPENDENCY = "core_dependency"
    MENTIONED_NAMESPACE = "mentioned_namespace"
    REGISTRY_NAMESPACE = "registry_namespace"
    PATH_HINT = "path_hint"
    LOW_VALUE_INFRASTRUCTURE = "low_value_infrastructure"
    UNSUPPORTED_SOURCE_TYPE = "unsupported_source_type"


class ContextPriority(str, Enum):
    """Stable ordering bucket for context candidates."""

    TARGET = "target"
    REQUIRED = "required"
    MINECRAFT = "minecraft"
    CORE = "core"
    PROMOTED_OPTIONAL = "promoted_optional"
    MENTIONED = "mentioned"
    EXCLUDED = "excluded"


class ReferenceBucket(str, Enum):
    """Priority bucket for selected reference translations."""

    EXACT_SOURCE = "exact_source"
    SAME_KEY_PREFIX = "same_key_prefix"
    KEY_TOKEN_OVERLAP = "key_token_overlap"
    TEXT_TOKEN_OVERLAP = "text_token_overlap"
    SAME_CATEGORY = "same_category"
    NAMESPACE_REFERENCE = "namespace_reference"


class RegistryId(BaseModel):
    """A namespaced Minecraft registry id such as `create:shaft`."""

    namespace: str
    path: str

    @property
    def value(self) -> str:
        """Return the full `namespace:path` value."""
        return f"{self.namespace}:{self.path}"


class TranslationContextSignal(BaseModel):
    """Signals extracted from a mod language translation target.

    Quest-derived fields are intentionally absent. Mod translation context must
    never use quest title/task/reward/dependency signals.
    """

    mod_id: str = ""
    namespace: str = ""
    source_type: str = ""
    source_path: Path
    keys: list[str] = Field(default_factory=list)
    source_texts: list[str] = Field(default_factory=list)
    registry_ids: list[RegistryId] = Field(default_factory=list)
    mentioned_namespaces: set[str] = Field(default_factory=set)
    path_tokens: set[str] = Field(default_factory=set)
    compat_path_hint: bool = False


class ContextCandidate(BaseModel):
    """A possible mod translation reference and its rule evidence."""

    mod_id: str
    installed: bool = False
    included: bool = False
    priority: ContextPriority = ContextPriority.EXCLUDED
    relations: list[ContextRelation] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class TranslationContext(BaseModel):
    """Assembled graph-aware context for a translation target."""

    target_mod_id: str = ""
    source_type: str = ""
    reference_mod_ids: list[str] = Field(default_factory=list)
    reference_entries: list[SelectedReferenceEntry] = Field(default_factory=list)
    candidates: list[ContextCandidate] = Field(default_factory=list)
    signals: TranslationContextSignal


class ReferenceEntry(BaseModel):
    """Existing source/target translation pair from a mod lang file."""

    mod_id: str
    namespace: str = ""
    key: str
    source_text: str
    target_text: str
    source_path: Path
    target_path: Path


class SelectedReferenceEntry(BaseModel):
    """Reference entry selected for prompt context with evidence."""

    entry: ReferenceEntry
    bucket: ReferenceBucket
    overlap_count: int = 0
    reasons: list[str] = Field(default_factory=list)
