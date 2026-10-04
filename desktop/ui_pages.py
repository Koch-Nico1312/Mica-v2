"""Local history, reminder and memory pages for the desktop shell."""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from desktop.ui_theme import C
from desktop.ui_widgets import LogWidget


class LocalPagesMixin:
    """Page rendering and local memory interactions, separate from the shell."""

    @staticmethod
    def _new_local_page(
        title: str, detail: str, object_name: str = ""
    ) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        if object_name:
            page.setObjectName(object_name)
        page.setStyleSheet(f"background: {C.BG};")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(46, 42, 46, 32)
        layout.setSpacing(14)
        heading = QLabel(title)
        heading.setFont(QFont("Segoe UI", 24, QFont.Weight.DemiBold))
        heading.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        layout.addWidget(heading)
        description = QLabel(detail)
        description.setFont(QFont("Segoe UI", 10))
        description.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        layout.addWidget(description)
        return page, layout

    def _build_history_page(self) -> QWidget:
        page, lay = self._new_local_page(
            "Verlauf", "Reale Sitzungsereignisse, Antworten und geladene Dateien.", ""
        )
        self._log = LogWidget()
        self._log.setAccessibleName("Sitzungsverlauf")
        lay.addWidget(self._log, stretch=1)
        return page

    def _build_reminders_page(self) -> QWidget:
        page, lay = self._new_local_page(
            "Erinnerungen",
            "Deine lokal geplanten Erinnerungen auf einen Blick.",
            "RemindersPage",
        )
        refresh = QPushButton("Aktualisieren")
        refresh.setAccessibleName("Erinnerungen aktualisieren")
        refresh.setFixedHeight(32)
        refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh.setStyleSheet(f"""
            QPushButton {{ background: {C.PRI_GHO}; color: {C.PRI}; border: 1px solid {C.BORDER};
                border-radius: 12px; padding: 0 14px; font-weight: 600; }}
            QPushButton:hover {{ background: #dceaff; border-color: {C.PRI_DIM}; }}
        """)
        refresh.clicked.connect(self._refresh_reminders_page)
        lay.addWidget(refresh, alignment=Qt.AlignmentFlag.AlignLeft)

        self._reminder_list = QWidget()
        self._reminder_list_layout = QVBoxLayout(self._reminder_list)
        self._reminder_list_layout.setContentsMargins(0, 4, 0, 0)
        self._reminder_list_layout.setSpacing(10)
        lay.addWidget(self._reminder_list)
        lay.addStretch()
        self._refresh_reminders_page()
        return page

    @staticmethod
    def _clear_widget_layout(layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _refresh_reminders_page(self) -> None:
        if not hasattr(self, "_reminder_list_layout"):
            return
        self._clear_widget_layout(self._reminder_list_layout)
        try:
            from desktop.actions.reminder import list_upcoming_reminders

            reminders = list_upcoming_reminders(limit=50)
        except Exception:
            reminders = []

        if not reminders:
            reminders = [
                {
                    "when": "Noch nichts geplant",
                    "message": "Bitte Mica im Chat, dich an etwas zu erinnern.",
                }
            ]
        for reminder in reminders:
            card = QFrame()
            card.setObjectName("ReminderPageCard")
            card.setMinimumHeight(92)
            card.setStyleSheet(
                f"QFrame#ReminderPageCard {{ background: {C.PANEL}; border: 1px solid {C.BORDER}; "
                f"border-radius: 16px; }}"
            )
            box = QVBoxLayout(card)
            box.setContentsMargins(20, 15, 20, 15)
            when = QLabel(str(reminder.get("when", "")))
            when.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
            when.setStyleSheet(f"color: {C.PRI}; background: transparent;")
            message = QLabel(str(reminder.get("message", "Erinnerung")))
            message.setWordWrap(True)
            message.setFont(QFont("Segoe UI", 10))
            message.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
            box.addWidget(when)
            box.addWidget(message)
            self._reminder_list_layout.addWidget(card)

    def _build_memory_page(self) -> QWidget:
        page, lay = self._new_local_page(
            "Gedächtnis",
            "Lokal gespeicherte Informationen verwalten. Änderungen bleiben auf diesem PC.",
            "MemoryPage",
        )
        composer = QFrame()
        composer.setObjectName("MemoryComposer")
        composer.setStyleSheet(f"""
            QFrame#MemoryComposer {{ background: {C.PANEL}; border: 1px solid {C.BORDER}; border-radius: 16px; }}
        """)
        form = QVBoxLayout(composer)
        form.setContentsMargins(18, 16, 18, 16)
        form.setSpacing(8)

        form_title = QLabel("Neue Information hinzufügen")
        form_title.setFont(QFont("Segoe UI", 11, QFont.Weight.DemiBold))
        form_title.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        form.addWidget(form_title)

        row = QHBoxLayout()
        row.setSpacing(8)
        self._memory_category_input = QComboBox()
        self._memory_category_input.addItems(
            ["Notizen", "Vorlieben", "Identität", "Projekte", "Wünsche", "Beziehungen"]
        )
        self._memory_category_input.setAccessibleName("Kategorie")
        self._memory_category_input.setFixedHeight(38)
        self._memory_category_input.setMinimumWidth(170)
        self._memory_category_input.setFont(QFont("Segoe UI", 10))
        # Keep dropdown labels readable independently of the Windows/Qt palette.
        self._memory_category_input.setStyleSheet(f"""
            QComboBox {{
                background: {C.PANEL}; color: {C.TEXT};
                border: 1px solid {C.BORDER_B}; border-radius: 10px;
                padding: 0 34px 0 12px;
            }}
            QComboBox:hover, QComboBox:focus {{ border-color: {C.PRI}; }}
            QComboBox::drop-down {{ width: 30px; border: none; }}
            QComboBox QAbstractItemView {{
                background: {C.PANEL}; color: {C.TEXT};
                border: 1px solid {C.BORDER_B};
                selection-background-color: {C.PRI_GHO};
                selection-color: {C.TEXT}; outline: 0; padding: 5px;
            }}
        """)
        self._memory_key_input = QLineEdit()
        self._memory_key_input.setPlaceholderText("Titel, z. B. Lieblingsgetränk")
        self._memory_key_input.setAccessibleName("Titel der Information")
        self._memory_key_input.setFixedHeight(38)
        self._memory_key_input.setFont(QFont("Segoe UI", 10))
        self._memory_key_input.setStyleSheet(f"""
            QLineEdit {{ background: {C.PANEL}; color: {C.TEXT};
                border: 1px solid {C.BORDER_B}; border-radius: 10px; padding: 0 12px; }}
            QLineEdit:focus {{ border: 2px solid {C.PRI}; }}
        """)
        row.addWidget(self._memory_category_input)
        row.addWidget(self._memory_key_input, stretch=1)
        form.addLayout(row)

        self._memory_value_input = QTextEdit()
        self._memory_value_input.setPlaceholderText("Was soll Mica sich merken?")
        self._memory_value_input.setAccessibleName("Inhalt der Information")
        self._memory_value_input.setFixedHeight(72)
        self._memory_value_input.setFont(QFont("Segoe UI", 10))
        self._memory_value_input.setStyleSheet(f"""
            QTextEdit {{ background: {C.PANEL}; color: {C.TEXT};
                border: 1px solid {C.BORDER_B}; border-radius: 10px; padding: 8px 10px; }}
            QTextEdit:focus {{ border: 2px solid {C.PRI}; }}
        """)
        form.addWidget(self._memory_value_input)

        add = QPushButton("Information speichern")
        add.setAccessibleName("Information im Gedächtnis speichern")
        add.setFixedHeight(36)
        add.setCursor(Qt.CursorShape.PointingHandCursor)
        add.setStyleSheet(f"""
            QPushButton {{ background: {C.PRI}; color: white; border: none; border-radius: 12px; padding: 0 16px; font-weight: 600; }}
            QPushButton:hover {{ background: {C.PRI_DIM}; }}
        """)
        add.clicked.connect(self._add_memory_entry)
        form.addWidget(add, alignment=Qt.AlignmentFlag.AlignRight)
        lay.addWidget(composer)

        self._memory_status = QLabel("")
        self._memory_status.setFont(QFont("Segoe UI", 9))
        self._memory_status.setStyleSheet(
            f"color: {C.TEXT_MED}; background: transparent;"
        )
        lay.addWidget(self._memory_status)

        self._memory_entries = QScrollArea()
        self._memory_entries.setWidgetResizable(True)
        self._memory_entries.setStyleSheet(f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{ background: transparent; width: 7px; }}
            QScrollBar::handle:vertical {{ background: {C.BORDER_B}; border-radius: 3px; min-height: 24px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)
        self._memory_entries_inner = QWidget()
        self._memory_entries_layout = QVBoxLayout(self._memory_entries_inner)
        self._memory_entries_layout.setContentsMargins(0, 0, 6, 0)
        self._memory_entries_layout.setSpacing(8)
        self._memory_entries.setWidget(self._memory_entries_inner)
        lay.addWidget(self._memory_entries, stretch=1)
        self._refresh_memory_page()
        return page

    def _refresh_memory_page(self) -> None:
        if not hasattr(self, "_memory_entries_layout"):
            return
        self._clear_widget_layout(self._memory_entries_layout)
        from desktop.memory.memory_manager import all_entries_for_ui

        rows = all_entries_for_ui()
        self._memory_status.setText(
            f"{len(rows)} lokal gespeicherte Information{'en' if len(rows) != 1 else ''}"
        )
        if not rows:
            empty = QLabel(
                "Noch nichts gespeichert. Du kannst oben eine Information hinzufügen."
            )
            empty.setFont(QFont("Segoe UI", 10))
            empty.setStyleSheet(
                f"color: {C.TEXT_MED}; background: transparent; padding: 14px;"
            )
            self._memory_entries_layout.addWidget(empty)
            self._memory_entries_layout.addStretch()
            return
        for entry in rows:
            card = QFrame()
            card.setObjectName("MemoryEntryCard")
            card.setStyleSheet(f"""
                QFrame#MemoryEntryCard {{ background: {C.PANEL}; border: 1px solid {C.BORDER}; border-radius: 14px; }}
            """)
            row = QHBoxLayout(card)
            row.setContentsMargins(16, 12, 12, 12)
            row.setSpacing(12)
            details = QVBoxLayout()
            details.setSpacing(3)
            key = QLabel(str(entry["key"]).replace("_", " ").title())
            key.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
            key.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
            value = QLabel(str(entry["value"]))
            value.setWordWrap(True)
            value.setFont(QFont("Segoe UI", 9))
            value.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
            meta = QLabel(
                f"{entry['category'].title()} · {entry['updated'] or 'lokal gespeichert'}"
            )
            meta.setFont(QFont("Segoe UI", 8))
            meta.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
            details.addWidget(key)
            details.addWidget(value)
            details.addWidget(meta)
            row.addLayout(details, stretch=1)
            delete = QPushButton("Löschen")
            delete.setAccessibleName(f"{key.text()} löschen")
            delete.setFixedHeight(30)
            delete.setCursor(Qt.CursorShape.PointingHandCursor)
            delete.setStyleSheet(f"""
                QPushButton {{ background: transparent; color: {C.TEXT_MED}; border: 1px solid {C.BORDER}; border-radius: 10px; padding: 0 10px; }}
                QPushButton:hover {{ color: {C.RED}; border-color: {C.RED}; background: #fff4f5; }}
            """)
            delete.clicked.connect(
                lambda _=False, c=entry["category"], k=entry["key"]: (
                    self._forget_memory_entry(c, k)
                )
            )
            row.addWidget(delete, alignment=Qt.AlignmentFlag.AlignTop)
            self._memory_entries_layout.addWidget(card)
        self._memory_entries_layout.addStretch()

    def _add_memory_entry(self) -> None:
        key = self._memory_key_input.text().strip()
        value = self._memory_value_input.toPlainText().strip()
        if not key or not value:
            self._memory_status.setText(
                "Bitte gib einen Titel und eine Information ein."
            )
            self._memory_status.setStyleSheet(
                f"color: {C.RED}; background: transparent;"
            )
            return
        categories = {
            "Notizen": "notes",
            "Vorlieben": "preferences",
            "Identität": "identity",
            "Projekte": "projects",
            "Wünsche": "wishes",
            "Beziehungen": "relationships",
        }
        from desktop.memory.memory_manager import remember

        remember(key, value, categories[self._memory_category_input.currentText()])
        self._memory_key_input.clear()
        self._memory_value_input.clear()
        self._refresh_memory_page()
        self._memory_status.setStyleSheet(f"color: {C.GREEN}; background: transparent;")
        self._memory_status.setText("Lokal gespeichert.")
        self._update_metrics()

    def _forget_memory_entry(self, category: str, key: str) -> None:
        from desktop.memory.memory_manager import forget

        forget(key, category)
        self._refresh_memory_page()
        self._memory_status.setStyleSheet(
            f"color: {C.TEXT_MED}; background: transparent;"
        )
        self._memory_status.setText("Information gelöscht.")
        self._update_metrics()
