"""Build normalized mod dependency metadata from Minecraft modpacks."""

from __future__ import annotations

import asyncio
import json
import logging
import tomllib
import zipfile
from pathlib import Path
from typing import Any

from .models import DependencyKind, GraphContext, ModDependency, ModInfo, ModLoader

logger = logging.getLogger(__name__)

FABRIC_METADATA = "fabric.mod.json"
FORGE_METADATA = "META-INF/mods.toml"
NEOFORGE_METADATA = "META-INF/neoforge.mods.toml"
LEGACY_FORGE_METADATA = "mcmod.info"


class DependencyGraphBuilder:
    """Extract mod metadata and dependency edges from a modpack."""

    async def scan_modpack(self, modpack_path: Path | str) -> GraphContext:
        """Scan a modpack directory for mod metadata.

        Args:
            modpack_path: Root modpack directory.

        Returns:
            Normalized graph context for all recognized mods.
        """
        root = Path(modpack_path)
        mods_dir = root / "mods" if (root / "mods").exists() else root
        if not mods_dir.exists():
            logger.info("No mod jar directory found for dependency graph: %s", mods_dir)
            return GraphContext()

        jar_paths = sorted(mods_dir.glob("*.jar"))
        logger.info("Scanning %d mod jars for dependency metadata", len(jar_paths))

        results = await asyncio.gather(
            *(asyncio.to_thread(self._scan_jar, jar_path) for jar_path in jar_paths)
        )

        mods: dict[str, ModInfo] = {}
        for mod_infos in results:
            for mod_info in mod_infos:
                if mod_info.mod_id in mods:
                    logger.warning(
                        "Duplicate mod id %s found in %s and %s; keeping latest",
                        mod_info.mod_id,
                        mods[mod_info.mod_id].source_path,
                        mod_info.source_path,
                    )
                mods[mod_info.mod_id] = mod_info

        logger.info(
            "Dependency graph metadata loaded: %d mods, %d dependency edges",
            len(mods),
            sum(len(mod.dependencies) for mod in mods.values()),
        )
        return GraphContext(mods=mods)

    def _scan_jar(self, jar_path: Path) -> list[ModInfo]:
        """Scan a single jar for recognized loader metadata."""
        try:
            with zipfile.ZipFile(jar_path, "r") as jar:
                names = set(jar.namelist())
                manifest = self._read_manifest(jar, names)

                if FABRIC_METADATA in names:
                    return self._parse_fabric_json(
                        self._read_json(jar, FABRIC_METADATA),
                        jar_path,
                        FABRIC_METADATA,
                    )

                if NEOFORGE_METADATA in names:
                    return self._parse_mods_toml(
                        self._read_toml(jar, NEOFORGE_METADATA),
                        jar_path,
                        NEOFORGE_METADATA,
                        ModLoader.NEOFORGE,
                        manifest,
                    )

                if FORGE_METADATA in names:
                    toml_data = self._read_toml(jar, FORGE_METADATA)
                    loader = (
                        ModLoader.NEOFORGE
                        if self._looks_like_neoforge_toml(toml_data)
                        else ModLoader.FORGE
                    )
                    return self._parse_mods_toml(
                        toml_data,
                        jar_path,
                        FORGE_METADATA,
                        loader,
                        manifest,
                    )

                if LEGACY_FORGE_METADATA in names:
                    return self._parse_mcmod_info(
                        self._read_json(jar, LEGACY_FORGE_METADATA),
                        jar_path,
                        LEGACY_FORGE_METADATA,
                    )

        except (zipfile.BadZipFile, OSError, KeyError, json.JSONDecodeError) as e:
            logger.debug("Failed to scan mod metadata from %s: %s", jar_path, e)
        except tomllib.TOMLDecodeError as e:
            logger.debug("Failed to parse TOML metadata from %s: %s", jar_path, e)

        return []

    def _read_json(self, jar: zipfile.ZipFile, entry: str) -> Any:
        with jar.open(entry) as file:
            return json.loads(file.read().decode("utf-8-sig"))

    def _read_toml(self, jar: zipfile.ZipFile, entry: str) -> dict[str, Any]:
        with jar.open(entry) as file:
            return tomllib.loads(file.read().decode("utf-8-sig"))

    def _read_manifest(
        self,
        jar: zipfile.ZipFile,
        names: set[str],
    ) -> dict[str, str]:
        if "META-INF/MANIFEST.MF" not in names:
            return {}

        with jar.open("META-INF/MANIFEST.MF") as file:
            lines = file.read().decode("utf-8", errors="replace").splitlines()

        manifest: dict[str, str] = {}
        current_key = ""
        for line in lines:
            if line.startswith(" ") and current_key:
                manifest[current_key] += line[1:]
                continue
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            current_key = key.strip()
            manifest[current_key] = value.strip()

        return manifest

    def _parse_fabric_json(
        self,
        data: Any,
        jar_path: Path,
        metadata_path: str,
    ) -> list[ModInfo]:
        """Parse Fabric Loader `fabric.mod.json` metadata."""
        if not isinstance(data, dict):
            return []

        mod_id = self._string_value(data.get("id"))
        if not mod_id:
            return []

        dependencies: list[ModDependency] = []
        dependency_sections = {
            "depends": DependencyKind.REQUIRED,
            "recommends": DependencyKind.OPTIONAL,
            "suggests": DependencyKind.SUGGESTED,
            "breaks": DependencyKind.INCOMPATIBLE,
            "conflicts": DependencyKind.INCOMPATIBLE,
        }

        for section, kind in dependency_sections.items():
            dependencies.extend(
                self._parse_fabric_dependency_section(
                    mod_id,
                    data.get(section),
                    kind,
                )
            )

        return [
            ModInfo(
                mod_id=mod_id,
                name=self._string_value(data.get("name")) or mod_id,
                version=self._string_value(data.get("version")),
                namespace=mod_id,
                loader=ModLoader.FABRIC,
                source_path=jar_path,
                metadata_path=metadata_path,
                description=self._string_value(data.get("description")),
                dependencies=dependencies,
            )
        ]

    def _parse_fabric_dependency_section(
        self,
        source_mod_id: str,
        section_data: Any,
        kind: DependencyKind,
    ) -> list[ModDependency]:
        if not isinstance(section_data, dict):
            return []

        dependencies: list[ModDependency] = []
        for target_mod_id, requirement in section_data.items():
            target = str(target_mod_id)
            if not target:
                continue

            dependencies.append(
                ModDependency(
                    source_mod_id=source_mod_id,
                    target_mod_id=target,
                    kind=kind,
                    version_requirement=self._version_requirement(requirement),
                )
            )
        return dependencies

    def _parse_mods_toml(
        self,
        data: dict[str, Any],
        jar_path: Path,
        metadata_path: str,
        loader: ModLoader,
        manifest: dict[str, str],
    ) -> list[ModInfo]:
        """Parse Forge/NeoForge `mods.toml` metadata."""
        raw_mods = data.get("mods")
        if not isinstance(raw_mods, list):
            return []

        raw_dependencies = data.get("dependencies")
        dependency_map = raw_dependencies if isinstance(raw_dependencies, dict) else {}

        mods: list[ModInfo] = []
        for raw_mod in raw_mods:
            if not isinstance(raw_mod, dict):
                continue

            mod_id = self._string_value(raw_mod.get("modId"))
            if not mod_id:
                continue

            dependencies = self._parse_mods_toml_dependencies(
                mod_id,
                dependency_map.get(mod_id),
                loader,
            )

            mods.append(
                ModInfo(
                    mod_id=mod_id,
                    name=self._string_value(raw_mod.get("displayName")) or mod_id,
                    version=self._resolve_toml_version(raw_mod.get("version"), manifest),
                    namespace=self._string_value(raw_mod.get("namespace")) or mod_id,
                    loader=loader,
                    source_path=jar_path,
                    metadata_path=metadata_path,
                    description=self._string_value(raw_mod.get("description")),
                    dependencies=dependencies,
                )
            )

        return mods

    def _parse_mods_toml_dependencies(
        self,
        source_mod_id: str,
        raw_dependencies: Any,
        loader: ModLoader,
    ) -> list[ModDependency]:
        if not isinstance(raw_dependencies, list):
            return []

        dependencies: list[ModDependency] = []
        for raw_dependency in raw_dependencies:
            if not isinstance(raw_dependency, dict):
                continue

            target_mod_id = self._string_value(raw_dependency.get("modId"))
            if not target_mod_id:
                continue

            dependencies.append(
                ModDependency(
                    source_mod_id=source_mod_id,
                    target_mod_id=target_mod_id,
                    kind=self._mods_toml_dependency_kind(raw_dependency, loader),
                    version_requirement=self._optional_string(
                        raw_dependency.get("versionRange")
                    ),
                    ordering=self._string_value(raw_dependency.get("ordering"))
                    or "NONE",
                    side=self._string_value(raw_dependency.get("side")) or "BOTH",
                )
            )

        return dependencies

    def _mods_toml_dependency_kind(
        self,
        raw_dependency: dict[Any, Any],
        loader: ModLoader,
    ) -> DependencyKind:
        dependency_type = self._string_value(raw_dependency.get("type")).lower()
        if dependency_type:
            if dependency_type == "optional":
                return DependencyKind.OPTIONAL
            if dependency_type == "incompatible":
                return DependencyKind.INCOMPATIBLE
            if dependency_type == "discouraged":
                return DependencyKind.SUGGESTED
            return DependencyKind.REQUIRED

        mandatory = raw_dependency.get("mandatory")
        if mandatory is False:
            return DependencyKind.OPTIONAL
        if mandatory is True:
            return DependencyKind.REQUIRED

        return DependencyKind.REQUIRED if loader == ModLoader.NEOFORGE else DependencyKind.OPTIONAL

    def _looks_like_neoforge_toml(self, data: dict[str, Any]) -> bool:
        raw_dependencies = data.get("dependencies")
        if not isinstance(raw_dependencies, dict):
            return False

        for dependency_group in raw_dependencies.values():
            if not isinstance(dependency_group, list):
                continue
            for dependency in dependency_group:
                if isinstance(dependency, dict) and "type" in dependency:
                    return True
        return False

    def _resolve_toml_version(
        self,
        raw_version: Any,
        manifest: dict[str, str],
    ) -> str:
        version = self._string_value(raw_version)
        if version == "${file.jarVersion}":
            return manifest.get("Implementation-Version", version)
        return version

    def _parse_mcmod_info(
        self,
        data: Any,
        jar_path: Path,
        metadata_path: str,
    ) -> list[ModInfo]:
        """Parse legacy Forge `mcmod.info` metadata."""
        if isinstance(data, dict) and isinstance(data.get("modList"), list):
            raw_mods = data["modList"]
        elif isinstance(data, list):
            raw_mods = data
        else:
            return []

        mods: list[ModInfo] = []
        for raw_mod in raw_mods:
            if not isinstance(raw_mod, dict):
                continue

            mod_id = self._string_value(
                raw_mod.get("modid", raw_mod.get("modId"))
            )
            if not mod_id:
                continue

            dependencies = self._parse_legacy_dependencies(
                mod_id,
                raw_mod.get("dependencies"),
            )

            mods.append(
                ModInfo(
                    mod_id=mod_id,
                    name=self._string_value(raw_mod.get("name")) or mod_id,
                    version=self._string_value(raw_mod.get("version")),
                    namespace=mod_id,
                    loader=ModLoader.LEGACY_FORGE,
                    source_path=jar_path,
                    metadata_path=metadata_path,
                    description=self._string_value(raw_mod.get("description")),
                    dependencies=dependencies,
                )
            )

        return mods

    def _parse_legacy_dependencies(
        self,
        source_mod_id: str,
        raw_dependencies: Any,
    ) -> list[ModDependency]:
        if not isinstance(raw_dependencies, list):
            return []

        dependencies: list[ModDependency] = []
        for raw_dependency in raw_dependencies:
            target_mod_id = self._string_value(raw_dependency)
            if not target_mod_id:
                continue

            dependencies.append(
                ModDependency(
                    source_mod_id=source_mod_id,
                    target_mod_id=target_mod_id,
                    kind=DependencyKind.REQUIRED,
                )
            )
        return dependencies

    def _version_requirement(self, value: Any) -> str | None:
        """Normalize loader-specific version requirements."""
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return ", ".join(str(item) for item in value)
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def _string_value(self, value: Any) -> str:
        """Convert metadata scalar values to strings."""
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        return str(value).strip()

    def _optional_string(self, value: Any) -> str | None:
        text = self._string_value(value)
        return text or None
