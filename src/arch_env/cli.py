from __future__ import annotations

from pathlib import Path
import json
import logging
import sys

import typer

from arch_env import __version__
from arch_env.config import CONFIG_FILE, load_config, resolve_config_path, write_default_config
from arch_env.environment import EnvironmentManager
from arch_env.errors import ArchEnvError, CommandExecutionError
from arch_env.prerequisites import validate_host_prerequisites
from arch_env.tui import InteractiveApp


RUN_CONTEXT = {"allow_extra_args": True, "ignore_unknown_options": True}

app = typer.Typer(
    add_completion=False,
    help="Disposable Arch package environments.",
    invoke_without_command=True,
)


def progress(message: str) -> None:
    typer.echo(f"==> {message}")


def build_manager(project_dir: Path) -> EnvironmentManager:
    return EnvironmentManager(project_dir.resolve(), progress=progress)


def selected_project_dir(ctx: typer.Context, override: Path | None = None) -> Path:
    if override is not None:
        return override.resolve()
    if isinstance(ctx.obj, dict) and isinstance(ctx.obj.get("project_dir"), Path):
        return ctx.obj["project_dir"]
    return Path.cwd().resolve()


def selected_config(ctx: typer.Context, override: Path | None = None) -> Path:
    if override is not None:
        return override
    if isinstance(ctx.obj, dict) and isinstance(ctx.obj.get("config"), Path):
        return ctx.obj["config"]
    return Path(CONFIG_FILE)


