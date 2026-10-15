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


@pytest.fixture
def mobile_graph():
    return {
        "arbitrary-text": {"class_type": "CustomText", "inputs": {"sentence": "old", "hidden": {"keep": True}}},
        "quantized": {"class_type": "GGUFLoaderWhatever", "inputs": {"file": "model.gguf"}},
        "lora-a": {"class_type": "CustomLoRA", "inputs": {"model": ["quantized", 0], "power": 0.7, "clip_power": 0.9}},
        "lora-b": {"class_type": "AnotherLoRA", "inputs": {"model": ["lora-a", 0], "power": 0.4}},
        "sampler": {"class_type": "UnknownSampler", "inputs": {"conditioning": ["arbitrary-text", 0], "iterations": 8, "noise": 123}},
    }
