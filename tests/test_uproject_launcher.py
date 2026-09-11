import json
import tempfile
import unittest
from pathlib import Path

from ue_forge.uproject_launcher.core import (
    ForgeProfile,
    LocalPlugin,
    ProfileError,
    build_launch_command,
    filter_plugins,
    load_profile,
    resolve_engine,
    resolve_engine_override,
    resolve_project_path,
    save_profile,
    scan_engine_plugins,
)
from ue_forge.plugin_builder.types import EngineInfo


class UProjectLauncherCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary_directory.name)

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    def _write_json(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_profile_round_trip_and_implicit_project(self) -> None:
        profile_path = self.root / "Sample.ulaunch"
        project_path = self.root / "Sample.uproject"
        self._write_json(project_path, {"EngineAssociation": "5.8"})
        profile = ForgeProfile(
            plugins=[LocalPlugin("EnabledPlugin"), LocalPlugin("DisabledPlugin", False)],
            arguments="-log",
        )

        save_profile(profile_path, profile)

        loaded = load_profile(profile_path)
        self.assertEqual(loaded, profile)
        self.assertEqual(resolve_project_path(profile_path, loaded.project), project_path.resolve())

    def test_relative_project_and_engine_resolution(self) -> None:
        profile_path = self.root / "Profiles" / "Developer.ulaunch"
        project_path = self.root / "Game" / "Game.uproject"
        engine_path = self.root / "UE_5.8"
        self._write_json(project_path, {"EngineAssociation": "UE_5.8"})
        engine = EngineInfo("5.8", engine_path)

        resolved_project = resolve_project_path(profile_path, "../Game/Game.uproject")

        self.assertEqual(resolved_project, project_path.resolve())
        self.assertEqual(resolve_engine(resolved_project, {"5.8": engine}), engine)
        self.assertEqual(resolve_engine_override("5.8", profile_path, {"5.8": engine}), engine)
        self.assertEqual(resolve_engine_override(str(engine_path), profile_path, {}), EngineInfo("5.8", engine_path))

    def test_unmatched_engine_is_rejected(self) -> None:
        project_path = self.root / "Game.uproject"
        self._write_json(project_path, {"EngineAssociation": "5.7"})

        with self.assertRaises(ProfileError):
            resolve_engine(project_path, {"5.8": EngineInfo("5.8", self.root / "UE_5.8")})

    def test_profile_rejects_non_boolean_enabled_value(self) -> None:
        profile_path = self.root / "Invalid.ulaunch"
        self._write_json(profile_path, {"Plugins": [{"Name": "LocalTools", "Enabled": "false"}]})

        with self.assertRaises(ProfileError):
            load_profile(profile_path)

    def test_scan_and_filter_plugin_metadata(self) -> None:
        engine_path = self.root / "UE_5.8"
        self._write_json(
            engine_path / "Engine" / "Plugins" / "Developer" / "LocalTools" / "LocalTools.uplugin",
            {
                "FriendlyName": "Local Tools",
                "VersionName": "2.1",
                "CreatedBy": "Forge Team",
                "Description": "Personal workflow helpers",
            },
        )

        plugins = scan_engine_plugins(engine_path)

        self.assertEqual(len(plugins), 1)
        self.assertEqual(plugins[0].name, "LocalTools")
        self.assertEqual(filter_plugins(plugins, "forge 2.1"), plugins)
        self.assertEqual(filter_plugins(plugins, "missing"), [])

    def test_command_contains_only_enabled_plugins(self) -> None:
        editor_path = self.root / "UnrealEditor.exe"
        project_path = self.root / "Game.uproject"
        editor_path.touch()
        project_path.touch()
        profile = ForgeProfile(
            plugins=[LocalPlugin("One"), LocalPlugin("Two", False), LocalPlugin("Three")],
            arguments='-log -ExecCmds="stat fps"',
        )

        command = build_launch_command(editor_path, project_path, profile)

        self.assertEqual(command[:3], [str(editor_path), str(project_path), "-EnablePlugins=One,Three"])
        self.assertEqual(command[3:], ["-log", "-ExecCmds=stat fps"])


if __name__ == "__main__":
    unittest.main()
