"""Configuration and commands, without shell interpolation."""
from dataclasses import asdict, dataclass, field, fields
import ast
import json
import os
from pathlib import Path
import shlex
import shutil
import tempfile
try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 still reads comfyui_version.py.
    tomllib = None


def config_path() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "comfyui-control" / "config.json"


def expand(value: str) -> Path:
    return Path(os.path.expandvars(value)).expanduser().absolute()


class OutputScriptError(ValueError):
    """An output setting is valid, but the selected script needs an update."""
    def __init__(self, summary, reason, script):
        self.summary, self.reason, self.script = summary, reason, script
        super().__init__(summary + '\n\n' + reason + '\n\nScript: ' + str(script))


def installed_version(directory: Path) -> str:
    """Read ComfyUI's version metadata without importing or executing its code."""
    def small_text(name):
        with (directory / name).open('rb') as stream:
            data = stream.read(65537)
        if len(data) > 65536:
            raise ValueError('Version metadata is too large.')
        return data.decode('utf-8-sig')

    try:
        tree = ast.parse(small_text('comfyui_version.py'))
        version = next((node.value.value for node in tree.body
                        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
                        and any(isinstance(target, ast.Name) and target.id == '__version__' for target in node.targets)), '')
    except (OSError, ValueError, SyntaxError, RecursionError):
        version = ''
    if tomllib is not None and (not isinstance(version, str) or not version):
        try:
            version = tomllib.loads(small_text('pyproject.toml')).get('project', {}).get('version', '')
        except (OSError, ValueError, TypeError, AttributeError):
            version = ''
    return version if isinstance(version, str) and 0 < len(version) <= 64 and all(c.isascii() and (c.isalnum() or c in '.+-_') for c in version) else ''


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
    monitoring_enabled: bool = True
    monitor_expanded: bool = False
    auto_restart: bool = False
    restart_limit: int = 3
    restart_backoff: int = 2
    application_style: str = ""
    close_behavior: str = 'ask'
    nfs_enabled: bool = False
    nfs_server: str = ""
    nfs_export: str = ""
    nfs_auto_connect: bool = True
    session_output_dir: str = field(default='', metadata={'runtime': True})
    session_network_output: bool = field(default=False, metadata={'runtime': True})

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or config_path()
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Configuration must be a JSON object.")
        accepted = {f.name for f in fields(cls) if not f.metadata.get('runtime')}
        data = {k: v for k, v in data.items() if k in accepted}
        for key, value in data.items():
            expected = bool if key in ("install_requirements", "managed_script", "monitoring_enabled", "monitor_expanded", "auto_restart", "nfs_enabled", "nfs_auto_connect") else int if key in ("restart_limit", "restart_backoff") else str
            if type(value) is not expected:
                raise ValueError(f"Invalid value for {key}.")
        if data.get("mode", "python") not in ("python", "script"):
            raise ValueError("Unknown launch mode.")
        if data.get("update_method", "git") not in ("git", "cli"):
            raise ValueError("Unknown update method.")
        if data.get('close_behavior', 'ask') not in ('ask', 'tray', 'quit'):
            raise ValueError('Unknown close button action. Choose ask, tray or quit.')
        if not 1 <= data.get('restart_limit', 3) <= 20 or not 1 <= data.get('restart_backoff', 2) <= 60:
            raise ValueError('Recovery requires 1–20 attempts and a 1–60 second initial delay.')
        result = cls(**data)
        if result.nfs_enabled:
            from .network_output import specification
            specification(result.nfs_server, result.nfs_export)
        return result

    def save(self, path: Path | None = None) -> None:
        path = path or config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".config-", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                values = asdict(self)
                for item in fields(self):
                    if item.metadata.get('runtime'):
                        values.pop(item.name, None)
                json.dump(values, stream, indent=2)
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
            candidate = expand(value)
            if candidate.is_dir():
                return str(candidate / "bin" / "python")
            if "/" in value:
                return str(candidate)
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
        if self.routes_output:
            # Replace only the output option; preserve all other launch flags.
            filtered, index = [], 0
            while index < len(args):
                if args[index] == '--output-directory':
                    if index + 1 >= len(args) or args[index + 1].startswith('--'):
                        raise ValueError('--output-directory needs a folder.')
                    index += 2
                elif args[index].startswith('--output-directory='):
                    index += 1
                else:
                    filtered.append(args[index]); index += 1
            args = [*filtered, '--output-directory', str(self.folder('output'))]
        if self.mode == "script":
            marker = ["--comfyui-control-args"] if self.managed_script else []
            return ["/bin/bash", str(expand(self.script)), *marker, *args]
        return [self.interpreter(), "-u", "main.py", *args]

    @property
    def routes_output(self):
        return self.nfs_enabled or bool(self.output_dir.strip())

    def folder(self, kind: str) -> Path:
        if kind == 'output' and self.nfs_enabled:
            return expand(self.session_output_dir) if self.session_output_dir else self.directory / 'output'
        override = self.output_dir if kind == "output" else self.models_dir
        return expand(override) if override.strip() else self.directory / kind

    def cli_update(self) -> tuple[list[str], dict[str, str]]:
        """Resolve the CLI separately from the environment it must update."""
        python = shutil.which(self.interpreter())
        if not python:
            raise ValueError(f"Python is unavailable: {self.interpreter()}. Choose your ComfyUI environment folder (such as comfy-env), or its bin/python.")
        # Do not resolve the Python symlink: its enclosing environment matters.
        prefix = Path(python).absolute().parent.parent
        if not (prefix / "bin" / "python").is_file():
            raise ValueError(f"Cannot identify an environment for {python}. Use Choose environment to select your ComfyUI environment folder, or enter its bin/python.")
        environment = {"PATH": str(prefix / "bin") + os.pathsep + os.environ.get("PATH", "")}
        if (prefix / "conda-meta").is_dir():
            environment["CONDA_PREFIX"] = str(prefix)
            environment["CONDA_DEFAULT_ENV"] = str(prefix)
        elif (prefix / "pyvenv.cfg").is_file() or (prefix / "bin" / "activate").is_file():
            environment["VIRTUAL_ENV"] = str(prefix)
        else:
            raise ValueError(f"The selected Python ({python}) does not identify a ComfyUI environment. Use Choose environment to select the comfy-env folder, or enter that environment's bin/python without resolving its symlink.")
        if self.comfy_cli.strip():
            value = self.comfy_cli.strip()
            executable = shutil.which(str(expand(value)) if "/" in value else value)
        else:
            executable = shutil.which(str(prefix / "bin" / "comfy")) or shutil.which("comfy")
        if not executable:
            raise ValueError(
                "Comfy CLI was not found. Select its executable in Settings, "
                f"or install it in your ComfyUI environment: {shlex.join([python, '-m', 'pip', 'install', 'comfy-cli'])}"
            )
        return [executable, "--workspace", str(self.directory), "--skip-prompt", "update"], environment

    def validate(self) -> None:
        if not self.comfy_dir.strip() or not (self.directory / "main.py").is_file():
            raise ValueError("Choose the ComfyUI folder containing main.py.")
        self.command()  # Validate argument quoting before starting anything.
        if self.nfs_enabled:
            from .network_output import specification
            specification(self.nfs_server, self.nfs_export)
        if self.mode == "script":
            if not self.script.strip() or not expand(self.script).is_file():
                raise ValueError("Choose an existing Bash launch script.")
            if self.routes_output and not self.managed_script:
                from .script_flags import inspect_script
                flags = inspect_script(expand(self.script))
                if not flags.recognized:
                    raise OutputScriptError('The app cannot identify how this script starts ComfyUI.',
                        flags.message + '\nThe selected output folder cannot be applied safely. '
                        'Open Settings and save to review the script, or choose Python — launch main.py with your ComfyUI environment.', expand(self.script))
                if any(arg == '--output-directory' or arg.startswith('--output-directory=') for arg in flags.arguments):
                    raise OutputScriptError('The launch script hardcodes a different output folder.',
                        'Its --output-directory option conflicts with the folder selected in the app. '
                        'Open Settings and save: the app can remove that option from a simple script, keep a backup and supply the chosen folder at launch.', expand(self.script))
                if not flags.forwards_arguments:
                    raise OutputScriptError('The launch script does not accept the app’s output folder.',
                        'It starts main.py without forwarding "$@" (the arguments supplied by the app), so --output-directory would be ignored. '
                        'Open Settings and save: the app can add argument forwarding to a simple script and keep a backup. '
                        'Your Python environment and existing launch flags are preserved.', expand(self.script))
        else:
            interpreter = self.interpreter()
            if not shutil.which(interpreter):
                raise ValueError(f"Python executable is unavailable: {interpreter}")
