# arch-env

`arch-env` creates disposable Arch Linux development environments backed by
`systemd-nspawn`. It is intended to feel like a virtual environment for Arch
packages and developer tools: create an isolated root, run commands against the
current project, install extra packages when needed, and remove the environment
when it is no longer useful.

The default host access is narrow. Only the current project directory is mounted
read-write into the container. Extra mounts, device forwarding, display
forwarding, and environment-variable passthrough are explicit config choices.

Interactive shells and `ae run` commands start as the `archenv` user. The tool
keeps official Arch and AUR package installation behind `ae install`, while
developer package managers such as uv, Bundler, npm, Cargo, and Go modules get
writable container-local prefixes by default.

## Requirements

- Arch Linux or an Arch-derived host
- Python 3.11+
- `sudo`
- `systemd-nspawn`
- `pacman`
- `pacstrap` from `arch-install-scripts`
- `uv` for local development targets such as `make test`

Install host and Python development dependencies:

```bash
make deps
```

## Installation

Install the `ae` and `arch-env` commands into your user PATH:

```bash
make install
```

This runs `uv tool install --force --reinstall .`. Run `make install` again
after source changes when using the installed tool. Make sure uv's tool bin
directory, usually `~/.local/bin`, is on `PATH`.

Uninstall:

```bash
make uninstall
```

## Quick Start

```bash
ae init
ae create
ae run python --version
ae shell
ae install jq
ae remove
```

Run `ae` with no subcommand to open the interactive TUI.

## Commands

All environment-targeting commands accept `--config/-c <file>`. The config file
name determines the environment name.

`ae init`

Writes a starter config file. It fails if the file already exists.

`ae create [--replace]`

Creates the environment from an existing config. Creation runs `pacstrap`,
creates the `archenv` user, initializes the pacman keyring, installs configured
packages, bootstraps `yay`, and writes metadata under
`.arch-env/envs/<name>/metadata.json`.

If creation fails, the environment status becomes `failed`. Fix the issue and
run either:

```bash
ae remove
ae create
```

or:

```bash
ae create --replace
```

`ae shell`

Starts an interactive Bash shell as `archenv`. The environment must have status
`ready`.

`ae run <command> [args...]`

Runs a single command as `archenv`. The environment must have status `ready`.
Only terminal defaults, developer package-manager defaults, display variables
when enabled, and variables listed in `[env].passthrough` are forwarded.

```bash
ae run python --version
ae run make test
ae run -- bash -c "echo hello"
```

Run `ae` as your normal user. The tool calls `sudo` internally for the specific
host and container operations that need it.

`ae install <packages...>`

Installs official repository and AUR packages into an existing `ready`
environment. Each package is checked against official repositories first. Any
remaining packages are checked against the AUR and installed with `yay`.

Official Arch and AUR package installation is intentionally supported through
`ae install`, not through direct `pacman` or `yay` use inside `ae shell`.

`ae remove`

Deletes the environment under `.arch-env/envs/<name>/`. It marks metadata as
`removing` before deletion when metadata is present, then falls back to
`sudo rm -rf --one-file-system` if root-owned files block normal removal.

`ae list`

Lists environments in the current project.

`ae info`

Prints metadata JSON for the selected environment.

`ae doctor`

Checks host prerequisites, selected config validity, and environment state.

`ae --version`

Prints the installed `arch-env` version.

## Configuration

`ae init` writes this config:

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

[devices]
gpu = false
paths = []

[env]
passthrough = []

[shell]
# forward_display = true  # forward X11/Wayland/audio/D-Bus sockets to the host desktop

