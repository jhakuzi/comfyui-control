Name:           comfyui-control
Version:        0.9.0
Release:        0.3.dev3%{?dist}
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
