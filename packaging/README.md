# Fedora RPM and COPR

This branch builds a preliminary `0.9.0.dev1` app / `0.9.0-0.1.dev1` RPM.
Build artifacts for testing only; stable COPR publishing is guarded against
development versions. See [Mobile WebUI testing](../docs/MOBILE.md).

## App ZIP download

Build the user download with Python 3.11 or newer:

```bash
python3 packaging/make_app_zip.py --outdir downloads
```

This creates a versioned ZIP and `downloads/comfyui-control.zip` containing only
the Python app and its icon, `pyproject.toml`, `install.sh`, and a short README. A project
license is included when present. Tests, screenshots, Git files, caches, and
packaging tools stay in the development repository. The main README links to
`downloads/comfyui-control.zip` on `main`; no separate download branch is needed.
After changing the app, rebuild the ZIP and commit the stable ZIP alongside the
source changes to keep the download current. The versioned copy is ignored by
Git. The same ZIP can also be uploaded as a GitHub Release asset when
release-upload access is available.

Tests remain in source RPMs so Fedora builds can run the required checks.

## Fedora packaging

The RPM uses Fedora's system Python and `python3-pyside6`, installs
`/usr/bin/comfyui-control`, and adds a desktop entry under
`/usr/share/applications`. It does not bundle ComfyUI, PyTorch, drivers, or models.
The Comfy CLI setup flow still creates a separate environment for ComfyUI.

## Build locally

On Fedora, install the build tools:

```bash
sudo dnf install python3 rpm-build dnf5-plugins
sudo dnf builddep packaging/comfyui-control.spec
python3 packaging/make_srpm.py --outdir dist
rpmbuild --rebuild dist/comfyui-control-0.9.0-0.1.dev1*.src.rpm
```

For a clean build environment, `mock` can build the generated SRPM instead.
The spec runs the existing test suite and validates the desktop entry.
The binary RPM is `noarch`, but must be built for each Fedora release because
Fedora's Python minor version and installation paths can change between releases.

Install the RPM built for your Fedora release:

```bash
sudo dnf install ./comfyui-control-0.9.0-0.1.dev1.fc44.noarch.rpm
```

The first RPM was built and installed in an isolated Fedora 44 container with
Python 3.14.8 and Fedora's PySide6 6.11.2. All 51 tests passed during the RPM
build. The installed executable and Qt controls, desktop entry validation,
`rpm -V`, and clean removal also passed using a virtual/offscreen display.
This RPM has not been validated on other Fedora releases or KDE Wayland.

Version 0.6.0 adds the saved Git/Comfy CLI update selector. Its suite has 61
tests, including CLI environment isolation, failure handling, and GUI selection.
The actual Comfy CLI was also tested through the GUI against a disposable local
checkout and requirement wheel; see the [verification notes](../docs/MAINTAINING.md#development-and-verification).

Version 0.7.0 adds an update-method dialog, aligned header controls, collapsed
launch flags, and a visible window version. All 70 tests pass, and both update
methods were exercised through the new dialog with the actual CLI.

Version 0.8.0 allows unrelated untracked files during updates, accepts environment
folders directly, and inspects existing script flags without running the script.
All 86 tests pass, including native Git conflict protection and flag preservation.

If you previously used `install.sh`, first remove its per-user app, wrapper, and
desktop entry as described in the [uninstall instructions](../docs/USAGE.md#uninstall). Both installation methods share
the same settings. Remove the RPM with `sudo dnf remove comfyui-control`.

## COPR publishing

Project: [jhakuzi/comfyui-control](https://copr.fedorainfracloud.org/coprs/jhakuzi/comfyui-control/).
The project currently targets **Fedora 44 x86_64**. The application is MIT licensed.

### First build: upload a source RPM

[Download the source RPM](https://github.com/jhakuzi/comfyui-control/raw/refs/heads/main/downloads/comfyui-control.src.rpm),
then open the project's **New Build** page, select **Upload**, and submit the
`.src.rpm` file. COPR builds and tests the binary package before publishing it.
The source RPM includes tests and the license, but excludes screenshots and the
app-download ZIP. Uploading it publishes its source even if GitHub is private.

To build a new source RPM yourself on Fedora:

```bash
sudo dnf install python3 rpm-build
python3 packaging/make_srpm.py --outdir dist
```

### Automated builds: one-time setup

The repository includes [a GitHub Actions workflow](../.github/workflows/copr.yml)
that creates downloadable source RPM/app ZIP artifacts and can submit the RPM
to COPR. This also works with a private repository.

1. Sign in to [COPR's API page](https://copr.fedorainfracloud.org/api/).
2. In [GitHub Actions secrets](https://github.com/jhakuzi/comfyui-control/settings/secrets/actions),
   add **COPR_LOGIN** from the API configuration's `login` field and
   **COPR_TOKEN** from its `token` field. The Fedora username is already set to
   `jhakuzi` in the workflow. Do not paste credentials into issues or commits.
3. Open **Actions → Build and publish to COPR → Run workflow**, select `main`,
   check **Submit the source RPM**, and run it. Leave the checkbox off to only
   generate downloadable artifacts without COPR credentials.

The workflow waits for COPR and reports a failed build as a failed run.
Artifacts are available from the run page for 30 days. COPR retains the published
packages independently of GitHub artifact retention.

For later releases, update the app version in `pyproject.toml` and
`comfyui_control/__init__.py`, update the RPM spec's `Version` and changelog,
reset `Release` to `1`, and rebuild the app ZIP on `main`. Then push a matching
version tag, for example:

```bash
git tag -a v0.9.0 -m 'Release 0.9.0'
git push origin main v0.9.0
```

Tag pushes automatically build and submit to COPR; ordinary commits do not.
The existing `v0.8.0` tag predates this workflow: use the manual run for the first
build. For packaging-only changes, keep the app version, increment the spec's
`Release`, and use a manual publishing run. Do not move existing release tags.

### Install after the first successful build

```bash
sudo dnf copr enable jhakuzi/comfyui-control
sudo dnf install comfyui-control
```

Future app updates arrive through `sudo dnf upgrade`. The app's **Update ComfyUI**
button updates ComfyUI itself.

An alternative to Actions is COPR's Git/SCM **make srpm** method using
`.copr/Makefile` and a GitHub webhook. That requires COPR to be able to clone the
repository; the Actions upload route does not.
