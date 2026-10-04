"""Shared palette, font registration and theme styling."""
from __future__ import annotations
import math
import os
import platform
from pathlib import Path
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QBrush, QColor, QFontDatabase, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QApplication, QPushButton
_OS = platform.system()


def style_toggle_button(button: QPushButton, enabled: bool) -> None:
    """One state/label/style contract for feature and plugin switches."""
    button.setText("AN" if enabled else "AUS")
    if enabled:
        button.setStyleSheet(f"QPushButton {{ background: {C.PRI_GHO}; color: {C.PRI}; border: 1px solid {C.PRI}; border-radius: 10px; }}")
    else:
        button.setStyleSheet(f"QPushButton {{ background: {C.PANEL}; color: {C.TEXT_MED}; border: 1px solid {C.BORDER}; border-radius: 10px; }} QPushButton:hover {{ border-color: {C.BORDER_B}; }}")


class C:
    # A quiet, daylight-first palette.  The two surface colours deliberately
    # stay close to white so the reactive voice canvas is the visual focus.
    BG        = "#f8faff"
    PANEL     = "#ffffff"
    PANEL2    = "#f3f7fd"
    BORDER    = "#dfe8f3"
    BORDER_B  = "#cadbec"
    BORDER_A  = "#d5e4f2"
    PRI       = "#4f8ff7"
    PRI_DIM   = "#7b9ed0"
    PRI_GHO   = "#e8f1ff"
    ACC       = "#6d9cf0"
    ACC2      = "#93b8f7"
    GREEN     = "#2eaf7d"
    GREEN_D   = "#a7e4ca"
    RED       = "#df7182"
    MUTED_C   = "#df7182"
    TEXT      = "#1c2b3b"
    TEXT_DIM  = "#8999ab"
    TEXT_MED  = "#5e748c"
    WHITE     = "#152434"
    DARK      = "#ffffff"
    BAR_BG    = "#e8eff8"

_HUE_LINKED = (
    "BG", "PANEL", "PANEL2", "BORDER", "BORDER_B", "BORDER_A",
    "PRI", "PRI_DIM", "PRI_GHO", "TEXT", "TEXT_DIM", "TEXT_MED",
    "WHITE", "DARK", "BAR_BG",
)

_PALETTE_DEFAULTS: dict[str, str] = {k: getattr(C, k) for k in _HUE_LINKED}

DEFAULT_UI_COLOR = _PALETTE_DEFAULTS["PRI"]

_UI_FONT_REGISTERED = False

def ensure_ui_font() -> None:
    """Make the calm UI typography available in bundled/headless Qt builds.

    Native Windows normally discovers Segoe UI itself.  Some portable Qt
    builds expose an empty font database, which previously rendered German
    labels as empty squares in screenshots and on packaged builds.  We only
    register the user's already-installed system font at runtime; nothing is
    copied into the project or redistributed.
    """
    global _UI_FONT_REGISTERED
    if _UI_FONT_REGISTERED:
        return
    _UI_FONT_REGISTERED = True
    if _OS != "Windows":
        return
    for font_path in (Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "segoeui.ttf",
                      Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "arial.ttf"):
        if font_path.exists() and QFontDatabase.addApplicationFont(str(font_path)) >= 0:
            return

def apply_ui_accent(accent_hex: str) -> bool:
    """
    Seçilen accent rengine göre tüm turkuaz-ailesi paleti yeniden türetir
    (hue kaydırma — parlaklık/doygunluk oranları korunur, tasarım bozulmaz).
    Boyanan öğeler (HUD, dalga formu, metrikler) bir sonraki karede yeni
    rengi alır; stylesheet tabanlı paneller yeniden kurulduklarında alır.
    """
    import colorsys

    accent_hex = (accent_hex or "").strip().lower()
    if not (accent_hex.startswith("#") and len(accent_hex) == 7):
        return False
    try:
        int(accent_hex[1:], 16)
    except ValueError:
        return False

    def _hsv(h: str) -> tuple[float, float, float]:
        r = int(h[1:3], 16) / 255
        g = int(h[3:5], 16) / 255
        b = int(h[5:7], 16) / 255
        return colorsys.rgb_to_hsv(r, g, b)

    base_h            = _hsv(_PALETTE_DEFAULTS["PRI"])[0]
    acc_h, acc_s, _av = _hsv(accent_hex)
    dh   = acc_h - base_h
    grey = acc_s < 0.08   # griye yakın accent → tüm tema desaturize edilir

    for key, hex0 in _PALETTE_DEFAULTS.items():
        h, s, v = _hsv(hex0)
        if grey:
            s *= 0.15
        r, g, b = colorsys.hsv_to_rgb((h + dh) % 1.0, s, v)
        setattr(C, key, "#{:02x}{:02x}{:02x}".format(
            int(r * 255 + 0.5), int(g * 255 + 0.5), int(b * 255 + 0.5)))
    return True

