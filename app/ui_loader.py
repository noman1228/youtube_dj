"""Load Designer forms onto the application's existing controller widgets."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Callable

from PySide6.QtCore import QFile, QIODevice
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QWidget


UI_DIRECTORY = Path(__file__).resolve().parent / "ui"


class _FormLoader(QUiLoader):
    def __init__(self, owner: QWidget, factories: dict[str, Callable]) -> None:
        super().__init__()
        self.owner = owner
        self.factories = factories
        self.objects = {}
        self.root_created = False
        self.factory_error: Exception | None = None

    def createWidget(self, class_name, parent=None, name=""):
        if not self.root_created:
            self.root_created = True
            widget = self.owner
        elif class_name in self.factories:
            try:
                widget = self.factories[class_name](parent, name)
            except Exception as error:
                self.factory_error = error
                return None
        else:
            widget = super().createWidget(class_name, parent, name)
        if widget is not None:
            widget.setObjectName(name)
            self.objects[name] = widget
        return widget

    def createLayout(self, class_name, parent=None, name=""):
        layout = super().createLayout(class_name, parent, name)
        self.objects[name] = layout
        return layout


def load_ui(owner: QWidget, filename: str, factories: dict[str, Callable] | None = None) -> SimpleNamespace:
    """Read a .ui directly, bind controller attributes, and restore theme names.

    Factories receive (parent, Designer object name), allowing custom widgets
    with required constructor arguments. Each composed widget loads its own form.
    pythonAttribute and runtimeObjectName are editable Designer dynamic properties;
    they keep the existing controller API and stylesheet selectors intact.
    """
    path = UI_DIRECTORY / filename
    source = QFile(str(path))
    if not source.open(QIODevice.OpenModeFlag.ReadOnly):
        raise OSError(f"Cannot open Designer form {path}: {source.errorString()}")
    loader = _FormLoader(owner, factories or {})
    try:
        result = loader.load(source)
    finally:
        source.close()
    if loader.factory_error is not None:
        raise RuntimeError(f"Cannot construct a custom widget in {path}") from loader.factory_error
    if result is None:
        raise RuntimeError(f"Cannot load Designer form {path}: {loader.errorString()}")
    for name, obj in loader.objects.items():
        attribute = obj.property("pythonAttribute")
        if attribute:
            setattr(owner, attribute, obj)
        elif name == "results_layout":
            owner.results_layout = obj
        runtime_name = obj.property("runtimeObjectName")
        if runtime_name:
            obj.setObjectName(runtime_name)
    # QUiLoader may polish children before their theme selector names are restored.
    for obj in loader.objects.values():
        if isinstance(obj, QWidget):
            obj.style().unpolish(obj)
            obj.style().polish(obj)
            obj.updateGeometry()
    return SimpleNamespace(**loader.objects)
