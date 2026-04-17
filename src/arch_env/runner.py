from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import logging
import shlex
import subprocess
from datetime import datetime, UTC

from arch_env.errors import CommandExecutionError


LOGGER = logging.getLogger("arch_env.runner")


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    returncode: int
    log_path: Path


class CommandRunner:
    def run(self, command: list[str], *, log_path: Path, check: bool = True) -> CommandResult:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        started_at = datetime.now(UTC).isoformat()
        LOGGER.info(
            "running command",
            extra={"command": shlex.join(command), "log_path": str(log_path)},
        )

        with log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(f"\n[{started_at}] $ {shlex.join(command)}\n")
            log_file.flush()
            process = subprocess.run(
                command,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
            log_file.write(f"[exit {process.returncode}]\n")

        if check and process.returncode != 0:
            raise CommandExecutionError(
                (
                    f"Command failed with exit code {process.returncode}. "
                    f"See log: {log_path}"
                ),
                command=command,
                returncode=process.returncode,
                log_path=str(log_path),
            )

        return CommandResult(command=command, returncode=process.returncode, log_path=log_path)
