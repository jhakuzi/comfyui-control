Name:           comfyui-control
Version:        1.0.0~rc2
Release:        0.2.dev2%{?dist}
Summary:        A compact Qt controller for a local ComfyUI installation

License:        MIT
URL:            https://github.com/jhakuzi/comfyui-control
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  python3-devel
BuildRequires:  python3-pip
BuildRequires:  pyproject-rpm-macros
BuildRequires:  python3-setuptools
BuildRequires:  python3-wheel
BuildRequires:  python3-pyside6 >= 6.7
BuildRequires:  python3-pytest
BuildRequires:  python3-aiohttp >= 3.10
BuildRequires:  python3-qrcode >= 7.4
BuildRequires:  desktop-file-utils
BuildRequires:  git-core
Requires:       python3-pyside6 >= 6.7
Requires:       python3-pip
Requires:       git-core
Requires:       /bin/bash
Requires:       hicolor-icon-theme
Requires:       python3-aiohttp >= 3.10
Requires:       python3-qrcode >= 7.4
Recommends:     konsole

%description
A native Qt window with live ComfyUI server output, start, stop, restart,
and update controls, folder shortcuts, launch flag selection, and guided
Comfy CLI setup. ComfyUI, its models, and GPU drivers are installed separately.

%prep
%autosetup
# Fedora supplies the complete PySide6 distribution rather than the PyPI-only
# PySide6-Essentials wheel. Keep matching installed Python metadata in the RPM.
sed -i 's/PySide6-Essentials/PySide6/' pyproject.toml

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files comfyui_control
desktop-file-install --dir=%{buildroot}%{_datadir}/applications packaging/%{name}.desktop
install -Dpm 0644 comfyui_control/assets/comfyui-control.png %{buildroot}%{_datadir}/icons/hicolor/256x256/apps/%{name}.png
install -Dpm 0644 packaging/README.md %{buildroot}%{_docdir}/%{name}/RPM.md

%check
QT_QPA_PLATFORM=offscreen %pytest
desktop-file-validate %{buildroot}%{_datadir}/applications/%{name}.desktop

%files -f %{pyproject_files}
%license LICENSE
%doc README.md docs
%doc %{_docdir}/%{name}/RPM.md
%{_bindir}/%{name}
%{_datadir}/applications/%{name}.desktop
%{_datadir}/icons/hicolor/256x256/apps/%{name}.png

%changelog
* Mon Oct 19 2026 ComfyUI Control contributors - 1.0.0~rc2-0.2.dev2
- Testing: responsive tablet/laptop Mobile WebUI with pinned preview and controls.
- Expand gallery and comparison layouts while preserving phone behavior.

* Mon Oct 19 2026 ComfyUI Control contributors - 1.0.0~rc2-0.1.dev1
- Testing: foreground SSH startup for configured ComfyUI and Mobile WebUI.
- Reuse process ownership, signal shutdown, NFS selection and hardware workers.

* Sun Oct 18 2026 ComfyUI Control contributors - 1.0.0~rc1-2
- Keep mount-content checks active in COPR without requiring a writable /run/systemd.
- Run native systemd validation separately where the runtime directory is available.

* Sun Oct 18 2026 ComfyUI Control contributors - 1.0.0~rc1-1
- First 1.0 release candidate: tray lifecycle and remembered close behavior.
- Expandable mobile prompt editor and integrated NFS output with local fallback.
- App-triggered mounts, scoped start permission and guarded removal/migration.
- Safe launch-script updates, clearer setup and local crash timestamps.

* Sun Oct 18 2026 ComfyUI Control contributors - 0.11.2-0.10.dev10
- Start NFS only from the app; migrate and remove the old boot-enabled automount.
- Grant only the setup user permission to start the specific static mount unit.

* Sun Oct 18 2026 ComfyUI Control contributors - 0.11.2-0.9.dev9
- Trigger NFS automount by opening the directory before checking the filesystem.
- Add authorized removal of exact managed mount units, refusing foreign or nested mounts.

* Sun Oct 18 2026 ComfyUI Control contributors - 0.11.2-0.8.dev8
- Testing: put mount setup in Settings and enlarge the dialog to fit the screen.
- Remember close choices and allow changing the X button action in Settings.

* Sun Oct 18 2026 ComfyUI Control contributors - 0.11.2-0.7.dev7
- Testing: repair simple output launch scripts with backups and actionable diagnostics.
- Apply the regular output-folder selection to the actual ComfyUI save destination.
- Display crash diagnostics in the system timezone, including daylight saving time.

* Sun Oct 18 2026 ComfyUI Control contributors - 0.11.2-0.6.dev6
- Testing: remove trailing ellipses from desktop and mobile button labels.

* Sun Oct 18 2026 ComfyUI Control contributors - 0.11.2-0.5.dev5
- Testing: detect missing NFS tools and offer a distro-specific terminal installer.

* Sun Oct 18 2026 ComfyUI Control contributors - 0.11.2-0.4.dev4
- Testing: persistent desktop/mobile mount errors and manual-upload fallback warnings.
- Keep the mobile gallery on the selected local fallback destination.

* Sun Oct 18 2026 ComfyUI Control contributors - 0.11.2-0.3.dev3
- Testing: optional NFS output with authorized automount setup and local fallback.
- Isolate network filesystem access and pin output selection to each server run.

* Sun Oct 18 2026 ComfyUI Control contributors - 0.11.2-0.2.dev2
- Testing: add a tray icon, close-window choices, restore action and graceful tray quit.

