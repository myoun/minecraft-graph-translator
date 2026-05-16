"""Models for Minecraft mod dependency metadata."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class ModLoader(str, Enum):
    """Supported Minecraft mod loaders."""

    FABRIC = "fabric"
    FORGE = "forge"
    NEOFORGE = "neoforge"
    LEGACY_FORGE = "legacy_forge"
    UNKNOWN = "unknown"


class DependencyKind(str, Enum):
    """Dependency relationship type normalized across loaders."""

    REQUIRED = "required"
    OPTIONAL = "optional"
    SUGGESTED = "suggested"
    INCOMPATIBLE = "incompatible"


class ModDependency(BaseModel):
    """A dependency edge between two mods."""

    source_mod_id: str = Field(..., description="Mod declaring the dependency")
    target_mod_id: str = Field(..., description="Referenced mod id")
    kind: DependencyKind = Field(..., description="Normalized dependency kind")
    version_requirement: str | None = Field(
        default=None,
        description="Loader-specific version requirement, if declared",
    )
    ordering: str | None = Field(
        default=None,
        description="Forge/NeoForge ordering hint such as BEFORE, AFTER, or NONE",
    )
    side: str | None = Field(
        default=None,
        description="Forge/NeoForge physical side such as CLIENT, SERVER, or BOTH",
    )

    @property
    def optional(self) -> bool:
        """Return whether this dependency is non-required."""
        return self.kind in {
            DependencyKind.OPTIONAL,
            DependencyKind.SUGGESTED,
            DependencyKind.INCOMPATIBLE,
        }


class ModInfo(BaseModel):
    """Normalized metadata for a single Minecraft mod."""

    mod_id: str = Field(..., description="Loader mod id")
    name: str = Field(default="", description="Human-readable mod name")
    version: str = Field(default="", description="Declared mod version")
    namespace: str = Field(default="", description="Primary resource namespace")
    loader: ModLoader = Field(default=ModLoader.UNKNOWN, description="Mod loader")
    source_path: Path = Field(..., description="Jar or metadata file path")
    metadata_path: str = Field(
        default="",
        description="Metadata entry path inside the jar, or file path",
    )
    description: str = Field(default="", description="Declared mod description")
    dependencies: list[ModDependency] = Field(default_factory=list)


class GraphContext(BaseModel):
    """Dependency graph metadata available to the translation pipeline."""

    mods: dict[str, ModInfo] = Field(default_factory=dict)

    @property
    def namespace_to_mod_id(self) -> dict[str, str]:
        """Build a lookup from resource namespace to mod id."""
        lookup: dict[str, str] = {}
        for mod_id, mod in self.mods.items():
            if mod.namespace:
                lookup[mod.namespace] = mod_id
            lookup.setdefault(mod_id, mod_id)
        return lookup

    @property
    def jar_to_mod_ids(self) -> dict[str, list[str]]:
        """Build a lookup from jar filename to declared mod ids."""
        lookup: dict[str, list[str]] = {}
        for mod_id, mod in self.mods.items():
            lookup.setdefault(mod.source_path.name, []).append(mod_id)
        return lookup

    @property
    def dependencies(self) -> list[ModDependency]:
        """Flatten all dependency edges."""
        return [
            dependency
            for mod in self.mods.values()
            for dependency in mod.dependencies
        ]

    def get_dependencies(
        self,
        mod_id: str,
        *,
        include_optional: bool = True,
        include_incompatible: bool = False,
    ) -> list[ModDependency]:
        """Get dependencies declared by a mod."""
        mod = self.mods.get(mod_id)
        if mod is None:
            return []

        dependencies = mod.dependencies
        if not include_optional:
            dependencies = [
                dependency
                for dependency in dependencies
                if dependency.kind == DependencyKind.REQUIRED
            ]
        if not include_incompatible:
            dependencies = [
                dependency
                for dependency in dependencies
                if dependency.kind != DependencyKind.INCOMPATIBLE
            ]
        return dependencies

    def get_mod_id_for_namespace(self, namespace: str) -> str | None:
        """Return the mod id associated with a namespace, if known."""
        return self.namespace_to_mod_id.get(namespace)

    def get_mod_ids_for_jar(self, jar_name: str) -> list[str]:
        """Return mod ids declared by a jar filename."""
        return self.jar_to_mod_ids.get(jar_name, [])
