from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from arch_env.commands import (
    build_yay_command,
    ARCH_ENV_DEVELOPER_WRITE_ACCESS,
    ARCH_ENV_HELPER_DIR,
    ARCH_ENV_PACKAGE_MANAGER_MODES,
    ARCH_ENV_PACMAN_HELPER,
    configure_container_sudo_command,
    configure_developer_write_access_command,
    configure_package_manager_helpers_command,
    container_term,
    create_container_user_command,
    DEVELOPER_WRITABLE_PREFIXES,
    developer_tool_environment,
    developer_write_access_script,
    device_bind_mounts,
    display_bind_mounts,
    display_environment,
    forwarded_run_environment,
    host_group_id,
    host_supplemental_group_ids,
    host_user_id,
    initialize_keyring_command,
    machine_name,
    nspawn_command,
    pacman_install_command,
    pacman_helper_script,
    pacstrap_command,
    restore_package_manager_directory_modes_command,
    safe_shell_environment,
    shell_command,
    install_built_yay_command,
    verify_yay_command,
    yay_install_command,
    yay_bootstrap_dependencies_command,
)
from arch_env.paths import build_environment_paths


class CommandTests(unittest.TestCase):
    def test_pacstrap_command_targets_environment_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = build_environment_paths(Path(directory), "dev")
            command = pacstrap_command(paths)

        self.assertEqual(command[:4], ["sudo", "pacstrap", "-c", "-G"])
        self.assertNotIn("-M", command)
        self.assertIn(str(paths.root_dir), command)
        self.assertIn("base-devel", command)

    def test_nspawn_command_mounts_project_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = build_environment_paths(Path(directory), "dev")
            command = nspawn_command(
                paths,
                ["bash", "-l"],
                project_mount=True,
                user="archenv",
                working_directory=paths.project_dir,
            )

        self.assertIn("--bind", command)
        self.assertIn("--background=", command)
        self.assertIn(f"{paths.project_dir}:{paths.project_dir}", command)
        self.assertIn(machine_name(paths), command)
        self.assertIn("--user", command)
        self.assertIn("archenv", command)
        self.assertEqual(command[-2:], ["bash", "-l"])

    def test_machine_name_includes_project_hash_and_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = build_environment_paths(Path(directory), "dev")

            name = machine_name(paths)

        self.assertTrue(name.startswith("archenv-dev-"))
        self.assertLessEqual(len(name), 64)

    def test_nspawn_command_mounts_explicit_extra_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            extra = project / "cache"
            extra.mkdir()
            paths = build_environment_paths(project, "dev")

            command = nspawn_command(paths, ["true"], project_mount=False, extra_mounts=(extra,))

        self.assertIn(f"{extra.resolve()}:{extra.resolve()}", command)

    def test_nspawn_command_mounts_explicit_source_to_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            cache = project / "cache"
            cache.mkdir()
            paths = build_environment_paths(project, "dev")

            command = nspawn_command(
                paths,
                ["true"],
                project_mount=False,
                bind_mounts=((cache, "/var/cache/pacman/pkg"),),
            )

        self.assertIn(f"{cache.resolve()}:/var/cache/pacman/pkg", command)

    def test_nspawn_command_sets_explicit_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = build_environment_paths(Path(directory), "dev")
            command = nspawn_command(paths, ["true"], project_mount=False, env={"TERM": "xterm"})

        self.assertIn("--setenv=TERM=xterm", command)

    def test_safe_shell_environment_does_not_include_secret_values(self) -> None:
        env = safe_shell_environment(
            {
                "TERM": "xterm",
                "COLORTERM": "truecolor",
                "SSH_AUTH_SOCK": "/tmp/agent",
                "TOKEN": "secret",
            }
        )

        self.assertEqual(env["TERM"], "xterm")
        self.assertEqual(env["COLORTERM"], "truecolor")
        self.assertEqual(env["PATH"], "/usr/local/sbin:/usr/local/bin:/usr/bin")
        self.assertEqual(env["USER"], "archenv")
        self.assertEqual(env["HOME"], "/home/archenv")
        self.assertEqual(env["GEM_HOME"], "/opt/arch-env/ruby/gems")
        self.assertEqual(env["NPM_CONFIG_PREFIX"], "/usr/local")
        self.assertNotIn("SSH_AUTH_SOCK", env)
        self.assertNotIn("TOKEN", env)

    def test_safe_shell_environment_uses_supported_term_for_kitty(self) -> None:
        env = safe_shell_environment({"TERM": "xterm-kitty", "COLORTERM": "truecolor"})

        self.assertEqual(env["TERM"], "xterm-256color")
        self.assertEqual(env["COLORTERM"], "truecolor")

    def test_forwarded_run_environment_only_uses_explicit_passthrough(self) -> None:
        env = forwarded_run_environment(
            {
                "PATH": "/usr/bin",
                "CUSTOM": "1",
                "TOKEN": "secret",
                "SUDO_UID": "1000",
                "PWD": "/host",
                "USER": "naek",
                "HOME": "/home/naek",
            },
            passthrough=("CUSTOM",),
        )

        self.assertEqual(env["PATH"], "/usr/local/sbin:/usr/local/bin:/usr/bin")
        self.assertEqual(env["CUSTOM"], "1")
        self.assertEqual(env["USER"], "archenv")
        self.assertEqual(env["HOME"], "/home/archenv")
        self.assertNotIn("TOKEN", env)
        self.assertNotIn("SUDO_UID", env)
        self.assertNotIn("PWD", env)

    def test_developer_tool_environment_targets_writable_prefixes(self) -> None:
        env = developer_tool_environment()

        self.assertEqual(env["BUNDLE_PATH"], "/opt/arch-env/ruby/bundle")
        self.assertEqual(env["CARGO_HOME"], "/opt/arch-env/cargo")
        self.assertEqual(env["GOPATH"], "/opt/arch-env/go")
        self.assertEqual(env["UV_CACHE_DIR"], "/var/cache/arch-env/uv")

    def test_forwarded_run_environment_uses_supported_term_for_kitty(self) -> None:
        env = forwarded_run_environment({"TERM": "xterm-kitty", "PATH": "/usr/bin"})

        self.assertEqual(env["TERM"], "xterm-256color")

    def test_forwarded_run_environment_rejects_invalid_passthrough_names(self) -> None:
        with self.assertRaises(ValueError):
            forwarded_run_environment({"BAD-NAME": "1"}, passthrough=("BAD-NAME",))

    def test_container_term_defaults_and_maps_host_specific_terms(self) -> None:
        self.assertEqual(container_term(None), "xterm-256color")
        self.assertEqual(container_term("xterm-kitty"), "xterm-256color")
        self.assertEqual(container_term("screen-256color"), "screen-256color")

    def test_shell_command_resets_terminal_color_state(self) -> None:
        command = shell_command()

        self.assertEqual(command[0:2], ["sh", "-lc"])
        self.assertIn("printf '\\033[0m'", command[2])
        self.assertNotIn("\\033]111\\007", command[2])
        self.assertIn("PS1=", command[2])
        self.assertIn("[archenv@\\h \\W]", command[2])
        self.assertIn("PROMPT_COMMAND", command[2])
        self.assertIn("/bin/bash --noprofile --norc -i", command[2])

    def test_pacman_install_command_is_noninteractive(self) -> None:
        self.assertEqual(
            pacman_install_command(("jq", "git")),
            ["/usr/bin/pacman", "--noconfirm", "-Syu", "jq", "git"],
        )

    def test_yay_bootstrap_dependencies_installs_go_without_prompt(self) -> None:
        self.assertEqual(
            yay_bootstrap_dependencies_command(),
            ["/usr/bin/pacman", "--noconfirm", "-S", "--needed", "go"],
        )

    def test_build_yay_command_does_not_install_with_makepkg(self) -> None:
        command = build_yay_command(Path("/home/archenv/.cache/yay"))

        self.assertIn("makepkg --noconfirm --nodeps --force", command[2])
        self.assertNotIn("--install", command[2])

    def test_install_built_yay_command_installs_as_root_with_pacman(self) -> None:
        command = install_built_yay_command(Path("/home/archenv/.cache/yay"))

        self.assertIn("find /home/archenv/.cache/yay/yay", command[2])
        self.assertIn("! -name 'yay-debug-*.pkg.tar.*'", command[2])
        self.assertIn("pacman --noconfirm -U", command[2])
        self.assertNotIn("sudo", command[2])

    def test_verify_yay_command_checks_executable(self) -> None:
        self.assertEqual(verify_yay_command(), ["/usr/bin/yay", "--version"])

    def test_container_sudo_command_grants_only_package_management_access(self) -> None:
        command = configure_container_sudo_command()

        self.assertIn(ARCH_ENV_PACMAN_HELPER, command[2])
        self.assertIn(ARCH_ENV_PACKAGE_MANAGER_MODES, command[2])
        self.assertIn(ARCH_ENV_DEVELOPER_WRITE_ACCESS, command[2])
        self.assertIn("visudo -cf", command[2])
        self.assertNotIn("NOPASSWD: /usr/bin/pacman", command[2])
        self.assertNotIn("/usr/local/bin/pacman", command[2])
        self.assertNotIn("/usr/local/lib/arch-env", command[2])
        self.assertNotIn("NOPASSWD: ALL", command[2])
        self.assertIn("/etc/sudoers.d/archenv", command[2])
        self.assertNotIn("chmod -R", command[2])
        self.assertNotIn("chgrp -R", command[2])

    def test_developer_write_access_command_grants_group_write_to_container_prefixes(self) -> None:
        command = configure_developer_write_access_command(gid=1000)

        self.assertNotIn("/usr/libexec", DEVELOPER_WRITABLE_PREFIXES)
        self.assertIn("/usr/local", command[2])
        self.assertIn("/opt/arch-env", command[2])
        self.assertIn("/var/cache/arch-env", command[2])
        self.assertNotIn("/usr/share", command[2])
        self.assertNotIn("/usr/include", command[2])
        self.assertNotIn("/var/cache ", command[2])
        self.assertIn("find \"$path\" -type d -exec chgrp 1000", command[2])
        self.assertIn("find \"$path\" -type d -exec chmod g+rwx,g+s", command[2])
        self.assertNotIn("chgrp -R", command[2])
        self.assertNotIn("chmod -R", command[2])
        self.assertNotIn("/home/naek/Projects", command[2])

    def test_package_manager_modes_command_removes_developer_directory_modes(self) -> None:
        command = restore_package_manager_directory_modes_command()

        self.assertIn("/usr/local", command[2])
        self.assertIn("/opt/arch-env", command[2])
        self.assertIn("/var/cache/arch-env", command[2])
        self.assertNotIn("/usr/share", command[2])
        self.assertNotIn("/usr/include", command[2])
        self.assertIn("find \"$path\" -type d -exec chmod go-w,g-s", command[2])
        self.assertNotIn("chmod -R", command[2])
        self.assertNotIn("/home/naek/Projects", command[2])

    def test_package_manager_helpers_restore_and_reapply_modes(self) -> None:
        command = configure_package_manager_helpers_command(gid=1000)

        self.assertIn(ARCH_ENV_HELPER_DIR, command[2])
        self.assertIn(ARCH_ENV_PACMAN_HELPER, command[2])
        self.assertIn(ARCH_ENV_PACKAGE_MANAGER_MODES, command[2])
        self.assertIn(ARCH_ENV_DEVELOPER_WRITE_ACCESS, command[2])
        self.assertNotIn("/usr/local/bin/pacman", command[2])
        self.assertNotIn("/usr/local/bin/yay", command[2])
        self.assertIn("/usr/bin/pacman \"$@\"", command[2])
        self.assertNotIn("/usr/local/lib/arch-env", command[2])
        self.assertIn("find \"$path\" -type d -exec chmod go-w,g-s", command[2])
        self.assertIn("find \"$path\" -type d -exec chmod g+rwx,g+s", command[2])
        self.assertNotIn("chmod -R", command[2])
        self.assertNotIn("|| true", command[2])

    def test_pacman_helper_fails_when_developer_write_access_cannot_be_restored(self) -> None:
        self.assertIn("failed to restore developer write access after pacman", pacman_helper_script())
        self.assertNotIn("|| true", pacman_helper_script())

    def test_yay_install_command_uses_root_owned_pacman_helper(self) -> None:
        command = yay_install_command(("paru-bin",))

        self.assertEqual(command[:3], ["/usr/bin/yay", "--pacman", ARCH_ENV_PACMAN_HELPER])
        self.assertIn("paru-bin", command)

    def test_developer_write_access_script_is_small_and_explicit(self) -> None:
        script = developer_write_access_script(1000)

        self.assertIn("#!/bin/sh", script)
        self.assertIn("/usr/local", script)
        self.assertIn("/opt/arch-env", script)
        self.assertNotIn("/usr/share", script)
        self.assertNotIn("BUNDLE", script)
        self.assertNotIn("GEM_HOME", script)

    def test_initialize_keyring_command_populates_archlinux_keys(self) -> None:
        command = initialize_keyring_command()

        self.assertEqual(command[0:2], ["sh", "-lc"])
        self.assertIn("pacman-key --init", command[2])
        self.assertIn("pacman-key --populate archlinux", command[2])

    def test_container_user_command_fails_on_useradd_errors(self) -> None:
        command = create_container_user_command(uid=1000, gid=1000, supplemental_gids=())

        self.assertIn("set -e", command[2])
        self.assertIn("useradd --uid 1000 --gid 1000", command[2])
        self.assertIn("test \"$(id -u archenv)\" -eq 1000", command[2])
        self.assertIn("test \"$(id -g archenv)\" -eq 1000", command[2])

    def test_container_user_command_repairs_home_cache_ownership(self) -> None:
        command = create_container_user_command(uid=1000, gid=1000, supplemental_gids=())

        self.assertIn("install -d -o 1000 -g 1000 /home/archenv", command[2])
        self.assertIn("install -d -o 1000 -g 1000 /home/archenv/.cache", command[2])
        self.assertIn("install -d -o 1000 -g 1000 /home/archenv/.cache/yay", command[2])

    def test_container_user_command_maps_supplemental_groups(self) -> None:
        command = create_container_user_command(uid=1000, gid=1000, supplemental_gids=(44, 985))

        self.assertIn("getent group 44", command[2])
        self.assertIn("|| true", command[2])
        self.assertIn("groupadd --gid 44 archenv-host-44", command[2])
        self.assertIn("usermod -a -G \"$group_name\" archenv", command[2])
        self.assertIn("getent group 985", command[2])

    def test_host_ids_prefer_sudo_original_user(self) -> None:
        env = {"SUDO_UID": "1000", "SUDO_GID": "1000"}

        self.assertEqual(host_user_id(env), 1000)
        self.assertEqual(host_group_id(env), 1000)

    def test_host_ids_ignore_root_sudo_values(self) -> None:
        self.assertNotEqual(host_user_id({"SUDO_UID": "0"}), 0)

    def test_host_supplemental_group_ids_excludes_primary_gid(self) -> None:
        with patch("arch_env.commands.os.getgroups", return_value=[1000, 44, 985]):
            group_ids = host_supplemental_group_ids(primary_gid=1000)

        self.assertEqual(group_ids, (44, 985))

    def test_host_supplemental_group_ids_use_original_sudo_user(self) -> None:
        with patch("arch_env.commands.pwd.getpwuid") as getpwuid:
            getpwuid.return_value.pw_name = "naek"
            with patch("arch_env.commands.os.getgrouplist", return_value=[1000, 44, 985]):
                group_ids = host_supplemental_group_ids(
                    primary_gid=1000,
                    host_env={"SUDO_UID": "1000"},
                )

        self.assertEqual(group_ids, (44, 985))

    def test_display_environment_forwards_display_vars(self) -> None:
        env = display_environment({
            "DISPLAY": ":1",
            "WAYLAND_DISPLAY": "wayland-1",
            "XDG_RUNTIME_DIR": "/run/user/1000",
            "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
        })

        self.assertEqual(env["DISPLAY"], ":1")
        self.assertEqual(env["WAYLAND_DISPLAY"], "wayland-1")
        self.assertEqual(env["XDG_RUNTIME_DIR"], "/run/user/1000")
        self.assertEqual(env["DBUS_SESSION_BUS_ADDRESS"], "unix:path=/run/user/1000/bus")

    def test_display_environment_omits_missing_vars(self) -> None:
        env = display_environment({})

        self.assertNotIn("DISPLAY", env)
        self.assertNotIn("WAYLAND_DISPLAY", env)
        self.assertNotIn("XDG_RUNTIME_DIR", env)
        self.assertNotIn("DBUS_SESSION_BUS_ADDRESS", env)
        self.assertNotIn("PULSE_SERVER", env)
        self.assertNotIn("XAUTHORITY", env)

    def test_display_environment_sets_pulse_server_when_socket_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime_dir = Path(directory)
            pulse_dir = runtime_dir / "pulse"
            pulse_dir.mkdir()
            (pulse_dir / "native").touch()

            env = display_environment({"XDG_RUNTIME_DIR": str(runtime_dir)})

        self.assertEqual(env["PULSE_SERVER"], f"unix:{runtime_dir}/pulse/native")

    def test_display_environment_maps_xauthority_to_container_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            xauth = Path(directory) / ".Xauthority"
            xauth.touch()

            env = display_environment({"XAUTHORITY": str(xauth)})

        self.assertEqual(env["XAUTHORITY"], "/home/archenv/.Xauthority")

    def test_display_bind_mounts_includes_existing_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime_dir = Path(directory) / "runtime"
            runtime_dir.mkdir()
            wayland_socket = runtime_dir / "wayland-1"
            wayland_socket.touch()
            pulse_dir = runtime_dir / "pulse"
            pulse_dir.mkdir()
            pulse_socket = pulse_dir / "native"
            pulse_socket.touch()
            dbus_socket = runtime_dir / "bus"
            dbus_socket.touch()
            xauth = Path(directory) / ".Xauthority"
            xauth.touch()

            mounts = display_bind_mounts({
                "XDG_RUNTIME_DIR": str(runtime_dir),
                "WAYLAND_DISPLAY": "wayland-1",
                "DBUS_SESSION_BUS_ADDRESS": f"unix:path={dbus_socket}",
                "XAUTHORITY": str(xauth),
            })

        targets = [target for _, target in mounts]
        self.assertIn(str(wayland_socket), targets)
        self.assertIn(str(pulse_socket), targets)
        self.assertIn(str(dbus_socket), targets)
        self.assertIn("/home/archenv/.Xauthority", targets)

    def test_display_bind_mounts_skips_missing_paths(self) -> None:
        with patch.object(Path, "exists", return_value=False):
            mounts = display_bind_mounts({
                "XDG_RUNTIME_DIR": "/nonexistent/runtime",
                "XAUTHORITY": "/nonexistent/.Xauthority",
            })

        self.assertEqual(mounts, ())

    def test_device_bind_mounts_includes_explicit_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            device = Path(directory) / "custom-device"
            device.touch()

            mounts = device_bind_mounts((device,), forward_gpu=False)

        self.assertEqual(mounts, ((device, str(device)),))

    def test_device_bind_mounts_includes_existing_gpu_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dev_root = Path(directory)
            (dev_root / "dri").mkdir()
            (dev_root / "nvidia0").touch()

            mounts = device_bind_mounts((), forward_gpu=True, dev_root=dev_root)

        self.assertIn((dev_root / "dri", "/dev/dri"), mounts)
        self.assertIn((dev_root / "nvidia0", "/dev/nvidia0"), mounts)


if __name__ == "__main__":
    unittest.main()
