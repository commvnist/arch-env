from __future__ import annotations

from pathlib import Path
import os

from arch_env.config import DEFAULT_BOOTSTRAP_PACKAGES
from arch_env.paths import EnvironmentPaths


CONTAINER_USER = "archenv"
CONTAINER_PATH_PREFIX = (
    "/usr/local/sbin",
    "/usr/local/bin",
    "/usr/bin",
)
TERM_FALLBACKS = {
    "xterm-kitty": "xterm-256color",
}


def pacstrap_command(paths: EnvironmentPaths) -> list[str]:
    return [
        "sudo",
        "pacstrap",
        "-c",
        "-G",
        str(paths.root_dir),
        *DEFAULT_BOOTSTRAP_PACKAGES,
    ]


def nspawn_command(
    paths: EnvironmentPaths,
    command: list[str],
    *,
    project_mount: bool,
    extra_mounts: tuple[Path, ...] = (),
    bind_mounts: tuple[tuple[Path, str], ...] = (),
    env: dict[str, str] | None = None,
    user: str | None = None,
    working_directory: Path | None = None,
) -> list[str]:
    result = [
        "sudo",
        "systemd-nspawn",
        "--quiet",
        "--background=",
        "--directory",
        str(paths.root_dir),
        "--machine",
        f"arch-env-{paths.name}",
    ]
    if project_mount:
        result.extend(["--bind", f"{paths.project_dir}:{paths.project_dir}"])
    for mount in extra_mounts:
        resolved_mount = mount.expanduser().resolve()
        result.extend(["--bind", f"{resolved_mount}:{resolved_mount}"])
    for source, target in bind_mounts:
        result.extend(["--bind", f"{source.expanduser().resolve()}:{target}"])
    for key, value in sorted((env or {}).items()):
        result.append(f"--setenv={key}={value}")
    if user:
        result.extend(["--user", user])
    if working_directory:
        result.extend(["--chdir", str(working_directory)])
    result.extend(["--", *command])
    return result


def safe_shell_environment(host_env: dict[str, str] | None = None) -> dict[str, str]:
    source = host_env if host_env is not None else os.environ
    allowed_keys = ("TERM", "COLORTERM", "NO_COLOR", "LANG", "LC_ALL", "LC_CTYPE", "LC_MESSAGES")
    result = {key: source[key] for key in allowed_keys if source.get(key)}
    result["TERM"] = container_term(source.get("TERM"))
    result["USER"] = CONTAINER_USER
    result["HOME"] = f"/home/{CONTAINER_USER}"
    result["SHELL"] = "/bin/bash"
    return result


def forwarded_run_environment(host_env: dict[str, str] | None = None) -> dict[str, str]:
    source = host_env if host_env is not None else os.environ
    blocked_prefixes = ("SUDO_",)
    blocked_names = {
        "LS_COLORS",
        "OLDPWD",
        "PWD",
        "SHLVL",
        "_",
    }
    result = {}
    for key, value in source.items():
        if not key or "=" in key:
            continue
        if key in blocked_names:
            continue
        if any(key.startswith(prefix) for prefix in blocked_prefixes):
            continue
        result[key] = value
    result["PATH"] = container_first_path(source.get("PATH", ""))
    result["TERM"] = container_term(source.get("TERM"))
    result["USER"] = CONTAINER_USER
    result["HOME"] = f"/home/{CONTAINER_USER}"
    result["SHELL"] = "/bin/bash"
    return result


def container_term(host_term: str | None) -> str:
    if not host_term:
        return "xterm-256color"
    return TERM_FALLBACKS.get(host_term, host_term)


def container_first_path(host_path: str) -> str:
    entries = [*CONTAINER_PATH_PREFIX]
    for entry in host_path.split(":"):
        if not entry or entry in entries:
            continue
        entries.append(entry)
    return ":".join(entries)


def create_container_user_command(uid: int | None = None, gid: int | None = None) -> list[str]:
    uid = uid if uid is not None else host_user_id()
    gid = gid if gid is not None else host_group_id()
    return [
        "sh",
        "-lc",
        (
            "set -e; "
            f"getent group {gid} >/dev/null || groupadd --gid {gid} {CONTAINER_USER}; "
            f"id -u {CONTAINER_USER} >/dev/null 2>&1 || "
            f"useradd --uid {uid} --gid {gid} --create-home --shell /bin/bash {CONTAINER_USER}; "
            f"install -d -o {uid} -g {gid} /home/{CONTAINER_USER}/.cache/yay"
        ),
    ]


def configure_container_sudo_command() -> list[str]:
    return [
        "sh",
        "-lc",
        (
            "set -e; "
            "install -d -m 0750 /etc/sudoers.d; "
            f"printf '%s\\n' '{CONTAINER_USER} ALL=(root) NOPASSWD: /usr/bin/pacman' "
            f"> /etc/sudoers.d/{CONTAINER_USER}-pacman; "
            f"chmod 0440 /etc/sudoers.d/{CONTAINER_USER}-pacman"
        ),
    ]


