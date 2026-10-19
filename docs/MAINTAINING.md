# Maintainer guide

[Back to the README](../README.md)

## Development and verification

Run these commands from the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e . pytest
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest
```

The `1.0.0rc1` suite has 337 automated tests covering desktop behaviour, appearance, hardware/timing, recovery, workflow imports, prompt history and gallery metadata. The feature browser check passed in Chromium and Linux WebKit at phone/tablet widths, including app restarts and simulated connection loss. This is not a physical iPhone Safari or VPN test. See [mobile verification notes](MOBILE_ARCHITECTURE.md) and the [feature guide](FEATURES.md) for scope and limitations. Real CPU installation, server controls, and update integration were verified on Fedora 44 with Python 3.14.8. CLI dependency isolation was checked with a disposable checkout and test package. These automated checks do not validate GPU inference or native KDE Wayland.
The user has separately confirmed NFS setup/removal, mobile gallery access and
recovery after connection loss on their actual installation.

Uninstaller coverage uses disposable user homes and fixture packages. It checks
the real installer/standalone script, legacy and current shortcut ownership,
pip-only removal, mounted/symlink/shared-folder guards, confirmation/cancellation,
folder identity changes and desktop server/child/WebUI shutdown before deletion.
The per-user subprocess cases intentionally skip root-only RPM runners; refusal
to uninstall as root is checked separately. A disposable full Qt environment
also completed self-removal and displayed its real success dialog after the
environment was deleted. No real user ComfyUI/NAS data is used.

[Current Fedora desktop screenshot](screenshots/desktop-0.10.2.png)

Screenshots live in `docs/screenshots/`. Use a versioned filename when replacing
one so GitHub refreshes the image. Keep example workflows and simulated progress
labeled; screenshots stay out of the app ZIP and source RPM.

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
5. For GitHub release assets, create a release draft for the tag, then run
   **Publish release downloads** from `main` with that tag and the successful
   build run ID. It attaches the verified packages and publishes the draft.

For release candidates, use Python `1.0.0rc1`, RPM `1.0.0~rc1-1`, and tag
`v1.0.0rc1`. The workflows permit RC COPR builds and publish GitHub prereleases
without replacing the latest stable release. `.dev` builds remain blocked.

For documentation-only changes, update the guides and commit to `main` without
creating a release tag. If `packaging/APP_README.md` changes, rebuild the app ZIP
to keep its included instructions current.

The full repository keeps tests and screenshots for development. The app ZIP
includes only runtime files, the optimized icon, installer, license, and short
instructions. GitHub's **Code → Download ZIP** includes the full repository.