@app.callback()
def default(
    ctx: typer.Context,
    project_dir: Path = typer.Option(Path.cwd(), "--project-dir", hidden=True),
    config: Path = typer.Option(Path(CONFIG_FILE), "--config", "-c", help="Config file for the environment."),
    version: bool = typer.Option(False, "--version", help="Show the arch-env version and exit."),
) -> None:
    """Disposable Arch package environments."""
    ctx.obj = {"project_dir": project_dir.resolve(), "config": config}
    if version:
        typer.echo(f"arch-env {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        InteractiveApp(selected_project_dir(ctx), selected_config(ctx)).run()


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    try:
        app(args=argv)
    except CommandExecutionError as exc:
        typer.echo(str(exc), err=True)
        typer.echo(f"command: {exc.display_command or ' '.join(exc.command)}", err=True)
        typer.echo(f"exit_code: {exc.returncode}", err=True)
        typer.echo(f"log: {exc.log_path}", err=True)
        return 1
    except ArchEnvError as exc:
        typer.echo(f"arch-env: {exc}", err=True)
        return 1
    return 0


@app.command()
def init(
    ctx: typer.Context,
    project_dir: Path | None = typer.Option(None, "--project-dir", hidden=True),
    config: Path | None = typer.Option(None, "--config", "-c", help="Config file to create."),
) -> None:
    """Create a starter config file."""
    path = write_default_config(selected_project_dir(ctx, project_dir), selected_config(ctx, config))
    typer.echo(f"wrote {path}")


@app.command()
def create(
    ctx: typer.Context,
    project_dir: Path | None = typer.Option(None, "--project-dir", hidden=True),
    config: Path | None = typer.Option(None, "--config", "-c", help="Config file to create from."),
    replace: bool = typer.Option(False, "--replace", help="Remove any existing environment before creating it."),
) -> None:
    """Create the environment described by a config file."""
    resolved_project = selected_project_dir(ctx, project_dir)
    loaded = load_config(resolved_project, selected_config(ctx, config), require_existing=True)
    manager = build_manager(resolved_project)
    paths = manager.create(loaded.environment_name, loaded, replace=replace)
    typer.echo(f"created environment {loaded.environment_name}: {paths.env_dir}")


@app.command()
def shell(
    ctx: typer.Context,
    project_dir: Path | None = typer.Option(None, "--project-dir", hidden=True),
    config: Path | None = typer.Option(None, "--config", "-c", help="Config file for the environment."),
) -> None:
    """Enter an interactive environment shell."""
    resolved_project = selected_project_dir(ctx, project_dir)
    loaded = load_config(resolved_project, selected_config(ctx, config), require_existing=True)
    manager = build_manager(resolved_project)
    typer.echo(f"entering environment {loaded.environment_name}: {manager.paths(loaded.environment_name).env_dir}", err=True)
    manager.shell(loaded.environment_name, loaded)


@app.command(context_settings=RUN_CONTEXT)
def run(
    ctx: typer.Context,
    command: list[str] = typer.Argument(..., help="Command and arguments to run inside the environment."),
    project_dir: Path | None = typer.Option(None, "--project-dir", hidden=True),
    config: Path | None = typer.Option(None, "--config", "-c", help="Config file for the environment."),
) -> None:
    """Run a command inside the environment."""
    resolved_project = selected_project_dir(ctx, project_dir)
    loaded = load_config(resolved_project, selected_config(ctx, config), require_existing=True)
    manager = build_manager(resolved_project)
    manager.run(loaded.environment_name, loaded, tuple(command))


@app.command()
def install(
    ctx: typer.Context,
    packages: list[str] = typer.Argument(..., help="Packages to install."),
    project_dir: Path | None = typer.Option(None, "--project-dir", hidden=True),
    config: Path | None = typer.Option(None, "--config", "-c", help="Config file for the environment."),
) -> None:
    """Install packages into the environment."""
    resolved_project = selected_project_dir(ctx, project_dir)
    loaded = load_config(resolved_project, selected_config(ctx, config), require_existing=True)
    manager = build_manager(resolved_project)
    paths = manager.install(loaded.environment_name, loaded, tuple(packages))
    typer.echo(f"installed packages into {loaded.environment_name}: {paths.env_dir}")


@app.command()
def remove(
    ctx: typer.Context,
    project_dir: Path | None = typer.Option(None, "--project-dir", hidden=True),
    config: Path | None = typer.Option(None, "--config", "-c", help="Config file for the environment."),
) -> None:
    """Delete the environment described by a config file."""
    resolved_project = selected_project_dir(ctx, project_dir)
    loaded = load_config(resolved_project, selected_config(ctx, config))
    manager = build_manager(resolved_project)
    paths = manager.remove(loaded.environment_name)
    typer.echo(f"removed environment {loaded.environment_name}: {paths.env_dir}")


@app.command(name="list")
def list_envs(
    ctx: typer.Context,
    project_dir: Path | None = typer.Option(None, "--project-dir", hidden=True),
) -> None:
    """List environments in this project."""
    manager = EnvironmentManager(selected_project_dir(ctx, project_dir))
    for paths in manager.list():
        typer.echo(paths.name)


@app.command()
def info(
    ctx: typer.Context,
    project_dir: Path | None = typer.Option(None, "--project-dir", hidden=True),
    config: Path | None = typer.Option(None, "--config", "-c", help="Config file for the environment."),
) -> None:
    """Show environment metadata."""
    resolved_project = selected_project_dir(ctx, project_dir)
    loaded = load_config(resolved_project, selected_config(ctx, config))
    manager = EnvironmentManager(resolved_project)
    typer.echo(json.dumps(manager.info(loaded.environment_name), indent=2, sort_keys=True))


@app.command()
def doctor(
    ctx: typer.Context,
    project_dir: Path | None = typer.Option(None, "--project-dir", hidden=True),
    config: Path | None = typer.Option(None, "--config", "-c", help="Config file for the environment."),
) -> None:
    """Check host prerequisites, config, and environment state."""
    resolved_project = selected_project_dir(ctx, project_dir)
    selected_config_path = selected_config(ctx, config)
    config_path = resolve_config_path(resolved_project, selected_config_path)
    errors: list[str] = []

    try:
        validate_host_prerequisites()
        typer.echo("host: ok")
    except ArchEnvError as exc:
        errors.append(f"host: {exc}")

    try:
        loaded = load_config(resolved_project, selected_config_path)
        if config_path.exists():
            typer.echo(f"config: ok ({loaded.config_path})")
        else:
            typer.echo(f"config: missing ({loaded.config_path})")
    except ArchEnvError as exc:
        errors.append(f"config: {exc}")
        loaded = None

    if loaded is not None:
        manager = EnvironmentManager(resolved_project)
        paths = manager.paths(loaded.environment_name)
        if paths.metadata_path.exists():
            try:
                metadata = manager.info(loaded.environment_name)
                typer.echo(f"environment: {metadata.get('status', 'unknown')} ({paths.env_dir})")
            except ArchEnvError as exc:
                errors.append(f"environment: {exc}")
        else:
            typer.echo(f"environment: missing ({paths.env_dir})")

    for error in errors:
        typer.echo(error, err=True)
    if errors:
        raise typer.Exit(1)


def configure_logging() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")


if __name__ == "__main__":
    sys.exit(main())