[developer]
writable_prefixes = true
```

Config parsing is strict. Unknown tables or keys, duplicate list values,
whitespace-padded strings, invalid environment variable names, and missing
mount/device paths are rejected. `create`, `shell`, `run`, and `install` require
the config file to exist.

`[pacman].packages`

Official repository packages installed during `ae create`.

`[aur].packages`

AUR packages installed during `ae create`.

`[mounts].project`

Mounts the project directory read-write at the same absolute path inside the
container. Defaults to `true`.

`[mounts].extra`

Additional host paths to bind-mount at the same path inside the container.
Relative paths are resolved relative to the project directory. `~` is expanded.
Every path must already exist.

`[devices].gpu`

Binds common GPU device nodes that exist on the host, including `/dev/dri`,
`/dev/kfd`, and `/dev/nvidia*`.

`[devices].paths`

Additional host device paths to bind-mount at the same path inside the
container. Relative paths are resolved relative to the project directory. Every
path must already exist.

`[env].passthrough`

Host environment variable names to forward into `ae shell` and `ae run`.
Variables not listed here are not forwarded.

`[shell].forward_display`

When `true`, forwards the host display/audio/session sockets that exist:

| Subsystem | Bound host path | Environment variables |
|-----------|-----------------|-----------------------|
| X11 | `/tmp/.X11-unix` | `DISPLAY`, `XAUTHORITY` |
| Wayland | `$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY` | `WAYLAND_DISPLAY`, `XDG_RUNTIME_DIR` |
| PulseAudio/PipeWire | `$XDG_RUNTIME_DIR/pulse/native` | `PULSE_SERVER` |
| D-Bus session | parsed `unix:path=` socket | `DBUS_SESSION_BUS_ADDRESS` |

`[developer].writable_prefixes`

Defaults to `true`. When enabled, arch-env prepares container-local writable
prefixes for developer package managers:

| Tool family | Defaults |
|-------------|----------|
| Python/uv/pip | `UV_CACHE_DIR`, `PIP_CACHE_DIR`, `PYTHONUSERBASE` |
| Ruby/Bundler/gem | `GEM_HOME`, `GEM_PATH`, `BUNDLE_PATH`, `BUNDLE_APP_CONFIG` |
| Node/npm | `NPM_CONFIG_PREFIX=/usr/local` |
| Rust/Cargo | `CARGO_HOME=/opt/arch-env/cargo` |
| Go modules | `GOPATH`, `GOMODCACHE`, `GOCACHE` |

Writable directory trees are limited to `/usr/local`, `/opt/arch-env`, and
`/var/cache/arch-env`. Package-owned trees such as `/usr/lib`, `/usr/share`, and
`/usr/include` are not made writable.

## Multiple Environments

The config file name determines the environment name:

| Config file | Environment |
|-------------|-------------|
| `arch-env.toml` | `default` |
| `tools.toml` | `tools` |
| `python-tools.toml` | `python-tools` |

Environment names must match `[A-Za-z0-9][A-Za-z0-9-]{0,63}`.

```bash
ae init --config tools.toml
ae create --config tools.toml
ae run --config tools.toml jq --version
ae shell --config tools.toml
```

## State, Logs, And Metadata

```
.arch-env/
`-- envs/
    `-- default/
        |-- root/
        |-- cache/
        |   |-- pacman/
        |   `-- aur/
        |-- logs/
        `-- metadata.json
```

Metadata contains `status`, `created_at`, `updated_at`, `last_error`,
`arch_env_version`, paths, and a config snapshot. `shell`, `run`, and `install`
only operate on environments with status `ready`.

External command logs are written under `.arch-env/envs/<name>/logs/`. Each log
starts with the command that was run. `--setenv` values are redacted in logs and
user-facing command failures.

## Package Management Model

Every environment bootstraps `yay` so `ae install <aur-package>` works after
creation. AUR builds run as the non-root `archenv` user.

Root package operations use helpers installed under `/usr/libexec/arch-env`.
The container sudoers entry grants `archenv` passwordless access only to those
helpers, and the sudoers file is validated with `visudo -cf` before
installation. The tool does not install writable `/usr/local/bin/pacman` or
`/usr/local/bin/yay` wrappers.

Before a package transaction, arch-env temporarily restores package-manager
directory modes on its managed writable prefixes. After the transaction, it
reapplies developer write access when `[developer].writable_prefixes` is enabled.

## Development

Run unit tests:

```bash
make test
```

Run the dry-run smoke plan without sudo or network access:

```bash
make smoke-dry-run
```

Run the real smoke test on an Arch host with sudo and network access:

```bash
make smoke
```

The smoke test creates a temporary project, creates an environment, installs
`python`, `uv`, `ruby`, `ruby-bundler`, `nodejs`, `npm`, `rust`, and `go`, then
runs dependency-backed Hello World programs through Python/uv, Ruby
Bundler/gem, Node/npm, Rust/Cargo, and Go modules. It removes the environment at
the end and prints log paths if a step fails.

`make check` runs unit tests and the smoke dry-run.

## Limitations

- Package versions follow current Arch repositories and AUR state. Version
  pinning is not supported.
- AUR package builds execute arbitrary package build scripts inside the
  container. Trust the packages you install.
- Removing an environment cannot undo writes made to mounted host paths such as
  the project directory or explicitly configured extra mounts.
- The host must be Arch Linux or Arch-derived.
