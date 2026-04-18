from __future__ import annotations

import unittest
from unittest.mock import patch
import importlib.util
import tempfile

if importlib.util.find_spec("typer") is None:
    raise unittest.SkipTest("typer is not installed")

from typer.testing import CliRunner
from arch_env.cli import app
from arch_env import __version__


class CliTests(unittest.TestCase):
    def test_no_args_opens_interactive_app(self) -> None:
        runner = CliRunner()

        with patch("arch_env.cli.InteractiveApp") as app_class:
            result = runner.invoke(app, [])

        self.assertEqual(result.exit_code, 0)
        app_class.assert_called_once()
        app_class.return_value.run.assert_called_once()

    def test_i_command_is_not_registered(self) -> None:
        runner = CliRunner()

        result = runner.invoke(app, ["i"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("No such command", result.output)

    def test_version_option_prints_version(self) -> None:
        runner = CliRunner()

        result = runner.invoke(app, ["--version"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn(f"arch-env {__version__}", result.output)

    def test_doctor_reports_missing_environment(self) -> None:
        runner = CliRunner()

        with patch("arch_env.cli.validate_host_prerequisites"):
            result = runner.invoke(app, ["doctor"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn("config: ok", result.output)
        self.assertIn("environment: missing", result.output)

    def test_global_project_dir_applies_to_subcommands(self) -> None:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as directory:
            with patch("arch_env.cli.validate_host_prerequisites"):
                result = runner.invoke(app, ["--project-dir", directory, "doctor"])

        self.assertEqual(result.exit_code, 0)
        self.assertIn(f"config: missing ({directory}/arch-env.toml)", result.output)
        self.assertIn(f"environment: missing ({directory}/.arch-env/envs/default)", result.output)


if __name__ == "__main__":
    unittest.main()
