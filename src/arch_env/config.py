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
SUPPORTED_TABLES = frozenset({"pacman", "aur", "mounts", "devices", "env", "shell", "developer"})
TABLE_KEYS = {
    "pacman": frozenset({"packages"}),
    "aur": frozenset({"packages"}),
    "mounts": frozenset({"project", "extra"}),
    "devices": frozenset({"gpu", "paths"}),
    "env": frozenset({"passthrough"}),
    "shell": frozenset({"forward_display"}),
    "developer": frozenset({"writable_prefixes"}),
}
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

[developer]
writable_prefixes = true
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
    developer_writable_prefixes: bool = True


def load_config(
    project_dir: Path,
    config_file: Path | None = None,
    *,
    require_existing: bool = False,
) -> ArchEnvConfig:
    resolved_project = project_dir.resolve()
    config_path = resolve_config_path(project_dir, config_file)
    if not config_path.exists():
        if require_existing:
            raise ConfigError(f"{config_path}: config file does not exist; run 'ae init' first")
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
            developer_writable_prefixes=True,
        )

    try:
        raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{config_path}: invalid TOML: {exc}") from exc

    _validate_top_level(raw, config_path)

    pacman = _table(raw, "pacman", config_path)
    aur = _table(raw, "aur", config_path)
    mounts = _table(raw, "mounts", config_path)
    devices = _table(raw, "devices", config_path)
    env = _table(raw, "env", config_path)
    shell = _table(raw, "shell", config_path)
    developer = _table(raw, "developer", config_path)

    mount_project = _boolean_value(mounts.get("project", True), "[mounts].project", config_path)
    forward_display = _boolean_value(shell.get("forward_display", False), "[shell].forward_display", config_path)
    forward_gpu = _boolean_value(devices.get("gpu", False), "[devices].gpu", config_path)
    developer_writable_prefixes = _boolean_value(
        developer.get("writable_prefixes", True),
        "[developer].writable_prefixes",
        config_path,
    )

    return ArchEnvConfig(
        environment_name=environment_name_from_config_path(config_path),
        config_path=config_path,
        pacman_packages=_string_tuple(pacman.get("packages", ()), "[pacman].packages", config_path),
        aur_packages=_string_tuple(aur.get("packages", ()), "[aur].packages", config_path),
        mount_project=mount_project,
        extra_mounts=_path_tuple(mounts.get("extra", ()), "[mounts].extra", resolved_project, config_path),
        forward_gpu=forward_gpu,
        device_paths=_path_tuple(devices.get("paths", ()), "[devices].paths", resolved_project, config_path),
        env_passthrough=_environment_variable_tuple(env.get("passthrough", ()), "[env].passthrough", config_path),
        forward_display=forward_display,
        developer_writable_prefixes=developer_writable_prefixes,
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


def _validate_top_level(raw: dict[str, object], config_path: Path) -> None:
    if "environment" in raw:
        raise ConfigError(f"{config_path}: environment names are derived from config file names; remove [environment]")
    for table_name, value in raw.items():
        if table_name not in SUPPORTED_TABLES:
            raise ConfigError(f"{config_path}: unsupported config table or key: {table_name}")
        if not isinstance(value, dict):
            raise ConfigError(f"{config_path}: top-level key '{table_name}' must be a TOML table")
        unknown_keys = sorted(set(value) - TABLE_KEYS[table_name])
        if unknown_keys:
            keys = ", ".join(unknown_keys)
            raise ConfigError(f"{config_path}: [{table_name}] has unsupported key(s): {keys}")


def _table(raw: dict[str, object], name: str, config_path: Path) -> dict[str, object]:
    value = raw.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"{config_path}: [{name}] must be a TOML table")
    return value


def _boolean_value(value: object, key: str, config_path: Path) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{config_path}: {key} must be a boolean")
    return value


def _string_tuple(value: object, key: str, config_path: Path) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        raise ConfigError(f"{config_path}: {key} must be a list of strings")
    result = []
    seen = set()
    for item in value:
        if not isinstance(item, str):
            raise ConfigError(f"{config_path}: {key} must contain only strings")
        if item != item.strip() or not item:
            raise ConfigError(f"{config_path}: {key} must contain non-empty strings without surrounding whitespace")
        if item in seen:
            raise ConfigError(f"{config_path}: {key} contains duplicate value: {item}")
        seen.add(item)
        result.append(item)
    return tuple(result)


def _path_tuple(value: object, key: str, project_dir: Path, config_path: Path) -> tuple[Path, ...]:
    paths = []
    for item in _string_tuple(value, key, config_path):
        path = Path(item).expanduser()
        resolved = path.resolve() if path.is_absolute() else (project_dir / path).resolve()
        if not resolved.exists():
            raise ConfigError(f"{config_path}: {key} path does not exist: {item}")
        paths.append(resolved)
    return tuple(paths)


def _environment_variable_tuple(value: object, key: str, config_path: Path) -> tuple[str, ...]:
    names = _string_tuple(value, key, config_path)
    for name in names:
        if not ENVIRONMENT_VARIABLE_PATTERN.fullmatch(name):
            raise ConfigError(f"{config_path}: {key} must contain only valid environment variable names")
    return names
