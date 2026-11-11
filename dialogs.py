"""Audio Extractor - finestre di dialogo: informazioni, licenze, dettaglio errori."""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QGuiApplication
from PySide6.QtWidgets import (
    QDialog, QGridLayout, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QTextBrowser, QVBoxLayout,
)

import icons
from common import APP_AUTHOR, APP_DIR, APP_NAME, APP_URL, APP_VERSION, DATA_DIR, open_path
from theme import SP_1, SP_2, SP_3, SP_4, SP_5, SP_6, titlebar
from widgets import IconLabel, a11y_pass, label, sep


class _Dialog(QDialog):
    def showEvent(self, e):
        titlebar(self)
        super().showEvent(e)


def _app_file(*parts):
    """File distribuito con il programma: cartella del progetto (sorgenti) o accanto all'exe (installato)."""
    return str(APP_DIR.joinpath(*parts))


class TextDialog(_Dialog):
    """Mostra un file di testo (licenza, avvisi di terze parti) dentro l'app."""

    def __init__(self, parent, title, path):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 600)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(SP_5, SP_4, SP_5, SP_4)
        lay.setSpacing(SP_3)
        lay.addWidget(label(title, "h1"))
        view = QTextBrowser()
        view.setOpenExternalLinks(True)
        view.setAccessibleName(title)
        try:
            with open(path, encoding="utf-8-sig") as f:
                view.setPlainText(f.read())
        except OSError:
            view.setPlainText(f"File non trovato:\n{path}")
        mono = QFont("Cascadia Mono")
        mono.setStyleHint(QFont.Monospace)
        mono.setPointSizeF(9.5)
        view.setFont(mono)
        lay.addWidget(view, 1)
        row = QHBoxLayout()
        row.addStretch()
        ok = QPushButton("Chiudi", objectName="primary")
        ok.clicked.connect(self.accept)
        ok.setDefault(True)
        row.addWidget(ok)
        lay.addLayout(row)
        a11y_pass(self)


class AboutDialog(_Dialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle(f"Informazioni su {APP_NAME}")
        self.setMinimumWidth(480)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(SP_6, SP_6, SP_6, SP_5)
        lay.setSpacing(SP_2)
        logo = QLabel()
        logo.setPixmap(icons.svg_pixmap(icons.ICON_SVG, 80))
        logo.setAlignment(Qt.AlignCenter)
        logo.setAccessibleName(f"Logo di {APP_NAME}")
        lay.addWidget(logo)
        for text, obj in ((APP_NAME, "h1"), (f"Versione {APP_VERSION}", "muted")):
            lab = label(text, obj)
            lab.setAlignment(Qt.AlignCenter)
            lay.addWidget(lab)
        desc = label("Estrae l'audio dai tuoi video in pochi clic, con la copertina presa dal video "
                     "o da un'immagine a tua scelta.", None, True)
        desc.setAlignment(Qt.AlignCenter)
        lay.addSpacing(SP_2)
        lay.addWidget(desc)
        lay.addSpacing(SP_2)
        cp = label(f"© 2026 {APP_AUTHOR}  ·  Licenza MIT", "small")
        cp.setAlignment(Qt.AlignCenter)
        lay.addWidget(cp)
        note = label("Usa FFmpeg (GPL v3), un programma separato, e Qt 6 / PySide6 (LGPL v3), "
                     "ciascuno con la propria licenza.", "small", True)
        note.setAlignment(Qt.AlignCenter)
        lay.addWidget(note)
        lay.addSpacing(SP_3)
        lay.addWidget(sep())
        lay.addSpacing(SP_1)

        grid = QGridLayout()
        grid.setSpacing(SP_2)
        items = (
            ("scale", "Licenza",
             lambda: TextDialog(self, f"Licenza MIT di {APP_NAME}", _app_file("LICENSE.txt")).exec()),
            ("file", "Componenti di terze parti",
             lambda: TextDialog(self, "Componenti di terze parti",
                                _app_file("licenses", "THIRD-PARTY-NOTICES.txt")).exec()),
            ("link", "Sito del progetto", lambda: QDesktopServices.openUrl(QUrl(APP_URL))),
            ("folder", "Cartella dei dati", self._open_data),
        )
        for i, (ic, text, fn) in enumerate(items):
            b = QPushButton(icons.icon(ic), "  " + text)
            b.clicked.connect(fn)
            b.setCursor(Qt.PointingHandCursor)
            grid.addWidget(b, i // 2, i % 2)
        lay.addLayout(grid)
        lay.addSpacing(SP_2)
        row = QHBoxLayout()
        row.addStretch()
        ok = QPushButton("Chiudi", objectName="primary")
        ok.clicked.connect(self.accept)
        ok.setDefault(True)
        row.addWidget(ok)
        lay.addLayout(row)
        a11y_pass(self)

    @staticmethod
    def _open_data():
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        open_path(str(DATA_DIR))


class ErrorDialog(_Dialog):
    """Errore comprensibile + dettaglio tecnico selezionabile e copiabile (niente traceback nudi)."""

    def __init__(self, parent, title, message, detail=""):
        super().__init__(parent)
        self.setWindowTitle(APP_NAME)
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(SP_5, SP_5, SP_5, SP_4)
        lay.setSpacing(SP_3)
        head = QHBoxLayout()
        head.setSpacing(SP_3)
        head.addWidget(IconLabel("alert", "warn", 28, 2.0), 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(SP_1)
        col.addWidget(label(title, "h1"))
        col.addWidget(label(message, None, True))
        head.addLayout(col, 1)
        lay.addLayout(head)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlainText(detail)
        self.detail.setAccessibleName("Dettagli tecnici")
        self.detail.setFixedHeight(150)
        mono = QFont("Cascadia Mono")
        mono.setStyleHint(QFont.Monospace)
        mono.setPointSizeF(9)
        self.detail.setFont(mono)
        self.detail.setVisible(bool(detail))
        if detail:
            lay.addWidget(label("DETTAGLI TECNICI", "sectionTitle"))
            lay.addWidget(self.detail)
        row = QHBoxLayout()
        self.btn_copy = QPushButton(icons.icon("copy"), "  Copia dettagli")
        self.btn_copy.clicked.connect(self.copy)
        self.btn_copy.setVisible(bool(detail))
        row.addWidget(self.btn_copy)
        row.addStretch()
        ok = QPushButton("Chiudi", objectName="primary")
        ok.clicked.connect(self.accept)
        ok.setDefault(True)
        row.addWidget(ok)
        lay.addLayout(row)
        a11y_pass(self)

    def copy(self):
        QGuiApplication.clipboard().setText(self.detail.toPlainText())
        self.btn_copy.setText("  Copiato")
