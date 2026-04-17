from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from arch_env.commands import (
    container_term,
    container_first_path,
    create_container_user_command,
    forwarded_run_environment,
    host_group_id,
    host_user_id,
    initialize_keyring_command,
    nspawn_command,
    pacman_install_command,
    pacstrap_command,
    safe_shell_environment,
    shell_command,
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
        self.assertIn("--user", command)
        self.assertIn("archenv", command)
        self.assertEqual(command[-2:], ["bash", "-l"])

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
        self.assertEqual(env["USER"], "archenv")
        self.assertNotIn("SSH_AUTH_SOCK", env)
        self.assertNotIn("TOKEN", env)

    def test_safe_shell_environment_uses_supported_term_for_kitty(self) -> None:
        env = safe_shell_environment({"TERM": "xterm-kitty", "COLORTERM": "truecolor"})

        self.assertEqual(env["TERM"], "xterm-256color")
        self.assertEqual(env["COLORTERM"], "truecolor")

    def test_forwarded_run_environment_preserves_user_values_but_normalizes_identity(self) -> None:
        env = forwarded_run_environment(
            {
                "PATH": "/usr/bin",
                "CUSTOM": "1",
                "SUDO_UID": "1000",
                "PWD": "/host",
                "USER": "naek",
                "HOME": "/home/naek",
            }
        )

        self.assertTrue(env["PATH"].startswith("/usr/local/sbin:/usr/local/bin:/usr/bin"))
        self.assertEqual(env["CUSTOM"], "1")
        self.assertEqual(env["USER"], "archenv")
        self.assertEqual(env["HOME"], "/home/archenv")
        self.assertNotIn("SUDO_UID", env)
        self.assertNotIn("PWD", env)

    def test_forwarded_run_environment_uses_supported_term_for_kitty(self) -> None:
        env = forwarded_run_environment({"TERM": "xterm-kitty", "PATH": "/usr/bin"})

        self.assertEqual(env["TERM"], "xterm-256color")

    def test_container_term_defaults_and_maps_host_specific_terms(self) -> None:
        self.assertEqual(container_term(None), "xterm-256color")
        self.assertEqual(container_term("xterm-kitty"), "xterm-256color")
        self.assertEqual(container_term("screen-256color"), "screen-256color")

    def test_container_first_path_prioritizes_arch_environment_bins(self) -> None:
        path = container_first_path("/home/project/.venv/bin:/usr/bin:/custom/bin")

        self.assertEqual(
            path,
            "/usr/local/sbin:/usr/local/bin:/usr/bin:/home/project/.venv/bin:/custom/bin",
        )

    def test_shell_command_resets_terminal_color_state(self) -> None:
        command = shell_command()

        self.assertEqual(command[0:2], ["sh", "-lc"])
        self.assertIn("printf '\\033[0m'", command[2])
        self.assertNotIn("\\033]111\\007", command[2])
        self.assertIn("PS1=", command[2])
        self.assertIn("PROMPT_COMMAND", command[2])
        self.assertIn("/bin/bash --noprofile --norc -i", command[2])

    def test_pacman_install_command_is_noninteractive(self) -> None:
        self.assertEqual(
            pacman_install_command(("jq", "git")),
            ["pacman", "--noconfirm", "-Syu", "jq", "git"],
        )

    def test_initialize_keyring_command_populates_archlinux_keys(self) -> None:
        command = initialize_keyring_command()

        self.assertEqual(command[0:2], ["sh", "-lc"])
        self.assertIn("pacman-key --init", command[2])
        self.assertIn("pacman-key --populate archlinux", command[2])

    def test_container_user_command_fails_on_useradd_errors(self) -> None:
        command = create_container_user_command(uid=1000, gid=1000)

        self.assertIn("set -e", command[2])
        self.assertIn("useradd --uid 1000 --gid 1000", command[2])

    def test_host_ids_prefer_sudo_original_user(self) -> None:
        env = {"SUDO_UID": "1000", "SUDO_GID": "1000"}

        self.assertEqual(host_user_id(env), 1000)
        self.assertEqual(host_group_id(env), 1000)

    def test_host_ids_ignore_root_sudo_values(self) -> None:
        self.assertNotEqual(host_user_id({"SUDO_UID": "0"}), 0)


if __name__ == "__main__":
    unittest.main()
