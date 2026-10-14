#!/usr/bin/env python3
"""Create an offline-buildable SRPM using only the Python standard library."""

import argparse
import gzip
import io
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import tomllib


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", type=Path, default=Path("dist"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    spec = root / "packaging/comfyui-control.spec"
    spec_version = next(line.split(":", 1)[1].strip() for line in spec.read_text().splitlines() if line.startswith("Version:"))
    if version != spec_version:
        parser.error("pyproject.toml and RPM spec versions must match")
    if not shutil.which("rpmbuild"):
        parser.error("Install RPM build tools first: sudo dnf install rpm-build")
    outdir = args.outdir.resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="comfyui-control-srpm-") as temporary:
        top = Path(temporary)
        for folder in ("BUILD", "BUILDROOT", "RPMS", "SOURCES", "SPECS", "SRPMS"):
            (top / folder).mkdir()
        # Stable timestamps/ownership; omit caches and local build artifacts.
        archive = top / "SOURCES" / f"comfyui-control-{version}.tar.gz"
        files = [root / "pyproject.toml", root / "README.md"]
        if (root / "LICENSE").exists():
            files.append(root / "LICENSE")
        for directory in ("comfyui_control", "tests", "packaging"):
            files.extend(path for path in (root / directory).rglob("*") if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc")
        with archive.open("wb") as output:
            with gzip.GzipFile(filename="", fileobj=output, mode="wb", mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode="w") as tar:
                    for path in sorted(files):
                        relative = path.relative_to(root)
                        data = path.read_bytes()
                        info = tarfile.TarInfo(f"comfyui-control-{version}/{relative.as_posix()}")
                        info.size = len(data)
                        info.mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
                        tar.addfile(info, io.BytesIO(data))
        shutil.copy2(spec, top / "SPECS" / spec.name)
        (top / "SPECS" / spec.name).chmod(0o644)
        subprocess.run(["rpmbuild", "-bs", "--define", f"_topdir {top}", str(top / "SPECS" / spec.name)], check=True)
        for srpm in (top / "SRPMS").glob("*.src.rpm"):
            target = outdir / srpm.name
            shutil.copy2(srpm, target)
            print(target)


if __name__ == "__main__":
    main()
