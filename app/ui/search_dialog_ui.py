# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'search_dialog.ui'
##
## Created by: Qt User Interface Compiler version 6.11.2
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel,
    QLayout, QLineEdit, QPushButton, QScrollArea,
    QSizePolicy, QSpacerItem, QVBoxLayout, QWidget)

class Ui_search_dialog(object):
    def setupUi(self, search_dialog):
        if not search_dialog.objectName():
            search_dialog.setObjectName(u"search_dialog")
        search_dialog.resize(860, 760)
        search_dialog.setMinimumSize(QSize(760, 0))
        search_dialog.setMaximumSize(QSize(900, 16777215))
        self.root = QVBoxLayout(search_dialog)
        self.root.setSpacing(12)
        self.root.setObjectName(u"root")
        self.root.setSizeConstraint(QLayout.SizeConstraint.SetDefaultConstraint)
        self.root.setContentsMargins(18, 18, 18, 18)
        self.header = QLabel(search_dialog)
        self.header.setObjectName(u"header")

        self.root.addWidget(self.header)

        self.subtitle = QLabel(search_dialog)
        self.subtitle.setObjectName(u"subtitle")

        self.root.addWidget(self.subtitle)

        self.controls = QHBoxLayout()
        self.controls.setSpacing(12)
        self.controls.setObjectName(u"controls")
        self.controls.setSizeConstraint(QLayout.SizeConstraint.SetDefaultConstraint)
        self.controls.setContentsMargins(0, 0, 0, 0)
        self.search_edit = QLineEdit(search_dialog)
        self.search_edit.setObjectName(u"search_edit")
        self.search_edit.setClearButtonEnabled(True)

        self.controls.addWidget(self.search_edit)

        self.search_button = QPushButton(search_dialog)
        self.search_button.setObjectName(u"search_button")
        self.search_button.setAutoDefault(False)

        self.controls.addWidget(self.search_button)

        self.controls.setStretch(0, 1)

        self.root.addLayout(self.controls)

        self.similar_controls = QHBoxLayout()
        self.similar_controls.setSpacing(12)
        self.similar_controls.setObjectName(u"similar_controls")
        self.similar_controls.setSizeConstraint(QLayout.SizeConstraint.SetDefaultConstraint)
        self.similar_controls.setContentsMargins(0, 0, 0, 0)
        self.similar_label = QLabel(search_dialog)
        self.similar_label.setObjectName(u"similar_label")

        self.similar_controls.addWidget(self.similar_label)

        self.similar_left = QPushButton(search_dialog)
        self.similar_left.setObjectName(u"similar_left")

        self.similar_controls.addWidget(self.similar_left)

        self.similar_right = QPushButton(search_dialog)
        self.similar_right.setObjectName(u"similar_right")

        self.similar_controls.addWidget(self.similar_right)

        self.similar_controls.setStretch(0, 1)

        self.root.addLayout(self.similar_controls)

        self.status = QLabel(search_dialog)
        self.status.setObjectName(u"status")
        self.status.setWordWrap(True)

        self.root.addWidget(self.status)

        self.scroll = QScrollArea(search_dialog)
        self.scroll.setObjectName(u"scroll")
        self.scroll.setWidgetResizable(True)
        self.results_widget = QWidget()
        self.results_widget.setObjectName(u"results_widget")
        self.results_widget.setGeometry(QRect(0, 0, 820, 584))
        self.results_widget.setAutoFillBackground(True)
        self.results_layout = QVBoxLayout(self.results_widget)
        self.results_layout.setSpacing(10)
        self.results_layout.setObjectName(u"results_layout")
        self.results_layout.setSizeConstraint(QLayout.SizeConstraint.SetDefaultConstraint)
        self.results_layout.setContentsMargins(0, 0, 0, 0)
        self.spacer_1 = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.results_layout.addItem(self.spacer_1)

        self.results_layout.setStretch(0, 1)
        self.scroll.setWidget(self.results_widget)

        self.root.addWidget(self.scroll)

        self.root.setStretch(5, 1)

        self.retranslateUi(search_dialog)

        QMetaObject.connectSlotsByName(search_dialog)
    # setupUi

    def retranslateUi(self, search_dialog):
        search_dialog.setWindowTitle(QCoreApplication.translate("search_dialog", u"YouTube Music Search", None))
        search_dialog.setStyleSheet(QCoreApplication.translate("search_dialog", u"QDialog#search_dialog QLabel#TrackTitle { font-size: 14pt; } QDialog#search_dialog QWidget#results_widget { background: transparent; }", None))
        self.header.setProperty(u"runtimeObjectName", QCoreApplication.translate("search_dialog", u"AppTitle", None))
        self.header.setText(QCoreApplication.translate("search_dialog", u"FIND YOUR NEXT TRACK", None))
        self.subtitle.setText(QCoreApplication.translate("search_dialog", u"Search YouTube Music and build your next set.", None))
        self.subtitle.setProperty(u"runtimeObjectName", QCoreApplication.translate("search_dialog", u"Subtle", None))
        self.search_edit.setProperty(u"pythonAttribute", QCoreApplication.translate("search_dialog", u"search_edit", None))
        self.search_edit.setPlaceholderText(QCoreApplication.translate("search_dialog", u"Search songs, artists, albums?", None))
        self.search_button.setText(QCoreApplication.translate("search_dialog", u"SEARCH", None))
        self.search_button.setProperty(u"pythonAttribute", QCoreApplication.translate("search_dialog", u"search_button", None))
        self.search_button.setProperty(u"runtimeObjectName", QCoreApplication.translate("search_dialog", u"PrimaryButton", None))
        self.similar_label.setText(QCoreApplication.translate("search_dialog", u"DISCOVER SIMILAR TRACKS", None))
        self.similar_label.setProperty(u"runtimeObjectName", QCoreApplication.translate("search_dialog", u"Subtle", None))
#if QT_CONFIG(tooltip)
        self.similar_left.setToolTip(QCoreApplication.translate("search_dialog", u"Find 10 random related songs using this deck's current track. Era and popularity matching depends on available metadata.", None))
#endif // QT_CONFIG(tooltip)
        self.similar_left.setProperty(u"runtimeObjectName", QCoreApplication.translate("search_dialog", u"PrimaryButton", None))
        self.similar_left.setText(QCoreApplication.translate("search_dialog", u"FROM LEFT", None))
#if QT_CONFIG(tooltip)
        self.similar_right.setToolTip(QCoreApplication.translate("search_dialog", u"Find 10 random related songs using this deck's current track. Era and popularity matching depends on available metadata.", None))
#endif // QT_CONFIG(tooltip)
        self.similar_right.setProperty(u"runtimeObjectName", QCoreApplication.translate("search_dialog", u"HotButton", None))
        self.similar_right.setText(QCoreApplication.translate("search_dialog", u"FROM RIGHT", None))
        self.status.setProperty(u"pythonAttribute", QCoreApplication.translate("search_dialog", u"status", None))
        self.status.setProperty(u"runtimeObjectName", QCoreApplication.translate("search_dialog", u"Subtle", None))
        self.status.setText(QCoreApplication.translate("search_dialog", u"Search for a song or artist, or discover tracks related to either deck.", None))
        self.scroll.setProperty(u"pythonAttribute", QCoreApplication.translate("search_dialog", u"scroll", None))
        self.results_widget.setProperty(u"pythonAttribute", QCoreApplication.translate("search_dialog", u"results_widget", None))
    # retranslateUi

