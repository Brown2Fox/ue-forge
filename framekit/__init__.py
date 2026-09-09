"""
framekit — opinionated mini-application chassis on top of pyside_frameless.

Provides: themed widgets, settings & message dialogs, sidebar host window,
standalone single-page shell, JSON-backed config, per-user platform paths,
localization with per-module registration, and ``run_standalone`` /
``run_host`` bootstrap helpers.
"""

from .app import run_host, run_standalone
from .config import AppConfig, ConfigManager, get_config_manager, set_config_manager
from .icons import Icons, get_indicator_icon_path
from .localization import (
    clear_custom_locale,
    detect_system_language,
    get_available_languages,
    get_current_language,
    init_localization,
    load_custom_locale,
    register_translations,
    set_language,
    tr,
)
from .platform import (
    LinuxHandler,
    MacOSHandler,
    PlatformHandler,
    WindowsHandler,
    default_handler_for,
    get_platform,
    platform_handler,
    set_platform_handler,
)
from .shell import HostWindow, SinglePageShell, ToolPage
from .styles import (
    COLORS,
    DARK_COLORS,
    FONTS,
    LIGHT_COLORS,
    RADIUS,
    SPACING,
    get_current_theme,
    get_main_stylesheet,
    set_theme,
)
from .types import LogLevel, LogMessage, StatusKind

__all__ = [
    # Types
    "LogLevel",
    "LogMessage",
    "StatusKind",
    # Localization
    "tr",
    "register_translations",
    "get_current_language",
    "set_language",
    "get_available_languages",
    "load_custom_locale",
    "clear_custom_locale",
    "init_localization",
    "detect_system_language",
    # Config
    "AppConfig",
    "ConfigManager",
    "get_config_manager",
    "set_config_manager",
    # Platform
    "PlatformHandler",
    "WindowsHandler",
    "LinuxHandler",
    "MacOSHandler",
    "get_platform",
    "platform_handler",
    "set_platform_handler",
    "default_handler_for",
    # Styles / icons
    "COLORS",
    "DARK_COLORS",
    "LIGHT_COLORS",
    "FONTS",
    "RADIUS",
    "SPACING",
    "get_main_stylesheet",
    "get_current_theme",
    "set_theme",
    "Icons",
    "get_indicator_icon_path",
    # Shell
    "HostWindow",
    "SinglePageShell",
    "ToolPage",
    # Bootstrap
    "run_standalone",
    "run_host",
]
