from __future__ import annotations

from pathlib import Path
import shutil

from arch_env.errors import PrerequisiteError


REQUIRED_COMMANDS = ("python", "uv", "sudo", "systemd-nspawn", "pacman", "pacstrap")


def validate_host_prerequisites() -> None:
    missing = [command for command in REQUIRED_COMMANDS if shutil.which(command) is None]
    if missing:
        guidance = {
            "uv": "Install uv from https://docs.astral.sh/uv/ or your package manager.",
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
        content = os_release.read_text(encoding="utf-8", errors="replace").lower()
        if "arch" not in content:
            raise PrerequisiteError("arch-env requires an Arch Linux or Arch-derived host.")
