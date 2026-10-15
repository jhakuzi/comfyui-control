Name:           comfyui-control
Version:        0.8.0
Release:        3%{?dist}
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
BuildRequires:  desktop-file-utils
BuildRequires:  git-core
Requires:       python3-pyside6 >= 6.7
Requires:       python3-pip
Requires:       git-core
Requires:       /bin/bash
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
install -Dpm 0644 packaging/README.md %{buildroot}%{_docdir}/%{name}/RPM.md

%check
QT_QPA_PLATFORM=offscreen %pytest
desktop-file-validate %{buildroot}%{_datadir}/applications/%{name}.desktop

%files -f %{pyproject_files}
%license LICENSE
%doc README.md
%doc %{_docdir}/%{name}/RPM.md
%{_bindir}/%{name}
%{_datadir}/applications/%{name}.desktop

%changelog
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
