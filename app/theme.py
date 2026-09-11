import re

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication


THEMES = {
    "Midnight": {},
    "Graphite": {
        "#0b0e14": "#191919", "#080b10": "#121212", "#111722": "#242424",
        "#0c111a": "#1c1c1c", "#1a2433": "#303030", "#1b2535": "#343434",
        "#172033": "#292929", "#253249": "#414141", "#263247": "#454545",
        "#34445f": "#505050", "#33435d": "#505050", "#29364c": "#454545",
        "#253147": "#414141", "#e8edf7": "#f0f0f0", "#8f9db2": "#b0b0b0",
    },
    "Deep Ocean": {
        "#0b0e14": "#071c22", "#080b10": "#041419", "#111722": "#0d2931",
        "#0c111a": "#092129", "#1a2433": "#163943", "#1b2535": "#193d47",
        "#172033": "#102f38", "#253249": "#24505c", "#263247": "#29505b",
        "#34445f": "#35616d", "#33435d": "#35616d", "#29364c": "#29505b",
        "#253147": "#24505c", "#e8edf7": "#e3f3f5", "#8f9db2": "#95b7bf",
    },
}
DEFAULT_APPEARANCE = {"theme": "Midnight", "left": "#00d8ff", "right": "#ff2fa7"}


def load_appearance() -> dict[str, str]:
    settings = QSettings()
    result = dict(DEFAULT_APPEARANCE)
    name = settings.value("appearance/theme", result["theme"])
    if name in THEMES:
        result["theme"] = name
    for side in ("left", "right"):
        color = QColor(str(settings.value(f"appearance/{side}", result[side])))
        if color.isValid():
            result[side] = color.name()
    return result


def apply_appearance(preferences: dict[str, str], *, save: bool = False) -> None:
    app = QApplication.instance()
    colors = dict(THEMES[preferences["theme"]])
    colors.update({
        "#00d8ff": preferences["left"], "#ff2fa7": preferences["right"],
        "#006f84": QColor(preferences["left"]).darker(220).name(),
        "#7b1552": QColor(preferences["right"]).darker(220).name(),
    })

    def recolor(style: str) -> str:
        return re.sub(r"#[0-9a-fA-F]{6}\b", lambda match: colors.get(match[0].lower(), match[0]), style)

    app.setProperty("appearance", dict(preferences))
    app.setStyleSheet(recolor(APP_STYLE))
    for widget in app.allWidgets():
        original = widget.property("originalAppearanceStyle")
        if original is None and widget.styleSheet():
            original = widget.styleSheet()
            widget.setProperty("originalAppearanceStyle", original)
        if original:
            widget.setStyleSheet(recolor(original))
        widget.update()
    if save:
        settings = QSettings()
        for key, value in preferences.items():
            settings.setValue(f"appearance/{key}", value)
        settings.sync()


