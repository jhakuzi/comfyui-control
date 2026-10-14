import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def app():
    instance = QApplication.instance() or QApplication([])
    return instance


@pytest.fixture(autouse=True)
def dispose_widgets(app):
    yield
    # Dispose C++ widgets while QApplication and Python callbacks are alive.
    # A closed QWidget is otherwise retained by Python signal reference cycles.
    for widget in app.topLevelWidgets():
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
