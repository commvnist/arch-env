from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
import curses
import json
import os
import shlex
import subprocess

from arch_env.config import CONFIG_FILE, ArchEnvConfig, load_config, write_default_config
from arch_env.environment import EnvironmentManager
from arch_env.errors import ArchEnvError, CommandExecutionError


@dataclass(frozen=True)
class MenuItem:
    key: str
    label: str
    description: str


MENU_ITEMS = (
    MenuItem("n", "Init", "Create the selected config file and optionally edit it."),
    MenuItem("c", "Create", "Create the selected environment from its config."),
    MenuItem("s", "Shell", "Enter an interactive shell. This exits the TUI."),
    MenuItem("r", "Run", "Run a command in the environment. This exits the TUI."),
    MenuItem("p", "Packages", "Install pacman/AUR packages into the environment."),
    MenuItem("d", "Delete", "Remove the selected environment."),
    MenuItem("i", "Info", "Show environment metadata."),
    MenuItem("f", "Config", "Switch to another config file."),
    MenuItem("q", "Quit", "Close the interactive UI."),
)


class Palette:
    title = 0
    label = 0
    key = 0
    status_ready = 0
    status_missing = 0
    status_failed = 0
    message = 0
    subtle = 0


class InteractiveApp:
    def __init__(self, project_dir: Path, config_path: Path):
        self.project_dir = project_dir.resolve()
        self.config_path = config_path
        self.manager = EnvironmentManager(self.project_dir, progress=print)
        self.config = load_config(self.project_dir, self.config_path)
        self.message = "Ready."

    def run(self) -> None:
        curses.wrapper(self._run)

    def _run(self, screen: curses.window) -> None:
        _configure_colors()
        curses.curs_set(0)
        screen.keypad(True)
        screen.bkgd(" ", curses.color_pair(0))
        while True:
            self._draw(screen)
            key = screen.getkey()
            if key == "KEY_RESIZE":
                continue
            key = key.lower()
            if key == "q":
                return
            self._handle_key(screen, key)

    def _handle_key(self, screen: curses.window, key: str) -> None:
        try:
            if key == "n":
                self._terminal_action(screen, "Initializing config...", self._init_config)
            elif key == "c":
                self._terminal_action(screen, "Creating environment...", self._create)
            elif key == "s":
                self._exec_action(screen, "Entering shell...", lambda: self.manager.shell(self.config.environment_name, self.config))
            elif key == "r":
                command = self._prompt(screen, "Command")
                if command:
                    args = tuple(shlex.split(command))
                    self._exec_action(screen, f"Running: {command}", lambda: self.manager.run(self.config.environment_name, self.config, args))
            elif key == "p":
                packages = self._prompt(screen, "Packages")
                if packages:
                    self._terminal_action(screen, f"Installing: {packages}", lambda: self._install(packages))
            elif key == "d":
                if self._confirm(screen, f"Remove environment '{self.config.environment_name}'?"):
                    self._terminal_action(screen, "Removing environment...", self._remove)
            elif key == "i":
                self._show_info(screen)
            elif key == "f":
                self._switch_config(screen)
            elif key != "\n":
                self.message = f"Unknown key: {key}"
        except (ArchEnvError, CommandExecutionError, ValueError) as exc:
            self.message = str(exc)

    def _create(self) -> None:
        paths = self.manager.create(self.config.environment_name, self.config)
        self.message = f"Created {self.config.environment_name}: {paths.env_dir}"

    def _init_config(self) -> None:
        path = write_default_config(self.project_dir, self.config_path)
        print(f"Wrote {path}")
        self.config = load_config(self.project_dir, self.config_path)
        self.message = f"Wrote {path}"
        answer = input("Open in $EDITOR now? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            return
        editor = preferred_editor(os.environ)
        if not editor:
            print("EDITOR is not set; skipping editor launch.")
            return
        subprocess.run(editor_command(editor, path), check=False)

    def _install(self, packages: str) -> None:
        package_names = tuple(shlex.split(packages))
        paths = self.manager.install(self.config.environment_name, self.config, package_names)
        self.message = f"Installed packages into {self.config.environment_name}: {paths.env_dir}"

    def _remove(self) -> None:
        paths = self.manager.remove(self.config.environment_name)
        self.message = f"Removed {self.config.environment_name}: {paths.env_dir}"

    def _switch_config(self, screen: curses.window) -> None:
        config = self._prompt(screen, "Config file")
        if not config:
            return
        self.config_path = Path(config)
        self.config = load_config(self.project_dir, self.config_path)
        self.message = f"Selected {self.config.config_path} -> {self.config.environment_name}"

    def _show_info(self, screen: curses.window) -> None:
        try:
            info = self.manager.info(self.config.environment_name)
            content = json.dumps(info, indent=2, sort_keys=True).splitlines()
        except ArchEnvError as exc:
            content = [str(exc)]
        self._pager(screen, content)

    def _terminal_action(self, screen: curses.window, label: str, action: Callable[[], None]) -> None:
        curses.endwin()
        print(label)
        try:
            action()
        finally:
            input("Press Enter to return to ae...")
            screen.clear()

    def _exec_action(self, screen: curses.window, label: str, action: Callable[[], None]) -> None:
        curses.endwin()
        print(label)
        action()

    def _draw(self, screen: curses.window) -> None:
        screen.erase()
        height, width = screen.getmaxyx()
        paths = self.manager.paths(self.config.environment_name)
        status = self._environment_status()

        self._add(screen, 0, 0, "arch-env interactive", Palette.title | curses.A_BOLD)
        self._add_labeled(screen, 2, "Project", str(self.project_dir))
        self._add_labeled(screen, 3, "Config", str(self.config.config_path))
        self._add_labeled(screen, 4, "Env", self.config.environment_name)
        self._add_labeled(screen, 5, "Path", str(paths.env_dir))
        self._add(screen, 6, 0, "Status:  ", Palette.label | curses.A_BOLD)
        self._add(screen, 6, 9, status, self._status_attr(status) | curses.A_BOLD)

        self._add(screen, 8, 0, "Actions", Palette.title | curses.A_BOLD)
        for index, item in enumerate(MENU_ITEMS, start=10):
            self._add(screen, index, 2, "[", Palette.subtle)
            self._add(screen, index, 3, item.key, Palette.key | curses.A_BOLD)
            self._add(screen, index, 4, f"] {item.label:<8}", Palette.label | curses.A_BOLD)
            self._add(screen, index, 16, item.description)

        message_y = max(0, height - 2)
        screen.move(message_y, 0)
        screen.clrtoeol()
        self._add(screen, message_y, 0, self.message[: max(0, width - 1)], Palette.message | curses.A_BOLD)
        self._add(screen, height - 1, 0, "Press a key to choose an action.", Palette.subtle)
        screen.refresh()

    def _environment_status(self) -> str:
        try:
            metadata = self.manager.info(self.config.environment_name)
        except ArchEnvError:
            return "missing"
        status = metadata.get("status")
        if isinstance(status, str):
            return status
        return "unknown"

    def _prompt(self, screen: curses.window, label: str) -> str:
        height, width = screen.getmaxyx()
        prompt = f"{label}: "
        y = max(0, height - 3)
        screen.move(y, 0)
        screen.clrtoeol()
        self._add(screen, y, 0, prompt, Palette.label | curses.A_BOLD)
        curses.echo()
        curses.curs_set(1)
        try:
            value = screen.getstr(y, min(len(prompt), width - 1), max(1, width - len(prompt) - 1))
        finally:
            curses.noecho()
            curses.curs_set(0)
        return value.decode("utf-8").strip()

    def _confirm(self, screen: curses.window, question: str) -> bool:
        answer = self._prompt(screen, f"{question} Type yes")
        return answer == "yes"

    def _pager(self, screen: curses.window, lines: list[str]) -> None:
        offset = 0
        while True:
            screen.erase()
            height, width = screen.getmaxyx()
            self._add(screen, 0, 0, "Info", Palette.title | curses.A_BOLD)
            visible_height = max(1, height - 3)
            for row, line in enumerate(lines[offset : offset + visible_height], start=1):
                self._add(screen, row, 0, line[: max(0, width - 1)])
            screen.move(height - 1, 0)
            screen.clrtoeol()
            self._add(screen, height - 1, 0, "Up/Down scroll, q returns.", Palette.message | curses.A_BOLD)
            screen.refresh()
            key = screen.getkey()
            if key.lower() == "q":
                return
            if key == "KEY_DOWN":
                offset = min(max(0, len(lines) - visible_height), offset + 1)
            elif key == "KEY_UP":
                offset = max(0, offset - 1)

    def _add(self, screen: curses.window, y: int, x: int, text: str, attr: int = 0) -> None:
        height, width = screen.getmaxyx()
        if y < 0 or y >= height or x >= width:
            return
        screen.addstr(y, x, text[: max(0, width - x - 1)], attr)

    def _add_labeled(self, screen: curses.window, y: int, label: str, value: str) -> None:
        self._add(screen, y, 0, f"{label:<7}", Palette.label | curses.A_BOLD)
        self._add(screen, y, 9, value)

    def _status_attr(self, status: str) -> int:
        if status == "ready":
            return Palette.status_ready
        if status == "failed":
            return Palette.status_failed
        return Palette.status_missing


def _configure_colors() -> None:
    if not curses.has_colors():
        return
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_CYAN, -1)
    curses.init_pair(2, curses.COLOR_MAGENTA, -1)
    curses.init_pair(3, curses.COLOR_GREEN, -1)
    curses.init_pair(4, curses.COLOR_YELLOW, -1)
    curses.init_pair(5, curses.COLOR_RED, -1)
    curses.init_pair(6, curses.COLOR_BLUE, -1)
    curses.init_pair(7, curses.COLOR_WHITE, -1)
    Palette.title = curses.color_pair(1)
    Palette.label = curses.color_pair(7)
    Palette.key = curses.color_pair(2)
    Palette.status_ready = curses.color_pair(3)
    Palette.status_missing = curses.color_pair(4)
    Palette.status_failed = curses.color_pair(5)
    Palette.message = curses.color_pair(6)
    Palette.subtle = curses.A_DIM


def preferred_editor(env: dict[str, str]) -> str | None:
    editor = env.get("EDITOR") or env.get("VISUAL")
    if editor and editor.strip():
        return editor.strip()
    return None


def editor_command(editor: str, path: Path) -> list[str]:
    return [*shlex.split(editor), str(path)]
