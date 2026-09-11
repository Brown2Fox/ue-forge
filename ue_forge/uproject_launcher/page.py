"""UI for local Unreal Engine plugin launch profiles."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QMimeData, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLayout,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from framekit.dialogs import MessageDialog
from framekit.icons import Icons
from framekit.localization import tr
from framekit.styles import COLORS, FONTS, RADIUS
from framekit.types import StatusKind
from framekit.widgets import PathInput
from pyside_frameless import DropZoneWidget
from ue_forge.config import get_ue_config_manager as get_config_manager
from ue_forge.platform import ue_platform_handler
from ue_forge.plugin_builder.engine_finder import EngineFinder
from ue_forge.plugin_builder.types import EngineInfo

from .core import (
    ForgeProfile,
    LocalPlugin,
    PluginMetadata,
    ProfileError,
    build_launch_command,
    filter_plugins,
    launch_editor,
    load_profile,
    resolve_engine,
    resolve_engine_override,
    resolve_project_path,
    save_profile,
    scan_engine_plugins,
)


def _table_stylesheet() -> str:
    return f"""
        QTableWidget {{
            background-color: {COLORS['bg_panel']};
            alternate-background-color: {COLORS['bg_group']};
            border: 1px solid {COLORS['border_default']};
            border-radius: 0px;
            gridline-color: {COLORS['border_default']};
            color: {COLORS['text_secondary']};
        }}
        QTableWidget::item {{ padding: 7px; }}
        QTableWidget::item:hover {{
            background-color: {COLORS['bg_item_hover']};
            color: {COLORS['text_primary']};
        }}
        QTableWidget::item:selected {{
            background-color: {COLORS['accent_bg']};
            color: {COLORS['text_primary']};
        }}
        QHeaderView::section {{
            background-color: {COLORS['bg_group']};
            color: {COLORS['text_muted']};
            border: none;
            border-bottom: 1px solid {COLORS['border_default']};
            padding: 8px;
            font-weight: 500;
        }}
    """


class PluginScanDialog(QDialog):
    def __init__(
        self,
        plugins: list[PluginMetadata],
        selected_names: set[str],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self._plugins = plugins
        self._selected_names = {name.lower() for name in selected_names}
        self._visible_plugins: list[PluginMetadata] = []
        self.setWindowTitle(tr("scan_plugins_title"))
        self.setMinimumSize(900, 620)
        self._setup_ui()
        self._apply_filter("")

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        self._filter = QLineEdit()
        self._filter.setPlaceholderText(tr("filter_plugins"))
        self._filter.setClearButtonEnabled(True)
        self._filter.textChanged.connect(self._apply_filter)
        layout.addWidget(self._filter)

        self._count_label = QLabel()
        self._count_label.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: {FONTS['size_xs']};")
        layout.addWidget(self._count_label)

        self._table = QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels([
            tr("enabled"),
            tr("plugin_name"),
            tr("plugin_id"),
            tr("plugin_version"),
            tr("plugin_author"),
            tr("plugin_description"),
        ])
        self._table.setAlternatingRowColors(True)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setStyleSheet(_table_stylesheet())
        header = self._table.horizontalHeader()
        for column in range(5):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        for column, width in enumerate((80, 210, 160, 100, 160)):
            self._table.setColumnWidth(column, width)
        self._table.itemChanged.connect(self._on_item_changed)
        layout.addWidget(self._table, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("add_selected_plugins"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("cancel"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _apply_filter(self, query: str) -> None:
        self._visible_plugins = filter_plugins(self._plugins, query)
        self._table.blockSignals(True)
        self._table.setRowCount(len(self._visible_plugins))
        for row, plugin in enumerate(self._visible_plugins):
            enabled = QTableWidgetItem()
            enabled.setFlags(
                Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            enabled.setCheckState(
                Qt.CheckState.Checked if plugin.name.lower() in self._selected_names else Qt.CheckState.Unchecked
            )
            enabled.setData(Qt.ItemDataRole.UserRole, plugin.name)
            self._table.setItem(row, 0, enabled)
            values = [plugin.friendly_name, plugin.name, plugin.version, plugin.author, plugin.description]
            for column, value in enumerate(values, start=1):
                item = QTableWidgetItem(value or "—")
                item.setToolTip(value)
                self._table.setItem(row, column, item)
        self._table.blockSignals(False)
        self._count_label.setText(tr("plugins_found", visible=len(self._visible_plugins), total=len(self._plugins)))

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        name = str(item.data(Qt.ItemDataRole.UserRole)).lower()
        if item.checkState() == Qt.CheckState.Checked:
            self._selected_names.add(name)
        else:
            self._selected_names.discard(name)

    def selected_names(self) -> set[str]:
        return self._selected_names.copy()


class UProjectLauncherPage(DropZoneWidget):
    PAGE_ID = "uproject_launcher"
    PAGE_ICON = "GAMEPAD_2"

    status_changed = Signal(object, str)

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        initial_profile_path: Optional[Path] = None,
        launch_immediately: bool = False,
    ):
        super().__init__(parent, valid_extensions=[".ulaunch"])
        self.setObjectName("uprojectLauncherPage")
        self.setStyleSheet(f"QWidget#uprojectLauncherPage {{ background-color: {COLORS['bg_primary']}; }}")
        self._config = get_config_manager()
        self._profile = ForgeProfile()
        self._profile_path: Optional[Path] = None
        self._project_path: Optional[Path] = None
        self._engine: Optional[EngineInfo] = None
        self._engines: Optional[dict[str, EngineInfo]] = None
        self._metadata: dict[str, PluginMetadata] = {}
        self._loading = False
        self._dirty = False
        self._setup_ui()
        for widget in self.findChildren(QWidget):
            widget.setAcceptDrops(False)
        overlay = self.setup_drop_overlay()
        overlay.configure(
            valid_pixmap=Icons.get_pixmap("UPLOAD", 48, COLORS["accent_primary"]),
            invalid_pixmap=Icons.get_pixmap("X_CIRCLE", 48, COLORS["warning"]),
            invalid_text=tr("drop_launch_profile_invalid"),
        )
        self._profile_input.setToolTip(tr("drop_launch_profile"))
        self.set_drop_callback(self._profile_input.set_path)
        self._load_config()
        if initial_profile_path:
            self._set_profile_input(initial_profile_path)
            loaded = self._load_profile(initial_profile_path, load_metadata=not launch_immediately)
            if loaded and launch_immediately:
                QTimer.singleShot(0, self._launch_from_file)

    @staticmethod
    def page_title() -> str:
        return tr("uproject_launcher")

    def _find_target_file(self, mime: QMimeData) -> str | None:
        urls = mime.urls()
        if len(urls) != 1 or not urls[0].isLocalFile():
            return None
        path = Path(urls[0].toLocalFile())
        if path.is_file() and path.suffix.lower() == ".ulaunch":
            return str(path)
        return None

    def _is_valid_drop(self, mime: QMimeData) -> bool:
        return self._find_target_file(mime) is not None

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setHandleWidth(1)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setStyleSheet(
            f"QSplitter::handle {{ background-color: {COLORS['border_default']}; }}"
        )
        layout.addWidget(self._splitter)

        self._settings_scroll = QScrollArea()
        self._settings_scroll.setObjectName("launcherSettingsScroll")
        self._settings_scroll.setWidgetResizable(True)
        self._settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._settings_scroll.setMinimumWidth(480)
        self._settings_scroll.setStyleSheet(
            f"QScrollArea#launcherSettingsScroll {{ background-color: {COLORS['bg_primary']}; }}"
        )
        settings = QWidget()
        settings_layout = QVBoxLayout(settings)
        settings_layout.setContentsMargins(24, 24, 24, 20)
        settings_layout.setSpacing(16)
        settings_layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        self._settings_scroll.setWidget(settings)
        self._splitter.addWidget(self._settings_scroll)

        header = QHBoxLayout()
        icon = QLabel()
        icon.setPixmap(Icons.get_pixmap("GAMEPAD_2", 22, COLORS["accent_primary"]))
        icon.setFixedSize(22, 22)
        header.addWidget(icon)
        title = QLabel(tr("local_profile"))
        title.setWordWrap(True)
        title.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: {FONTS['size_xl']}; font-weight: 600;")
        header.addWidget(title)
        header.addStretch()
        self._new_button = QPushButton(f"  {tr('new_profile')}")
        self._new_button.setIcon(Icons.get_icon("FILE_CODE", 14, COLORS["text_dim"]))
        self._new_button.clicked.connect(self._create_profile)
        header.addWidget(self._new_button)
        settings_layout.addLayout(header)

        self._profile_input = PathInput(
            placeholder=tr("profile_path"),
            icon_name="FILE_CODE",
            file_filter=tr("profile_filter"),
        )
        self._profile_input.path_changed.connect(self._on_profile_path_changed)
        settings_layout.addWidget(self._profile_input)

        self._profile_content = QWidget()
        profile_layout = QVBoxLayout(self._profile_content)
        profile_layout.setContentsMargins(0, 0, 0, 0)
        profile_layout.setSpacing(16)
        settings_layout.addWidget(self._profile_content)
        settings_layout.addStretch()

        context_card = QFrame()
        context_card.setObjectName("launcherContextCard")
        context_card.setStyleSheet(f"""
            QFrame#launcherContextCard {{
                background-color: {COLORS['bg_group']};
                border: 1px solid {COLORS['border_default']};
                border-radius: {RADIUS['lg']};
            }}
        """)
        context_layout = QVBoxLayout(context_card)
        context_layout.setContentsMargins(16, 14, 16, 14)
        context_layout.setSpacing(10)
        context_header = QHBoxLayout()
        context_header.addStretch()
        self._auto_detect_button = QPushButton(f"  {tr('auto_detect')}")
        self._auto_detect_button.setIcon(Icons.get_icon("REFRESH_CW", 14, COLORS["text_dim"]))
        self._auto_detect_button.clicked.connect(self._auto_detect)
        context_header.addWidget(self._auto_detect_button)
        context_layout.addLayout(context_header)
        self._project_input = PathInput(
            label=tr("project_path"),
            placeholder=tr("project_path_placeholder"),
            icon_name="FOLDER_OPEN",
            file_filter=tr("project_filter"),
        )
        self._project_input.path_changed.connect(self._on_project_changed)
        self._project_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        context_layout.addWidget(self._project_input)
        project_hint = QLabel(tr("project_path_hint"))
        project_hint.setWordWrap(True)
        project_hint.setStyleSheet(f"color: {COLORS['text_placeholder']}; font-size: {FONTS['size_xs']};")
        context_layout.addWidget(project_hint)
        self._engine_input = PathInput(
            label=tr("engine"),
            placeholder=tr("engine_path_placeholder"),
            icon_name="HARD_DRIVE",
            directory_mode=True,
        )
        self._engine_input.path_changed.connect(self._on_engine_changed)
        self._engine_input.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        context_layout.addWidget(self._engine_input)
        engine_hint = QLabel(tr("engine_path_hint"))
        engine_hint.setWordWrap(True)
        engine_hint.setStyleSheet(f"color: {COLORS['text_placeholder']}; font-size: {FONTS['size_xs']};")
        context_layout.addWidget(engine_hint)
        self._engine_label = QLabel(tr("engine_unresolved"))
        self._engine_label.setWordWrap(True)
        self._engine_label.setTextFormat(Qt.TextFormat.PlainText)
        self._engine_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._engine_label.setStyleSheet(f"color: {COLORS['warning']}; font-family: {FONTS['family_mono']};")
        context_layout.addWidget(self._engine_label)
        profile_layout.addWidget(context_card)

        args_label = QLabel(tr("additional_arguments"))
        args_label.setWordWrap(True)
        args_label.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: {FONTS['size_xs']}; font-weight: 500;")
        profile_layout.addWidget(args_label)
        self._arguments = QLineEdit()
        self._arguments.setPlaceholderText(tr("additional_arguments_hint"))
        self._arguments.textChanged.connect(self._on_arguments_changed)
        profile_layout.addWidget(self._arguments)

        preview_label = QLabel(tr("command_preview"))
        preview_label.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: {FONTS['size_xs']}; font-weight: 500;")
        profile_layout.addWidget(preview_label)
        self._command_preview = QLineEdit()
        self._command_preview.setReadOnly(True)
        profile_layout.addWidget(self._command_preview)

        plugins_panel = QWidget()
        plugins_panel.setMinimumWidth(400)
        plugins_layout = QVBoxLayout(plugins_panel)
        plugins_layout.setContentsMargins(0, 0, 0, 0)
        plugins_layout.setSpacing(0)
        self._plugins_content = QWidget()
        plugins_layout.addWidget(self._plugins_content)
        plugins_content_layout = QVBoxLayout(self._plugins_content)
        plugins_content_layout.setContentsMargins(0, 0, 0, 0)
        plugins_content_layout.setSpacing(0)

        plugins_toolbar = QWidget()
        plugins_header = QHBoxLayout()
        plugins_header.setContentsMargins(16, 16, 16, 16)
        plugins_toolbar.setLayout(plugins_header)
        plugins_title = QLabel(tr("local_plugins"))
        plugins_title.setWordWrap(True)
        plugins_title.setStyleSheet(f"color: {COLORS['text_secondary']}; font-weight: 500;")
        plugins_header.addWidget(plugins_title)
        plugins_header.addStretch()
        self._remove_button = QPushButton(f"  {tr('remove_plugin')}")
        self._remove_button.setIcon(Icons.get_icon("TRASH_2", 14, COLORS["text_dim"]))
        self._remove_button.clicked.connect(self._remove_selected)
        plugins_header.addWidget(self._remove_button)
        self._scan_button = QPushButton(f"  {tr('scan_plugins')}")
        self._scan_button.setIcon(Icons.get_icon("SEARCH", 14, COLORS["text_dim"]))
        self._scan_button.clicked.connect(self._scan_plugins)
        plugins_header.addWidget(self._scan_button)
        plugins_content_layout.addWidget(plugins_toolbar)

        self._table = QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels([
            tr("enabled"), tr("plugin_name"), tr("plugin_version"), tr("plugin_author"), tr("plugin_description")
        ])
        self._table.setAlternatingRowColors(True)
        self._table.setWordWrap(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setStyleSheet(_table_stylesheet())
        table_header = self._table.horizontalHeader()
        for column in range(4):
            table_header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        table_header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        table_header.setMinimumSectionSize(60)
        for column, width in enumerate((76, 180, 70, 110)):
            self._table.setColumnWidth(column, width)
        self._table.itemChanged.connect(self._on_plugin_changed)
        self._table.itemSelectionChanged.connect(self._update_controls)
        plugins_content_layout.addWidget(self._table, 1)

        controls_panel = QFrame()
        controls_panel.setObjectName("launcherControls")
        controls_panel.setStyleSheet(f"""
            QFrame#launcherControls {{
                background-color: {COLORS['bg_panel']};
                border: none;
                border-top: 1px solid {COLORS['border_default']};
            }}
        """)
        controls = QHBoxLayout()
        controls.setContentsMargins(16, 14, 16, 14)
        controls.setSpacing(12)
        controls_panel.setLayout(controls)
        controls.addStretch()
        self._save_button = QPushButton(f"  {tr('save_profile')}")
        self._save_button.setIcon(Icons.get_icon("FILE_CODE", 14, COLORS["text_dim"]))
        self._save_button.clicked.connect(self._save_profile)
        controls.addWidget(self._save_button)
        self._launch_button = QPushButton(f"  {tr('launch_project')}")
        self._launch_button.setIcon(Icons.get_icon("PLAY", 16, "#ffffff"))
        self._launch_button.setProperty("class", "primary")
        self._launch_button.setMinimumWidth(180)
        self._launch_button.clicked.connect(self._launch)
        controls.addWidget(self._launch_button)
        plugins_content_layout.addWidget(controls_panel)
        self._splitter.addWidget(plugins_panel)
        self._splitter.setSizes([480, 720])
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 1)
        self._set_profile_visible(False)
        self._update_controls()

    def _set_profile_visible(self, visible: bool) -> None:
        self._profile_content.setVisible(visible)
        self._plugins_content.setVisible(visible)

    def _load_config(self) -> None:
        config = self._config.load_config()
        last_path = getattr(config, "last_uproject_launcher_path", "")
        self._profile_input.set_browse_start_path(last_path)

    def _confirm_discard(self) -> bool:
        if not self._dirty:
            return True
        result = MessageDialog.question(
            self, tr("unsaved_profile"), tr("discard_changes"), [tr("no"), tr("yes")]
        )
        return result == tr("yes")

    def _create_profile(self) -> None:
        if not self._confirm_discard():
            return
        start = str(self._profile_path.parent) if self._profile_path else self._profile_input.path()
        path, _ = QFileDialog.getSaveFileName(self, tr("create_profile"), start, tr("profile_filter"))
        if not path:
            return
        profile_path = Path(path)
        if profile_path.suffix.lower() != ".ulaunch":
            profile_path = profile_path.with_suffix(".ulaunch")
        try:
            save_profile(profile_path, ForgeProfile())
        except (OSError, ProfileError) as error:
            MessageDialog.error(self, tr("error"), tr("profile_save_failed", error=error))
            return
        self._set_profile_input(profile_path)
        self._load_profile(profile_path)

    def _set_profile_input(self, path: Path) -> None:
        self._loading = True
        self._profile_input.set_path(str(path))
        self._loading = False

    def _on_profile_path_changed(self, path: str) -> None:
        if self._loading:
            return
        candidate = Path(path)
        if not candidate.is_file() or candidate.suffix.lower() != ".ulaunch":
            self._set_profile_visible(False)
            return
        if self._profile_path and candidate.resolve() == self._profile_path.resolve():
            self._set_profile_visible(True)
            return
        if not self._confirm_discard():
            self._set_profile_input(self._profile_path) if self._profile_path else None
            return
        self._load_profile(candidate)

    def _load_profile(self, profile_path: Path, load_metadata: bool = True) -> bool:
        try:
            profile = load_profile(profile_path)
        except ProfileError as error:
            self._set_profile_visible(False)
            MessageDialog.error(self, tr("error"), tr("profile_load_failed", error=error))
            return False
        self._profile = profile
        self._profile_path = profile_path.resolve()
        self._metadata = {}
        self._loading = True
        self._project_input.set_path(profile.project)
        self._engine_input.set_path(profile.engine)
        self._arguments.setText(profile.arguments)
        self._loading = False
        self._dirty = False
        self._config.update_config(last_uproject_launcher_path=str(self._profile_path))
        self._refresh_context(load_metadata=load_metadata)
        self._refresh_table()
        self._set_profile_visible(True)
        self._update_controls()
        return True

    def _on_project_changed(self, path: str) -> None:
        if self._loading:
            return
        self._profile.project = path
        self._mark_dirty()
        self._refresh_context(load_metadata=False)

    def _on_arguments_changed(self, arguments: str) -> None:
        if self._loading:
            return
        self._profile.arguments = arguments
        self._mark_dirty()

    def _on_engine_changed(self, path: str) -> None:
        if self._loading:
            return
        self._profile.engine = path
        self._mark_dirty()
        self._refresh_context(load_metadata=False)

    def _auto_detect(self) -> None:
        if not self._profile_path:
            MessageDialog.warning(self, tr("error"), tr("profile_required"))
            return
        project_path = self._profile_path.with_suffix(".uproject")
        try:
            project_path = resolve_project_path(self._profile_path, project_path.name)
            self._engines = EngineFinder().find_all_engines()
            engine = resolve_engine(project_path, self._engines)
        except ProfileError as error:
            MessageDialog.warning(self, tr("error"), tr("auto_detect_failed", error=error))
            return
        self._loading = True
        self._project_input.set_path(project_path.name)
        self._engine_input.set_path(str(engine.path))
        self._loading = False
        self._profile.project = project_path.name
        self._profile.engine = str(engine.path)
        self._mark_dirty()
        self._refresh_context(load_metadata=True)
        self._refresh_table()

    def _mark_dirty(self) -> None:
        if self._profile_path:
            self._dirty = True
        self._update_controls()
        self._update_command_preview()

    def _ensure_engines(self) -> dict[str, EngineInfo]:
        if self._engines is None:
            self._engines = EngineFinder().find_all_engines()
        return self._engines

    def _refresh_context(self, load_metadata: bool) -> bool:
        self._project_path = None
        self._engine = None
        if not self._profile_path:
            self._engine_label.setText(tr("engine_unresolved"))
            self._update_controls()
            return False
        try:
            self._project_path = resolve_project_path(self._profile_path, self._profile.project)
            self._engine = resolve_engine_override(
                self._profile.engine,
                self._profile_path,
                self._ensure_engines(),
            )
        except ProfileError as error:
            self._engine_label.setText(str(error))
            self._engine_label.setStyleSheet(f"color: {COLORS['warning']}; font-family: {FONTS['family_mono']};")
            self._update_controls()
            return False
        self._engine_label.setText(f"UE {self._engine.version} — {self._engine.path}")
        self._engine_label.setStyleSheet(f"color: {COLORS['success']}; font-family: {FONTS['family_mono']};")
        if load_metadata:
            self._reload_metadata(show_errors=False)
        self._update_controls()
        self._update_command_preview()
        return True

    def _reload_metadata(self, show_errors: bool) -> bool:
        if not self._engine:
            return False
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            plugins = scan_engine_plugins(self._engine.path)
        except ProfileError as error:
            if show_errors:
                MessageDialog.error(self, tr("error"), tr("plugin_scan_failed", error=error))
            return False
        finally:
            QApplication.restoreOverrideCursor()
        self._metadata = {plugin.name.lower(): plugin for plugin in plugins}
        return True

    def _refresh_table(self) -> None:
        self._table.blockSignals(True)
        self._table.setRowCount(len(self._profile.plugins))
        for row, local_plugin in enumerate(self._profile.plugins):
            metadata = self._metadata.get(local_plugin.name.lower())
            enabled = QTableWidgetItem()
            enabled.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
            enabled.setCheckState(Qt.CheckState.Checked if local_plugin.enabled else Qt.CheckState.Unchecked)
            enabled.setData(Qt.ItemDataRole.UserRole, local_plugin.name)
            self._table.setItem(row, 0, enabled)
            values = [
                metadata.friendly_name if metadata else local_plugin.name,
                metadata.version if metadata else "",
                metadata.author if metadata else "",
                metadata.description if metadata else "",
            ]
            for column, value in enumerate(values, start=1):
                item = QTableWidgetItem(value or "—")
                item.setToolTip(value)
                item.setData(Qt.ItemDataRole.UserRole, local_plugin.name)
                self._table.setItem(row, column, item)
        self._table.blockSignals(False)
        self._update_controls()
        self._update_command_preview()

    def _on_plugin_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        name = str(item.data(Qt.ItemDataRole.UserRole))
        for plugin in self._profile.plugins:
            if plugin.name == name:
                plugin.enabled = item.checkState() == Qt.CheckState.Checked
                self._mark_dirty()
                break

    def _remove_selected(self) -> None:
        rows = {index.row() for index in self._table.selectedIndexes()}
        if not rows:
            return
        self._profile.plugins = [plugin for row, plugin in enumerate(self._profile.plugins) if row not in rows]
        self._mark_dirty()
        self._refresh_table()

    def _scan_plugins(self) -> None:
        if not self._refresh_context(load_metadata=False):
            MessageDialog.warning(self, tr("error"), tr("engine_unresolved_error", error=self._engine_label.text()))
            return
        if not self._reload_metadata(show_errors=True):
            return
        plugins = list(self._metadata.values())
        dialog = PluginScanDialog(plugins, {plugin.name for plugin in self._profile.plugins}, self)
        if not dialog.exec():
            self._refresh_table()
            return
        existing = {plugin.name.lower(): plugin.enabled for plugin in self._profile.plugins}
        selected = dialog.selected_names()
        self._profile.plugins = [
            LocalPlugin(plugin.name, existing.get(plugin.name.lower(), True))
            for plugin in plugins
            if plugin.name.lower() in selected
        ]
        self._mark_dirty()
        self._refresh_table()

    def _editor_path(self) -> Path:
        if not self._engine:
            return Path()
        platform = ue_platform_handler()
        directory = self._engine.path / "Engine" / "Binaries" / platform.get_binaries_subdir()
        editor = directory / platform.get_editor_executable_name()
        if editor.is_file():
            return editor
        fallback_name = "UE4Editor.exe" if os.name == "nt" else "UE4Editor"
        return directory / fallback_name

    def _command(self) -> list[str]:
        if not self._project_path or not self._engine:
            raise ProfileError(tr("engine_unresolved"))
        return build_launch_command(self._editor_path(), self._project_path, self._profile)

    def _update_command_preview(self) -> None:
        try:
            command = self._command()
        except ProfileError:
            self._command_preview.clear()
            self._command_preview.setToolTip("")
            return
        preview = subprocess.list2cmdline(command) if os.name == "nt" else shlex.join(command)
        self._command_preview.setText(preview)
        self._command_preview.setCursorPosition(0)
        self._command_preview.setToolTip(preview)

    def _update_controls(self) -> None:
        has_profile = self._profile_path is not None
        has_context = self._project_path is not None and self._engine is not None
        self._save_button.setEnabled(has_profile)
        self._scan_button.setEnabled(has_context)
        self._launch_button.setEnabled(has_context)
        self._remove_button.setEnabled(bool(self._table.selectedIndexes()))
        self._save_button.setText(f"  {tr('save_profile')}{' *' if self._dirty else ''}")

    def _save_profile(self, show_message: bool = True) -> bool:
        if not self._profile_path:
            MessageDialog.warning(self, tr("error"), tr("profile_required"))
            return False
        try:
            save_profile(self._profile_path, self._profile)
        except (OSError, ProfileError) as error:
            MessageDialog.error(self, tr("error"), tr("profile_save_failed", error=error))
            return False
        self._dirty = False
        self._update_controls()
        self.status_changed.emit(StatusKind.SUCCESS, tr("profile_saved"))
        if show_message:
            MessageDialog.information(self, tr("uproject_launcher"), tr("profile_saved"))
        return True

    def _launch(self) -> bool:
        if not self._refresh_context(load_metadata=False):
            MessageDialog.warning(self, tr("error"), tr("engine_unresolved_error", error=self._engine_label.text()))
            return False
        if not self._save_profile(show_message=False):
            return False
        try:
            command = self._command()
            launch_editor(command, self._project_path)
        except (OSError, ProfileError) as error:
            self.status_changed.emit(StatusKind.FAILED, tr("launch_failed", error=error))
            MessageDialog.error(self, tr("error"), tr("launch_failed", error=error))
            return False
        self.status_changed.emit(StatusKind.SUCCESS, tr("project_launched"))
        return True

    def _launch_from_file(self) -> None:
        if not self._launch():
            return
        application = QApplication.instance()
        if application:
            application.quit()

    def get_settings_tabs(self) -> list:
        return []

    def show_settings(self) -> None:
        from framekit.dialogs import SettingsDialog
        SettingsDialog(self, extra_tabs=self.get_settings_tabs()).exec()

    def can_close(self) -> bool:
        return self._confirm_discard()

    def cleanup(self) -> None:
        pass
