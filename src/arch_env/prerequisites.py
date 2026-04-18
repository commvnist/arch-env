from __future__ import annotations

from pathlib import Path
import shutil

from arch_env.errors import PrerequisiteError


REQUIRED_COMMANDS = ("python", "sudo", "systemd-nspawn", "pacman", "pacstrap")


def validate_host_prerequisites() -> None:
    missing = [command for command in REQUIRED_COMMANDS if shutil.which(command) is None]
    if missing:
        guidance = {
            "pacstrap": "Install arch-install-scripts.",
            "systemd-nspawn": "Install systemd.",
            "sudo": "Install sudo and ensure your user can elevate.",
            "pacman": "Run arch-env on Arch Linux or an Arch-derived host.",
            "python": "Install Python 3.11 or newer.",
        }
        details = "\n".join(f"- {command}: {guidance.get(command, 'Install this command.')}" for command in missing)
        raise PrerequisiteError(f"Missing required host commands:\n{details}")

    os_release = Path("/etc/os-release")
    if os_release.exists():
        values = _parse_os_release(os_release.read_text(encoding="utf-8", errors="replace"))
        ids = {values.get("ID", ""), *values.get("ID_LIKE", "").split()}
        if "arch" not in ids:
            raise PrerequisiteError("arch-env requires an Arch Linux or Arch-derived host.")


def _parse_os_release(content: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in content.splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value.strip().strip('"')
    return values
