from __future__ import annotations

from pathlib import Path
import json
import logging
import sys

import typer

from arch_env.config import CONFIG_FILE, load_config, write_default_config
from arch_env.environment import EnvironmentManager
from arch_env.errors import ArchEnvError, CommandExecutionError
from arch_env.tui import InteractiveApp


RUN_CONTEXT = {"allow_extra_args": True, "ignore_unknown_options": True}

app = typer.Typer(
    add_completion=False,
    help="Disposable Arch package environments.",
    invoke_without_command=True,
)


@app.callback()
def default(
    ctx: typer.Context,
    project_dir: Path = typer.Option(Path.cwd(), "--project-dir", hidden=True),
    config: Path = typer.Option(Path(CONFIG_FILE), "--config", "-c", help="Config file for the environment."),
) -> None:
    """Disposable Arch package environments."""
    if ctx.invoked_subcommand is None:
        InteractiveApp(project_dir.resolve(), config).run()


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    try:
        app(args=argv)
    except CommandExecutionError as exc:
        typer.echo(str(exc), err=True)
        typer.echo(f"command: {' '.join(exc.command)}", err=True)
        typer.echo(f"exit_code: {exc.returncode}", err=True)
        typer.echo(f"log: {exc.log_path}", err=True)
        return 1
    except ArchEnvError as exc:
        typer.echo(f"arch-env: {exc}", err=True)
        return 1
    return 0


@app.command()
def init(
    project_dir: Path = typer.Option(Path.cwd(), "--project-dir", hidden=True),
    config: Path = typer.Option(Path(CONFIG_FILE), "--config", "-c", help="Config file to create."),
) -> None:
    """Create a starter config file."""
    path = write_default_config(project_dir.resolve(), config)
    typer.echo(f"wrote {path}")


@app.command()
def create(
    project_dir: Path = typer.Option(Path.cwd(), "--project-dir", hidden=True),
    config: Path = typer.Option(Path(CONFIG_FILE), "--config", "-c", help="Config file to create from."),
) -> None:
    """Create the environment described by a config file."""
    loaded = load_config(project_dir.resolve(), config)
    manager = EnvironmentManager(project_dir.resolve())
    paths = manager.create(loaded.environment_name, loaded)
    typer.echo(f"created environment {loaded.environment_name}: {paths.env_dir}")


@app.command()
def shell(
    project_dir: Path = typer.Option(Path.cwd(), "--project-dir", hidden=True),
    config: Path = typer.Option(Path(CONFIG_FILE), "--config", "-c", help="Config file for the environment."),
) -> None:
    """Enter an interactive environment shell."""
    loaded = load_config(project_dir.resolve(), config)
    manager = EnvironmentManager(project_dir.resolve())
    typer.echo(f"entering environment {loaded.environment_name}: {manager.paths(loaded.environment_name).env_dir}", err=True)
    manager.shell(loaded.environment_name, loaded)


@app.command(context_settings=RUN_CONTEXT)
def run(
    command: list[str] = typer.Argument(..., help="Command and arguments to run inside the environment."),
    project_dir: Path = typer.Option(Path.cwd(), "--project-dir", hidden=True),
    config: Path = typer.Option(Path(CONFIG_FILE), "--config", "-c", help="Config file for the environment."),
) -> None:
    """Run a command inside the environment."""
    loaded = load_config(project_dir.resolve(), config)
    manager = EnvironmentManager(project_dir.resolve())
    manager.run(loaded.environment_name, loaded, tuple(command))


@app.command()
def install(
    packages: list[str] = typer.Argument(..., help="Packages to install."),
    project_dir: Path = typer.Option(Path.cwd(), "--project-dir", hidden=True),
    config: Path = typer.Option(Path(CONFIG_FILE), "--config", "-c", help="Config file for the environment."),
) -> None:
    """Install packages into the environment."""
    loaded = load_config(project_dir.resolve(), config)
    manager = EnvironmentManager(project_dir.resolve())
    paths = manager.install(loaded.environment_name, tuple(packages))
    typer.echo(f"installed packages into {loaded.environment_name}: {paths.env_dir}")


@app.command()
def remove(
    project_dir: Path = typer.Option(Path.cwd(), "--project-dir", hidden=True),
    config: Path = typer.Option(Path(CONFIG_FILE), "--config", "-c", help="Config file for the environment."),
) -> None:
    """Delete the environment described by a config file."""
    loaded = load_config(project_dir.resolve(), config)
    manager = EnvironmentManager(project_dir.resolve())
    paths = manager.remove(loaded.environment_name)
    typer.echo(f"removed environment {loaded.environment_name}: {paths.env_dir}")


@app.command(name="list")
def list_envs(project_dir: Path = typer.Option(Path.cwd(), "--project-dir", hidden=True)) -> None:
    """List environments in this project."""
    manager = EnvironmentManager(project_dir.resolve())
    for paths in manager.list():
        typer.echo(paths.name)


@app.command()
def info(
    project_dir: Path = typer.Option(Path.cwd(), "--project-dir", hidden=True),
    config: Path = typer.Option(Path(CONFIG_FILE), "--config", "-c", help="Config file for the environment."),
) -> None:
    """Show environment metadata."""
    loaded = load_config(project_dir.resolve(), config)
    manager = EnvironmentManager(project_dir.resolve())
    typer.echo(json.dumps(manager.info(loaded.environment_name), indent=2, sort_keys=True))


def configure_logging() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")


if __name__ == "__main__":
    sys.exit(main())
