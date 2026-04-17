# arch-env

`arch-env` creates disposable Arch Linux development environments backed by
`systemd-nspawn`. It is intended to feel like a Python virtualenv for Arch
packages: install packages into an isolated root, work against the current
project, and delete the environment when it is no longer needed.

The default environment mount policy is intentionally narrow. Only the current
project directory is mounted read-write into the container.

## Requirements

- Arch Linux or an Arch-derived host
- Python 3.11+
- `uv`
- `sudo`
- `systemd-nspawn`
- `pacman`
- `pacstrap` from `arch-install-scripts`

Install host dependencies and Python dependencies:

```bash
make deps
```

Install `ae` and `arch-env` into your user PATH:

```bash
make install
```

`make install` uses `uv tool install --force --reinstall .`. The reinstall flag
matters while the project version is unchanged because it copies current local
source into uv's tool environment instead of only refreshing command shims.
Ensure the uv tool bin directory is on your `PATH`, usually `~/.local/bin`.

Run `make install` again after changing the source if you want the PATH-installed
`ae` command to use the latest local code.

## Quick Start

```bash
uv run ae init
uv run ae create
uv run ae run python --version
uv run ae shell
uv run ae install jq
uv run ae remove
```

Open the interactive TUI:

```bash
uv run ae
```

The TUI shows the selected project, config file, environment path, and status.
It provides keyboard actions for initializing a config file, creating an
environment, entering a shell, running a command, installing packages, removing
the environment, viewing metadata, and switching config files. When initializing
a config file, the TUI asks whether to open it with `$EDITOR`.

## Configuration

`ae init` writes `arch-env.toml`. The config file name determines the
environment name:

- `arch-env.toml` creates `.arch-env/envs/default`
- `tools.toml` creates `.arch-env/envs/tools`
- `python-tools.toml` creates `.arch-env/envs/python-tools`

Use `--config` to select another config file:

```bash
uv run ae init --config tools.toml
uv run ae create --config tools.toml
uv run ae run --config tools.toml jq --version
```

```toml
# The environment name is derived from this file name.
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
```

Environments are stored under `.arch-env/envs/<name>/`.
Every created environment bootstraps `yay` inside the container so AUR packages
can be installed without relying on the host `yay`.

## Running Commands

`ae run <command>` executes a command inside the environment and streams output
directly to the current terminal, similar to `uv run`.

The current project directory is mounted read-write at the same path inside the
container. The command receives the current shell environment with container
identity values normalized to the `archenv` user. Container package paths are
placed before the host `PATH`, so commands like `python`, `python3`, and `jq`
resolve to packages installed in the Arch environment before any project-local
Python `.venv` or host path entries.

Run `ae` as your normal user. The tool invokes `sudo` for the specific Arch
container operations that need it; wrapping the whole command in `sudo` can
strip the shell environment before `ae run` sees it.

## Shell Appearance

`ae shell` does not try to clone the host prompt theme. It forwards terminal
capability variables such as `TERM` and `COLORTERM`, then starts a clean
interactive Bash session with a simple prompt that explicitly resets terminal
style before and after each prompt. This avoids container startup files or
terminal-control sequences forcing a background color in the host terminal.
The underlying `systemd-nspawn` invocation also disables nspawn's terminal
background marker so the shell uses the host terminal background.

Host-specific terminal names are normalized when the base Arch root does not
ship the matching terminfo entry. For example, `TERM=xterm-kitty` is exposed
inside the environment as `TERM=xterm-256color`, while `COLORTERM=truecolor` is
still preserved.

## Limitations

This is not a Nix replacement. Package versions follow current Arch repository
and AUR state unless pinning is added in a future version. AUR package builds
execute arbitrary build scripts inside the environment, so users still need to
trust the packages they install. Deleting an environment removes package state
inside the environment root, but it cannot undo writes made to explicitly
mounted host paths such as the current project directory.