def current_palette() -> dict[str, str]:
    """C sınıfındaki accent'e bağlı renklerin anlık kopyası."""
    return {k: getattr(C, k) for k in _HUE_LINKED}

def retheme_all_widgets(old: dict[str, str], new: dict[str, str]) -> None:
    """
    CANLI tam tema değişimi. Uygulamadaki HER widget'ın stylesheet'inde eski
    palet renklerini yenileriyle değiştirir ve yeniden çizdirir. Böylece renk
    değişimi yalnızca boyanan öğelerde değil, panel/buton/kenarlık dahil tüm
    arayüzde ANINDA uygulanır — yeniden başlatma gerekmez.
    """
    mapping = {old[k].lower(): new[k].lower()
               for k in old if old[k].lower() != new.get(k, old[k]).lower()}
    if not mapping:
        return
    app = QApplication.instance()
    if app is None:
        return
    for w in app.allWidgets():
        try:
            ss = w.styleSheet()
            if ss:
                s2 = ss
                for o, n in mapping.items():
                    if o in s2:
                        s2 = s2.replace(o, n)
                if s2 != ss:
                    w.setStyleSheet(s2)
            w.update()
        except Exception:
            pass

def qcol(h: str, a: int = 255) -> QColor:
    c = QColor(h); c.setAlpha(a); return c

def _outline_nav_icon(kind: str, colour: str, size: int = 28) -> QIcon:
    """Create the small, legible outline icons used by the MICA rail."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(qcol(colour), 1.8)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    inset, span = 4.0, float(size - 8)
    if kind == "chat":
        painter.drawRoundedRect(QRectF(inset, inset + 1, span, span * .68), 6, 6)
        painter.drawLine(QPointF(size * .37, size * .73), QPointF(size * .30, size * .87))
        painter.drawLine(QPointF(size * .30, size * .87), QPointF(size * .51, size * .74))
        painter.setBrush(QBrush(qcol(colour)))
        for x in (.37, .50, .63):
            painter.drawEllipse(QRectF(size * x - 1.1, size * .38 - 1.1, 2.2, 2.2))
    elif kind == "history":
        painter.drawEllipse(QRectF(inset + 1, inset + 1, span - 2, span - 2))
        painter.drawLine(QPointF(size * .5, size * .5), QPointF(size * .5, size * .30))
        painter.drawLine(QPointF(size * .5, size * .5), QPointF(size * .64, size * .59))
        painter.drawLine(QPointF(size * .20, size * .36), QPointF(size * .12, size * .36))
        painter.drawLine(QPointF(size * .12, size * .36), QPointF(size * .16, size * .28))
    elif kind == "reminders":
        painter.drawRoundedRect(QRectF(inset + 1, inset + 3, span - 2, span - 4), 4, 4)
        painter.drawLine(QPointF(size * .28, size * .29), QPointF(size * .72, size * .29))
        painter.setBrush(QBrush(qcol(colour)))
        for x, y in ((.36, .49), (.50, .49), (.64, .49), (.36, .64), (.50, .64)):
            painter.drawEllipse(QRectF(size * x - 1.2, size * y - 1.2, 2.4, 2.4))
    elif kind == "memory":
        painter.drawRoundedRect(QRectF(inset + 1, inset + 2, span - 2, span - 4), 7, 7)
        painter.drawLine(QPointF(size * .40, size * .36), QPointF(size * .60, size * .36))
        painter.drawLine(QPointF(size * .36, size * .51), QPointF(size * .64, size * .51))
        painter.drawLine(QPointF(size * .40, size * .66), QPointF(size * .60, size * .66))
    else:
        centre = size / 2
        for index in range(8):
            angle = math.tau * index / 8
            inner, outer = size * .30, size * .42
            painter.drawLine(QPointF(centre + math.cos(angle) * inner, centre + math.sin(angle) * inner),
                             QPointF(centre + math.cos(angle) * outer, centre + math.sin(angle) * outer))
        painter.drawEllipse(QRectF(size * .28, size * .28, size * .44, size * .44))
        painter.drawEllipse(QRectF(size * .43, size * .43, size * .14, size * .14))
    painter.end()
    return QIcon(pixmap)
