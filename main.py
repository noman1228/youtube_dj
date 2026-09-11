from __future__ import annotations

import sys

from app.runtime import configure_playback, readiness_issues

configure_playback(software_video="--software-video" in sys.argv)

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox

from app.main_window import MainWindow
from app.theme import apply_appearance, load_appearance


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("EncoreMix 2026")
    app.setOrganizationName("JMT")
    app.setFont(QFont("Segoe UI", 10))
    apply_appearance(load_appearance())
    issues = readiness_issues()
    if "--check" in sys.argv:
        print("\n\n".join(issues) if issues else "Playback codecs, audio output, and YouTube dependencies are ready.")
        return 1 if issues else 0
    if issues:
        QMessageBox.critical(None, "Setup needs attention", "\n\n".join(issues))
        return 1
    window = MainWindow()
    apply_appearance(load_appearance())
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
