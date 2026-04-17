from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, UTC
from pathlib import Path
import json
import os
import shutil

from arch_env import __version__
from arch_env.commands import (
    CONTAINER_USER,
    bootstrap_yay_command,
    create_container_user_command,
    forwarded_run_environment,
    initialize_keyring_command,
    nspawn_command,
    pacman_install_command,
    pacman_query_command,
    safe_shell_environment,
    pacstrap_command,
    shell_command,
    yay_install_command,
)
from arch_env.config import ArchEnvConfig
from arch_env.errors import ArchEnvError, CommandExecutionError
from arch_env.paths import EnvironmentPaths, build_environment_paths, ensure_managed_environment_path
from arch_env.prerequisites import validate_host_prerequisites
from arch_env.runner import CommandRunner


class EnvironmentManager:
    def __init__(
        self,
        project_dir: Path,
        runner: CommandRunner | None = None,
        progress: Callable[[str], None] | None = None,
    ):
        self.project_dir = project_dir.resolve()
        self.runner = runner or CommandRunner()
        self.progress = progress

    def paths(self, name: str) -> EnvironmentPaths:
        return build_environment_paths(self.project_dir, name)

    def create(self, name: str, config: ArchEnvConfig) -> EnvironmentPaths:
        self._progress(f"Validating host prerequisites for environment '{name}'.")
        validate_host_prerequisites()
        paths = self.paths(name)
        if paths.metadata_path.exists():
            raise ArchEnvError(f"Environment already exists: {paths.env_dir}")

        self._progress(f"Creating environment '{name}' at {paths.env_dir}.")
        paths.root_dir.mkdir(parents=True, exist_ok=True)
        paths.pacman_cache_dir.mkdir(parents=True, exist_ok=True)
        paths.aur_cache_dir.mkdir(parents=True, exist_ok=True)
        paths.logs_dir.mkdir(parents=True, exist_ok=True)
        self._write_metadata(paths, config, status="creating")

        try:
            self._run_host_command(
                pacstrap_command(paths),
                paths.logs_dir / "bootstrap-pacstrap.log",
                "Bootstrapping Arch root with pacstrap",
            )
            self._run_in_container(
                paths,
                create_container_user_command(),
                "bootstrap-user.log",
                "Creating container user",
                project_mount=False,
                package_caches=False,
            )
            self._run_in_container(
                paths,
                initialize_keyring_command(),
                "bootstrap-keyring.log",
                "Initializing pacman keyring",
                project_mount=False,
                package_caches=False,
            )

            if config.pacman_packages:
                self.install_pacman_packages(paths, config.pacman_packages)
            self.bootstrap_yay(paths)
            if config.aur_packages:
                self.install_aur_packages(paths, config.aur_packages)
        except ArchEnvError:
            self._write_metadata(paths, config, status="failed")
            self._progress(f"Environment '{name}' failed. Logs are in {paths.logs_dir}.")
            raise

        self._write_metadata(paths, config, status="ready")
        self._progress(f"Environment '{name}' is ready.")
        return paths

    def shell(self, name: str, config: ArchEnvConfig) -> None:
        paths = self.paths(name)
        self._require_environment(paths)
        self._run_in_container(
            paths,
            create_container_user_command(),
            "shell-user-check.log",
            "Ensuring container user exists",
            project_mount=False,
            package_caches=False,
        )
        self._progress(f"Entering shell for environment '{name}'.")
        command = nspawn_command(
            paths,
            shell_command(),
            project_mount=config.mount_project,
            extra_mounts=config.extra_mounts,
            env=safe_shell_environment(),
            user=CONTAINER_USER,
            working_directory=paths.project_dir if config.mount_project else None,
        )
        os.execvpe(command[0], command, _sudo_environment())

    def run(self, name: str, config: ArchEnvConfig, command_to_run: tuple[str, ...]) -> None:
        if not command_to_run:
            raise ArchEnvError("run requires a command")
        paths = self.paths(name)
        self._require_environment(paths)
        self._run_in_container(
            paths,
            create_container_user_command(),
            "run-user-check.log",
            "Ensuring container user exists",
            project_mount=False,
            package_caches=False,
        )
        self._progress(f"Running in environment '{name}': {' '.join(command_to_run)}")
        command = nspawn_command(
            paths,
            list(command_to_run),
            project_mount=config.mount_project,
            extra_mounts=config.extra_mounts,
            env=forwarded_run_environment(),
            user=CONTAINER_USER,
            working_directory=paths.project_dir if config.mount_project else None,
        )
        os.execvpe(command[0], command, _sudo_environment())

    def install(self, name: str, packages: tuple[str, ...]) -> EnvironmentPaths:
        self._progress(f"Validating host prerequisites for package install in '{name}'.")
        validate_host_prerequisites()
        paths = self.paths(name)
        self._require_environment(paths)
        pacman_packages: list[str] = []
        aur_packages: list[str] = []

        for package in packages:
            self._progress(f"Resolving package source: {package}")
            if self._is_pacman_package(paths, package):
                pacman_packages.append(package)
            else:
                aur_packages.append(package)

        if pacman_packages:
            self.install_pacman_packages(paths, tuple(pacman_packages))
        if aur_packages:
            self.install_aur_packages(paths, tuple(aur_packages))
        self._progress(f"Package install complete for environment '{name}'.")
        return paths

    def install_pacman_packages(self, paths: EnvironmentPaths, packages: tuple[str, ...]) -> None:
        self._progress(f"Installing pacman packages: {', '.join(packages)}")
        self._run_in_container(
            paths,
            pacman_install_command(packages),
            "install-pacman.log",
            "Installing pacman packages",
            project_mount=False,
        )

    def install_aur_packages(self, paths: EnvironmentPaths, packages: tuple[str, ...]) -> None:
        self.bootstrap_yay(paths)
        self._progress(f"Installing AUR packages: {', '.join(packages)}")
        self._run_in_container(
            paths,
            yay_install_command(packages),
            "install-aur.log",
            "Installing AUR packages",
            project_mount=False,
            user=CONTAINER_USER,
        )

    def bootstrap_yay(self, paths: EnvironmentPaths) -> None:
        self._progress("Bootstrapping yay inside the environment.")
        self._run_in_container(
            paths,
            bootstrap_yay_command(Path(f"/home/{CONTAINER_USER}/.cache/yay")),
            "bootstrap-yay.log",
            "Bootstrapping yay",
            project_mount=False,
            user=CONTAINER_USER,
        )

    def remove(self, name: str) -> EnvironmentPaths:
        paths = self.paths(name)
        self._progress(f"Removing environment '{name}' at {paths.env_dir}.")
        ensure_managed_environment_path(paths)
        try:
            shutil.rmtree(paths.env_dir)
        except PermissionError:
            self._run_host_command(
                ["sudo", "rm", "-rf", "--one-file-system", str(paths.env_dir)],
                paths.state_dir / f"remove-{paths.name}.log",
                "Removing root-owned environment files",
            )
        self._progress(f"Removed environment '{name}'.")
        return paths

    def list(self) -> list[EnvironmentPaths]:
        envs_dir = self.project_dir / ".arch-env" / "envs"
        if not envs_dir.exists():
            return []
        return [self.paths(path.name) for path in sorted(envs_dir.iterdir()) if path.is_dir()]

    def info(self, name: str) -> dict[str, object]:
        paths = self.paths(name)
        self._require_environment(paths)
        try:
            return json.loads(paths.metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ArchEnvError(f"Environment metadata is invalid: {paths.metadata_path}") from exc

    def _run_in_container(
        self,
        paths: EnvironmentPaths,
        command: list[str],
        log_name: str,
        description: str,
        *,
        project_mount: bool,
        package_caches: bool = True,
        user: str | None = None,
    ) -> None:
        bind_mounts = _package_cache_bind_mounts(paths) if package_caches else ()
        command_to_run = nspawn_command(
            paths,
            command,
            project_mount=project_mount,
            bind_mounts=bind_mounts,
            user=user,
        )
        self._run_host_command(command_to_run, paths.logs_dir / log_name, description)

    def _is_pacman_package(self, paths: EnvironmentPaths, package: str) -> bool:
        try:
            self._run_in_container(
                paths,
                pacman_query_command(package),
                "package-resolution.log",
                f"Checking official repositories for {package}",
                project_mount=False,
            )
            return True
        except CommandExecutionError:
            self._progress(f"{package} was not found in official repositories; treating it as AUR.")
            return False

    def _require_environment(self, paths: EnvironmentPaths) -> None:
        if not paths.metadata_path.exists():
            raise ArchEnvError(f"Environment does not exist: {paths.env_dir}")

    def _write_metadata(self, paths: EnvironmentPaths, config: ArchEnvConfig, *, status: str) -> None:
        metadata = {
            "name": paths.name,
            "status": status,
            "created_at": datetime.now(UTC).isoformat(),
            "arch_env_version": __version__,
            "project_dir": str(paths.project_dir),
            "paths": {
                "env_dir": str(paths.env_dir),
                "root_dir": str(paths.root_dir),
                "pacman_cache_dir": str(paths.pacman_cache_dir),
                "aur_cache_dir": str(paths.aur_cache_dir),
                "logs_dir": str(paths.logs_dir),
            },
            "config": _json_safe_config(config),
        }
        paths.metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")

    def _run_host_command(self, command: list[str], log_path: Path, description: str) -> None:
        self._progress(f"{description}.")
        self._progress(f"Log: {log_path}")
        self.runner.run(command, log_path=log_path)

    def _progress(self, message: str) -> None:
        if self.progress is not None:
            self.progress(message)


def _json_safe_config(config: ArchEnvConfig) -> dict[str, object]:
    raw = asdict(config)
    raw["config_path"] = str(config.config_path)
    raw["extra_mounts"] = [str(path) for path in config.extra_mounts]
    return raw


def _sudo_environment() -> dict[str, str]:
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "TERM": os.environ.get("TERM", "xterm")}


def _package_cache_bind_mounts(paths: EnvironmentPaths) -> tuple[tuple[Path, str], ...]:
    return (
        (paths.pacman_cache_dir, "/var/cache/pacman/pkg"),
        (paths.aur_cache_dir, f"/home/{CONTAINER_USER}/.cache/yay"),
    )
