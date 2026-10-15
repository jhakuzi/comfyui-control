# Maintainer guide

[Back to the README](../README.md)

## Development and verification

Run these commands from the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e . pytest
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest
```

The suite covers desktop behaviour plus the mobile integration on this testing branch. See [mobile verification notes](MOBILE_ARCHITECTURE.md) for its scope and limitations. Real CPU installation, server controls, and update integration were verified on Fedora 44 with Python 3.14.8. CLI dependency isolation was checked with a disposable checkout and test package. GPU/ROCm, model inference, and KDE Wayland remain untested.

[Live ComfyUI server screenshot](../live-test-preview.png)

## Build and release

The [packaging and COPR guide](../packaging/README.md) contains the app ZIP and
source RPM commands, COPR credential setup, manual publishing, and version-tag
workflow. The GitHub Actions workflow builds and tests the RPM before submission.

For an app release:

1. Update the version in `pyproject.toml`, `comfyui_control/__init__.py`, and
   `packaging/comfyui-control.spec`; reset the RPM `Release` to `1` and add a changelog entry.
2. Run the checks above, rebuild `downloads/comfyui-control.zip`, and refresh the
   source RPM download using the packaging guide.
3. Commit the source and downloads to `main`, then push a matching version tag.
   The tag triggers COPR publishing. Do not move an existing tag.
4. Check the [Actions run](https://github.com/jhakuzi/comfyui-control/actions/workflows/copr.yml)
   and [COPR build](https://copr.fedorainfracloud.org/coprs/jhakuzi/comfyui-control/).

For documentation-only changes, update the guides and commit to `main` without
creating a release tag. If `packaging/APP_README.md` changes, rebuild the app ZIP
to keep its included instructions current.

The full repository keeps tests and screenshots for development. The app ZIP
includes only runtime files, the optimized icon, installer, license, and short
instructions. GitHub's **Code → Download ZIP** includes the full repository.
