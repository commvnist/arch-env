from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from arch_env.config import ArchEnvConfig
from arch_env.environment import EnvironmentManager
from arch_env.errors import CommandExecutionError


def _config(**kwargs: object) -> ArchEnvConfig:
    defaults: dict[str, object] = {
        "environment_name": "dev",
        "config_path": Path("/tmp/dev.toml"),
        "pacman_packages": (),
        "aur_packages": (),
        "mount_project": True,
        "extra_mounts": (),
        "forward_display": False,
    }
    defaults.update(kwargs)
    return ArchEnvConfig(**defaults)  # type: ignore[arg-type]


class EnvironmentMetadataTests(unittest.TestCase):
    def test_metadata_serializes_path_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            manager = EnvironmentManager(project)
            paths = manager.paths("dev")
            paths.env_dir.mkdir(parents=True)
            config = _config(
                config_path=project / "dev.toml",
                pacman_packages=("jq",),
                extra_mounts=(project / "cache",),
            )

            manager._write_metadata(paths, config, status="ready")
            metadata = json.loads(paths.metadata_path.read_text(encoding="utf-8"))

        self.assertEqual(metadata["config"]["extra_mounts"], [str(project / "cache")])
        self.assertEqual(metadata["status"], "ready")

    def test_create_marks_failed_environment_when_external_command_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            runner = FailingRunner()
            manager = EnvironmentManager(project, runner=runner)
            config = _config(config_path=project / "dev.toml")

            with patch("arch_env.environment.validate_host_prerequisites"):
                with self.assertRaises(CommandExecutionError):
                    manager.create("dev", config)

            paths = manager.paths("dev")
            metadata = json.loads(paths.metadata_path.read_text(encoding="utf-8"))

        self.assertEqual(metadata["status"], "failed")

    def test_bootstrap_user_does_not_mount_package_caches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            runner = RecordingRunner()
            manager = EnvironmentManager(project, runner=runner)
            config = _config(config_path=project / "dev.toml")

            with patch("arch_env.environment.validate_host_prerequisites"):
                manager.create("dev", config)

        bootstrap_user_command = runner.commands[1]
        self.assertNotIn("/var/cache/pacman/pkg", bootstrap_user_command)
        self.assertNotIn("/home/archenv/.cache/yay", bootstrap_user_command)

    def test_create_bootstraps_yay_after_package_install(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            runner = RecordingRunner()
            manager = EnvironmentManager(project, runner=runner)
            config = _config(config_path=project / "dev.toml", pacman_packages=("jq",))

            with patch("arch_env.environment.validate_host_prerequisites"):
                manager.create("dev", config)

        keyring_command = runner.commands[2]
        install_command = runner.commands[3]
        yay_sudo_command = runner.commands[4]
        yay_deps_command = runner.commands[5]
        yay_build_command = runner.commands[6]
        yay_install_command = runner.commands[7]
        self.assertIn("pacman-key --init", " ".join(keyring_command))
        self.assertIn("pacman --noconfirm -Syu jq", " ".join(install_command))
        self.assertIn("NOPASSWD: /usr/bin/pacman", " ".join(yay_sudo_command))
        self.assertIn("pacman --noconfirm -S --needed go", " ".join(yay_deps_command))
        self.assertIn("git clone https://aur.archlinux.org/yay.git", " ".join(yay_build_command))
        self.assertIn("pacman --noconfirm -U", " ".join(yay_install_command))

    def test_create_bootstraps_yay_without_configured_packages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            runner = RecordingRunner()
            manager = EnvironmentManager(project, runner=runner)
            config = _config(config_path=project / "dev.toml")

            with patch("arch_env.environment.validate_host_prerequisites"):
                manager.create("dev", config)

        commands = [" ".join(command) for command in runner.commands]
        self.assertTrue(any("git clone https://aur.archlinux.org/yay.git" in command for command in commands))

    def test_create_emits_progress_messages_with_log_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            runner = RecordingRunner()
            messages: list[str] = []
            manager = EnvironmentManager(project, runner=runner, progress=messages.append)
            config = _config(config_path=project / "dev.toml")

            with patch("arch_env.environment.validate_host_prerequisites"):
                manager.create("dev", config)

        self.assertIn("Validating host prerequisites for environment 'dev'.", messages)
        self.assertIn("Bootstrapping Arch root with pacstrap.", messages)
        self.assertTrue(any("bootstrap-pacstrap.log" in message for message in messages))
        self.assertIn("Environment 'dev' is ready.", messages)

    def test_shell_repairs_missing_container_user_before_exec(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            runner = ExecStoppingRunner()
            manager = EnvironmentManager(project, runner=runner)
            paths = manager.paths("dev")
            paths.env_dir.mkdir(parents=True)
            paths.metadata_path.write_text("{}", encoding="utf-8")
            config = _config(config_path=project / "dev.toml")

            with patch("arch_env.environment.os.execvpe", side_effect=RuntimeError("stop")):
                with self.assertRaises(RuntimeError):
                    manager.shell("dev", config)

        user_check_command = runner.commands[0]
        self.assertIn("useradd", " ".join(user_check_command))
        self.assertIn("shell-user-check.log", str(runner.log_paths[0]))

    def test_run_repairs_user_and_execs_requested_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            runner = ExecStoppingRunner()
            manager = EnvironmentManager(project, runner=runner)
            paths = manager.paths("dev")
            paths.env_dir.mkdir(parents=True)
            paths.metadata_path.write_text("{}", encoding="utf-8")
            config = _config(config_path=project / "dev.toml")

            with patch("arch_env.environment.os.execvpe", side_effect=RuntimeError("stop")) as execvpe:
                with self.assertRaises(RuntimeError):
                    manager.run("dev", config, ("python", "--version"))

        user_check_command = runner.commands[0]
        executed_command = execvpe.call_args.args[1]
        self.assertIn("useradd", " ".join(user_check_command))
        self.assertIn("run-user-check.log", str(runner.log_paths[0]))
        self.assertEqual(executed_command[-2:], ["python", "--version"])

    def test_shell_includes_display_mounts_when_forward_display_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            runtime_dir = Path(directory) / "runtime"
            runtime_dir.mkdir()
            manager = EnvironmentManager(project)
            paths = manager.paths("dev")
            paths.env_dir.mkdir(parents=True)
            paths.metadata_path.write_text("{}", encoding="utf-8")
            config = _config(
                config_path=project / "dev.toml",
                forward_display=True,
            )

            captured: list[list[str]] = []

            def fake_execvpe(path: str, args: list[str], env: dict[str, str]) -> None:
                captured.append(args)
                raise RuntimeError("stop")

            fake_display = {"DISPLAY": ":1", "WAYLAND_DISPLAY": "wayland-1"}
            fake_mounts: tuple[tuple[Path, str], ...] = ((runtime_dir, str(runtime_dir)),)
            with patch("arch_env.environment.os.execvpe", side_effect=fake_execvpe):
                with patch("arch_env.environment.display_environment", return_value=fake_display):
                    with patch("arch_env.environment.display_bind_mounts", return_value=fake_mounts):
                        with patch("arch_env.environment.EnvironmentManager._run_in_container"):
                            with self.assertRaises(RuntimeError):
                                manager.shell("dev", config)

        nspawn_args = captured[0]
        self.assertIn(f"--setenv=DISPLAY=:1", nspawn_args)
        self.assertIn(f"--setenv=WAYLAND_DISPLAY=wayland-1", nspawn_args)
        self.assertIn(f"{runtime_dir}:{runtime_dir}", nspawn_args)

    def test_shell_omits_display_mounts_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            manager = EnvironmentManager(project)
            paths = manager.paths("dev")
            paths.env_dir.mkdir(parents=True)
            paths.metadata_path.write_text("{}", encoding="utf-8")
            config = _config(config_path=project / "dev.toml")

            captured: list[list[str]] = []

            def fake_execvpe(path: str, args: list[str], env: dict[str, str]) -> None:
                captured.append(args)
                raise RuntimeError("stop")

            with patch("arch_env.environment.os.execvpe", side_effect=fake_execvpe):
                with patch("arch_env.environment.EnvironmentManager._run_in_container"):
                    with self.assertRaises(RuntimeError):
                        manager.shell("dev", config)

        nspawn_args = captured[0]
        self.assertNotIn("--setenv=DISPLAY=:1", nspawn_args)

    def test_remove_uses_sudo_after_permission_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            runner = RecordingRunner()
            manager = EnvironmentManager(project, runner=runner)
            paths = manager.paths("dev")
            paths.env_dir.mkdir(parents=True)
            paths.metadata_path.write_text("{}", encoding="utf-8")

            with patch("arch_env.environment.shutil.rmtree", side_effect=PermissionError("denied")):
                manager.remove("dev")

        self.assertEqual(
            runner.commands[0],
            ["sudo", "rm", "-rf", "--one-file-system", str(paths.env_dir)],
        )


class RecordingRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def run(self, command: list[str], *, log_path: Path, check: bool = True) -> None:
        self.commands.append(command)


class ExecStoppingRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.log_paths: list[Path] = []

    def run(self, command: list[str], *, log_path: Path, check: bool = True) -> None:
        self.commands.append(command)
        self.log_paths.append(log_path)


class FailingRunner:
    def run(self, command: list[str], *, log_path: Path, check: bool = True) -> None:
        raise CommandExecutionError(
            "failed",
            command=command,
            returncode=1,
            log_path=str(log_path),
        )


if __name__ == "__main__":
    unittest.main()