APP_STYLE = r"""
QWidget {
    background: #0b0e14;
    color: #e8edf7;
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 10pt;
}
QMainWindow, QDialog { background: #080b10; }
QFrame#TopBar, QFrame#CenterConsole, QFrame#DeckFrame, QFrame#ResultCard {
    background: #111722;
    border: 1px solid #263247;
    border-radius: 14px;
}
QFrame#LeftDeck { border: 1px solid #00d8ff; }
QFrame#RightDeck { border: 1px solid #ff2fa7; }
QScrollArea#CenterControlsScroll,
QWidget#CenterControlsViewport,
QWidget#CenterControls,
QFrame#CenterConsole QLabel,
QFrame#CenterConsole QCheckBox,
QFrame#CenterConsole QSlider {
    background: transparent;
}
QFrame#KaraokeRemote {
    background: #111722;
    border: 3px solid #263247;
    border-radius: 14px;
}
QLabel#KaraokeRemoteTitle {
    background: transparent;
    font-weight: 900;
}
QFrame#KaraokeRemote[playing="true"] {
    background: #493600;
    border-color: #e6ac00;
}
QFrame#KaraokeRemote[playing="true"] QLabel#KaraokeRemoteTitle { color: #ffe768; }
QFrame#KaraokeRemote[playing="true"][flashOn="true"] {
    background: #ffcf33;
    border-color: #fff3b0;
}
QFrame#KaraokeRemote[playing="true"][flashOn="true"] QLabel#KaraokeRemoteTitle { color: #171000; }
QLabel#AppTitle {
    font-size: 22pt;
    font-weight: 800;
    letter-spacing: 2px;
    color: #ffffff;
}
QLabel#DeckBadge {
    font-size: 10pt;
    font-weight: 800;
    padding: 5px 10px;
    border-radius: 9px;
    background: #1b2535;
}
QLabel#TrackTitle { font-size: 15pt; font-weight: 750; }
QLabel#Subtle { color: #8f9db2; }
QLabel#TimeLabel { font-family: "Cascadia Mono", monospace; font-size: 11pt; }
QPushButton {
    background: #1a2433;
    border: 1px solid #33435d;
    border-radius: 9px;
    padding: 8px 12px;
    font-weight: 650;
}
QPushButton:hover { background: #253249; border-color: #60799e; }
QPushButton:pressed { background: #111722; }
QPushButton#PrimaryButton { background: #006f84; border-color: #00d8ff; }
QPushButton#HotButton { background: #7b1552; border-color: #ff2fa7; }
QPushButton#PlayButton { font-size: 13pt; min-width: 58px; min-height: 36px; }
QPushButton#MixerButton { font-size: 8pt; padding: 6px 3px; }
QPushButton[compactControl="true"] { font-size: 8pt; padding: 5px 3px; }
QLineEdit, QComboBox, QSpinBox {
    background: #0c111a;
    border: 1px solid #34445f;
    border-radius: 9px;
    padding: 8px;
    selection-background-color: #28567a;
}
QSpinBox { padding-right: 32px; }
QSpinBox::up-button {
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 26px;
    border-left: 1px solid #34445f;
    border-bottom: 1px solid #34445f;
    border-top-right-radius: 8px;
    background: #172033;
}
QSpinBox::down-button {
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 26px;
    border-left: 1px solid #34445f;
    border-bottom-right-radius: 8px;
    background: #172033;
}
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: #253249; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus { border-color: #00d8ff; }
QListWidget {
    background: #0c111a;
    border: 1px solid #29364c;
    border-radius: 10px;
    padding: 4px;
    outline: none;
}
QListWidget::item { padding: 7px; border-radius: 6px; }
QListWidget::item:selected { background: #253952; }
QListWidget#MainKaraokePlaylist { font-size: 9pt; }
QListWidget#MainKaraokePlaylist::item { padding: 3px 5px; }
QSlider::groove:horizontal {
    height: 7px;
    background: #253147;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #ffffff;
    border: 2px solid #00d8ff;
    width: 18px;
    margin: -7px 0;
    border-radius: 10px;
}
QSlider#Crossfader::groove:horizontal {
    height: 10px;
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #00d8ff,stop:.5 #dbe7ff,stop:1 #ff2fa7);
    border-radius: 5px;
}
QSlider#Crossfader::handle:horizontal {
    background: #ffffff;
    border: 2px solid #0b0e14;
    width: 24px;
    margin: -8px 0;
    border-radius: 13px;
}
QCheckBox { spacing: 8px; font-weight: 700; }
QCheckBox::indicator {
    width: 18px; height: 18px; border-radius: 5px;
    border: 1px solid #4d607e; background: #0c111a;
}
QCheckBox::indicator:checked { background: #00b88a; border-color: #2dffc6; }
QScrollArea { border: none; }
QToolTip { background: #172033; color: white; border: 1px solid #52698e; }
QMessageBox { background: #111722; }
"""
