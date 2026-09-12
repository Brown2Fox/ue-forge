"""Settings for Windows launch profile integration."""

import os
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from framekit.dialogs import MessageDialog, SettingsTab
from framekit.localization import tr
from framekit.styles import COLORS
from framekit.widgets import PathInput

from .file_associations import association_status, register_associations, suggested_executable


class AssociationsSettingsTab(SettingsTab):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(16)

        description = QLabel(tr("associations_description"))
        description.setWordWrap(True)
        layout.addWidget(description)

        self._executable = PathInput(
            label=tr("association_application"),
            placeholder=tr("association_executable_hint"),
            file_filter="Windows executable (*.exe)",
            icon_name="FILE_CODE",
        )
        layout.addWidget(self._executable)

        self._status = QLabel()
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        controls = QHBoxLayout()
        self._register_button = QPushButton(tr("register_associations"))
        self._register_button.setProperty("class", "primary")
        self._register_button.clicked.connect(self._register)
        controls.addWidget(self._register_button)
        self._defaults_button = QPushButton(tr("windows_default_apps"))
        self._defaults_button.clicked.connect(self._open_defaults)
        controls.addWidget(self._defaults_button)
        controls.addStretch()
        layout.addLayout(controls)

        note = QLabel(tr("associations_note"))
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {COLORS['text_muted']};")
        layout.addWidget(note)
        layout.addStretch()

        self._executable.path_changed.connect(self._update_button)
        self._defaults_button.setEnabled(os.name == "nt")
        self._executable.setEnabled(os.name == "nt")
        try:
            candidate = suggested_executable() if os.name == "nt" else None
            if candidate:
                self._executable.set_path(str(candidate))
            self._refresh_status()
        except OSError as error:
            self._status.setText(tr("association_failed", error=error))
        self._update_button()

    def tab_title(self) -> str:
        return tr("file_associations")

    def on_apply(self) -> None:
        pass

    def _update_button(self) -> None:
        path = Path(self._executable.path())
        self._register_button.setEnabled(os.name == "nt" and path.is_file() and path.suffix.lower() == ".exe")

    def _refresh_status(self) -> None:
        if os.name != "nt":
            self._status.setText(tr("associations_windows_only"))
            return
        status = association_status()
        if status.is_default:
            self._status.setText(tr("associations_registered"))
        elif status.registered:
            self._status.setText(tr("associations_choose_default"))
        else:
            self._status.setText(tr("associations_not_registered"))

    def _register(self) -> None:
        try:
            register_associations(
                Path(self._executable.path()), tr("launch_project"), tr("edit_launch_profile")
            )
            self._refresh_status()
        except (OSError, ValueError) as error:
            MessageDialog.error(self, tr("error"), tr("association_failed", error=error))

    def _open_defaults(self) -> None:
        QDesktopServices.openUrl(QUrl("ms-settings:defaultapps"))
