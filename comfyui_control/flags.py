"""Read boolean CLI flags without importing or executing ComfyUI code."""
import ast
from dataclasses import dataclass
from pathlib import Path


HIP_PRESET = ["--use-pytorch-cross-attention", "--disable-smart-memory", "--reserve-vram", "1"]


@dataclass(frozen=True)
class Flag:
    name: str
    help: str = ""
    group: str = ""


COMMON_FLAGS = [
    Flag("--disable-smart-memory", "Offload models more aggressively instead of keeping them in VRAM."),
    Flag("--use-pytorch-cross-attention", "Use PyTorch cross attention.", "attention"),
    Flag("--use-split-cross-attention", "Use split cross attention.", "attention"),
    Flag("--use-quad-cross-attention", "Use sub-quadratic cross attention.", "attention"),
    Flag("--disable-xformers", "Disable xFormers."),
    Flag("--gpu-only", "Keep models on the GPU.", "vram"),
    Flag("--highvram", "Keep models loaded in GPU memory.", "vram"),
    Flag("--normalvram", "Use normal VRAM management.", "vram"),
    Flag("--lowvram", "Reduce VRAM usage.", "vram"),
    Flag("--novram", "Use minimal VRAM.", "vram"),
    Flag("--cpu", "Use the CPU.", "vram"),
    Flag("--force-fp32", "Force 32-bit floating point.", "precision"),
    Flag("--force-fp16", "Force 16-bit floating point.", "precision"),
    Flag("--cpu-vae", "Run the VAE on the CPU."),
    Flag("--disable-metadata", "Do not save workflow metadata in images."),
    Flag("--disable-all-custom-nodes", "Disable all custom nodes."),
]


def literal(node, default=None):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError):
        return default


def available_flags(directory: Path) -> tuple[list[Flag], bool, bool]:
    """Return flags, whether read locally, and whether reserve-vram exists."""
    try:
        tree = ast.parse((directory / "comfy" / "cli_args.py").read_text(encoding="utf-8"))
    except (OSError, SyntaxError, ValueError):
        return COMMON_FLAGS.copy(), False, True
    groups = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            method = node.value.func
            if isinstance(method, ast.Attribute) and method.attr == "add_mutually_exclusive_group":
                groups.update(target.id for target in node.targets if isinstance(target, ast.Name))
    found, reserve = {}, False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr != "add_argument":
            continue
        names = [literal(arg) for arg in node.args]
        names = [name for name in names if isinstance(name, str) and name.startswith("--")]
        reserve = reserve or "--reserve-vram" in names
        kwargs = {item.arg: literal(item.value) for item in node.keywords}
        if not names or kwargs.get("action") not in ("store_true", "store_false"):
            continue
        receiver = node.func.value
        group = receiver.id if isinstance(receiver, ast.Name) and receiver.id in groups else ""
        name = names[0]
        found[name] = Flag(name, str(kwargs.get("help") or ""), group)
    if not found:
        return COMMON_FLAGS.copy(), False, True
    return list(found.values()), True, reserve


def validate_groups(arguments: list[str], flags: list[Flag]) -> None:
    selected = set(arguments)
    groups = {}
    for flag in flags:
        if flag.group and flag.name in selected:
            groups.setdefault(flag.group, []).append(flag.name)
    for names in groups.values():
        if len(names) > 1:
            raise ValueError("Choose only one of: " + ", ".join(names))
