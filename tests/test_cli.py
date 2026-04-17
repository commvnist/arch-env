from __future__ import annotations

import unittest
from unittest.mock import patch
import importlib.util

if importlib.util.find_spec("typer") is None:
    raise unittest.SkipTest("typer is not installed")

from typer.testing import CliRunner
from arch_env.cli import app


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


if __name__ == "__main__":
    unittest.main()
