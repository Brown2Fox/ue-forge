"""Windows file associations for launch profiles."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

if os.name == "nt":
    import winreg
else:
    winreg = None


PROG_ID = "UEForge.LaunchProfile"
APPLICATION_NAME = "UE Forge UProject Launcher"
CLASSES_KEY = r"Software\Classes"
CAPABILITIES_KEY = r"Software\UEForge\Launcher\Capabilities"
USER_CHOICE_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.ulaunch\UserChoice"


@dataclass(frozen=True)
class AssociationStatus:
    registered: bool = False
    is_default: bool = False
    executable: Path | None = None


def association_commands(executable: Path) -> tuple[str, str]:
    application = subprocess.list2cmdline([str(executable)])
    return (
        f'{application} --launch-profile "%1"',
        f'{application} --open --launch-profile "%1"',
    )


def _read_value(key: str, name: str = "", root=None) -> str:
    try:
        with winreg.OpenKey(root if root is not None else winreg.HKEY_CURRENT_USER, key) as handle:
            value, _ = winreg.QueryValueEx(handle, name)
            return value if isinstance(value, str) else ""
    except FileNotFoundError:
        return ""


def association_status() -> AssociationStatus:
    if winreg is None:
        return AssociationStatus()
    key = f"{CLASSES_KEY}\\{PROG_ID}"
    stored_path = _read_value(key, "LauncherExecutable")
    if not stored_path:
        return AssociationStatus()
    executable = Path(stored_path)
    launch, edit = association_commands(executable)
    registered = (
        executable.is_file()
        and _read_value(f"{key}\\shell") == "open"
        and _read_value(f"{key}\\shell\\open\\command") == launch
        and _read_value(f"{key}\\shell\\edit\\command") == edit
    )
    default = _read_value(USER_CHOICE_KEY, "ProgId") or _read_value(
        ".ulaunch", root=winreg.HKEY_CLASSES_ROOT
    )
    return AssociationStatus(registered, registered and default == PROG_ID, executable)


def suggested_executable() -> Path | None:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    registered = association_status().executable
    if registered and registered.is_file():
        return registered
    bundled = Path(__file__).resolve().parents[2] / "dist" / "UE UProject Launcher.exe"
    return bundled if bundled.is_file() else None


def register_associations(executable: Path, launch_label: str, edit_label: str) -> AssociationStatus:
    if winreg is None:
        raise OSError("File associations are supported only on Windows.")
    executable = executable.resolve(strict=True)
    if not executable.is_file() or executable.suffix.lower() != ".exe":
        raise ValueError("Select a UE Forge or UProject Launcher executable.")
    launch, edit = association_commands(executable)
    key = f"{CLASSES_KEY}\\{PROG_ID}"
    values = [
        (key, "", "Unreal Engine Launch Profile"),
        (key, "LauncherExecutable", str(executable)),
        (f"{key}\\DefaultIcon", "", f'"{executable}",0'),
        (f"{key}\\shell", "", "open"),
        (f"{key}\\shell\\open", "", launch_label),
        (f"{key}\\shell\\open\\command", "", launch),
        (f"{key}\\shell\\edit", "", edit_label),
        (f"{key}\\shell\\edit\\command", "", edit),
        (CAPABILITIES_KEY, "ApplicationName", APPLICATION_NAME),
        (CAPABILITIES_KEY, "ApplicationDescription", "Launch and edit Unreal Engine launch profiles"),
        (f"{CAPABILITIES_KEY}\\FileAssociations", ".ulaunch", PROG_ID),
        (r"Software\RegisteredApplications", APPLICATION_NAME, CAPABILITIES_KEY),
        (f"{CLASSES_KEY}\\.ulaunch", "", PROG_ID),
    ]
    for path, name, value in values:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE) as handle:
            winreg.SetValueEx(handle, name, 0, winreg.REG_SZ, value)
    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, f"{CLASSES_KEY}\\.ulaunch\\OpenWithProgids", 0, winreg.KEY_SET_VALUE
    ) as handle:
        winreg.SetValueEx(handle, PROG_ID, 0, winreg.REG_NONE, b"")
    ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
    return association_status()
