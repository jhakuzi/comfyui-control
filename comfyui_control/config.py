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
    comfy_dir: str = "/mnt/Ironforge/ComfyUI"
    python: str = ""
    mode: str = "python"
    script: str = ""
    arguments: str = ""
    output_dir: str = ""
    models_dir: str = ""
    install_requirements: bool = False
    managed_script: bool = False

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
        return expand(self.comfy_dir)

    def interpreter(self) -> str:
        if self.python.strip():
            value = self.python.strip()
            if "/" in value:
                return str(expand(value))
            return shutil.which(value) or value
        for name in (".venv", "venv"):
            candidate = self.directory / name / "bin" / "python"
            if candidate.is_file():
                return str(candidate)
        return shutil.which("python3") or "python3"

    def command(self) -> list[str]:
        args = shlex.split(self.arguments)
        if self.mode == "script":
            marker = ["--comfyui-control-args"] if self.managed_script else []
            return ["/bin/bash", str(expand(self.script)), *marker, *args]
        return [self.interpreter(), "-u", "main.py", *args]

    def folder(self, kind: str) -> Path:
        override = self.output_dir if kind == "output" else self.models_dir
        return expand(override) if override.strip() else self.directory / kind

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