def host_user_id(host_env: dict[str, str] | None = None) -> int:
    source = host_env if host_env is not None else os.environ
    return _positive_int(source.get("SUDO_UID")) or os.getuid()


def host_group_id(host_env: dict[str, str] | None = None) -> int:
    source = host_env if host_env is not None else os.environ
    return _positive_int(source.get("SUDO_GID")) or os.getgid()


def _positive_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    if parsed <= 0:
        return None
    return parsed


def initialize_keyring_command() -> list[str]:
    return ["sh", "-lc", "pacman-key --init && pacman-key --populate archlinux"]


def pacman_install_command(packages: tuple[str, ...] | list[str]) -> list[str]:
    return ["pacman", "--noconfirm", "-Syu", *packages]


def pacman_query_command(package: str) -> list[str]:
    return ["pacman", "-Si", package]


def yay_query_command(package: str) -> list[str]:
    return ["yay", "-Si", package]


def yay_install_command(packages: tuple[str, ...] | list[str]) -> list[str]:
    return ["yay", "--noconfirm", "-S", *packages]


def yay_bootstrap_dependencies_command() -> list[str]:
    return ["pacman", "--noconfirm", "-S", "--needed", "go"]


def build_yay_command(aur_cache_dir: Path) -> list[str]:
    return [
        "sh",
        "-lc",
        (
            "command -v yay >/dev/null 2>&1 || "
            f"(export GOCACHE={aur_cache_dir}/.go-build && "
            f"mkdir -p {aur_cache_dir} && "
            f"cd {aur_cache_dir} && "
            "rm -rf yay && "
            "git clone https://aur.archlinux.org/yay.git && "
            "cd yay && "
            "makepkg --noconfirm --nodeps --force)"
        ),
    ]


def install_built_yay_command(aur_cache_dir: Path) -> list[str]:
    return [
        "sh",
        "-lc",
        (
            "command -v yay >/dev/null 2>&1 || "
            f"(package=$(find {aur_cache_dir}/yay -maxdepth 1 -type f "
            "-name 'yay-*.pkg.tar.*' ! -name '*.sig' | sort | tail -n 1) && "
            "test -n \"$package\" && "
            "pacman --noconfirm -U \"$package\")"
        ),
    ]


def display_environment(host_env: dict[str, str] | None = None) -> dict[str, str]:
    source = host_env if host_env is not None else os.environ
    result = {}
    for key in ("DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS"):
        if source.get(key):
            result[key] = source[key]
    xdg_runtime = source.get("XDG_RUNTIME_DIR", "")
    if xdg_runtime:
        pulse_socket = Path(xdg_runtime) / "pulse" / "native"
        if pulse_socket.exists():
            result["PULSE_SERVER"] = f"unix:{pulse_socket}"
    xauthority_str = source.get("XAUTHORITY")
    xauthority = Path(xauthority_str) if xauthority_str else Path.home() / ".Xauthority"
    if xauthority.exists():
        result["XAUTHORITY"] = f"/home/{CONTAINER_USER}/.Xauthority"
    return result


def display_bind_mounts(host_env: dict[str, str] | None = None) -> tuple[tuple[Path, str], ...]:
    source = host_env if host_env is not None else os.environ
    mounts: list[tuple[Path, str]] = []
    x11_socket_dir = Path("/tmp/.X11-unix")
    if x11_socket_dir.exists():
        mounts.append((x11_socket_dir, "/tmp/.X11-unix"))
    xdg_runtime = source.get("XDG_RUNTIME_DIR")
    if xdg_runtime and Path(xdg_runtime).exists():
        mounts.append((Path(xdg_runtime), xdg_runtime))
    xauthority_str = source.get("XAUTHORITY")
    xauthority = Path(xauthority_str) if xauthority_str else Path.home() / ".Xauthority"
    if xauthority.exists():
        mounts.append((xauthority, f"/home/{CONTAINER_USER}/.Xauthority"))
    return tuple(mounts)


def shell_command(shell: str = "/bin/bash") -> list[str]:
    terminal_reset = "printf '\\033[0m'"
    return [
        "sh",
        "-lc",
        (
            f"{terminal_reset}; "
            "export PS1='\\[\\033[0m\\][archenv@\\h \\W]\\$ \\[\\033[0m\\]'; "
            "export PROMPT_COMMAND='printf \"\\033[0m\"'; "
            "alias ls='ls --color=auto'; "
            "alias grep='grep --color=auto'; "
            f"{shell} --noprofile --norc -i; "
            "status=$?; "
            f"{terminal_reset}; "
            "exit \"$status\""
        ),
    ]
