from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from arch_env.config import load_config, write_default_config
from arch_env.errors import ConfigError


class ConfigTests(unittest.TestCase):
    def test_missing_config_uses_safe_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config = load_config(Path(directory))

        self.assertEqual(config.environment_name, "default")
        self.assertEqual(config.pacman_packages, ())
        self.assertEqual(config.aur_packages, ())
        self.assertTrue(config.mount_project)
        self.assertFalse(config.forward_gpu)
        self.assertEqual(config.device_paths, ())
        self.assertEqual(config.env_passthrough, ())
        self.assertFalse(config.forward_display)

    def test_valid_config_is_parsed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "arch-env.toml").write_text(
                """
[pacman]
packages = ["git", "jq"]

[aur]
packages = ["paru-bin"]

[mounts]
project = false
extra = ["/tmp/example"]

[devices]
gpu = true
paths = ["/dev/example"]

[env]
passthrough = ["OPENAI_API_KEY", "CUSTOM_ENV"]
""",
                encoding="utf-8",
            )

            config = load_config(project)

        self.assertEqual(config.environment_name, "default")
        self.assertEqual(config.pacman_packages, ("git", "jq"))
        self.assertEqual(config.aur_packages, ("paru-bin",))
        self.assertFalse(config.mount_project)
        self.assertEqual(config.extra_mounts, (Path("/tmp/example"),))
        self.assertTrue(config.forward_gpu)
        self.assertEqual(config.device_paths, (Path("/dev/example"),))
        self.assertEqual(config.env_passthrough, ("OPENAI_API_KEY", "CUSTOM_ENV"))

    def test_non_default_config_file_sets_environment_name(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "tools.toml").write_text("[pacman]\npackages = []\n", encoding="utf-8")

            config = load_config(project, Path("tools.toml"))

        self.assertEqual(config.environment_name, "tools")

    def test_invalid_config_filename_raises_config_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "bad name.toml").write_text("", encoding="utf-8")

            with self.assertRaises(ConfigError):
                load_config(project, Path("bad name.toml"))

    def test_invalid_toml_raises_config_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "arch-env.toml").write_text("[", encoding="utf-8")

            with self.assertRaises(ConfigError):
                load_config(project)

    def test_invalid_package_list_raises_config_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "arch-env.toml").write_text("[pacman]\npackages = [1]\n", encoding="utf-8")

            with self.assertRaises(ConfigError):
                load_config(project)

    def test_environment_table_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "arch-env.toml").write_text("[environment]\nname = \"dev\"\n", encoding="utf-8")

            with self.assertRaises(ConfigError):
                load_config(project)

    def test_forward_display_defaults_to_false(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "arch-env.toml").write_text("[pacman]\npackages = []\n", encoding="utf-8")

            config = load_config(project)

        self.assertFalse(config.forward_display)

    def test_forward_display_can_be_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "arch-env.toml").write_text(
                "[pacman]\npackages = []\n\n[shell]\nforward_display = true\n",
                encoding="utf-8",
            )

            config = load_config(project)

        self.assertTrue(config.forward_display)

    def test_invalid_forward_display_raises_config_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "arch-env.toml").write_text(
                '[shell]\nforward_display = "yes"\n',
                encoding="utf-8",
            )

            with self.assertRaises(ConfigError):
                load_config(project)

    def test_invalid_forward_gpu_raises_config_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "arch-env.toml").write_text(
                '[devices]\ngpu = "yes"\n',
                encoding="utf-8",
            )

            with self.assertRaises(ConfigError):
                load_config(project)

    def test_invalid_device_paths_raises_config_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "arch-env.toml").write_text(
                "[devices]\npaths = [1]\n",
                encoding="utf-8",
            )

            with self.assertRaises(ConfigError):
                load_config(project)

    def test_invalid_env_passthrough_raises_config_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "arch-env.toml").write_text(
                "[env]\npassthrough = [1]\n",
                encoding="utf-8",
            )

            with self.assertRaises(ConfigError):
                load_config(project)

    def test_invalid_env_passthrough_name_raises_config_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "arch-env.toml").write_text(
                '[env]\npassthrough = ["BAD=VALUE"]\n',
                encoding="utf-8",
            )

            with self.assertRaises(ConfigError):
                load_config(project)

    def test_write_default_config_refuses_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            write_default_config(project)

            with self.assertRaises(ConfigError):
                write_default_config(project)


if __name__ == "__main__":
    unittest.main()
