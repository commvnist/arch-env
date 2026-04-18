from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

from arch_env.config import ArchEnvConfig
from arch_env.commands import ARCH_ENV_HELPER_DIR
from arch_env.environment import EnvironmentManager
from arch_env.errors import ArchEnvError, CommandExecutionError


def _config(**kwargs: object) -> ArchEnvConfig:
    defaults: dict[str, object] = {
        "environment_name": "dev",
        "config_path": Path("/tmp/dev.toml"),
        "pacman_packages": (),
        "aur_packages": (),
        "mount_project": True,
        "extra_mounts": (),
        "forward_gpu": False,
        "device_paths": (),
        "env_passthrough": (),
        "forward_display": False,
        "developer_writable_prefixes": True,
    }
    defaults.update(kwargs)
    return ArchEnvConfig(**defaults)  # type: ignore[arg-type]


def _write_ready_metadata(manager: EnvironmentManager, name: str, config: ArchEnvConfig) -> None:
    paths = manager.paths(name)
    paths.env_dir.mkdir(parents=True)
    manager._write_metadata(paths, config, status="ready")


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
                device_paths=(project / "device",),
            )

            manager._write_metadata(paths, config, status="ready")
            metadata = json.loads(paths.metadata_path.read_text(encoding="utf-8"))

        self.assertEqual(metadata["config"]["extra_mounts"], [str(project / "cache")])
        self.assertEqual(metadata["config"]["device_paths"], [str(project / "device")])
        self.assertEqual(metadata["status"], "ready")
        self.assertIn("updated_at", metadata)
        self.assertIsNone(metadata["last_error"])

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
        self.assertEqual(metadata["last_error"], "failed")

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

        commands = [" ".join(command) for command in runner.commands]
        keyring_command = commands[2]
        install_command = next(command for command in commands if "/usr/bin/pacman --noconfirm -Syu jq" in command)
        yay_sudo_command = next(command for command in commands if "NOPASSWD: /usr/libexec/arch-env/pacman" in command)
        yay_deps_command = next(command for command in commands if "pacman --noconfirm -S --needed go" in command)
        yay_build_command = next(command for command in commands if "git clone https://aur.archlinux.org/yay.git" in command)
        yay_install_command = next(command for command in commands if "pacman --noconfirm -U" in command)
        yay_verify_command = next(command for command in runner.commands if command[-2:] == ["/usr/bin/yay", "--version"])
        self.assertIn("pacman-key --init", keyring_command)
        self.assertIn("/usr/bin/pacman --noconfirm -Syu jq", install_command)
        self.assertIn("NOPASSWD: /usr/libexec/arch-env/pacman", yay_sudo_command)
        self.assertIn("pacman --noconfirm -S --needed go", yay_deps_command)
        self.assertIn("git clone https://aur.archlinux.org/yay.git", yay_build_command)
        self.assertIn("pacman --noconfirm -U", yay_install_command)
        self.assertEqual(yay_verify_command[-2:], ["/usr/bin/yay", "--version"])

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

    def test_create_bootstraps_yay_once_with_configured_aur_packages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            runner = RecordingRunner()
            manager = EnvironmentManager(project, runner=runner)
            config = _config(config_path=project / "dev.toml", aur_packages=("paru-bin",))

            with patch("arch_env.environment.validate_host_prerequisites"):
                manager.create("dev", config)

        commands = [" ".join(command) for command in runner.commands]
        yay_build_commands = [command for command in commands if "git clone https://aur.archlinux.org/yay.git" in command]
        self.assertEqual(len(yay_build_commands), 1)

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

    def test_shell_repairs_user_write_access_and_execs_as_archenv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            runner = ExecStoppingRunner()
            manager = EnvironmentManager(project, runner=runner)
            config = _config(config_path=project / "dev.toml")
            _write_ready_metadata(manager, "dev", config)

            with patch("arch_env.environment.os.execvpe", side_effect=RuntimeError("stop")) as execvpe:
                with self.assertRaises(RuntimeError):
                    manager.shell("dev", config)

        executed_command = execvpe.call_args.args[1]
        commands = [" ".join(command) for command in runner.commands]
        self.assertIn("useradd", commands[0])
        self.assertIn("NOPASSWD: /usr/libexec/arch-env/pacman", commands[1])
        self.assertIn("find \"$path\" -type d -exec chmod g+rwx,g+s", commands[2])
        self.assertIn(ARCH_ENV_HELPER_DIR, commands[3])
        self.assertNotIn("/usr/local/bin/pacman", commands[3])
        self.assertIn("shell-user-check.log", str(runner.log_paths[0]))
        self.assertIn("--user", executed_command)
        self.assertIn("archenv", executed_command)

    def test_run_repairs_user_write_access_and_execs_as_archenv(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            runner = ExecStoppingRunner()
            manager = EnvironmentManager(project, runner=runner)
            config = _config(config_path=project / "dev.toml")
            _write_ready_metadata(manager, "dev", config)

            with patch("arch_env.environment.os.execvpe", side_effect=RuntimeError("stop")) as execvpe:
                with self.assertRaises(RuntimeError):
                    manager.run("dev", config, ("python", "--version"))

        executed_command = execvpe.call_args.args[1]
        commands = [" ".join(command) for command in runner.commands]
        self.assertIn("useradd", commands[0])
        self.assertIn("NOPASSWD: /usr/libexec/arch-env/pacman", commands[1])
        self.assertIn("find \"$path\" -type d -exec chmod g+rwx,g+s", commands[2])
        self.assertIn(ARCH_ENV_HELPER_DIR, commands[3])
        self.assertNotIn("/usr/local/bin/pacman", commands[3])
        self.assertIn("run-user-check.log", str(runner.log_paths[0]))
        self.assertIn("--user", executed_command)
        self.assertIn("archenv", executed_command)
        self.assertEqual(executed_command[-2:], ["python", "--version"])

    def test_install_repairs_user_and_sudo_before_package_operations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            runner = RecordingRunner()
            messages: list[str] = []
            manager = EnvironmentManager(project, runner=runner, progress=messages.append)
            config = _config(config_path=project / "dev.toml")
            _write_ready_metadata(manager, "dev", config)

            with patch("arch_env.environment.validate_host_prerequisites"):
                manager.install("dev", config, ("jq",))

        commands = [" ".join(command) for command in runner.commands]
        self.assertIn("useradd", commands[0])
        self.assertIn("NOPASSWD: /usr/libexec/arch-env/pacman", commands[1])
        self.assertIn("find \"$path\" -type d -exec chmod go-w,g-s", commands[2])
        self.assertTrue(any("/usr/bin/pacman -Si jq" in command for command in commands))
        self.assertTrue(any("/usr/bin/pacman --noconfirm -Syu jq" in command for command in commands))
        self.assertTrue(any(ARCH_ENV_HELPER_DIR in command for command in commands))
        self.assertFalse(any("/usr/local/bin/pacman" in command for command in commands))
        self.assertTrue(any("find \"$path\" -type d -exec chmod g+rwx,g+s" in command for command in commands))
        self.assertEqual(messages.count("Checking official repositories for jq."), 1)
        self.assertNotIn("Checking official repositories for jq", messages)

    def test_install_fails_when_package_cannot_be_resolved_in_pacman_or_aur(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            runner = PackageResolutionFailingRunner()
            manager = EnvironmentManager(project, runner=runner)
            config = _config(config_path=project / "dev.toml")
            _write_ready_metadata(manager, "dev", config)

            with patch("arch_env.environment.validate_host_prerequisites"):
                with self.assertRaises(ArchEnvError) as context:
                    manager.install("dev", config, ("missing-package",))

        self.assertIn("Could not resolve package 'missing-package'", str(context.exception))
        self.assertIn("package-resolution.log", str(context.exception))
        self.assertIn("aur-package-resolution.log", str(context.exception))

    def test_shell_includes_display_mounts_when_forward_display_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            runtime_dir = Path(directory) / "runtime"
            runtime_dir.mkdir()
            manager = EnvironmentManager(project)
            config = _config(
                config_path=project / "dev.toml",
                forward_display=True,
            )
            _write_ready_metadata(manager, "dev", config)

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

    def test_shell_includes_configured_device_and_env_passthrough(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            device = project / "device"
            device.touch()
            manager = EnvironmentManager(project)
            config = _config(
                config_path=project / "dev.toml",
                device_paths=(device,),
                env_passthrough=("CUSTOM_TOKEN",),
            )
            _write_ready_metadata(manager, "dev", config)

            captured: list[list[str]] = []

            def fake_execvpe(path: str, args: list[str], env: dict[str, str]) -> None:
                captured.append(args)
                raise RuntimeError("stop")

            with patch.dict("arch_env.commands.os.environ", {"CUSTOM_TOKEN": "abc"}, clear=False):
                with patch("arch_env.environment.os.execvpe", side_effect=fake_execvpe):
                    with patch("arch_env.environment.EnvironmentManager._run_in_container"):
                        with self.assertRaises(RuntimeError):
                            manager.shell("dev", config)

        nspawn_args = captured[0]
        self.assertIn(f"{device.resolve()}:{device}", nspawn_args)
        self.assertIn("--setenv=CUSTOM_TOKEN=abc", nspawn_args)

    def test_shell_omits_display_mounts_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            manager = EnvironmentManager(project)
            config = _config(config_path=project / "dev.toml")
            _write_ready_metadata(manager, "dev", config)

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
        self.assertNotIn("--setenv=CUSTOM_TOKEN=abc", nspawn_args)

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


class PackageResolutionFailingRunner:
    def run(self, command: list[str], *, log_path: Path, check: bool = True) -> None:
        command_text = " ".join(command)
        if "/usr/bin/pacman -Si missing-package" in command_text:
            raise CommandExecutionError(
                "pacman query failed",
                command=command,
                returncode=1,
                log_path=str(log_path),
            )
        if "/usr/bin/yay -Si missing-package" in command_text:
            raise CommandExecutionError(
                "yay query failed",
                command=command,
                returncode=1,
                log_path=str(log_path),
            )


if __name__ == "__main__":
    unittest.main()
