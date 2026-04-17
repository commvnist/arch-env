from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib

from arch_env.errors import ConfigError, PathSafetyError
from arch_env.paths import validate_environment_name


CONFIG_FILE = "arch-env.toml"
DEFAULT_ENVIRONMENT_NAME = "default"
DEFAULT_BOOTSTRAP_PACKAGES = [
    "base",
    "base-devel",
    "git",
    "sudo",
    "ca-certificates",
    "archlinux-keyring",
]
DEFAULT_CONFIG_TEXT = """# The environment name is derived from this file name.
# arch-env.toml creates .arch-env/envs/default
# tools.toml creates .arch-env/envs/tools

[pacman]
packages = [
  "base",
  "base-devel",
  "git",
  "python",
]

[aur]
packages = []

[mounts]
project = true
extra = []
"""


@dataclass(frozen=True)
class ArchEnvConfig:
    environment_name: str
    config_path: Path
    pacman_packages: tuple[str, ...]
    aur_packages: tuple[str, ...]
    mount_project: bool
    extra_mounts: tuple[Path, ...]


def load_config(project_dir: Path, config_file: Path | None = None) -> ArchEnvConfig:
    config_path = resolve_config_path(project_dir, config_file)
    if not config_path.exists():
        return ArchEnvConfig(
            environment_name=environment_name_from_config_path(config_path),
            config_path=config_path,
            pacman_packages=(),
            aur_packages=(),
            mount_project=True,
            extra_mounts=(),
        )

    try:
        raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{CONFIG_FILE} is invalid TOML: {exc}") from exc

    environment = _table(raw, "environment")
    if environment:
        raise ConfigError("Environment names are derived from config file names; remove the [environment] table.")

    pacman = _table(raw, "pacman")
    aur = _table(raw, "aur")
    mounts = _table(raw, "mounts")

    mount_project = mounts.get("project", True)
    if not isinstance(mount_project, bool):
        raise ConfigError("[mounts].project must be a boolean")

    return ArchEnvConfig(
        environment_name=environment_name_from_config_path(config_path),
        config_path=config_path,
        pacman_packages=_string_tuple(pacman.get("packages", ()), "[pacman].packages"),
        aur_packages=_string_tuple(aur.get("packages", ()), "[aur].packages"),
        mount_project=mount_project,
        extra_mounts=_path_tuple(mounts.get("extra", ()), "[mounts].extra"),
    )


def write_default_config(project_dir: Path, config_file: Path | None = None) -> Path:
    config_path = resolve_config_path(project_dir, config_file)
    if config_path.exists():
        raise ConfigError(f"{config_path} already exists")
    config_path.write_text(DEFAULT_CONFIG_TEXT, encoding="utf-8")
    return config_path


def resolve_config_path(project_dir: Path, config_file: Path | None = None) -> Path:
    selected = config_file or Path(CONFIG_FILE)
    if selected.is_absolute():
        return selected.resolve()
    return (project_dir / selected).resolve()


def environment_name_from_config_path(config_path: Path) -> str:
    if config_path.name == CONFIG_FILE:
        return DEFAULT_ENVIRONMENT_NAME
    name = config_path.stem
    try:
        return validate_environment_name(name)
    except PathSafetyError as exc:
        raise ConfigError(f"Config filename does not produce a valid environment name: {config_path.name}") from exc


def _table(raw: dict[str, object], name: str) -> dict[str, object]:
    value = raw.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"[{name}] must be a TOML table")
    return value


def _string_tuple(value: object, key: str) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        raise ConfigError(f"{key} must be a list of strings")
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ConfigError(f"{key} must contain only non-empty strings")
        result.append(item)
    return tuple(result)


def _path_tuple(value: object, key: str) -> tuple[Path, ...]:
    return tuple(Path(item).expanduser() for item in _string_tuple(value, key))
