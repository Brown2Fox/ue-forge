import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ue_forge.uproject_launcher import file_associations as associations


class RegistryKey:
    def __init__(self, root, path):
        self.root, self.path = root, path

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


class MemoryRegistry:
    HKEY_CURRENT_USER = "HKCU"
    HKEY_CLASSES_ROOT = "HKCR"
    KEY_SET_VALUE = 2
    REG_SZ = 1
    REG_NONE = 0

    def __init__(self):
        self.values = {}

    def OpenKey(self, root, path):
        if root == self.HKEY_CLASSES_ROOT:
            root, path = self.HKEY_CURRENT_USER, f"Software\\Classes\\{path}"
        return RegistryKey(root, path)

    def CreateKeyEx(self, root, path, *_):
        return RegistryKey(root, path)

    def SetValueEx(self, key, name, _, kind, value):
        self.values[(key.root, key.path, name)] = (value, kind)

    def QueryValueEx(self, key, name):
        try:
            return self.values[(key.root, key.path, name)]
        except KeyError:
            raise FileNotFoundError(key.path) from None


class LauncherFileAssociationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.executable = Path(temporary.name).resolve() / "UE Forge.exe"
        self.executable.touch()
        self.registry = MemoryRegistry()
        patcher = patch.object(associations, "winreg", self.registry)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = patch.object(associations.ctypes, "windll", create=True)
        self.shell = patcher.start().shell32
        self.addCleanup(patcher.stop)

    def value(self, path, name=""):
        return self.registry.values[("HKCU", path, name)][0]

    def test_registers_launch_as_default_and_edit_with_quoted_file_argument(self):
        status = associations.register_associations(self.executable, "Launch project", "Edit profile")
        base = r"Software\Classes\UEForge.LaunchProfile"
        self.assertTrue(status.registered)
        self.assertTrue(status.is_default)
        self.assertEqual(self.value(r"Software\Classes\.ulaunch"), associations.PROG_ID)
        self.assertEqual(self.value(base + r"\shell"), "open")
        self.assertEqual(self.value(base + r"\shell\open\command"), f'"{self.executable}" --launch-profile "%1"')
        self.assertEqual(self.value(base + r"\shell\edit\command"), f'"{self.executable}" --open --launch-profile "%1"')
        self.assertEqual(self.value(base + r"\shell\edit"), "Edit profile")
        self.assertEqual(self.value(associations.CAPABILITIES_KEY + r"\FileAssociations", ".ulaunch"), associations.PROG_ID)
        self.assertTrue(all(root == "HKCU" for root, _, _ in self.registry.values))
        self.shell.SHChangeNotify.assert_called_once_with(0x08000000, 0, None, None)

    def test_preserves_windows_user_choice(self):
        key = ("HKCU", associations.USER_CHOICE_KEY, "ProgId")
        self.registry.values[key] = ("OtherApp.Profile", 1)
        status = associations.register_associations(self.executable, "Launch", "Edit")
        self.assertTrue(status.registered)
        self.assertFalse(status.is_default)
        self.assertEqual(self.registry.values[key], ("OtherApp.Profile", 1))

    def test_reregister_updates_application_path_and_detects_missing_executable(self):
        associations.register_associations(self.executable, "Launch", "Edit")
        replacement = self.executable.with_name("Launcher.exe")
        replacement.touch()
        associations.register_associations(replacement, "Launch", "Edit")
        self.assertEqual(associations.association_status().executable, replacement)
        replacement.unlink()
        self.assertFalse(associations.association_status().registered)

    def test_invalid_executable_does_not_write_registry(self):
        with self.assertRaises(FileNotFoundError):
            associations.register_associations(self.executable.with_name("Missing.exe"), "Launch", "Edit")
        invalid = self.executable.with_suffix(".txt")
        invalid.touch()
        with self.assertRaises(ValueError):
            associations.register_associations(invalid, "Launch", "Edit")
        self.assertEqual(self.registry.values, {})
        self.shell.SHChangeNotify.assert_not_called()

    def test_profile_cli_launch_and_edit_modes(self):
        from ue_forge.uproject_launcher.__main__ import main
        profile = self.executable.with_name("Game Profile.ulaunch")
        for arguments, launch in (([str(profile)], True), (["--launch-profile", str(profile)], True),
                                  (["--open", "--launch-profile", str(profile)], False)):
            with self.subTest(arguments=arguments), patch("ue_forge.uproject_launcher.__main__.run_standalone") as run:
                run.return_value = 0
                with patch("ue_forge.uproject_launcher.page.UProjectLauncherPage") as page:
                    self.assertEqual(main(arguments), 0)
                    run.call_args.kwargs["page_factory"]()
                    page.assert_called_once_with(initial_profile_path=profile, launch_immediately=launch)

    def test_combined_executable_routes_association_arguments_to_launcher(self):
        from ue_forge.__main__ import main
        arguments = ["--open", "--launch-profile", "Game Profile.ulaunch"]
        with patch("sys.argv", ["UE Forge.exe", *arguments]), patch("ue_forge.uproject_launcher.__main__.main", return_value=0) as launch:
            self.assertEqual(main(), 0)
            launch.assert_called_once_with(arguments)
