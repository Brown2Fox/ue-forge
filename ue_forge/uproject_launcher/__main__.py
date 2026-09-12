"""Standalone entry point for the UProject Launcher."""

import argparse
import sys
from pathlib import Path

from framekit import run_standalone
from ue_forge import APP_ORG, APP_SLUG
from ue_forge.assets import icon_path
from ue_forge.config import UEForgeConfigManager
from ue_forge.platform import ue_handler_for


def main(argv: list[str] | None = None) -> int:
    from ue_forge.uproject_launcher.page import UProjectLauncherPage

    parser = argparse.ArgumentParser(prog="UE UProject Launcher")
    profiles = parser.add_mutually_exclusive_group()
    profiles.add_argument("profile", nargs="?", help="Path to a .ulaunch profile")
    profiles.add_argument("--launch-profile", metavar="PROFILE", help="Path to a .ulaunch profile")
    parser.add_argument("--open", action="store_true", dest="open_only", help="Open the profile without launching")
    arguments = parser.parse_args(argv)
    selected_profile = arguments.profile or arguments.launch_profile
    profile_path = Path(selected_profile).resolve() if selected_profile else None

    return run_standalone(
        page_factory=lambda: UProjectLauncherPage(
            initial_profile_path=profile_path,
            launch_immediately=profile_path is not None and not arguments.open_only,
        ),
        app_name="UE UProject Launcher",
        org_name=APP_ORG,
        app_slug=APP_SLUG,
        icon_path=icon_path(),
        platform_handler=ue_handler_for(APP_SLUG),
        config_manager=UEForgeConfigManager(),
    )


if __name__ == "__main__":
    sys.exit(main())
