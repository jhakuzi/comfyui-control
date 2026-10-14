"""Configuration and commands, without shell interpolation."""
from dataclasses import asdict, dataclass, fields
import json
import os
from pathlib import Path
import shlex
import shutil
import tempfile


def config_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "comfyui-control" / "config.json"


def expand(value: str) -> Path:
    return Path(os.path.expandvars(value)).expanduser().absolute()


@dataclass
class Config:
    comfy_dir: str = ""
    python: str = ""
    mode: str = "python"
    script: str = ""
    arguments: str = ""
    output_dir: str = ""
    models_dir: str = ""
    install_requirements: bool = False
    managed_script: bool = False
    update_method: str = "git"
    comfy_cli: str = ""

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or config_path()
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Configuration must be a JSON object.")
        accepted = {f.name for f in fields(cls)}
        data = {k: v for k, v in data.items() if k in accepted}
        for key, value in data.items():
            expected = bool if key in ("install_requirements", "managed_script") else str
            if not isinstance(value, expected):
                raise ValueError(f"Invalid value for {key}.")
        if data.get("mode", "python") not in ("python", "script"):
            raise ValueError("Unknown launch mode.")
        if data.get("update_method", "git") not in ("git", "cli"):
            raise ValueError("Unknown update method.")
        return cls(**data)

    def save(self, path: Path | None = None) -> None:
        path = path or config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".config-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(asdict(self), stream, indent=2)
                stream.write("\n")
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @property
    def directory(self) -> Path:
        return expand(self.comfy_dir) if self.comfy_dir.strip() else Path.home()

    def interpreter(self) -> str:
        if self.python.strip():
            value = self.python.strip()
            if "/" in value:
                return str(expand(value))
            return shutil.which(value) or value
        for candidate in self.local_interpreters():
            if candidate.is_file():
                return str(candidate)
        return shutil.which("python3") or "python3"

    def local_interpreters(self) -> list[Path]:
        return [
            *(self.directory / name / "bin" / "python" for name in ("comfy-env", ".venv", "venv")),
            self.directory.parent / (self.directory.name + "-env") / "bin" / "python",
        ]

    def command(self) -> list[str]:
        args = shlex.split(self.arguments)
        if self.mode == "script":
            marker = ["--comfyui-control-args"] if self.managed_script else []
            return ["/bin/bash", str(expand(self.script)), *marker, *args]
        return [self.interpreter(), "-u", "main.py", *args]

    def folder(self, kind: str) -> Path:
        override = self.output_dir if kind == "output" else self.models_dir
        return expand(override) if override.strip() else self.directory / kind

    def cli_update(self) -> tuple[list[str], dict[str, str]]:
        """Resolve the CLI separately from the environment it must update."""
        python = shutil.which(self.interpreter())
        if not python:
            raise ValueError("Select a working ComfyUI Python executable before using Comfy CLI updates.")
        # Do not resolve the Python symlink: its enclosing environment matters.
        prefix = Path(python).absolute().parent.parent
        if not (prefix / "bin" / "python").is_file():
            raise ValueError("Select your ComfyUI environment's bin/python in Edit launch configuration.")
        environment = {"PATH": str(prefix / "bin") + os.pathsep + os.environ.get("PATH", "")}
        if (prefix / "pyvenv.cfg").is_file():
            environment["VIRTUAL_ENV"] = str(prefix)
        elif (prefix / "conda-meta").is_dir():
            environment["CONDA_PREFIX"] = str(prefix)
            environment["CONDA_DEFAULT_ENV"] = str(prefix)
        else:
            raise ValueError("For Comfy CLI updates, select your ComfyUI virtual environment's bin/python in Edit launch configuration.")
        if self.comfy_cli.strip():
            value = self.comfy_cli.strip()
            executable = shutil.which(str(expand(value)) if "/" in value else value)
        else:
            executable = shutil.which(str(prefix / "bin" / "comfy")) or shutil.which("comfy")
        if not executable:
            raise ValueError(
                "Comfy CLI was not found. Select its executable in Edit launch configuration, "
                f"or install it in your ComfyUI environment: {shlex.join([python, '-m', 'pip', 'install', 'comfy-cli'])}"
            )
        return [executable, "--workspace", str(self.directory), "--skip-prompt", "update"], environment

    def validate(self) -> None:
        if not self.comfy_dir.strip() or not (self.directory / "main.py").is_file():
            raise ValueError("Choose the ComfyUI folder containing main.py.")
        self.command()  # Validate argument quoting before starting anything.
        if self.mode == "script":
            if not self.script.strip() or not expand(self.script).is_file():
                raise ValueError("Choose an existing Bash launch script.")
        else:
            interpreter = self.interpreter()
            if not shutil.which(interpreter):
                raise ValueError(f"Python executable is unavailable: {interpreter}")
