import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtTest import QTest

from framekit.config import set_config_manager
from framekit.localization import get_current_language, set_language
from framekit.platform import set_platform_handler
from framekit.shell import HostWindow, SinglePageShell
from framekit.styles import get_main_stylesheet, get_current_theme, set_theme
from ue_forge.config import UEForgeConfigManager
from ue_forge.uproject_launcher.core import ForgeProfile, LocalPlugin, save_profile
from ue_forge.uproject_launcher.page import PluginScanDialog, UProjectLauncherPage
from ue_forge.platform import ue_handler_for


class UProjectLauncherPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        if os.name == "nt":
            fonts = Path(os.environ["WINDIR"]) / "Fonts"
            for name in ("segoeui.ttf", "segoeuib.ttf", "seguisb.ttf", "consola.ttf"):
                QFontDatabase.addApplicationFont(str(fonts / name))
            cls.app.setFont(QFont("Segoe UI", 10))

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

    def test_profile_layout_keeps_fields_and_plugins_readable(self) -> None:
        project_path = self.root / "Game.uproject"
        project_path.write_text(json.dumps({"EngineAssociation": "5.8"}), encoding="utf-8")
        profile_path = self.root / "Game.ulaunch"
        save_profile(profile_path, ForgeProfile(
            engine=str(self.engine_path),
            plugins=[LocalPlugin(f"LocalTools{index}") for index in range(20)],
        ))
        original_language, original_theme = get_current_language(), get_current_theme()
        original_stylesheet = self.app.styleSheet()
        self.addCleanup(set_language, original_language)
        self.addCleanup(set_theme, original_theme)
        self.addCleanup(self.app.setStyleSheet, original_stylesheet)

        for shell_type in (SinglePageShell, HostWindow):
            for theme, language in (("light", "en"), ("dark", "ru")):
                with self.subTest(shell=shell_type.__name__, theme=theme, language=language):
                    set_language(language)
                    set_theme(theme)
                    self.app.setStyleSheet(get_main_stylesheet())
                    page = UProjectLauncherPage(initial_profile_path=profile_path)
                    if shell_type is SinglePageShell:
                        window = shell_type(page=page, title="UProject Launcher")
                    else:
                        window = shell_type(title="UE Forge")
                        window.add_page(page)
                    self.addCleanup(window.deleteLater)
                    self.addCleanup(window.close)
                    window.show()

                    for size in ((1268, 730), (1000, 600)):
                        window.resize(*size)
                        QTest.qWait(20)
                        self.assertGreaterEqual(page._table.viewport().height(), page._table.rowHeight(0) * 10)
                        card = page._project_input.parentWidget()
                        card_layout = card.layout()
                        for index in range(card_layout.count() - 1):
                            first = card_layout.itemAt(index).geometry()
                            second = card_layout.itemAt(index + 1).geometry()
                            self.assertLess(first.bottom(), second.top())
                        for label in card.findChildren(QLabel):
                            if label.wordWrap():
                                self.assertGreaterEqual(label.height(), label.heightForWidth(label.width()))
                        for path_input in (page._project_input, page._engine_input):
                            self.assertGreaterEqual(path_input.height(), path_input.minimumSizeHint().height())
                            self.assertLess(
                                path_input.layout().itemAt(0).geometry().bottom(),
                                path_input.layout().itemAt(1).geometry().top(),
                            )
                        for button in (page._save_button, page._launch_button):
                            self.assertTrue(window.rect().contains(QRect(button.mapTo(window, QPoint()), button.size())))
                        scroll_bar = page._settings_scroll.verticalScrollBar()
                        scroll_bar.setValue(scroll_bar.maximum())
                        self.app.processEvents()
                        viewport = page._settings_scroll.viewport()
                        preview_rect = QRect(page._command_preview.mapTo(viewport, QPoint()), page._command_preview.size())
                        self.assertTrue(viewport.rect().contains(preview_rect), (size, viewport.rect(), preview_rect))
                    window.close()


if __name__ == "__main__":
    unittest.main()
