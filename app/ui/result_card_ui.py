# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'result_card.ui'
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
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel,
    QPushButton, QSizePolicy, QSpacerItem, QVBoxLayout,
    QWidget)
class Ui_ResultCard(object):
    def setupUi(self, result_card):
        if not result_card.objectName():
            result_card.setObjectName(u"result_card")
        result_card.resize(760, 155)
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(result_card.sizePolicy().hasHeightForWidth())
        result_card.setSizePolicy(sizePolicy)
        result_card.setMinimumSize(QSize(0, 155))
        result_card.setMaximumSize(QSize(16777215, 155))
        self.row = QHBoxLayout(result_card)
        self.row.setSpacing(14)
        self.row.setObjectName(u"row")
        self.row.setSizeConstraint(QHBoxLayout.SetDefaultConstraint)
        self.row.setContentsMargins(12, 12, 12, 12)
        self.thumbnail = QLabel(result_card)
        self.thumbnail.setObjectName(u"thumbnail")
        self.thumbnail.setMinimumSize(QSize(160, 90))
        self.thumbnail.setMaximumSize(QSize(160, 90))
        self.thumbnail.setStyleSheet(u"background:#080b10;border:1px solid #34445f;border-radius:8px;color:#66758c;")
        self.thumbnail.setAlignment(AlignCenter)

        self.row.addWidget(self.thumbnail, 0, Qt.AlignmentFlag.AlignVCenter)

        self.text_panel = QWidget(result_card)
        self.text_panel.setObjectName(u"text_panel")
        self.text_panel.setMinimumSize(QSize(0, 0))
        self.text_panel.setMaximumSize(QSize(16777215, 16777215))
        self.text_panel.setStyleSheet(u"background: transparent;")
        sizePolicy1 = QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        sizePolicy1.setHorizontalStretch(0)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.text_panel.sizePolicy().hasHeightForWidth())
        self.text_panel.setSizePolicy(sizePolicy1)
        self.text_col = QVBoxLayout(self.text_panel)
        self.text_col.setSpacing(6)
        self.text_col.setObjectName(u"text_col")
        self.text_col.setSizeConstraint(QVBoxLayout.SetDefaultConstraint)
        self.text_col.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel(self.text_panel)
        self.title.setObjectName(u"title")
        self.title.setMaximumSize(QSize(16777215, 44))
        self.title.setWordWrap(True)

        self.text_col.addWidget(self.title)

        self.meta_label = QLabel(self.text_panel)
        self.meta_label.setObjectName(u"meta_label")
        self.meta_label.setWordWrap(True)

        self.text_col.addWidget(self.meta_label)

        self.description = QLabel(self.text_panel)
        self.description.setObjectName(u"description")
        self.description.setMaximumSize(QSize(16777215, 38))
        self.description.setWordWrap(True)

        self.text_col.addWidget(self.description)


        self.row.addWidget(self.text_panel, 0, Qt.AlignmentFlag.AlignVCenter)

        self.buttons = QVBoxLayout()
        self.buttons.setSpacing(7)
        self.buttons.setObjectName(u"buttons")
        self.buttons.setSizeConstraint(QVBoxLayout.SetDefaultConstraint)
        self.buttons.setContentsMargins(0, 0, 0, 0)
        self.spacer_1 = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.buttons.addItem(self.spacer_1)

        self.add_left = QPushButton(result_card)
        self.add_left.setObjectName(u"add_left")
        self.add_left.setMinimumSize(QSize(112, 0))
        self.add_left.setMaximumSize(QSize(112, 16777215))

        self.buttons.addWidget(self.add_left)

        self.add_right = QPushButton(result_card)
        self.add_right.setObjectName(u"add_right")
        self.add_right.setMinimumSize(QSize(112, 0))
        self.add_right.setMaximumSize(QSize(112, 16777215))

        self.buttons.addWidget(self.add_right)

        self.details = QPushButton(result_card)
        self.details.setObjectName(u"details")
        self.details.setMinimumSize(QSize(112, 0))
        self.details.setMaximumSize(QSize(112, 16777215))

        self.buttons.addWidget(self.details)

        self.spacer_2 = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)

        self.buttons.addItem(self.spacer_2)

        self.buttons.setStretch(0, 1)
        self.buttons.setStretch(4, 1)

        self.row.addLayout(self.buttons)

        self.row.setStretch(1, 1)

        self.retranslateUi(result_card)

        QMetaObject.connectSlotsByName(result_card)
    # setupUi

    def retranslateUi(self, result_card):
        result_card.setProperty(u"runtimeObjectName", QCoreApplication.translate("ResultCard", u"ResultCard", None))
        self.thumbnail.setText(QCoreApplication.translate("ResultCard", u"NO ART", None))
        self.thumbnail.setProperty(u"pythonAttribute", QCoreApplication.translate("ResultCard", u"thumbnail", None))
        self.text_panel.setProperty(u"runtimeObjectName", QCoreApplication.translate("ResultCard", u"ResultTextPanel", None))
#if QT_CONFIG(tooltip)
        self.title.setToolTip(QCoreApplication.translate("ResultCard", u"Track title", None))
#endif // QT_CONFIG(tooltip)
        self.title.setText(QCoreApplication.translate("ResultCard", u"Track title", None))
        self.title.setProperty(u"runtimeObjectName", QCoreApplication.translate("ResultCard", u"TrackTitle", None))
        self.meta_label.setText(QCoreApplication.translate("ResultCard", u"YouTube \u2022 Artist / channel \u2022 3:30", None))
        self.meta_label.setProperty(u"runtimeObjectName", QCoreApplication.translate("ResultCard", u"Subtle", None))
#if QT_CONFIG(tooltip)
        self.description.setToolTip(QCoreApplication.translate("ResultCard", u"Track description", None))
#endif // QT_CONFIG(tooltip)
        self.description.setText(QCoreApplication.translate("ResultCard", u"Track description", None))
        self.add_left.setText(QCoreApplication.translate("ResultCard", u"ADD LEFT", None))
        self.add_left.setProperty(u"runtimeObjectName", QCoreApplication.translate("ResultCard", u"PrimaryButton", None))
        self.add_right.setText(QCoreApplication.translate("ResultCard", u"ADD RIGHT", None))
        self.add_right.setProperty(u"runtimeObjectName", QCoreApplication.translate("ResultCard", u"HotButton", None))
        self.details.setText(QCoreApplication.translate("ResultCard", u"DETAILS", None))
    # retranslateUi

