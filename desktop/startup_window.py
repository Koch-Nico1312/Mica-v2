"""Responsive desktop startup progress and recovery actions."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import sys

from PyQt6.QtCore import QThread, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QFont, QPixmap
from PyQt6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QStyle, QVBoxLayout,
)

from desktop.ui_theme import C, ensure_ui_font

STAGES = {
    "docker": ("Docker wird vorbereitet", "Docker Desktop starten und erneut versuchen."),
    "configuration": ("Zugriff wird eingerichtet", "Backend-Konfiguration und Windows-Anmeldeinformationen pruefen."),
    "host": ("Windows-Aktionsdienst wird vorbereitet", "Die Einrichtung des Windows-Aktionsdienstes pruefen."),
    "services": ("Dienste und Modelle werden gestartet", "Docker Desktop auf fehlende Modelle oder Dienstfehler pruefen."),
    "connection": ("Sichere Verbindung wird geprueft", "HTTPS-Adresse, Zertifikat und Core-Zugriff pruefen."),
}


class StartupWorker(QThread):
    progress = pyqtSignal(str)
    succeeded = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, starter: Callable, parent=None):
        super().__init__(parent)
        self.starter = starter

    def run(self):
        try:
            result = self.starter(self.progress.emit)
            self.succeeded.emit(result)
        except Exception as error:
            # Report only the type: raw command lines can contain secrets.
            self.failed.emit(type(error).__name__)


class StartupWindow(QDialog):
    def __init__(self, starter: Callable, root: Path):
        super().__init__()
        ensure_ui_font()
        self.setFont(QFont("Segoe UI", 10))
        self.starter = starter
        self.root = root
        self.worker = None
        self.stage = "docker"
        self.outcome = None
        self.setWindowTitle("MICA starten")
        self.setMinimumWidth(440)
        self.resize(520, 340)
        self.setStyleSheet(f"""
            QDialog {{ background: {C.BG}; color: {C.TEXT}; }}
            QLabel {{ color: {C.TEXT}; font-size: 14px; }}
            QPushButton {{ padding: 9px 14px; border: 1px solid {C.BORDER};
                border-radius: 6px; background: {C.PANEL}; color: {C.TEXT}; }}
            QPushButton:hover {{ background: {C.PRI_GHO}; }}
            QPushButton:disabled {{ color: {C.TEXT_DIM}; }}
            QProgressBar {{ border: 0; background: {C.BAR_BG}; height: 6px; }}
            QProgressBar::chunk {{ background: {C.PRI}; }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        heading = QHBoxLayout()
        asset = QLabel()
        asset.setPixmap(QPixmap(str(root / "desktop/assets/mica-orb-v2.png")).scaledToWidth(52))
        heading.addWidget(asset)
        title = QLabel("MICA")
        title.setStyleSheet(f"font-size: 28px; font-weight: 600; color: {C.TEXT};")
        heading.addWidget(title, 1)
        layout.addLayout(heading)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        layout.addWidget(self.bar)
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet(f"color: {C.TEXT_MED}; font-size: 13px;")
        layout.addWidget(self.detail)
        layout.addStretch()
        buttons = QHBoxLayout()
        self.help_button = QPushButton("Einrichtung oeffnen")
        self.help_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        self.help_button.clicked.connect(self.open_help)
        buttons.addWidget(self.help_button)
        buttons.addStretch()
        self.retry = QPushButton("Erneut versuchen")
        self.retry.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        self.retry.clicked.connect(self.begin)
        buttons.addWidget(self.retry)
        self.continue_button = QPushButton("MICA oeffnen")
        self.continue_button.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowForward))
        self.continue_button.clicked.connect(self.accept)
        buttons.addWidget(self.continue_button)
        layout.addLayout(buttons)
        self.offline_button = QPushButton('Offline weiterarbeiten')
        self.offline_button.clicked.connect(self.open_offline)
        layout.addWidget(self.offline_button)
        self.set_stage("docker")
        self.retry.hide()
        self.help_button.hide()
        self.continue_button.hide()
        self.offline_button.hide()

    def begin(self):
        if self.worker and self.worker.isRunning():
            return
        if self.worker:
            self.worker.deleteLater()
        self.outcome = None
        self.retry.hide()
        self.help_button.hide()
        self.continue_button.hide()
        self.offline_button.hide()
        self.set_stage("docker")
        self.worker = StartupWorker(self.starter, self)
        self.worker.progress.connect(self.set_stage)
        self.worker.succeeded.connect(self.on_success)
        self.worker.failed.connect(self.on_failure)
        self.worker.finished.connect(self.on_finished)
        self.worker.start()

    def set_stage(self, stage: str):
        if stage not in STAGES:
            return
        self.stage = stage
        self.help_button.setText("Docker Desktop oeffnen" if stage in {"docker", "services"} else "Einrichtung oeffnen")
        self.bar.setRange(0, 0)
        self.status.setText(STAGES[stage][0])
        step = list(STAGES).index(stage) + 1
        self.detail.setText(
            f"Schritt {step} von {len(STAGES)}. Beim ersten Start kann die Einrichtung mehrere Minuten dauern."
        )

    def on_success(self, health: dict):
        self.outcome = "ready" if health.get("status") == "ready" else "limited"
        self.bar.setRange(0, 1)
        self.bar.setValue(1)
        if self.outcome == "ready":
            self.status.setText("Core verbunden")
            self.detail.setText("MICA wird geoeffnet.")
        else:
            self.status.setText("Core verbunden - Funktionen eingeschraenkt")
            self.detail.setText("Einige Betriebspruefungen sind noch offen. Details findest du in MICA unter Betrieb und Diagnose.")

    def on_failure(self, kind: str):
        self.outcome = "failed"
        self.bar.setRange(0, 1)
        self.bar.setValue(0)
        self.status.setText("Start konnte nicht abgeschlossen werden")
        self.detail.setText(f"{STAGES[self.stage][1]}\nFehlerart: {kind}")

    def on_finished(self):
        if self.outcome == "ready":
            self.accept()
        elif self.outcome == "limited":
            self.continue_button.show()
            self.retry.show()
            self.help_button.show()
        else:
            self.retry.show()
            self.help_button.show()
            self.offline_button.show()

    def open_offline(self):
        if self.worker and self.worker.isRunning():
            return
        self.outcome = 'offline'
        self.accept()

    def open_help(self):
        if self.stage in {"docker", "services"}:
            QDesktopServices.openUrl(QUrl("docker-desktop://dashboard"))
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.root / "backend")))

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            event.ignore()
        else:
            super().closeEvent(event)

    def reject(self):
        # Escape must not destroy the dialog while its worker is still running.
        if not self.worker or not self.worker.isRunning():
            super().reject()


def run_startup(starter: Callable, root: Path, *, return_outcome=False):
    app = QApplication.instance() or QApplication(sys.argv)
    ensure_ui_font()
    window = StartupWindow(starter, root)
    QTimer.singleShot(0, window.begin)
    result = window.exec() == QDialog.DialogCode.Accepted
    outcome = window.outcome if result else None
    # Keep the application alive until the startup worker has finished.
    if window.worker:
        window.worker.wait()
    window.deleteLater()
    app.processEvents()
    return outcome if return_outcome else result
