"""UProject launch profiles with process-local Unreal Engine plugins."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from ue_forge.plugin_builder.types import EngineInfo


PROFILE_VERSION = 1


class ProfileError(ValueError):
    """Invalid or unresolved local launch profile."""


@dataclass
class LocalPlugin:
    name: str
    enabled: bool = True


@dataclass
class ForgeProfile:
    project: str = ""
    engine: str = ""
    plugins: list[LocalPlugin] = field(default_factory=list)
    arguments: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "ForgeProfile":
        raw_plugins = data.get("Plugins", [])
        plugins: list[LocalPlugin] = []
        plugin_names: set[str] = set()
        if not isinstance(raw_plugins, list):
            raise ProfileError("Plugins must be an array")
        for item in raw_plugins:
            if isinstance(item, str):
                name = item.strip()
                enabled = True
            elif isinstance(item, dict) and isinstance(item.get("Name"), str):
                name = item["Name"].strip()
                enabled = item.get("Enabled", True)
                if not isinstance(enabled, bool):
                    raise ProfileError("Plugin Enabled must be true or false")
            else:
                raise ProfileError("Each plugin must have a Name")
            if not name:
                raise ProfileError("Plugin Name cannot be empty")
            normalized_name = name.lower()
            if normalized_name not in plugin_names:
                plugins.append(LocalPlugin(name, enabled))
                plugin_names.add(normalized_name)
        project = data.get("Project", "")
        engine = data.get("Engine", "")
        arguments = data.get("Arguments", "")
        if not isinstance(project, str) or not isinstance(engine, str) or not isinstance(arguments, str):
            raise ProfileError("Project, Engine, and Arguments must be strings")
        return cls(project=project, engine=engine, plugins=plugins, arguments=arguments)

    def to_dict(self) -> dict:
        data = {"FileVersion": PROFILE_VERSION}
        if self.project:
            data["Project"] = self.project
        if self.engine:
            data["Engine"] = self.engine
        data["Plugins"] = [
            {"Name": plugin.name, "Enabled": plugin.enabled}
            for plugin in self.plugins
        ]
        data["Arguments"] = self.arguments
        return data


@dataclass(frozen=True)
class PluginMetadata:
    name: str
    friendly_name: str
    version: str
    author: str
    description: str
    descriptor_path: Path

    @property
    def searchable_text(self) -> str:
        return " ".join((self.name, self.friendly_name, self.version, self.author, self.description)).lower()


def load_profile(profile_path: Path) -> ForgeProfile:
    if profile_path.suffix.lower() != ".ulaunch":
        raise ProfileError("Profile must use the .ulaunch extension")
    try:
        with open(profile_path, "r", encoding="utf-8-sig") as stream:
            data = json.load(stream)
    except (OSError, json.JSONDecodeError) as error:
        raise ProfileError(str(error)) from error
    if not isinstance(data, dict):
        raise ProfileError("Profile root must be an object")
    version = data.get("FileVersion", PROFILE_VERSION)
    if version != PROFILE_VERSION:
        raise ProfileError(f"Unsupported FileVersion: {version}")
    return ForgeProfile.from_dict(data)


def save_profile(profile_path: Path, profile: ForgeProfile) -> None:
    if profile_path.suffix.lower() != ".ulaunch":
        raise ProfileError("Profile must use the .ulaunch extension")
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = profile_path.with_name(f".{profile_path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(temporary_path, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(profile.to_dict(), stream, indent=2, ensure_ascii=False)
            stream.write("\n")
        os.replace(temporary_path, profile_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def resolve_project_path(profile_path: Path, project_value: str) -> Path:
    if project_value.strip():
        project_path = Path(project_value.strip())
        if not project_path.is_absolute():
            project_path = profile_path.parent / project_path
    else:
        project_path = profile_path.with_suffix(".uproject")
    project_path = project_path.resolve()
    if project_path.suffix.lower() != ".uproject" or not project_path.is_file():
        raise ProfileError(f"Project not found: {project_path}")
    return project_path


def read_engine_association(project_path: Path) -> str:
    try:
        with open(project_path, "r", encoding="utf-8-sig") as stream:
            data = json.load(stream)
    except (OSError, json.JSONDecodeError) as error:
        raise ProfileError(str(error)) from error
    association = data.get("EngineAssociation", "") if isinstance(data, dict) else ""
    if not isinstance(association, str) or not association.strip():
        raise ProfileError("Project has no EngineAssociation")
    return association.strip()


def resolve_engine(project_path: Path, engines: dict[str, EngineInfo]) -> EngineInfo:
    association = read_engine_association(project_path)
    if "/" in association or "\\" in association:
        association_path = Path(association)
        if not association_path.is_absolute():
            association_path = project_path.parent / association_path
        resolved_association = os.path.normcase(str(association_path.resolve()))
        for engine in engines.values():
            if os.path.normcase(str(engine.path.resolve())) == resolved_association:
                return engine
    candidates = {
        association.lower(),
        association.lower().removeprefix("ue_"),
        association.lower().removeprefix("ue "),
    }
    for version, engine in engines.items():
        if version.lower() in candidates:
            return engine
    raise ProfileError(f"No registered engine matches EngineAssociation '{association}'")


def resolve_engine_override(
    engine_value: str,
    profile_path: Path,
    engines: dict[str, EngineInfo],
) -> EngineInfo:
    value = engine_value.strip()
    if not value:
        raise ProfileError("Engine is not specified")
    normalized_value = value.lower().removeprefix("ue_").removeprefix("ue ")
    for version, engine in engines.items():
        if version.lower() == normalized_value:
            return engine
    engine_path = Path(value)
    if not engine_path.is_absolute():
        engine_path = profile_path.parent / engine_path
    engine_path = engine_path.resolve()
    normalized_path = os.path.normcase(str(engine_path))
    for engine in engines.values():
        if os.path.normcase(str(engine.path.resolve())) == normalized_path:
            return engine
    plugins_path = engine_path / "Engine" / "Plugins"
    if not plugins_path.is_dir():
        raise ProfileError(f"Invalid engine root: {engine_path}")
    version_match = re.search(r"(\d+\.\d+)", engine_path.name)
    version = version_match.group(1) if version_match else engine_path.name
    return EngineInfo(version=version, path=engine_path)


def scan_engine_plugins(engine_path: Path) -> list[PluginMetadata]:
    plugins_root = engine_path / "Engine" / "Plugins"
    if not plugins_root.is_dir():
        raise ProfileError(f"Engine plugins directory not found: {plugins_root}")
    discovered: dict[str, PluginMetadata] = {}
    for root, directories, files in os.walk(plugins_root):
        descriptor_names = [name for name in files if name.lower().endswith(".uplugin")]
        if not descriptor_names:
            continue
        directories.clear()
        for descriptor_name in descriptor_names:
            descriptor_path = Path(root) / descriptor_name
            try:
                with open(descriptor_path, "r", encoding="utf-8-sig") as stream:
                    data = json.load(stream)
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            name = descriptor_path.stem
            version = str(data.get("VersionName") or data.get("Version") or "")
            metadata = PluginMetadata(
                name=name,
                friendly_name=str(data.get("FriendlyName") or name),
                version=version,
                author=str(data.get("CreatedBy") or ""),
                description=str(data.get("Description") or ""),
                descriptor_path=descriptor_path,
            )
            discovered.setdefault(name.lower(), metadata)
    return sorted(discovered.values(), key=lambda plugin: (plugin.friendly_name.lower(), plugin.name.lower()))


def filter_plugins(plugins: list[PluginMetadata], query: str) -> list[PluginMetadata]:
    terms = query.lower().split()
    if not terms:
        return plugins
    return [plugin for plugin in plugins if all(term in plugin.searchable_text for term in terms)]


def parse_additional_arguments(arguments: str) -> list[str]:
    try:
        return shlex.split(arguments, posix=True)
    except ValueError as error:
        raise ProfileError(f"Invalid command-line arguments: {error}") from error


def build_launch_command(
    editor_path: Path,
    project_path: Path,
    profile: ForgeProfile,
) -> list[str]:
    if not editor_path.is_file():
        raise ProfileError(f"Unreal Editor not found: {editor_path}")
    command = [str(editor_path), str(project_path)]
    enabled_plugins = [plugin.name for plugin in profile.plugins if plugin.enabled]
    if enabled_plugins:
        command.append(f"-EnablePlugins={','.join(enabled_plugins)}")
    command.extend(parse_additional_arguments(profile.arguments))
    return command


def launch_editor(command: list[str], project_path: Path) -> subprocess.Popen:
    creation_flags = subprocess.DETACHED_PROCESS if os.name == "nt" else 0
    return subprocess.Popen(
        command,
        cwd=str(project_path.parent),
        creationflags=creation_flags,
        close_fds=True,
    )
