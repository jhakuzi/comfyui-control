#!/usr/bin/env python3
"""Build the user download without development files or screenshots (Python 3.11+)."""
import argparse
from pathlib import Path
import shutil
import stat
import tomllib
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", type=Path, default=Path("dist"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    files = {
        "install.sh": root / "install.sh",
        "pyproject.toml": root / "pyproject.toml",
        "README.md": root / "packaging/APP_README.md",
    }
    if (root / "LICENSE").is_file():
        files["LICENSE"] = root / "LICENSE"
    for path in (root / "comfyui_control").rglob("*.py"):
        if "__pycache__" not in path.parts:
            files[path.relative_to(root).as_posix()] = path
    for path in (root / "comfyui_control/assets").glob("*.png"):
        files[path.relative_to(root).as_posix()] = path
    for path in (root / "comfyui_control/mobile/web").glob("*"):
        if path.is_file():
            files[path.relative_to(root).as_posix()] = path
    args.outdir.mkdir(parents=True, exist_ok=True)
    archive = args.outdir / f"comfyui-control-{version}.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output:
        for relative, source in sorted(files.items()):
            info = zipfile.ZipInfo(f"comfyui-control/{relative}", date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | (0o755 if relative == "install.sh" else 0o644)) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            output.writestr(info, source.read_bytes())
    # A stable filename keeps the README's app-download link valid.
    stable = args.outdir / "comfyui-control.zip"
    shutil.copyfile(archive, stable)
    print(f"{archive} ({archive.stat().st_size:,} bytes, {len(files)} files)")
    print(stable)


if __name__ == "__main__":
    main()
