# arch-env

`arch-env` creates disposable Arch Linux development environments backed by
`systemd-nspawn`. It is intended to feel like a Python virtualenv for Arch
packages: install packages into an isolated root, work against the current
project, and delete the environment when it is no longer needed.

The default mount policy is intentionally narrow. Only the current project
directory is mounted read-write into the container. The host system is otherwise
untouched.

Interactive shells and `ae run` commands start as the `archenv` user. Common
container-local install and cache directories are writable by that user's group,
so development tools can install dependencies without writing to the host or
creating root-owned project files.

## Requirements

- Arch Linux or an Arch-derived host
- `python` 3.11+
- `uv`
- `sudo`
- `systemd-nspawn`
- `pacman`
- `pacstrap` from `arch-install-scripts`

Install all host and Python dependencies at once:

```bash
make deps
```

## Installation

Install the `ae` and `arch-env` commands into your user PATH:

```bash
make install
```

This runs `uv tool install --force --reinstall .`. The `--reinstall` flag
ensures the current local source is copied into uv's tool environment rather
than only refreshing the command shim. Make sure `~/.local/bin` is on your
`PATH` (uv's default tool bin directory).

Run `make install` again after any source change to pick up the latest code.

To uninstall:

```bash
make uninstall
```

## Quick Start

```bash
ae init          # write arch-env.toml
ae create        # bootstrap the environment
ae run python --version
ae shell         # interactive shell inside the environment
ae install jq    # install a package at any time
ae remove        # delete the environment
```

Run `ae` with no arguments to open the interactive TUI.

## Commands

All commands accept `--config/-c <file>` to target a specific config file and
therefore a specific named environment (see [Multiple Environments](#multiple-environments)).

### `ae init`

Write a starter `arch-env.toml` in the current directory. Does nothing if the
file already exists. Optionally opens the file in `$EDITOR` when run through the
TUI.

### `ae create`

Bootstrap a new environment: runs `pacstrap`, creates the container user,
initialises the pacman keyring, installs configured packages, and bootstraps
`yay` for AUR support. All steps are logged under
`.arch-env/envs/<name>/logs/`.

If creation fails, the environment is marked `failed`. Fix the config and re-run
`ae create` (delete the failed environment first with `ae remove`).

### `ae shell`

Enter an interactive Bash session inside the environment. The project directory
is mounted at the same path inside the container. Exit with `exit` or `Ctrl-D`.

### `ae run <command> [args...]`

Run a single command inside the environment and stream its output directly to the
terminal, similar to `uv run`. Only safe terminal defaults and environment
variables explicitly listed in `[env].passthrough` are forwarded.

```bash
ae run python --version
ae run make test
ae run -- bash -c "echo hello"
```

Run `ae` (not `sudo ae`). The tool calls `sudo` internally for the specific
container operations that need it; wrapping the whole command in `sudo` strips
the shell environment before `ae run` sees it.

### `ae install <packages...>`

Install one or more packages into an existing environment. Each package is
checked against the official Arch repositories first; if not found there it is
checked against the AUR and installed via `yay`. If neither lookup succeeds,
`ae install` stops with both package-resolution log paths.

```bash
ae install jq
ae install paru-bin neovim
```

### `ae remove`

Delete the environment and all its state under `.arch-env/envs/<name>/`. Uses
`sudo rm -rf` when the container root contains root-owned files.

### `ae list`

List all environments in the current project, one per line.

### `ae info`

Print environment metadata as JSON: creation time, status, config snapshot,
arch-env version, and all relevant paths.

## Interactive TUI

Running `ae` with no subcommand opens a curses-based interactive interface.

```
arch-env interactive

Project    /home/user/myproject
Config     arch-env.toml
Env        default
Path       /home/user/myproject/.arch-env/envs/default
Status     ready

[n] init    [c] create  [s] shell   [r] run
[p] install [d] delete  [i] info    [f] config  [q] quit
```

| Key | Action |
|-----|--------|
| `n` | Create the config file (prompts to open in `$EDITOR`) |
| `c` | Create the environment |
| `s` | Enter an interactive shell (exits TUI) |
| `r` | Run a command (prompts for command, then exits TUI) |
| `p` | Install packages (prompts for package names) |
| `d` | Delete the environment (requires typing `yes`) |
| `i` | Show JSON metadata in a scrollable pager |
| `f` | Switch to a different config file |
| `q` | Quit |

Long-running operations (create, install, remove) display progress lines, then
wait for Enter before returning to the TUI. Shell and run replace the TUI
process entirely via `exec`.

## Configuration

`ae init` writes `arch-env.toml`. The complete set of options:

```toml
# The environment name is derived from this file name.
# arch-env.toml  →  .arch-env/envs/default
# tools.toml     →  .arch-env/envs/tools

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
project = true   # mount the project directory read-write into the container
extra = []       # additional host paths to mount at the same path inside the container

[devices]
gpu = false      # bind common GPU device nodes when they exist
paths = []       # additional host device paths to bind at the same path

[env]
passthrough = [] # host environment variable names to forward into shell/run

[shell]
# forward_display = true  # forward X11/Wayland/audio/D-Bus to the host desktop
```

### `[pacman]`

`packages` — list of packages to install from the official Arch repositories
during `ae create`. Packages are installed with `pacman -Syu`.

### `[aur]`

`packages` — list of AUR packages to install via `yay` during `ae create`.

### `[mounts]`

`project` — when `true` (the default), the project directory is mounted
read-write at the same absolute path inside the container. Set to `false` to
run the environment in a fully isolated root.

`extra` — additional host paths to bind-mount at their same path inside the
container. Supports `~` expansion. These paths are explicit host access and are
not removed with the environment.

```toml
[mounts]
extra = ["~/fonts", "/media/data"]
```

### `[devices]`

`gpu` — when `true`, bind common GPU device nodes that exist on the host, such
as `/dev/dri`, `/dev/kfd`, and `/dev/nvidia*`.

`paths` — additional host device paths to bind-mount at their same path inside
the container. These are explicit host access and are not removed with the
environment.

```toml
[devices]
gpu = true
paths = ["/dev/input/js0"]
```

The container user is added to mirrored host supplemental groups by numeric GID
so explicitly forwarded devices can use normal Unix group permissions.

### `[env]`

`passthrough` — host environment variable names to forward into `ae shell` and
`ae run`. Variables not listed here are not forwarded, which avoids accidental
secret leakage.

```toml
[env]
passthrough = ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"]
```

### `[shell]`

`forward_display` — when `true`, `ae shell` and `ae run` forward the host
display and audio stack into the container, enabling GUI applications to render
on the host desktop. Disabled by default.

What gets forwarded (each only if present on the host):

| Subsystem | Socket | Environment variables |
|-----------|--------|-----------------------|
| X11 | `/tmp/.X11-unix` | `DISPLAY`, `XAUTHORITY` |
| Wayland | `$XDG_RUNTIME_DIR` | `WAYLAND_DISPLAY`, `XDG_RUNTIME_DIR` |
| PulseAudio / PipeWire | inside `XDG_RUNTIME_DIR` | `PULSE_SERVER` |
| D-Bus session | inside `XDG_RUNTIME_DIR` | `DBUS_SESSION_BUS_ADDRESS` |

Packages that GUI apps commonly need beyond their direct dependencies:

```toml
[pacman]
packages = [
  ...
  "libsm",       # Qt xcb platform plugin
  "ttf-dejavu",  # fallback fonts
]
```

## Multiple Environments

The config file name determines the environment name:

| Config file | Environment |
|-------------|-------------|
| `arch-env.toml` | `default` |
| `tools.toml` | `tools` |
| `python-tools.toml` | `python-tools` |

Environment names must start with a letter or digit and contain only letters,
digits, or dashes.

Pass `--config/-c` to target a specific environment:

```bash
ae init --config tools.toml
ae create --config tools.toml
ae run --config tools.toml jq --version
ae shell --config tools.toml
```

Environment names must match `[A-Za-z0-9][A-Za-z0-9_.-]{0,63}`.

## Directory Layout

```
.arch-env/
└── envs/
    └── default/
        ├── root/              # container root filesystem (pacstrap output)
        ├── cache/
        │   ├── pacman/        # shared pacman package cache
        │   └── aur/           # yay build and package cache
        ├── logs/              # per-operation log files
        └── metadata.json      # environment status and config snapshot
```

Log files follow the pattern `<step>.log`, e.g. `bootstrap-pacstrap.log`,
`install-pacman.log`, `bootstrap-yay-build.log`. Each log starts with the exact
command that was run.

## Logs and Errors

Long-running operations print a progress line before each external command:

```
==> Bootstrapping Arch root with pacstrap.
==> Log: .arch-env/envs/default/logs/bootstrap-pacstrap.log
```

When a command fails, the error includes the command, exit code, and log path.
Read the log to see the exact output from `pacstrap`, `pacman`, `makepkg`, etc.

## AUR Bootstrap

Every environment bootstraps `yay` regardless of whether AUR packages are
configured, so `ae install <aur-package>` works at any time without additional
setup. The bootstrap process:

1. Grants the container user passwordless `sudo` access only for root-owned package-management helpers
2. Installs `go` with root pacman (build dependency)
3. Clones the `yay` AUR repository and runs `makepkg` as the container user
4. Installs the built `yay` package with root pacman
5. Verifies `yay --version` as the container user

This means AUR builds run as the non-root `archenv` user but installation
is handled by root pacman — `makepkg` never prompts for a password.

## Container Privileges

Interactive shells and `ae run` commands start as the `archenv` user. Common
container-local install and cache directory trees under `/usr/local`, `/usr/lib`,
`/usr/share`, `/usr/include`, `/opt`, and `/var/cache` are group-writable for
that user inside the isolated root, so normal developer commands can install
there without `sudo`:

```bash
bundle install
npm install -g typescript
pip install --prefix=/usr/local some-tool
```

Those commands modify the isolated container root, not the host system. The
project directory and any explicit host mounts remain real host paths, and
commands run as the mapped `archenv` user keep project file ownership aligned
with the host user.

Only directory permissions are changed; package-owned file contents and file
modes are not recursively rewritten. Package-manager transactions temporarily
restore package-style directory modes on the managed development prefixes before
invoking pacman, then reapply developer write access afterward. Failures in that
repair step are reported as command failures instead of being silently ignored.
The `pacman` and `yay` commands available in the shell are wrappers; privileged
operations are delegated only to root-owned helpers under `/usr/libexec/arch-env`,
not to writable `/usr/local` paths.

## Shell Appearance

`ae shell` starts a clean interactive Bash session. It does not clone the host
prompt theme. Terminal capability variables (`TERM`, `COLORTERM`) are forwarded,
and the prompt explicitly resets terminal styles to avoid bleeding colour
sequences from nspawn's startup.

Host-specific terminal names that lack a matching terminfo entry in the base Arch
root are normalised: `TERM=xterm-kitty` becomes `TERM=xterm-256color` while
`COLORTERM=truecolor` is preserved.

## Development

### Running Tests

```bash
make test
```

Tests use the standard library `unittest` runner via `uv run`. No external test
framework is required.

### Project Structure

```
src/arch_env/
├── __init__.py       # version
├── __main__.py       # python -m arch_env entry point
├── cli.py            # Typer CLI definition
├── commands.py       # systemd-nspawn and shell command builders
├── config.py         # TOML config parsing and ArchEnvConfig dataclass
├── environment.py    # EnvironmentManager — create/shell/run/install/remove
├── errors.py         # exception types
├── paths.py          # EnvironmentPaths and directory layout
├── prerequisites.py  # host dependency checks
├── runner.py         # subprocess wrapper with log file output
└── tui.py            # curses interactive interface

tests/
├── test_cli.py
├── test_commands.py
├── test_config.py
├── test_environment.py
├── test_paths.py
├── test_runner.py
└── test_tui.py
```

### Makefile Targets

| Target | Description |
|--------|-------------|
| `make deps` | Install host packages and sync Python dependencies |
| `make install` | Install `ae`/`arch-env` into `~/.local/bin` via uv |
| `make reinstall` | Alias for install |
| `make uninstall` | Remove the uv tool install |
| `make test` | Run the test suite |

## Limitations

- Package versions follow current Arch repository and AUR state. Version pinning
  is not yet supported.
- AUR package builds execute arbitrary build scripts inside the container; trust
  the packages you install.
- Deleting an environment removes state inside the container root but cannot undo
  writes made to mounted host paths such as the project directory.
- The host must be running Arch Linux or an Arch-derived distribution.
  `pacstrap` and `pacman` are not available on other distributions.
