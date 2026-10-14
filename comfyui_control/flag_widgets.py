"""Reusable checkbox selector for launch settings and script creation."""
import shlex

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QScrollArea,
    QVBoxLayout, QWidget,
)

from .flags import HIP_PRESET, available_flags, validate_groups


class LaunchFlags(QWidget):
    def __init__(self, directory, arguments="", parent=None):
        super().__init__(parent)
        self.flags, local, reserve_available = available_flags(directory)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Flags from your ComfyUI installation" if local else "Common flags (local CLI definitions unavailable)"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search flags…")
        layout.addWidget(self.search)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setMinimumHeight(130)
        area.setMaximumHeight(180)
        content = QWidget()
        self.grid = QGridLayout(content)
        self.checkboxes = {}
        for index, flag in enumerate(self.flags):
            checkbox = QCheckBox(flag.name)
            checkbox.setToolTip(flag.help)
            self.grid.addWidget(checkbox, index // 2, index % 2)
            self.checkboxes[flag.name] = checkbox
        self.grid.setRowStretch((len(self.flags) + 1) // 2, 1)
        area.setWidget(content)
        layout.addWidget(area)
        reserve_row = QHBoxLayout()
        self.reserve = QCheckBox("Reserve VRAM (--reserve-vram)")
        self.reserve.setEnabled(reserve_available)
        self.reserve_value = QDoubleSpinBox()
        self.reserve_value.setRange(0, 1024)
        self.reserve_value.setDecimals(2)
        self.reserve_value.setValue(1)
        self.reserve_value.setSuffix(" GB")
        self.reserve_value.setEnabled(False)
        self.reserve.toggled.connect(self.reserve_value.setEnabled)
        reserve_row.addWidget(self.reserve)
        reserve_row.addWidget(self.reserve_value)
        reserve_row.addStretch()
        layout.addLayout(reserve_row)
        layout.addWidget(QLabel("Other arguments"))
        self.extra_arguments = QPlainTextEdit()
        self.extra_arguments.setPlaceholderText('--listen 127.0.0.1 --port 8188\nQuote paths containing spaces.')
        self.extra_arguments.setMaximumHeight(70)
        layout.addWidget(self.extra_arguments)
        self._load(arguments)
        for flag in self.flags:
            self.checkboxes[flag.name].toggled.connect(lambda checked, item=flag: self._toggle(item, checked))
        self.search.textChanged.connect(self._filter)

    def _load(self, arguments):
        try:
            tokens = shlex.split(arguments)
        except ValueError:
            self.extra_arguments.setPlainText(arguments)
            return
        extras = []
        index = 0
        recognized = False
        while index < len(tokens):
            token = tokens[index]
            if token in self.checkboxes:
                self.checkboxes[token].setChecked(True)
                recognized = True
            elif self.reserve.isEnabled() and (token == "--reserve-vram" or token.startswith("--reserve-vram=")):
                value = token.partition("=")[2] if "=" in token else tokens[index + 1] if index + 1 < len(tokens) else ""
                try:
                    number = float(value)
                    if not 0 <= number <= 1024:
                        raise ValueError()
                except ValueError:
                    extras.append(token)
                else:
                    self.reserve.setChecked(True)
                    self.reserve_value.setValue(number)
                    recognized = True
                    if "=" not in token:
                        index += 1
            else:
                extras.append(token)
            index += 1
        self.extra_arguments.setPlainText(shlex.join(extras) if recognized else arguments)

    def _toggle(self, flag, checked):
        if checked and flag.group:
            for other in self.flags:
                if other.group == flag.group and other.name != flag.name:
                    self.checkboxes[other.name].setChecked(False)

    def _filter(self, query):
        query = query.casefold()
        visible = [flag for flag in self.flags if query in (flag.name + " " + flag.help).casefold()]
        for flag in self.flags:
            self.checkboxes[flag.name].setVisible(flag in visible)
        for index, flag in enumerate(visible):
            self.grid.addWidget(self.checkboxes[flag.name], index // 2, index % 2)

    def argument_string(self):
        selected = [flag.name for flag in self.flags if self.checkboxes[flag.name].isChecked()]
        if self.reserve.isChecked():
            selected.extend(["--reserve-vram", format(self.reserve_value.value(), "g")])
        extra = self.extra_arguments.toPlainText().strip()
        validate_groups(selected + shlex.split(extra), self.flags)
        return " ".join(part for part in (shlex.join(selected), extra) if part)


class LaunchScriptDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create launch script — choose flags")
        self.resize(660, 460)
        layout = QVBoxLayout(self)
        explanation = QLabel("Use the selected Python environment, set the HIP allocator, and launch with these flags:")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.options = LaunchFlags(config.directory, config.arguments or shlex.join(HIP_PRESET))
        layout.addWidget(self.options)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Choose script file…")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _accept(self):
        try:
            self.options.argument_string()
        except ValueError as exc:
            QMessageBox.warning(self, "Check launch flags", str(exc))
            return
        self.accept()