* Sat Oct 17 2026 ComfyUI Control contributors - 0.11.2-0.1.dev1
- Testing: double the mobile prompt editor height and add a saved expand/collapse control.

* Sat Oct 17 2026 ComfyUI Control contributors - 0.11.1-1
- Keep comparison Close and gallery selection controls reachable on iPhone.
- Synchronize deleted/replaced output files and preserve unchanged thumbnails.

* Sat Oct 17 2026 ComfyUI Control contributors - 0.11.1-0.2.dev2
- Testing: keep gallery comparison controls reachable while scrolling on iPhone.
- Reconcile deleted/replaced output files without reloading unchanged thumbnails.

* Sat Oct 17 2026 ComfyUI Control contributors - 0.11.1-0.1.dev1
- Testing: respect iPhone safe areas and keep comparison Close reachable while scrolling.

* Sat Oct 17 2026 ComfyUI Control contributors - 0.11.0-1
- Release mobile sampling/GPU metrics, private prompt history and image details.
- Cache selected comparison images in memory and handle typed LoRA bypass chains.
- Consolidate desktop Settings, add the Qt style picker and show the ComfyUI version.
- Refresh randomized seed defaults while preserving fixed-seed reuse and recovery.

* Sat Oct 17 2026 ComfyUI Control contributors - 0.11.0-0.1.dev1
- Testing: shared mobile generation metrics, private prompt history and favorites.
- Add image details with PNG metadata and persistent image ownership protection.

* Fri Oct 16 2026 ComfyUI Control contributors - 0.10.2-1
- Enlarge the main window and keep crash diagnostics aligned in the header.
- Compact mobile settings and show a shutdown completion message.

* Fri Oct 16 2026 ComfyUI Control contributors - 0.10.1-2
- Make the telemetry delivery check independent of concurrent disconnect events.

* Fri Oct 16 2026 ComfyUI Control contributors - 0.10.1-1
- Left-align monitoring and prevent wrapped/scaled metrics from overlapping the log.
- Remove GPU power readings and show only Current/Average generation speed.

* Fri Oct 16 2026 ComfyUI Control contributors - 0.10.0-1
- Release hardware/sampling monitoring, mobile image comparison and optional crash recovery.
- Show mobile preparation activity and default to randomized generation seeds.

* Fri Oct 16 2026 ComfyUI Control contributors - 0.10.0-0.2.dev2
- Show indeterminate preparation/loading progress before sampling and between stages.
- Default mobile generations to randomized seeds; preserve explicit fixed-seed reuse.

* Fri Oct 16 2026 ComfyUI Control contributors - 0.10.0-0.1.dev1
- Testing build: collapsible hardware/sampling monitor and mobile image comparison.
- Add private bounded crash diagnostics and optional recovery with capped backoff.

* Fri Oct 16 2026 ComfyUI Control contributors - 0.9.0-1
- Release integrated Mobile WebUI with workflow mapping, model controls, gallery and session recovery.
- Keep live progress and previews anchored above Generate while browsing.

* Fri Oct 16 2026 ComfyUI Control contributors - 0.9.0-0.6.dev6
- Show GGUF diffusion choices beside VAE and text encoder, including Advanced mappings.
- Discover GGUF filename combos from loader metadata without guessing node classes.

* Fri Oct 16 2026 ComfyUI Control contributors - 0.9.0-0.5.dev5
- Restore missing diffusion model controls in older mobile presets and custom loaders.
- Refresh model choices without losing prompt edits or changing saved workflow graphs.

* Fri Oct 16 2026 ComfyUI Control contributors - 0.9.0-0.4.dev4
- Discover local saved workflows in the default picker and simplify the mobile dialog.
- Preserve unused nodes without requiring inputs outside executable output branches.

* Fri Oct 16 2026 ComfyUI Control contributors - 0.9.0-0.3.dev3
- Auto LAN addressing, optional authentication, saved/default workflows and model/sampler/resolution controls.

* Thu Oct 15 2026 ComfyUI Control contributors - 0.9.0-0.2.dev2
- Restore mobile sessions on foreground/network recovery; isolate browser jobs.

* Thu Oct 15 2026 ComfyUI Control contributors - 0.9.0-0.1.dev1
- Preliminary integrated Mobile WebUI with explicit API workflow mapping.

* Thu Oct 15 2026 ComfyUI Control contributors - 0.8.1-1
- Add the application icon to Qt, desktop launchers, and both installation methods.

* Thu Oct 15 2026 ComfyUI Control contributors - 0.8.0-3
- Declare pip as a build dependency for clean Fedora and COPR builds.

* Thu Oct 15 2026 ComfyUI Control contributors - 0.8.0-2
- License the application under MIT and prepare automated COPR submissions.

* Thu Oct 15 2026 ComfyUI Control contributors - 0.8.0-1
- Allow unrelated untracked files during updates and select venv folders directly.
- Inspect existing launch scripts and show baked-in flags without duplicating them.

* Thu Oct 15 2026 ComfyUI Control contributors - 0.7.0-1
- Add update-method confirmation, align header controls, and collapse launch flags.

* Wed Oct 14 2026 ComfyUI Control contributors - 0.6.0-1
- Add Comfy CLI update selection with explicit workspace and environment.

* Wed Oct 14 2026 ComfyUI Control contributors - 0.5.0-1
- Add Fedora packaging and COPR source RPM preparation.
