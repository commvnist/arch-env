from __future__ import annotations

import argparse
from collections.abc import Iterable
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap


PACMAN_PACKAGES = (
    "python",
    "uv",
    "ruby",
    "ruby-bundler",
    "nodejs",
    "npm",
    "rust",
    "go",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run arch-env package-manager smoke checks.")
    parser.add_argument("--dry-run", action="store_true", help="Print the commands without running them.")
    parser.add_argument("--keep", action="store_true", help="Keep the temporary project after a real run.")
    args = parser.parse_args(argv)

    project_dir = Path(tempfile.mkdtemp(prefix="arch-env-smoke-"))
    try:
        return run_smoke(project_dir, dry_run=args.dry_run, keep=args.keep)
    finally:
        if args.dry_run and not args.keep:
            shutil.rmtree(project_dir, ignore_errors=True)


def run_smoke(project_dir: Path, *, dry_run: bool, keep: bool) -> int:
    write_smoke_config(project_dir)
    commands = smoke_commands(project_dir)
    if dry_run:
        print(f"project: {project_dir}")
        for command in commands:
            print(render_command(command))
        if keep:
            print(f"kept smoke project: {project_dir}")
        return 0

    try:
        for command in commands:
            run(command)
    except subprocess.CalledProcessError as exc:
        print(f"smoke command failed with exit code {exc.returncode}: {render_command(exc.cmd)}", file=sys.stderr)
        print_log_paths(project_dir)
        print(f"kept failed smoke project: {project_dir}", file=sys.stderr)
        return exc.returncode or 1

    remove_command = ae(project_dir, "remove")
    try:
        run(remove_command)
    except subprocess.CalledProcessError as exc:
        print(f"cleanup failed with exit code {exc.returncode}: {render_command(exc.cmd)}", file=sys.stderr)
        print_log_paths(project_dir)
        print(f"kept smoke project after cleanup failure: {project_dir}", file=sys.stderr)
        return exc.returncode or 1

    if keep:
        print(f"kept smoke project: {project_dir}")
    else:
        shutil.rmtree(project_dir, ignore_errors=True)
    return 0


def write_smoke_config(project_dir: Path) -> None:
    (project_dir / "arch-env.toml").write_text(
        textwrap.dedent(
            """
            [pacman]
            packages = []

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
            forward_display = false

            [developer]
            writable_prefixes = true
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


def smoke_commands(project_dir: Path) -> list[list[str]]:
    return [
        ae(project_dir, "create"),
        ae(project_dir, "install", *PACMAN_PACKAGES),
        ae(project_dir, "run", "--", "sh", "-lc", python_uv_smoke()),
        ae(project_dir, "run", "--", "sh", "-lc", ruby_bundler_smoke()),
        ae(project_dir, "run", "--", "sh", "-lc", node_npm_smoke()),
        ae(project_dir, "run", "--", "sh", "-lc", rust_cargo_smoke()),
        ae(project_dir, "run", "--", "sh", "-lc", go_modules_smoke()),
    ]


def ae(project_dir: Path, command: str, *args: str) -> list[str]:
    return [sys.executable, "-m", "arch_env", "--project-dir", str(project_dir), command, *args]


def python_uv_smoke() -> str:
    return (
        "uv run --with rich python -c "
        "'from rich.console import Console; Console().print(\"Hello, Python\")'"
    )


def ruby_bundler_smoke() -> str:
    return "\n".join(
        (
            "set -e",
            "mkdir -p smoke-ruby",
            "cd smoke-ruby",
            "printf '%s\\n' 'source \"https://rubygems.org\"' 'gem \"colorize\"' > Gemfile",
            "bundle install",
            "bundle exec ruby -e 'require \"colorize\"; puts \"Hello, Ruby\".green'",
        )
    )


def node_npm_smoke() -> str:
    return "\n".join(
        (
            "set -e",
            "mkdir -p smoke-node",
            "cd smoke-node",
            "npm init -y",
            "npm install left-pad",
            "node -e 'const leftPad = require(\"left-pad\"); console.log(leftPad(\"Hello, Node\", 13));'",
        )
    )


def rust_cargo_smoke() -> str:
    return "\n".join(
        (
            "set -e",
            "mkdir -p smoke-rust/src",
            "cd smoke-rust",
            "cat > Cargo.toml <<'EOF'",
            "[package]",
            "name = \"arch_env_smoke\"",
            "version = \"0.1.0\"",
            "edition = \"2024\"",
            "",
            "[dependencies]",
            "anyhow = \"1\"",
            "EOF",
            "cat > src/main.rs <<'EOF'",
            "fn main() -> anyhow::Result<()> {",
            "    println!(\"Hello, Rust\");",
            "    Ok(())",
            "}",
            "EOF",
            "cargo run --quiet",
        )
    )


def go_modules_smoke() -> str:
    return "\n".join(
        (
            "set -e",
            "mkdir -p smoke-go",
            "cd smoke-go",
            "go mod init example.com/arch-env-smoke",
            "go get github.com/fatih/color@latest",
            "cat > main.go <<'EOF'",
            "package main",
            "",
            "import \"github.com/fatih/color\"",
            "",
            "func main() {",
            "    color.Green(\"Hello, Go\")",
            "}",
            "EOF",
            "go run .",
        )
    )


def run(command: list[str]) -> None:
    print(render_command(command), flush=True)
    subprocess.run(command, check=True)


def render_command(command: Iterable[str]) -> str:
    return shlex.join([str(part) for part in command])


def print_log_paths(project_dir: Path) -> None:
    logs_root = project_dir / ".arch-env" / "envs" / "default" / "logs"
    if not logs_root.exists():
        return
    print("logs:", file=sys.stderr)
    for log_path in sorted(logs_root.glob("*.log")):
        print(f"  {log_path}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
