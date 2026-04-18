from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from arch_env.errors import PathSafetyError


STATE_DIR_NAME = ".arch-env"
ENV_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,63}$")


@dataclass(frozen=True)
class EnvironmentPaths:
    project_dir: Path
    name: str
    state_dir: Path
    env_dir: Path
    root_dir: Path
    pacman_cache_dir: Path
    aur_cache_dir: Path
    logs_dir: Path
    metadata_path: Path


def build_environment_paths(project_dir: Path, name: str) -> EnvironmentPaths:
    validated_name = validate_environment_name(name)
    resolved_project = project_dir.resolve()
    state_dir = resolved_project / STATE_DIR_NAME
    env_dir = state_dir / "envs" / validated_name
    return EnvironmentPaths(
        project_dir=resolved_project,
        name=validated_name,
        state_dir=state_dir,
        env_dir=env_dir,
        root_dir=env_dir / "root",
        pacman_cache_dir=env_dir / "cache" / "pacman",
        aur_cache_dir=env_dir / "cache" / "aur",
        logs_dir=env_dir / "logs",
        metadata_path=env_dir / "metadata.json",
    )


def validate_environment_name(name: str) -> str:
    if not ENV_NAME_PATTERN.fullmatch(name):
        raise PathSafetyError(
            "Environment names must start with a letter or digit and contain "
            "only letters, digits, or dashes."
        )
    if name in {".", ".."}:
        raise PathSafetyError("Environment name cannot be '.' or '..'")
    return name


def ensure_managed_environment_path(paths: EnvironmentPaths) -> None:
    resolved_env = paths.env_dir.resolve()
    managed_root = (paths.state_dir / "envs").resolve()
    if managed_root not in resolved_env.parents:
        raise PathSafetyError(f"Refusing to operate outside {managed_root}")
    if paths.metadata_path.exists():
        return
    if _looks_like_partial_arch_environment(paths):
        return
    raise PathSafetyError(f"Refusing to remove unmanaged path: {paths.env_dir}")


def _looks_like_partial_arch_environment(paths: EnvironmentPaths) -> bool:
    return (
        paths.root_dir.is_dir()
        and (paths.root_dir / "etc" / "arch-release").is_file()
        and (paths.root_dir / "var" / "lib" / "pacman").is_dir()
    )
