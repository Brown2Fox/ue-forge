import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from framekit.config import set_config_manager
from framekit.platform import set_platform_handler
from ue_forge.config import UEForgeConfigManager
from ue_forge.uproject_launcher.core import ForgeProfile, LocalPlugin, save_profile
from ue_forge.uproject_launcher.page import PluginScanDialog, UProjectLauncherPage
from ue_forge.platform import ue_handler_for


class UProjectLauncherPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary_directory.name)
        manager = UEForgeConfigManager(config_dir=self.root / "Config")
        set_config_manager(manager)
        set_platform_handler(ue_handler_for("ue-forge-tests"))
        self.engine_path = self.root / "UE_5.8"
        (self.engine_path / "Engine" / "Build" / "BatchFiles").mkdir(parents=True)
        (self.engine_path / "Engine" / "Content").mkdir(parents=True)
        (self.engine_path / "Engine" / "Binaries" / "Win64").mkdir(parents=True)
        (self.engine_path / "Engine" / "Plugins" / "Developer" / "LocalTools").mkdir(parents=True)
        (self.engine_path / "Engine" / "Build" / "BatchFiles" / "RunUAT.bat").touch()
        (self.engine_path / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe").touch()
        (self.engine_path / "Engine" / "Plugins" / "Developer" / "LocalTools" / "LocalTools.uplugin").write_text(
            json.dumps({
                "FriendlyName": "Local Tools",
                "VersionName": "2.1",
                "CreatedBy": "Forge Team",
                "Description": "Personal workflow helpers",
            }),
            encoding="utf-8",
        )
        manager.save_engines({"5.8": str(self.engine_path)})

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    def test_profile_populates_table_and_launch_command(self) -> None:
        project_path = self.root / "Game.uproject"
        project_path.write_text(json.dumps({"EngineAssociation": "5.8"}), encoding="utf-8")
        profile_path = self.root / "Game.ulaunch"
        save_profile(profile_path, ForgeProfile(plugins=[LocalPlugin("LocalTools")], arguments="-log"))

        page = UProjectLauncherPage()
        page._load_profile(profile_path)
        page._auto_detect()

        self.assertEqual(page._table.rowCount(), 1)
        self.assertEqual(page._table.item(0, 1).text(), "Local Tools")
        self.assertEqual(page._project_input.path(), "Game.uproject")
        self.assertEqual(page._engine_input.path(), str(self.engine_path))
        self.assertIn("-EnablePlugins=LocalTools", page._command_preview.text())
        self.assertIn("-log", page._command_preview.text())
        self.assertTrue(page._launch_button.isEnabled())

        dialog = PluginScanDialog(list(page._metadata.values()), set())
        dialog._table.item(0, 0).setCheckState(Qt.CheckState.Checked)
        dialog._apply_filter("missing")
        dialog._apply_filter("forge team")
        self.assertEqual(dialog.selected_names(), {"localtools"})
        self.assertEqual(dialog._table.rowCount(), 1)
        dialog.deleteLater()
        page.deleteLater()


if __name__ == "__main__":
    unittest.main()
