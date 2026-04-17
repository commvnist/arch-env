from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from arch_env.errors import CommandExecutionError
from arch_env.runner import CommandRunner


class RunnerTests(unittest.TestCase):
    def test_failed_command_reports_exit_code_and_log_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "command.log"

            with self.assertRaises(CommandExecutionError) as context:
                CommandRunner().run(["python", "-c", "raise SystemExit(7)"], log_path=log_path)

        self.assertEqual(context.exception.returncode, 7)
        self.assertEqual(context.exception.log_path, str(log_path))
        self.assertEqual(context.exception.command, ["python", "-c", "raise SystemExit(7)"])


if __name__ == "__main__":
    unittest.main()
