from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from arch_env.errors import CommandExecutionError
from arch_env.runner import CommandRunner, redact_command


class RunnerTests(unittest.TestCase):
    def test_failed_command_reports_exit_code_and_log_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "command.log"

            with self.assertRaises(CommandExecutionError) as context:
                CommandRunner().run(["python", "-c", "raise SystemExit(7)"], log_path=log_path)

        self.assertEqual(context.exception.returncode, 7)
        self.assertEqual(context.exception.log_path, str(log_path))
        self.assertEqual(context.exception.command, ["python", "-c", "raise SystemExit(7)"])

    def test_setenv_values_are_redacted_in_logs_and_errors(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "command.log"

            with self.assertRaises(CommandExecutionError) as context:
                CommandRunner().run(
                    ["python", "-c", "raise SystemExit(3)", "--setenv=TOKEN=secret"],
                    log_path=log_path,
                )

            content = log_path.read_text(encoding="utf-8")

        self.assertIn("--setenv=TOKEN=<redacted>", content)
        self.assertNotIn("secret", content)
        self.assertIn("--setenv=TOKEN=<redacted>", context.exception.display_command or "")
        self.assertEqual(context.exception.command[3], "--setenv=TOKEN=secret")

    def test_redact_command_only_redacts_setenv_values(self) -> None:
        self.assertEqual(
            redact_command(["systemd-nspawn", "--setenv=OPENAI_API_KEY=value", "--", "true"]),
            ["systemd-nspawn", "--setenv=OPENAI_API_KEY=<redacted>", "--", "true"],
        )


if __name__ == "__main__":
    unittest.main()
