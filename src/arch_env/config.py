from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import tomllib

from arch_env.errors import ConfigError, PathSafetyError
from arch_env.paths import validate_environment_name


CONFIG_FILE = "arch-env.toml"
DEFAULT_ENVIRONMENT_NAME = "default"
ENVIRONMENT_VARIABLE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
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

[devices]
gpu = false
paths = []

[env]
passthrough = []

[shell]
# forward_display = true  # forward X11/Wayland/audio/D-Bus sockets to the host desktop
"""


@dataclass(frozen=True)
class ArchEnvConfig:
    environment_name: str
    config_path: Path
    pacman_packages: tuple[str, ...]
    aur_packages: tuple[str, ...]
    mount_project: bool
    extra_mounts: tuple[Path, ...]
    forward_gpu: bool = False
    device_paths: tuple[Path, ...] = ()
    env_passthrough: tuple[str, ...] = ()
    forward_display: bool = False


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
            forward_gpu=False,
            device_paths=(),
            env_passthrough=(),
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
    devices = _table(raw, "devices")
    env = _table(raw, "env")
    shell = _table(raw, "shell")

    mount_project = mounts.get("project", True)
    if not isinstance(mount_project, bool):
        raise ConfigError("[mounts].project must be a boolean")

    forward_display = shell.get("forward_display", False)
    if not isinstance(forward_display, bool):
        raise ConfigError("[shell].forward_display must be a boolean")

    forward_gpu = devices.get("gpu", False)
    if not isinstance(forward_gpu, bool):
        raise ConfigError("[devices].gpu must be a boolean")

    return ArchEnvConfig(
        environment_name=environment_name_from_config_path(config_path),
        config_path=config_path,
        pacman_packages=_string_tuple(pacman.get("packages", ()), "[pacman].packages"),
        aur_packages=_string_tuple(aur.get("packages", ()), "[aur].packages"),
        mount_project=mount_project,
        extra_mounts=_path_tuple(mounts.get("extra", ()), "[mounts].extra"),
        forward_gpu=forward_gpu,
        device_paths=_path_tuple(devices.get("paths", ()), "[devices].paths"),
        env_passthrough=_environment_variable_tuple(env.get("passthrough", ()), "[env].passthrough"),
        forward_display=forward_display,
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


def _environment_variable_tuple(value: object, key: str) -> tuple[str, ...]:
    names = _string_tuple(value, key)
    for name in names:
        if not ENVIRONMENT_VARIABLE_PATTERN.fullmatch(name):
            raise ConfigError(f"{key} must contain only valid environment variable names")
    return names
