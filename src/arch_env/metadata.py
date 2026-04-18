from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
import json

from arch_env import __version__
from arch_env.config import ArchEnvConfig
from arch_env.errors import ArchEnvError
from arch_env.paths import EnvironmentPaths


CREATING = "creating"
READY = "ready"
FAILED = "failed"
REMOVING = "removing"
KNOWN_STATUSES = {CREATING, READY, FAILED, REMOVING}


def read_metadata(paths: EnvironmentPaths) -> dict[str, object]:
    try:
        value = json.loads(paths.metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ArchEnvError(f"Environment metadata is invalid: {paths.metadata_path}") from exc
    if not isinstance(value, dict):
        raise ArchEnvError(f"Environment metadata must be a JSON object: {paths.metadata_path}")
    return value


def write_metadata(
    paths: EnvironmentPaths,
    config: ArchEnvConfig,
    *,
    status: str,
    last_error: str | None = None,
) -> None:
    if status not in KNOWN_STATUSES:
        raise ArchEnvError(f"Unknown environment status: {status}")

    now = datetime.now(UTC).isoformat()
    existing = _read_existing_metadata(paths.metadata_path)
    created_at = existing.get("created_at")
    if not isinstance(created_at, str):
        created_at = now

    metadata = {
        "name": paths.name,
        "status": status,
        "created_at": created_at,
        "updated_at": now,
        "last_error": last_error,
        "arch_env_version": __version__,
        "project_dir": str(paths.project_dir),
        "paths": {
            "env_dir": str(paths.env_dir),
            "root_dir": str(paths.root_dir),
            "pacman_cache_dir": str(paths.pacman_cache_dir),
            "aur_cache_dir": str(paths.aur_cache_dir),
            "logs_dir": str(paths.logs_dir),
        },
        "config": json_safe_config(config),
    }
    paths.metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")


def update_metadata_status(
    paths: EnvironmentPaths,
    *,
    status: str,
    last_error: str | None = None,
) -> None:
    if status not in KNOWN_STATUSES:
        raise ArchEnvError(f"Unknown environment status: {status}")
    metadata = _read_existing_metadata(paths.metadata_path)
    if not metadata:
        return
    metadata["status"] = status
    metadata["updated_at"] = datetime.now(UTC).isoformat()
    metadata["last_error"] = last_error
    paths.metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")


def json_safe_config(config: ArchEnvConfig) -> dict[str, object]:
    raw = asdict(config)
    raw["config_path"] = str(config.config_path)
    raw["extra_mounts"] = [str(path) for path in config.extra_mounts]
    raw["device_paths"] = [str(path) for path in config.device_paths]
    return raw


def _read_existing_metadata(metadata_path: Path) -> dict[str, object]:
    if not metadata_path.exists():
        return {}
    try:
        value = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(value, dict):
        return {}
    return value
