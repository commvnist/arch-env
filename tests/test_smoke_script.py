from __future__ import annotations

from pathlib import Path
import contextlib
import importlib.util
import io
import tempfile
import unittest


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "smoke_dev_package_managers.py"


def load_smoke_module() -> object:
    spec = importlib.util.spec_from_file_location("smoke_dev_package_managers", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load smoke script")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SmokeScriptTests(unittest.TestCase):
    def test_smoke_commands_cover_five_package_managers(self) -> None:
        smoke = load_smoke_module()
        with tempfile.TemporaryDirectory() as directory:
            commands = smoke.smoke_commands(Path(directory))

        rendered = "\n".join(smoke.render_command(command) for command in commands)

        self.assertIn("install python uv ruby ruby-bundler nodejs npm rust go", rendered)
        self.assertIn("uv run --with rich", rendered)
        self.assertIn("bundle install", rendered)
        self.assertIn("npm install left-pad", rendered)
        self.assertIn("cargo run --quiet", rendered)
        self.assertIn("go run .", rendered)

    def test_dry_run_main_does_not_execute_external_commands(self) -> None:
        smoke = load_smoke_module()
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            self.assertEqual(smoke.main(["--dry-run"]), 0)
        self.assertIn("arch_env", output.getvalue())


if __name__ == "__main__":
    unittest.main()
