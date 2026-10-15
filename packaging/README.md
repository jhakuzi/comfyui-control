# Fedora RPM and COPR

## App ZIP download

Build the user download with Python 3.11 or newer:

```bash
python3 packaging/make_app_zip.py --outdir dist
```

This creates a versioned ZIP and `dist/comfyui-control.zip` containing only
the Python app, `pyproject.toml`, `install.sh`, and a short README. A project
license is included when present. Tests, screenshots, Git files, caches, and
packaging tools stay in the development repository. The main README links to
`comfyui-control.zip` on the separate `downloads` branch. After building a new
version, replace that branch's ZIP and push it to update the download. The same
ZIP can also be uploaded as a GitHub Release asset when release-upload access
is available.

Tests remain in source RPMs so Fedora builds can run the required checks.

## Fedora packaging

The RPM uses Fedora's system Python and `python3-pyside6`, installs
`/usr/bin/comfyui-control`, and adds a desktop entry under
`/usr/share/applications`. It does not bundle ComfyUI, PyTorch, drivers, or models.
The Comfy CLI setup flow still creates a separate environment for ComfyUI.

## Build locally

On Fedora, install the build tools:

```bash
sudo dnf install rpm-build python3-devel pyproject-rpm-macros python3-setuptools python3-wheel python3-pyside6 python3-pytest desktop-file-utils git-core
python3 packaging/make_srpm.py --outdir dist
rpmbuild --rebuild dist/comfyui-control-0.8.0-1*.src.rpm
```

For a clean build environment, `mock` can build the generated SRPM instead.
The spec runs the existing test suite and validates the desktop entry.
The binary RPM is `noarch`, but must be built for each Fedora release because
Fedora's Python minor version and installation paths can change between releases.

Install the RPM built for your Fedora release:

```bash
sudo dnf install ./comfyui-control-0.8.0-1.fc44.noarch.rpm
```

The first RPM was built and installed in an isolated Fedora 44 container with
Python 3.14.8 and Fedora's PySide6 6.11.2. All 51 tests passed during the RPM
build. The installed executable and Qt controls, desktop entry validation,
`rpm -V`, and clean removal also passed using a virtual/offscreen display.
This RPM has not been validated on other Fedora releases or KDE Wayland.

Version 0.6.0 adds the saved Git/Comfy CLI update selector. Its suite has 61
tests, including CLI environment isolation, failure handling, and GUI selection.
The actual Comfy CLI was also tested through the GUI against a disposable local
checkout and requirement wheel, as described in the main README.

Version 0.7.0 adds an update-method dialog, aligned header controls, collapsed
launch flags, and a visible window version. All 70 tests pass, and both update
methods were exercised through the new dialog with the actual CLI.

Version 0.8.0 allows unrelated untracked files during updates, accepts environment
folders directly, and inspects existing script flags without running the script.
All 86 tests pass, including native Git conflict protection and flag preservation.

If you previously used `install.sh`, first remove its per-user app, wrapper, and
desktop entry as described in the main README. Both installation methods share
the same settings. Remove the RPM with `sudo dnf remove comfyui-control`.

## COPR preparation

COPR setup requires a Fedora account and that account's COPR API configuration.
A linked GitHub account does not grant access to COPR. Get the configuration
from https://copr.fedorainfracloud.org/api/ and save it locally as
`~/.config/copr` with permissions `0600`. Never commit or paste its secret values.

**Public publishing is pending the owner's choice of an open-source license.**
Until then, the spec uses `LicenseRef-Proprietary` for private test builds.
No live COPR project has been created by adding these files.

After choosing and adding the license, install `copr-cli`, check which Fedora
chroots are available, create the project, then upload a source RPM:

```bash
sudo dnf install copr-cli
copr-cli list-chroots
copr-cli create comfyui-control --chroot fedora-44-x86_64
copr-cli build comfyui-control dist/comfyui-control-0.8.0-1*.src.rpm
```

Select your actual Fedora release from the available chroots. Additional
architectures/releases must be built and verified before advertising support.
Uploading an SRPM works even while the GitHub repository is private; COPR's
public build will publish the source contained in it. The repository's visibility
is not changed by this packaging work.

For future SCM builds, `.copr/Makefile` supports COPR's **make srpm** method.
See the [official COPR source-build documentation](https://docs.copr.fedorainfracloud.org/user_documentation.html#scm).
Once COPR can access the source repository, select Git, its clone URL, the
desired branch/tag, and the make-srpm method. The Makefile must run from the
repository root and receives COPR's `outdir` variable. No GitHub Actions secrets
or automatic publishing workflow are installed.

Once a project exists and a build succeeds, users can install with:

```bash
sudo dnf copr enable <fedora-account>/comfyui-control
sudo dnf install comfyui-control
```

The Fedora account placeholder above is not a published repository address.
Future app versions update both `pyproject.toml` and the spec's `Version`, then
build and submit a new SRPM. Subsequent app updates arrive through `dnf upgrade`;
the app's Update button updates the selected ComfyUI checkout.
