from __future__ import annotations

from pathlib import Path
import os
import pwd

from arch_env.config import DEFAULT_BOOTSTRAP_PACKAGES, ENVIRONMENT_VARIABLE_PATTERN
from arch_env.paths import EnvironmentPaths


CONTAINER_USER = "archenv"
CONTAINER_PATH_PREFIX = (
    "/usr/local/sbin",
    "/usr/local/bin",
    "/usr/bin",
)
DEFAULT_CONTAINER_PATH = ":".join(CONTAINER_PATH_PREFIX)
ARCH_ENV_HELPER_DIR = "/usr/libexec/arch-env"
ARCH_ENV_PACMAN_HELPER = f"{ARCH_ENV_HELPER_DIR}/pacman"
ARCH_ENV_PACKAGE_MANAGER_MODES = f"{ARCH_ENV_HELPER_DIR}/package-manager-modes"
ARCH_ENV_DEVELOPER_WRITE_ACCESS = f"{ARCH_ENV_HELPER_DIR}/developer-write-access"
DEVELOPER_WRITABLE_PREFIXES = (
    "/usr/local",
    "/usr/lib",
    "/usr/share",
    "/usr/include",
    "/opt",
    "/var/cache",
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


def safe_shell_environment(
    host_env: dict[str, str] | None = None,
    passthrough: tuple[str, ...] = (),
) -> dict[str, str]:
    source = host_env if host_env is not None else os.environ
    allowed_keys = ("TERM", "COLORTERM", "NO_COLOR", "LANG", "LC_ALL", "LC_CTYPE", "LC_MESSAGES")
    result = {key: source[key] for key in allowed_keys if source.get(key)}
    result.update(explicit_passthrough_environment(source, passthrough))
    result["PATH"] = DEFAULT_CONTAINER_PATH
    result["TERM"] = container_term(source.get("TERM"))
    result["USER"] = CONTAINER_USER
    result["HOME"] = f"/home/{CONTAINER_USER}"
    result["SHELL"] = "/bin/bash"
    return result


def forwarded_run_environment(
    host_env: dict[str, str] | None = None,
    passthrough: tuple[str, ...] = (),
) -> dict[str, str]:
    source = host_env if host_env is not None else os.environ
    return safe_shell_environment(source, passthrough)


def explicit_passthrough_environment(source: dict[str, str], names: tuple[str, ...]) -> dict[str, str]:
    result = {}
    for name in names:
        if not _valid_environment_name(name):
            raise ValueError(f"Invalid environment variable name: {name!r}")
        if name in source:
            result[name] = source[name]
    return result


def _valid_environment_name(name: str) -> bool:
    return ENVIRONMENT_VARIABLE_PATTERN.fullmatch(name) is not None


def container_term(host_term: str | None) -> str:
    if not host_term:
        return "xterm-256color"
    return TERM_FALLBACKS.get(host_term, host_term)


def create_container_user_command(
    uid: int | None = None,
    gid: int | None = None,
    supplemental_gids: tuple[int, ...] | None = None,
) -> list[str]:
    uid = uid if uid is not None else host_user_id()
    gid = gid if gid is not None else host_group_id()
    group_ids = supplemental_gids if supplemental_gids is not None else host_supplemental_group_ids(primary_gid=gid)
    group_membership = " ".join(_container_group_membership_fragment(group_id) for group_id in group_ids)
    return [
        "sh",
        "-lc",
        (
            "set -e; "
            f"getent group {gid} >/dev/null || groupadd --gid {gid} {CONTAINER_USER}; "
            f"if id -u {CONTAINER_USER} >/dev/null 2>&1; then "
            f"test \"$(id -u {CONTAINER_USER})\" -eq {uid}; "
            f"test \"$(id -g {CONTAINER_USER})\" -eq {gid}; "
            "else "
            f"useradd --uid {uid} --gid {gid} --create-home --shell /bin/bash {CONTAINER_USER}; "
            "fi; "
            f"{group_membership} "
            f"install -d -o {uid} -g {gid} /home/{CONTAINER_USER}; "
            f"install -d -o {uid} -g {gid} /home/{CONTAINER_USER}/.cache; "
            f"install -d -o {uid} -g {gid} /home/{CONTAINER_USER}/.cache/yay"
        ),
    ]


def _container_group_name(group_id: int) -> str:
    return f"archenv-host-{group_id}"


def _container_group_membership_fragment(group_id: int) -> str:
    group_name = _container_group_name(group_id)
    return (
        f"group_name=$(getent group {group_id} | cut -d: -f1 || true); "
        f"if [ -z \"$group_name\" ]; then groupadd --gid {group_id} {group_name}; group_name={group_name}; fi; "
        f"usermod -a -G \"$group_name\" {CONTAINER_USER};"
    )


def configure_container_sudo_command() -> list[str]:
    return [
        "sh",
        "-lc",
        (
            "set -e; "
            "install -d -m 0750 /etc/sudoers.d; "
            f"printf '%s\\n' '{CONTAINER_USER} ALL=(root) NOPASSWD: "
            f"/usr/bin/pacman, {ARCH_ENV_PACMAN_HELPER}, "
            f"{ARCH_ENV_PACKAGE_MANAGER_MODES}, "
            f"{ARCH_ENV_DEVELOPER_WRITE_ACCESS}' "
            f"> /etc/sudoers.d/{CONTAINER_USER}; "
            f"chmod 0440 /etc/sudoers.d/{CONTAINER_USER}"
        ),
    ]


def configure_developer_write_access_command(gid: int | None = None) -> list[str]:
    gid = gid if gid is not None else host_group_id()
    return [
        "sh",
        "-lc",
        f"set -e; {_developer_write_access_shell(gid)}",
    ]


def restore_package_manager_directory_modes_command() -> list[str]:
    return [
        "sh",
        "-lc",
        f"set -e; {_restore_package_manager_directory_modes_shell()}",
    ]


def configure_package_manager_wrappers_command(gid: int | None = None) -> list[str]:
    gid = gid if gid is not None else host_group_id()
    return [
        "sh",
        "-lc",
        (
            "set -e; "
            f"install -d -m 0755 /usr/local/bin {ARCH_ENV_HELPER_DIR}; "
            f"{_write_script_shell(ARCH_ENV_DEVELOPER_WRITE_ACCESS, developer_write_access_script(gid))} "
            f"{_write_script_shell(ARCH_ENV_PACKAGE_MANAGER_MODES, package_manager_modes_script())} "
            f"{_write_script_shell(ARCH_ENV_PACMAN_HELPER, pacman_helper_script())} "
            f"{_write_script_shell('/usr/local/bin/pacman', pacman_wrapper_script())} "
            "if [ -x /usr/bin/yay ]; then "
            f"{_write_script_shell('/usr/local/bin/yay', yay_wrapper_script())} "
            "chmod 0755 /usr/local/bin/yay; "
            "fi; "
            f"chmod 0755 {ARCH_ENV_DEVELOPER_WRITE_ACCESS} "
            f"{ARCH_ENV_PACKAGE_MANAGER_MODES} {ARCH_ENV_PACMAN_HELPER} /usr/local/bin/pacman"
        ),
    ]


def _write_script_shell(path: str, content: str) -> str:
    return f"cat > {path} <<'ARCHENV_EOF'\n{content}\nARCHENV_EOF\n"


def developer_write_access_script(gid: int) -> str:
    return "#!/bin/sh\nset -e\n" + _developer_write_access_shell(gid)


def package_manager_modes_script() -> str:
    return "#!/bin/sh\nset -e\n" + _restore_package_manager_directory_modes_shell()


def pacman_helper_script() -> str:
    return "\n".join(
        (
            "#!/bin/sh",
            "set -u",
            ARCH_ENV_PACKAGE_MANAGER_MODES,
            '/usr/bin/pacman "$@"',
            "status=$?",
            f"if ! {ARCH_ENV_DEVELOPER_WRITE_ACCESS}; then",
            "  printf '%s\\n' 'arch-env: failed to restore developer write access after pacman' >&2",
            "  exit 1",
            "fi",
            'exit "$status"',
        )
    )


def pacman_wrapper_script() -> str:
    return "\n".join(
        (
            "#!/bin/sh",
            "set -u",
            'if [ "$(id -u)" -eq 0 ]; then',
            f'  exec {ARCH_ENV_PACMAN_HELPER} "$@"',
            "fi",
            f'exec sudo {ARCH_ENV_PACMAN_HELPER} "$@"',
        )
    )


def yay_wrapper_script() -> str:
    return "\n".join(
        (
            "#!/bin/sh",
            "set -u",
            f"sudo {ARCH_ENV_PACKAGE_MANAGER_MODES} || exit 1",
            '/usr/bin/yay "$@"',
            "status=$?",
            f"if ! sudo {ARCH_ENV_DEVELOPER_WRITE_ACCESS}; then",
            "  printf '%s\\n' 'arch-env: failed to restore developer write access after yay' >&2",
            "  exit 1",
            "fi",
            'exit "$status"',
        )
    )


def _developer_write_access_shell(gid: int) -> str:
    return (
        f"for path in {' '.join(DEVELOPER_WRITABLE_PREFIXES)}; do "
        "[ -e \"$path\" ] || continue; "
        f"find \"$path\" -type d -exec chgrp {gid} {{}} +; "
        "find \"$path\" -type d -exec chmod g+rwx,g+s {} +; "
        "done"
    )


def _restore_package_manager_directory_modes_shell() -> str:
    return (
        f"for path in {' '.join(DEVELOPER_WRITABLE_PREFIXES)}; do "
        "[ -e \"$path\" ] || continue; "
        "find \"$path\" -type d -exec chmod go-w,g-s {} +; "
        "done"
    )


def host_user_id(host_env: dict[str, str] | None = None) -> int:
    source = host_env if host_env is not None else os.environ
    return _positive_int(source.get("SUDO_UID")) or os.getuid()


def host_group_id(host_env: dict[str, str] | None = None) -> int:
    source = host_env if host_env is not None else os.environ
    return _positive_int(source.get("SUDO_GID")) or os.getgid()


def host_supplemental_group_ids(
    primary_gid: int | None = None,
    host_env: dict[str, str] | None = None,
) -> tuple[int, ...]:
    primary = primary_gid if primary_gid is not None else host_group_id()
    user_groups = _original_user_group_ids(primary, host_env)
    group_ids = {primary, *user_groups}
    return tuple(sorted(group_id for group_id in group_ids if group_id > 0 and group_id != primary))


def _original_user_group_ids(primary_gid: int, host_env: dict[str, str] | None = None) -> tuple[int, ...]:
    source = host_env if host_env is not None else os.environ
    original_uid = _positive_int(source.get("SUDO_UID"))
    if original_uid is None:
        return tuple(os.getgroups())

    try:
        username = pwd.getpwuid(original_uid).pw_name
    except KeyError:
        return tuple(os.getgroups())

    try:
        return tuple(os.getgrouplist(username, primary_gid))
    except OSError:
        return tuple(os.getgroups())


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
    return ["/usr/bin/pacman", "--noconfirm", "-Syu", *packages]


def pacman_query_command(package: str) -> list[str]:
    return ["/usr/bin/pacman", "-Si", package]


def yay_query_command(package: str) -> list[str]:
    return ["/usr/bin/yay", "-Si", package]


def yay_install_command(packages: tuple[str, ...] | list[str]) -> list[str]:
    return ["/usr/bin/yay", "--noconfirm", "-S", *packages]


def yay_bootstrap_dependencies_command() -> list[str]:
    return ["/usr/bin/pacman", "--noconfirm", "-S", "--needed", "go"]


def build_yay_command(aur_cache_dir: Path) -> list[str]:
    return [
        "sh",
        "-lc",
        (
            "test -x /usr/bin/yay || "
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
            "test -x /usr/bin/yay || "
            f"(package=$(find {aur_cache_dir}/yay -maxdepth 1 -type f "
            "-name 'yay-*.pkg.tar.*' ! -name 'yay-debug-*.pkg.tar.*' "
            "! -name '*.sig' | sort | tail -n 1) && "
            "test -n \"$package\" && "
            "/usr/bin/pacman --noconfirm -U \"$package\")"
        ),
    ]


def verify_yay_command() -> list[str]:
    return ["/usr/bin/yay", "--version"]


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


def device_bind_mounts(
    paths: tuple[Path, ...],
    *,
    forward_gpu: bool,
    dev_root: Path = Path("/dev"),
) -> tuple[tuple[Path, str], ...]:
    mounts = [(path, str(path)) for path in paths]
    if forward_gpu:
        mounts.extend(gpu_bind_mounts(dev_root))
    return _dedupe_bind_mounts(tuple(mounts))


def gpu_bind_mounts(dev_root: Path = Path("/dev")) -> tuple[tuple[Path, str], ...]:
    mounts: list[tuple[Path, str]] = []
    for relative_path in ("dri", "kfd"):
        source = dev_root / relative_path
        if source.exists():
            mounts.append((source, f"/dev/{relative_path}"))
    for source in sorted(dev_root.glob("nvidia*")):
        mounts.append((source, f"/dev/{source.name}"))
    return tuple(mounts)


def _dedupe_bind_mounts(bind_mounts: tuple[tuple[Path, str], ...]) -> tuple[tuple[Path, str], ...]:
    result: list[tuple[Path, str]] = []
    seen: set[tuple[str, str]] = set()
    for source, target in bind_mounts:
        key = (str(source.expanduser()), target)
        if key in seen:
            continue
        seen.add(key)
        result.append((source, target))
    return tuple(result)


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
