from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from arch_env.errors import PathSafetyError
from arch_env.paths import build_environment_paths, ensure_managed_environment_path, validate_environment_name


class PathTests(unittest.TestCase):
    def test_valid_environment_name(self) -> None:
        self.assertEqual(validate_environment_name("dev-1.test"), "dev-1.test")

    def test_environment_name_rejects_traversal(self) -> None:
        for name in ("../prod", "/prod", ".hidden", "bad/name", ""):
            with self.subTest(name=name):
                with self.assertRaises(PathSafetyError):
                    validate_environment_name(name)

    def test_managed_environment_requires_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = build_environment_paths(Path(directory), "dev")
            paths.env_dir.mkdir(parents=True)

            with self.assertRaises(PathSafetyError):
                ensure_managed_environment_path(paths)

    def test_partial_arch_root_without_metadata_is_managed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = build_environment_paths(Path(directory), "dev")
            (paths.root_dir / "etc").mkdir(parents=True)
            (paths.root_dir / "etc" / "arch-release").write_text("", encoding="utf-8")
            (paths.root_dir / "var" / "lib" / "pacman").mkdir(parents=True)

            ensure_managed_environment_path(paths)

    def test_non_arch_root_without_metadata_is_unmanaged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = build_environment_paths(Path(directory), "dev")
            (paths.root_dir / "etc").mkdir(parents=True)
            (paths.root_dir / "etc" / "not-arch").write_text("", encoding="utf-8")

            with self.assertRaises(PathSafetyError):
                ensure_managed_environment_path(paths)

    def test_managed_environment_accepts_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = build_environment_paths(Path(directory), "dev")
            paths.env_dir.mkdir(parents=True)
            paths.metadata_path.write_text("{}", encoding="utf-8")

            ensure_managed_environment_path(paths)


if __name__ == "__main__":
    unittest.main()
