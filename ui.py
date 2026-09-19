from __future__ import annotations

import json
import math
import os
import platform
import random
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import psutil

# Must run before importing PyQt6.  If Windows (or a launcher) already chose a
# process DPI context, Qt must not try to set it a second time.
from core.windows_dpi import configure_qt_dpi_startup

configure_qt_dpi_startup()

if platform.system() == "Windows":
    _WIN_HIDE: dict = {"creationflags": subprocess.CREATE_NO_WINDOW}
else:
    _WIN_HIDE: dict = {}

from PyQt6.QtCore import (
    QEasingCurve, QMimeData, QObject, QPointF, QRectF, QSize, Qt,
    QTimer, QUrl, pyqtSignal,
)
from PyQt6.QtGui import (
    QBrush, QColor, QConicalGradient, QDragEnterEvent, QDropEvent, QFont,
    QFontDatabase, QIcon, QKeySequence, QLinearGradient, QPainter, QPainterPath,
    QPen, QPixmap, QRadialGradient, QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QPushButton, QScrollArea, QSizePolicy, QSplitter,
    QStackedWidget, QTextEdit, QVBoxLayout, QWidget, QProgressBar, QStyle,
    QGraphicsDropShadowEffect,
)

def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent

BASE_DIR   = _base_dir()
CONFIG_DIR = BASE_DIR / "config"
API_FILE   = CONFIG_DIR / "api_keys.json"

PRESENCE_STATES = frozenset({
    "offline", "idle", "listening", "thinking", "approval_required", "executing", "speaking", "error",
})


def canonical_presence_state(state: str | None, *, speaking: bool = False, muted: bool = False) -> str:
    """Map legacy desktop voice labels onto the Phase-4 shared state machine."""
    value = (state or "idle").strip().lower()
    if speaking or value == "speaking":
        return "speaking"
    if value in {"offline", "sleeping", "disconnected"}:
        return "offline"
    if value in {"initialising", "connecting", "idle", "muted", "cancelled"} or muted:
        return "idle"
    if value in {"listening"}:
        return "listening"
    if value in {"thinking", "processing", "planning", "transcribing"}:
        return "thinking"
    if value in {"approval_required"}:
        return "approval_required"
    if value in {"executing"}:
        return "executing"
    if value in {"error", "failed"}:
        return "error"
    return "idle"


def day_presence_state(moment: datetime | None = None) -> str:
    hour = (moment or datetime.now().astimezone()).hour
    return "morning" if 5 <= hour < 11 else "day" if 11 <= hour < 18 else "evening" if 18 <= hour < 23 else "night"

def _read_full_config() -> dict:
    """Read api_keys.json config dict. Returns {} on any error."""
    try:
        return json.loads(API_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


_DEFAULT_W, _DEFAULT_H = 1440, 900
_MIN_W,     _MIN_H     = 960, 680
_LEFT_W  = 164
_RIGHT_W = 320

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"


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


def latest_project_context(memory_data: dict | None = None) -> tuple[str, str] | None:
    """Return the newest real project saved in long-term memory.

    The HUD deliberately has no demonstration project: if memory has not yet
    recorded a project, callers receive ``None`` and render a clear empty
    state instead.
    """
    try:
        if memory_data is None:
            from memory.memory_manager import load_memory
            memory_data = load_memory()
        projects = (memory_data or {}).get("projects", {})
        if not isinstance(projects, dict):
            return None
        entries: list[tuple[str, int, str, str]] = []
        for position, (key, entry) in enumerate(projects.items()):
            if isinstance(entry, dict):
                value = str(entry.get("value", "") or "").strip()
                updated = str(entry.get("updated_at") or entry.get("updated", "") or "")
            else:
                value, updated = str(entry or "").strip(), ""
            if value:
                entries.append((updated, position, str(key), value))
        if not entries:
            return None
        _updated, _position, key, value = max(entries, key=lambda item: (item[0], item[1]))
        return key.replace("_", " ").strip().title(), value
    except Exception:
        return None


def next_reminder_context() -> tuple[str, str] | None:
    """Read the local reminder index without inventing a calendar entry."""
    try:
        from actions.reminder import list_upcoming_reminders
        reminders = list_upcoming_reminders(limit=1)
        if not reminders:
            return None
        reminder = reminders[0]
        return str(reminder["when"]), str(reminder["message"])
    except Exception:
        return None


# Ana renge (accent) bağlı anahtarlar — durum renkleri (ACC, GREEN, RED…) sabit kalır
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


# ── Windows GPU via NVML DLL (no subprocess, no console window) ──────────────
_nvml_lib: object = None   # cached ctypes DLL
_nvml_ok:  object = None   # None=untested, True=works, False=unavailable


def _nvml_gpu_windows() -> float:
    """Return NVIDIA GPU utilisation % using nvml.dll directly — zero subprocess."""
    global _nvml_lib, _nvml_ok
    if _nvml_ok is False:
        return -1.0
    try:
        import ctypes

        class _Util(ctypes.Structure):
            _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

        if _nvml_lib is None:
            for dll_name in ("nvml", r"C:\Windows\System32\nvml.dll"):
                try:
                    lib = ctypes.WinDLL(dll_name)
                    lib.nvmlInit_v2()
                    _nvml_lib = lib
                    break
                except Exception:
                    continue

        if _nvml_lib is None:
            import pynvml  # type: ignore
            pynvml.nvmlInit()
            h = pynvml.nvmlDeviceGetHandleByIndex(0)
            _nvml_ok = True
            return float(pynvml.nvmlDeviceGetUtilizationRates(h).gpu)

        dev = ctypes.c_void_p()
        _nvml_lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(dev))
        util = _Util()
        _nvml_lib.nvmlDeviceGetUtilizationRates(dev, ctypes.byref(util))
        _nvml_ok = True
        return float(util.gpu)
    except Exception:
        _nvml_ok = False
        return -1.0


class _SysMetrics:
    def __init__(self):
        self.cpu  = 0.0
        self.mem  = 0.0
        self.net  = 0.0
        self.gpu  = -1.0
        self.tmp  = -1.0
        self._lock = threading.Lock()
        self._last_net = psutil.net_io_counters()
        self._last_net_t = time.time()
        self._running = True
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()

    def _loop(self):
        while self._running:
            try:
                self._update()
            except Exception:
                pass
            time.sleep(1.5)

    def _update(self):
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent

        nc  = psutil.net_io_counters()
        now = time.time()
        dt  = now - self._last_net_t
        if dt > 0:
            sent = (nc.bytes_sent - self._last_net.bytes_sent) / dt
            recv = (nc.bytes_recv - self._last_net.bytes_recv) / dt
            net  = (sent + recv) / (1024 * 1024)
        else:
            net = 0.0
        self._last_net   = nc
        self._last_net_t = now

        gpu = self._get_gpu()

        tmp = self._get_temp()

        with self._lock:
            self.cpu = cpu
            self.mem = mem
            self.net = net
            self.gpu = gpu
            self.tmp = tmp

    def _get_gpu(self) -> float:
        # pynvml — subprocess-free, works on all platforms if installed
        try:
            import pynvml  # type: ignore
            pynvml.nvmlInit()
            h = pynvml.nvmlDeviceGetHandleByIndex(0)
            return float(pynvml.nvmlDeviceGetUtilizationRates(h).gpu)
        except Exception:
            pass

        # Windows: nvml.dll via ctypes (already cached in _nvml_gpu_windows)
        if _OS == "Windows":
            return _nvml_gpu_windows()

        # Linux / macOS: libnvidia-ml shared lib via ctypes
        try:
            import ctypes
            _lib = "libnvidia-ml.so.1" if _OS == "Linux" else "libnvidia-ml.dylib"

            class _Util(ctypes.Structure):
                _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

            nv = ctypes.CDLL(_lib)
            nv.nvmlInit_v2()
            dev = ctypes.c_void_p()
            nv.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(dev))
            u = _Util()
            nv.nvmlDeviceGetUtilizationRates(dev, ctypes.byref(u))
            return float(u.gpu)
        except Exception:
            pass

        return -1.0   # N/A — zero subprocess on all platforms

    def _get_temp(self) -> float:
        # psutil — works on Linux; occasionally Windows with driver support
        try:
            temps = psutil.sensors_temperatures()
            for name in ["coretemp", "k10temp", "cpu_thermal", "acpitz",
                         "cpu-thermal", "zenpower", "it8688"]:
                if name in temps and temps[name]:
                    return temps[name][0].current
            for entries in temps.values():
                if entries:
                    return entries[0].current
        except Exception:
            pass

        # Windows: wmi module (pure Python COM, zero subprocess)
        if _OS == "Windows":
            try:
                import wmi  # type: ignore
                w = wmi.WMI(namespace="root/wmi")
                tz = w.MSAcpi_ThermalZoneTemperature()
                if tz:
                    return (tz[0].CurrentTemperature / 10.0) - 273.15
            except Exception:
                pass

        return -1.0   # N/A — zero subprocess on all platforms

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "cpu": self.cpu,
                "mem": self.mem,
                "net": self.net,
                "gpu": self.gpu,
                "tmp": self.tmp,
            }


_metrics = _SysMetrics()

class HudCanvas(QWidget):
    def __init__(self, face_path: str, assistant_name: str = "J.A.R.V.I.S", parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.muted    = False
        self.speaking = False
        self.state    = "INITIALISING"
        self._assistant_name = assistant_name

        self._tick       = 0
        self._scale      = 1.0
        self._tgt_scale  = 1.0
        self._halo       = 55.0
        self._tgt_halo   = 55.0
        self._last_t     = time.time()
        self._scan       = 0.0
        self._scan2      = 180.0
        self._rings      = [0.0, 120.0, 240.0]
        self._pulses: list[float] = [0.0, 50.0, 100.0]
        self._blink      = True
        self._blink_tick = 0
        self._particles: list[list[float]] = []
        self._face_px: QPixmap | None = None
        self._face_source: Path | None = None
        self._load_face(face_path)
        self.reduced_motion = bool(_read_full_config().get("reduced_motion", False))
        self._flow_phase = 0.0

        # An assistant should have a calm presence even between turns.  These
        # values drive a very small gaze drift and natural, non-looping blinks.
        self._gaze_x = self._gaze_y = 0.0
        self._gaze_target_x = self._gaze_target_y = 0.0
        self._next_gaze = time.time() + 1.5
        self._blink_until = 0.0
        self._next_face_blink = time.time() + random.uniform(2.2, 4.5)

        # Live audio reactivity: _live_amp is written from the audio threads
        # (0.0–1.0), _amp_disp is the smoothed value the paint code reads.
        self._live_amp  = 0.0
        self._amp_disp  = 0.0
        self._base_scale = 1.0    # slow "breathing" target; amp is added per-frame
        self._base_halo  = 55.0

        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._tmr.start(16)

    def set_audio_level(self, level: float) -> None:
        """Thread-safe entry point for the audio threads. Stores the louder of
        the incoming level and the current value so brief gaps between chunks
        don't make the waveform stutter; _step() decays it back down."""
        try:
            lv = float(level)
        except (TypeError, ValueError):
            return
        if lv < 0.0:
            lv = 0.0
        elif lv > 1.0:
            lv = 1.0
        if lv > self._live_amp:
            self._live_amp = lv

    def _load_face(self, path: str):
        try:
            from PIL import Image, ImageDraw, ImageChops
            import io
            # The HUD has its own friendly Mica portrait.  The caller-provided
            # face remains a fallback for installations that predate the asset.
            mica_asset = BASE_DIR / "assets" / "mica-orb-v2.png"
            source = mica_asset if mica_asset.exists() else Path(path)
            self._face_source = source
            img = Image.open(source).convert("RGBA")
            sz  = min(img.size)
            img = img.resize((sz, sz), Image.LANCZOS)
            mk  = Image.new("L", (sz, sz), 0)
            ImageDraw.Draw(mk).ellipse((2, 2, sz - 2, sz - 2), fill=255)
            # Preserve the asset's transparent exterior; replacing alpha with
            # a plain circle turns transparent pixels into a visible black disk.
            img.putalpha(ImageChops.multiply(img.getchannel("A"), mk))
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            px = QPixmap(); px.loadFromData(buf.getvalue())
            self._face_px = px
        except Exception:
            self._face_px = None

    def _step(self):
        self._tick += 1
        now = time.time()

        # ── Live audio reactivity ────────────────────────────────────────────
        # Audio threads push peaks into _live_amp; decay it toward silence so
        # gaps between chunks fade out instead of freezing, then smooth it.
        self._live_amp *= 0.86
        self._amp_disp += (self._live_amp - self._amp_disp) * 0.45
        amp = self._amp_disp

        # Each conversational state uses the same audio value, but gives it a
        # distinct intensity and pace.  That makes the central presence, the
        # text and every waveform tell the same story.
        if now - self._last_t > (0.12 if self.speaking else 0.5):
            if self.speaking:
                self._base_scale = 1.03
                self._base_halo  = 122.0
            elif self.state == "PROCESSING":
                self._base_scale = 1.010
                self._base_halo = 92.0
            elif self.state == "THINKING":
                self._base_scale = 1.004
                self._base_halo = 76.0
            elif self.state == "LISTENING":
                self._base_scale = 1.006
                self._base_halo = 70.0
            elif self.muted:
                self._base_scale = 1.0
                self._base_halo  = 22.0
            else:
                self._base_scale = 1.002
                self._base_halo  = 54.0
            self._last_t = now

        # Every frame, the live audio level lifts the target on top of the base
        # — this is what makes the core visibly pulse to the actual voice.
        if self.muted:
            self._tgt_scale, self._tgt_halo = self._base_scale, self._base_halo
        elif self.speaking:
            self._tgt_scale = self._base_scale + amp * 0.13
            self._tgt_halo  = self._base_halo  + amp * 95.0
        else:
            self._tgt_scale = self._base_scale + amp * 0.06
            self._tgt_halo  = self._base_halo  + amp * 75.0

        sp = 0.38 if self.speaking else (0.30 if amp > 0.02 else 0.15)
        self._scale += (self._tgt_scale - self._scale) * sp
        self._halo  += (self._tgt_halo  - self._halo)  * sp

        # Rings/scanners spin faster while speaking, reacting to loudness.
        boost  = 1.0 + amp * 1.6
        motion = .22 if self.reduced_motion else 1.0
        state_speed = {"LISTENING": 1.0, "THINKING": .55, "PROCESSING": 1.3,
                       "SPEAKING": 1.7, "MUTED": .18}.get(self.state, .7)
        speeds = ([1.3, -0.9, 2.0] if self.speaking else [0.55, -0.35, 0.9])
        for i, spd in enumerate(speeds):
            self._rings[i] = (self._rings[i] + spd * boost * motion * state_speed) % 360

        self._flow_phase = (self._flow_phase + (.010 + amp * .035) * motion * state_speed) % (2 * math.pi)
        self._scan  = (self._scan  + (3.0 if self.speaking else 1.3) * boost * motion) % 360
        self._scan2 = (self._scan2 + (-2.0 if self.speaking else -0.75) * boost * motion) % 360

        fw  = min(self.width(), self.height())
        lim = fw * 0.74
        spd = (4.2 if self.speaking else 2.0) * motion
        self._pulses = [r + spd for r in self._pulses if r + spd < lim]
        if len(self._pulses) < 3 and random.random() < (0.07 if self.speaking else 0.025):
            self._pulses.append(0.0)

        # In reduced-motion mode the drifting accent particles are both rarer
        # and slower.  The aura still communicates real audio activity, but
        # it no longer creates distracting independent movement.
        if self.speaking and random.random() < (0.28 * motion):
            cx, cy = self.width() / 2, self.height() / 2
            ang = random.uniform(0, 2 * math.pi)
            r_s = fw * 0.28
            self._particles.append([
                cx + math.cos(ang) * r_s, cy + math.sin(ang) * r_s,
                math.cos(ang) * random.uniform(0.9, 2.4) * motion,
                (math.sin(ang) * random.uniform(0.9, 2.4) - 0.4) * motion, 1.0,
            ])
        self._particles = [
            [p[0]+p[2], p[1]+p[3], p[2]*0.97, p[3]*0.97, p[4]-0.028]
            for p in self._particles if p[4] > 0
        ]

        # Idle behaviour is intentionally understated: a glance every few
        # seconds, then a relaxed return to centre.  While actively listening
        # or speaking Mica stays focused on the user.
        if self.speaking or self.state == "LISTENING":
            self._gaze_target_x, self._gaze_target_y = 0.0, 0.0
        elif now >= self._next_gaze:
            self._gaze_target_x = random.uniform(-0.16, 0.16)
            self._gaze_target_y = random.uniform(-0.08, 0.10)
            self._next_gaze = now + random.uniform(1.8, 4.2)
        self._gaze_x += (self._gaze_target_x - self._gaze_x) * .055
        self._gaze_y += (self._gaze_target_y - self._gaze_y) * .055
        if now >= self._next_face_blink:
            self._blink_until = now + .13
            self._next_face_blink = now + random.uniform(2.6, 5.4)

        self._blink_tick += 1
        if self._blink_tick >= 38:
            self._blink = not self._blink
            self._blink_tick = 0
        self.update()

    def _draw_flow_ribbons(self, painter: QPainter, cx: float, cy: float,
                           radius: float, colour: str) -> None:
        """Draw the reference-like, slow moving aura from the actual level.

        The paths intentionally share a single phase.  That makes the field
        feel like one calm audio surface rather than decorative random rings.
        """
        amp = self._amp_disp
        motion = .22 if self.reduced_motion else 1.0
        state_gain = 1.45 if self.speaking else (1.15 if self.state == "LISTENING" else .82)
        if self.muted:
            state_gain = .25
        for line in range(30):
            fraction = line / 29.0
            base = radius * (.88 + fraction * .36)
            drift_x = radius * .055 * math.sin(fraction * math.pi * 2 + self._flow_phase * .22)
            drift_y = radius * .035 * math.cos(fraction * math.pi * 2 - self._flow_phase * .18)
            path = QPainterPath()
            steps = 112
            for step in range(steps + 1):
                theta = 2 * math.pi * step / steps
                ripple = (math.sin(theta * 3 + self._flow_phase * (1.0 + fraction)
                                   + fraction * 3.8) * .058
                          + math.sin(theta * 5 - self._flow_phase * 1.7
                                     + fraction * 5.6) * .036)
                audio_ripple = amp * state_gain * math.sin(theta * 2 + self._flow_phase * 2.4) * .072
                r = base * (1.0 + ripple * motion + audio_ripple)
                x = cx + drift_x + math.cos(theta) * r * (
                    1.0 + .12 * math.sin(theta + fraction * 3.7 + self._flow_phase * .12)
                )
                y = cy + drift_y + math.sin(theta) * r * (
                    .90 + .085 * math.cos(theta * 2 - fraction * 2.8)
                )
                if step == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
            alpha = 15 + int(18 * (1 - abs(fraction - .5) * 1.5))
            painter.setPen(QPen(qcol(colour, max(5, alpha)), 0.72))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

    def _draw_asset_expression(self, painter: QPainter, cx: float, cy: float, size: float) -> None:
        """Layer a small stateful expression over the high-resolution Mica asset.

        The asset supplies material, light and friendly identity; this vector
        layer keeps the mouth visibly alive while speaking or thinking without
        mutating the source image.  It is deliberately subtle at HUD scale.
        """
        mouth_y = cy + size * .125
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(qcol("#dcecff", 158)))
        painter.drawEllipse(QRectF(cx - size * .115, mouth_y - size * .052,
                                  size * .23, size * .105))
        pen = QPen(qcol("#17355f", 220), max(1.5, size * .018))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        if self.muted:
            painter.setPen(QPen(qcol(C.MUTED_C, 220), max(1.5, size * .018)))
            painter.drawLine(QPointF(cx - size * .065, mouth_y), QPointF(cx + size * .065, mouth_y))
        elif self.speaking:
            openness = size * (.026 + self._amp_disp * .05 + .012 * math.sin(self._tick * .5))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(qcol("#163868", 220)))
            painter.drawRoundedRect(QRectF(cx - size * .065, mouth_y - openness,
                                           size * .13, max(size * .026, openness * 2)),
                                  size * .035, size * .035)
        elif self.state == "THINKING":
            painter.setPen(pen)
            painter.drawLine(QPointF(cx - size * .055, mouth_y), QPointF(cx + size * .055, mouth_y))
        elif self.state == "PROCESSING":
            painter.setPen(pen)
            painter.drawArc(QRectF(cx - size * .07, mouth_y - size * .025,
                                   size * .14, size * .08), 180 * 16, 180 * 16)
        else:
            painter.setPen(pen)
            painter.drawArc(QRectF(cx - size * .07, mouth_y - size * .04,
                                   size * .14, size * .095), 205 * 16, 130 * 16)

    def paintEvent(self, _):
        p = QPainter(self)
        if not p.isActive():      # device not ready (e.g. 0-size during layout) — skip cleanly
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # A daylight canvas lets the voice state, rather than UI chrome, lead.
        bg = QRadialGradient(self.width() * .5, self.height() * .42,
                             max(self.width(), self.height()) * .72)
        bg.setColorAt(0.0, qcol("#f7faff"))
        bg.setColorAt(0.48, qcol("#fbfdff"))
        bg.setColorAt(1.0, qcol("#ffffff"))
        p.fillRect(self.rect(), QBrush(bg))

        W, H = self.width(), self.height()
        cx, cy = W / 2, H * .33
        fw = min(W, H)
        # Match the reference hierarchy: Mica is the central hero, not a
        # toolbar-sized icon.
        r_orb = fw * .205
        state_col = (C.MUTED_C if self.muted else
                     (C.TEXT_DIM if self.state in ("SLEEPING", "OFFLINE", "DISCONNECTED")
                      else C.PRI))

        # The broad, translucent field replaces technical HUD chrome.  It is
        # deliberately rendered before the portrait so it stays soft and airy.
        # The supplied reference keeps the portrait high in the composition,
        # while the much larger audio field is visually centred lower down.
        # Separating those two centres prevents the aura from being clipped at
        # the top edge and preserves the quiet white canvas around it.
        self._draw_flow_ribbons(p, cx, H * .41, fw * .37, state_col)

        # Diffuse halo and a pair of quiet construction rings.
        for i in range(8, 0, -1):
            r = r_orb * (1.15 + i * .105)
            alpha = int((10 + self._halo * .24) * (i / 8))
            p.setPen(QPen(qcol(state_col, max(0, min(80, alpha))), 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        p.setBrush(QBrush(qcol("#ffffff", 218)))
        p.setPen(QPen(qcol(C.BORDER, 235), 1))
        p.drawEllipse(QRectF(cx-r_orb, cy-r_orb, r_orb*2, r_orb*2))

        for idx, (frac, width, span) in enumerate(((1.34, 3, 104), (1.13, 1, 72))):
            radius = r_orb * frac
            p.setPen(QPen(qcol(state_col, 215 if idx == 0 else 135), width))
            p.setBrush(Qt.BrushStyle.NoBrush)
            rect = QRectF(cx-radius, cy-radius, radius*2, radius*2)
            p.drawArc(rect, int(self._rings[idx] * 16), int(span * 16))
            p.drawArc(rect, int((self._rings[idx] + 180) * 16), int(span * 16))

        # Gentle outward ripples communicate actual microphone / speaker activity.
        for pr in self._pulses:
            radius = r_orb + pr * .52
            alpha = int(76 * (1.0 - pr / max(1, fw * .74)))
            p.setPen(QPen(qcol(state_col, max(0, alpha)), 1))
            p.drawEllipse(QRectF(cx-radius, cy-radius, radius*2, radius*2))

        # face
        if self._face_px:
            fsz    = int(r_orb * 1.55 * self._scale)
            scaled = self._face_px.scaled(
                fsz, fsz,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            p.drawPixmap(int(cx - fsz / 2), int(cy - fsz / 2), scaled)
            # Preserve the supplied face exactly. State remains visible in the
            # reactive aura and waveform without painting a second mouth over it.
        else:
            # A small code-native 3D portrait: deliberately soft and friendly,
            # not a realistic human. It remains animated even without an image
            # asset and uses the live audio amplitude for its speaking mouth.
            head_r = r_orb * .64 * self._scale
            head = QRadialGradient(cx - head_r*.27, cy - head_r*.35, head_r*1.45)
            head.setColorAt(0.0, qcol("#ffffff"))
            head.setColorAt(.52, qcol("#deedff"))
            head.setColorAt(1.0, qcol("#a9c9f4"))
            p.setBrush(QBrush(head))
            p.setPen(QPen(qcol("#9fc3f0", 180), 1))
            p.drawEllipse(QRectF(cx-head_r*.78, cy-head_r, head_r*1.56, head_r*2.02))

            # Side plane and highlight make the portrait read as a softly lit
            # object rather than a flat icon.
            p.setBrush(QBrush(qcol("#7faee9", 58)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QRectF(cx+head_r*.19, cy-head_r*.76, head_r*.51, head_r*1.48))
            p.setBrush(QBrush(qcol("#ffffff", 120)))
            p.drawEllipse(QRectF(cx-head_r*.50, cy-head_r*.70, head_r*.38, head_r*.50))

            eye_y = cy - head_r*.08 + self._gaze_y * head_r
            eye_dx = head_r*.29
            pupil_dx = self._gaze_x * head_r*.32
            blinked = time.time() < self._blink_until
            p.setPen(QPen(qcol("#45698e"), max(1, int(head_r*.045))))
            p.setBrush(QBrush(qcol("#ffffff", 220)))
            for sign in (-1, 1):
                ex = cx + sign*eye_dx
                if blinked:
                    p.drawLine(QPointF(ex-head_r*.11, eye_y), QPointF(ex+head_r*.11, eye_y))
                else:
                    p.drawEllipse(QRectF(ex-head_r*.12, eye_y-head_r*.085, head_r*.24, head_r*.17))
                    p.setBrush(QBrush(qcol("#365d88")))
                    p.setPen(Qt.PenStyle.NoPen)
                    p.drawEllipse(QRectF(ex-head_r*.035+pupil_dx, eye_y-head_r*.032,
                                         head_r*.07, head_r*.07))
                    p.setBrush(QBrush(qcol("#ffffff", 220)))
                    p.setPen(QPen(qcol("#45698e"), max(1, int(head_r*.045))))

            # Brows lift very slightly while listening; the mouth opens only
            # when audio is actually playing, so the avatar follows the turn.
            brow_y = eye_y - head_r*.20
            brow_lift = -head_r*.05 if self.state == "LISTENING" else 0
            p.setPen(QPen(qcol("#5e83aa", 180), max(1, int(head_r*.025))))
            p.drawLine(QPointF(cx-eye_dx-head_r*.11, brow_y),
                       QPointF(cx-eye_dx+head_r*.10, brow_y+brow_lift))
            p.drawLine(QPointF(cx+eye_dx-head_r*.10, brow_y+brow_lift),
                       QPointF(cx+eye_dx+head_r*.11, brow_y))

            mouth_y = cy + head_r*.39
            if self.speaking:
                openness = head_r * (.055 + self._amp_disp*.12 + .025*math.sin(self._tick*.5))
                p.setBrush(QBrush(qcol("#6e91b9", 180)))
                p.setPen(Qt.PenStyle.NoPen)
                p.drawRoundedRect(QRectF(cx-head_r*.16, mouth_y-openness/2,
                                         head_r*.32, max(head_r*.06, openness)),
                                  head_r*.08, head_r*.08)
            else:
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.setPen(QPen(qcol("#6e91b9", 195), max(1, int(head_r*.027))))
                p.drawArc(QRectF(cx-head_r*.18, mouth_y-head_r*.08,
                                 head_r*.36, head_r*.20), 200 * 16, 140 * 16)

        # particles
        for pt in self._particles:
            a = max(0, min(255, int(pt[4] * 255)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(C.PRI, a)))
            p.drawEllipse(QPointF(pt[0], pt[1]), 2.5, 2.5)

        # Normal-language states make the AI's turn in a conversation legible.
        # Keep the conversational copy clearly below Mica rather than visually
        # attached to the orb.  The offset scales with the HUD, so it also
        # remains balanced when the window is resized.
        sy = cy + r_orb * 1.28
        if self.muted:
            txt, sub, col = "Mikrofon ist pausiert", "Tippe oder aktiviere das Mikrofon.", qcol(C.MUTED_C)
        elif self.state in ("SLEEPING", "OFFLINE", "DISCONNECTED"):
            txt, sub, col = "Mica ist nicht verbunden", "Die Verbindung wird wiederhergestellt.", qcol(C.TEXT_MED)
        elif self.speaking:
            txt, sub, col = f"{self._assistant_name} spricht", "Du kannst jederzeit unterbrechen.", qcol(C.ACC)
        elif self.state == "THINKING":
            txt, sub, col = "Ich denke nach", "Einen Moment bitte.", qcol(C.ACC)
        elif self.state == "PROCESSING":
            txt, sub, col = "Ich bearbeite das", "Ich halte dich auf dem Laufenden.", qcol(C.ACC)
        elif self.state == "LISTENING":
            txt, sub, col = f"Hallo, ich bin {self._assistant_name}.", "Ich höre zu und bin bereit zu antworten.", qcol(C.TEXT)
        else:
            txt, sub, col = f"Hallo, ich bin {self._assistant_name}.", "Wie kann ich dir helfen?", qcol(C.TEXT)

        # The reference uses a confident, dark display line rather than an
        # accent-coloured caption.  State colour remains visible in the aura,
        # portrait rings and waveform, while the primary message stays calm
        # and readable at both the reference and minimum window sizes.
        p.setPen(QPen(col, 1)); p.setFont(QFont("Segoe UI", 27, QFont.Weight.DemiBold))
        p.drawText(QRectF(0, sy, W, 48), Qt.AlignmentFlag.AlignCenter, txt)
        p.setPen(QPen(qcol(C.TEXT_MED), 1)); p.setFont(QFont("Segoe UI", 11))
        p.drawText(QRectF(0, sy + 48, W, 24), Qt.AlignmentFlag.AlignCenter, sub)

        # waveform — reacts to the real audio level (mic while listening,
        # JARVIS's own voice while speaking). Falls back to a gentle idle
        # ripple when there's no sound. _amp_disp is the smoothed 0–1 level.
        wy = sy + 105
        N, bw = 31, 7
        wx0 = (W - N * bw) / 2
        amp = self._amp_disp
        mid = (N - 1) / 2.0
        for i in range(N):
            if self.muted:
                hgt, cl = 2, qcol(C.MUTED_C)
            else:
                env     = (1.0 - abs(i - mid) / mid) ** 0.7      # center-weighted hump
                shimmer = 0.55 + 0.45 * math.sin(self._tick * 0.18 + i * 0.7)
                idle    = 3.0 + 2.0 * math.sin(self._tick * 0.09 + i * 0.6)
                hgt     = int(max(2, min(18, idle + amp * 17.0 * env * shimmer)))
                if amp > 0.05:
                    cl = qcol(C.PRI) if hgt > 12 else qcol(C.PRI_DIM)
                else:
                    cl = qcol(C.BORDER_B)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(cl))
            p.drawRoundedRect(QRectF(wx0 + i * bw, wy + 14 - hgt / 2, bw - 2, hgt), 2, 2)

        p.end()   # end deterministically so the backing store never flushes an active painter

class MetricBar(QWidget):

    def __init__(self, label: str, color: str = C.PRI, parent=None):
        super().__init__(parent)
        self._label = label
        self._color = color
        self._value = 0.0       # 0–100
        self._text  = "--"
        self.setFixedHeight(38)
        self.setMinimumWidth(80)

    def set_value(self, pct: float, text: str):
        self._value = max(0.0, min(100.0, pct))
        self._text  = text
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        if not p.isActive():
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        p.setBrush(QBrush(qcol(C.PANEL2)))
        p.setPen(QPen(qcol(C.BORDER_A), 1))
        p.drawRoundedRect(QRectF(1, 1, W - 2, H - 2), 4, 4)

        bar_h   = 4
        bar_y   = H - bar_h - 5
        bar_w   = W - 12
        bar_x   = 6
        fill_w  = int(bar_w * self._value / 100)

        p.setBrush(QBrush(qcol(C.BAR_BG)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), 2, 2)

        if self._value > 85:
            bar_col = qcol(C.RED)
        elif self._value > 65:
            bar_col = qcol(C.ACC)
        else:
            bar_col = qcol(self._color)

        if fill_w > 0:
            p.setBrush(QBrush(bar_col))
            p.drawRoundedRect(QRectF(bar_x, bar_y, fill_w, bar_h), 2, 2)

        p.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(8, 5, 50, 14), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._label)

        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(bar_col if self._text != "--" else qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(0, 4, W - 6, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, self._text)

        p.end()

class LogWidget(QTextEdit):
    _sig = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Courier New", 9))
        self.setStyleSheet(f"""
            QTextEdit {{
                background: {C.PANEL};
                color: {C.TEXT};
                border: 1px solid {C.BORDER};
                border-radius: 4px;
                padding: 6px;
                selection-background-color: {C.PRI_GHO};
            }}
            QScrollBar:vertical {{
                background: {C.BG};
                width: 8px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {C.BORDER_B};
                border-radius: 4px;
                min-height: 20px;
            }}
        """)
        self._queue: list[str] = []
        self._typing  = False
        self._text    = ""
        self._pos     = 0
        self._tag     = "sys"
        self._ai_name_lc = "jarvis"   # updated when assistant name changes
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._sig.connect(self._enqueue)

    def append_log(self, text: str):
        self._sig.emit(text)

    def _enqueue(self, text: str):
        self._queue.append(text)
        if not self._typing:
            self._next()

    def _next(self):
        if not self._queue:
            self._typing = False
            return
        self._typing = True
        self._text   = self._queue.pop(0)
        self._pos    = 0
        tl = self._text.lower()
        _ai_pfx = f"{self._ai_name_lc}:"
        if   tl.startswith("you:"):                              self._tag = "you"
        elif tl.startswith(_ai_pfx) or tl.startswith("jarvis:"): self._tag = "ai"
        elif tl.startswith("file:"):                             self._tag = "file"
        elif "err" in tl:                                        self._tag = "err"
        else:                                                    self._tag = "sys"
        self._tmr.start(6)

    def _step(self):
        if self._pos < len(self._text):
            ch  = self._text[self._pos]
            cur = self.textCursor()
            fmt = cur.charFormat()
            col = {
                "you":  qcol(C.WHITE),
                "ai":   qcol(C.PRI),
                "err":  qcol(C.RED),
                "file": qcol(C.GREEN),
                "sys":  qcol(C.ACC2),
            }.get(self._tag, qcol(C.TEXT))
            fmt.setForeground(QBrush(col))
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText(ch, fmt)
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            self._pos += 1
        else:
            self._tmr.stop()
            cur = self.textCursor()
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText("\n")
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            QTimer.singleShot(20, self._next)


class ComposerInput(QLineEdit):
    """The message field is also the unobtrusive file-drop target."""
    file_dropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path and Path(path).is_file():
                self.file_dropped.emit(path)
                event.acceptProposedAction()
                return
        super().dropEvent(event)


class LiveWaveform(QWidget):
    """A small, real-level waveform used by context and the composer."""
    def __init__(self, compact: bool = False, parent=None):
        super().__init__(parent)
        self._level = 0.0
        self._display = 0.0
        self._phase = 0.0
        self._compact = compact
        self._muted = False
        self.setMinimumHeight(34 if compact else 48)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)
        self._timer.start(33)

    def set_level(self, level: float) -> None:
        self._level = max(0.0, min(1.0, float(level)))

    def set_muted(self, muted: bool) -> None:
        self._muted = muted
        self.update()

    def _step(self) -> None:
        self._display += (self._level - self._display) * .35
        self._level *= .88
        self._phase += .12 if not self._muted else .035
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        if not p.isActive():
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        count = 14 if self._compact else 34
        gap = max(3.0, W / max(1, count))
        mid = (count - 1) / 2
        base_col = C.MUTED_C if self._muted else C.PRI
        for index in range(count):
            envelope = .35 + .65 * (1.0 - abs(index - mid) / max(1, mid))
            rhythm = .35 + .65 * abs(math.sin(self._phase + index * .56))
            idle = 2.5 + 1.3 * abs(math.sin(self._phase * .35 + index))
            height = idle if self._muted else min(H * .82, idle + self._display * H * envelope * rhythm)
            alpha = 80 if self._muted else int(90 + 150 * min(1, self._display + .20))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(base_col, alpha)))
            p.drawRoundedRect(QRectF(index * gap + gap * .25, (H - height) / 2,
                                    max(2, gap * .36), height), 2, 2)
        p.end()


def _context_card(icon: QStyle.StandardPixmap, title: str, detail: str,
                  parent: QWidget | None = None,
                  minimum_height: int = 76) -> tuple[QFrame, QLabel, QLabel]:
    """Build one consistent, readable context card from real HUD data."""
    card = QFrame(parent)
    card.setObjectName("ContextCard")
    card.setMinimumHeight(minimum_height)
    card.setStyleSheet(f"""
        QFrame#ContextCard {{
            background: {C.PANEL}; border: 1px solid {C.BORDER}; border-radius: 12px;
        }}
    """)
    layout = QHBoxLayout(card)
    layout.setContentsMargins(12, 12, 12, 12)
    layout.setSpacing(10)
    icon_label = QLabel()
    icon_label.setFixedSize(34, 34)
    icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    icon_label.setPixmap(QApplication.style().standardIcon(icon).pixmap(22, 22))
    icon_label.setStyleSheet(f"background: {C.PRI_GHO}; border: none; border-radius: 9px;")
    layout.addWidget(icon_label, alignment=Qt.AlignmentFlag.AlignTop)
    words = QVBoxLayout()
    words.setSpacing(3)
    heading = QLabel(title)
    heading.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
    heading.setStyleSheet(f"color: {C.TEXT}; background: transparent; border: none;")
    heading.setWordWrap(True)
    body = QLabel(detail)
    body.setFont(QFont("Segoe UI", 8))
    body.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent; border: none;")
    body.setWordWrap(True)
    words.addWidget(heading)
    words.addWidget(body)
    layout.addLayout(words, stretch=1)
    return card, heading, body

_FILE_ICONS = {
    "image":   ("🖼", "#00d4ff"), "video":   ("🎬", "#ff6b00"),
    "audio":   ("🎵", "#cc44ff"), "pdf":     ("📄", "#ff4444"),
    "word":    ("📝", "#4488ff"), "excel":   ("📊", "#44bb44"),
    "code":    ("💻", "#ffcc00"), "archive": ("📦", "#ff8844"),
    "pptx":    ("📊", "#ff6622"), "text":    ("📃", "#aaaaaa"),
    "data":    ("🔧", "#88ddff"), "unknown": ("📎", "#888888"),
}
_EXT_TO_CAT = {
    **dict.fromkeys(["jpg","jpeg","png","gif","webp","bmp","tiff","svg","ico"], "image"),
    **dict.fromkeys(["mp4","avi","mov","mkv","wmv","flv","webm","m4v"],         "video"),
    **dict.fromkeys(["mp3","wav","ogg","m4a","aac","flac","wma","opus"],        "audio"),
    **dict.fromkeys(["pdf"],                                                     "pdf"),
    **dict.fromkeys(["doc","docx"],                                              "word"),
    **dict.fromkeys(["xls","xlsx","ods"],                                        "excel"),
    **dict.fromkeys(["ppt","pptx"],                                              "pptx"),
    **dict.fromkeys(["py","js","ts","jsx","tsx","html","css","java","c","cpp",
                     "cs","go","rs","rb","php","swift","kt","sh","sql","lua"],   "code"),
    **dict.fromkeys(["zip","rar","tar","gz","7z","bz2","xz"],                   "archive"),
    **dict.fromkeys(["txt","md","rst","log"],                                    "text"),
    **dict.fromkeys(["csv","tsv","json","xml"],                                  "data"),
}

def _file_category(path: Path) -> str:
    return _EXT_TO_CAT.get(path.suffix.lower().lstrip("."), "unknown")

def _fmt_size(size: int) -> str:
    if   size < 1024:    return f"{size} B"
    elif size < 1024**2: return f"{size/1024:.1f} KB"
    elif size < 1024**3: return f"{size/1024**2:.1f} MB"
    else:                return f"{size/1024**3:.1f} GB"


class FileDropZone(QWidget):
    file_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(100)
        self._current_file: str | None = None
        self._hovering  = False
        self._drag_over = False
        self._dash_offset = 0.0
        self._anim_tmr = QTimer(self)
        self._anim_tmr.timeout.connect(self._animate)
        self._anim_tmr.start(40)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._canvas = _DropCanvas(self)
        layout.addWidget(self._canvas)

    def _animate(self):
        self._dash_offset = (self._dash_offset + 0.8) % 20
        self._canvas.update()

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._drag_over = True; self._canvas.update()

    def dragLeaveEvent(self, e):
        self._drag_over = False; self._canvas.update()

    def dropEvent(self, e: QDropEvent):
        self._drag_over = False
        urls = e.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if Path(path).is_file():
                self._set_file(path)
        self._canvas.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._browse()

    def enterEvent(self, e):
        self._hovering = True; self._canvas.update()

    def leaveEvent(self, e):
        self._hovering = False; self._canvas.update()

    def current_file(self) -> str | None:
        return self._current_file

    def clear_file(self):
        self._current_file = None; self._canvas.update()

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select a file for JARVIS", str(Path.home()),
            "All Files (*.*);;"
            "Images (*.jpg *.jpeg *.png *.gif *.webp *.bmp *.svg);;"
            "Documents (*.pdf *.docx *.txt *.md *.pptx);;"
            "Data (*.csv *.xlsx *.json *.xml);;"
            "Code (*.py *.js *.ts *.html *.css *.java *.cpp *.go);;"
            "Audio (*.mp3 *.wav *.ogg *.m4a *.aac *.flac);;"
            "Video (*.mp4 *.avi *.mov *.mkv *.wmv *.webm);;"
            "Archives (*.zip *.rar *.tar *.gz *.7z)",
        )
        if path:
            self._set_file(path)

    def _set_file(self, path: str):
        self._current_file = path
        self._canvas.update()
        self.file_selected.emit(path)


class _DropCanvas(QWidget):
    def __init__(self, zone: FileDropZone):
        super().__init__(zone)
        self._z = zone

    def paintEvent(self, _):
        p = QPainter(self)
        if not p.isActive():
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        z    = self._z
        W, H = self.width(), self.height()
        pad  = 6
        rect = QRectF(pad, pad, W - pad * 2, H - pad * 2)

        bg_col = qcol("#001a24" if z._drag_over else ("#001218" if z._hovering else C.PANEL))
        p.setBrush(QBrush(bg_col)); p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, 6, 6)

        if z._current_file:   border_col = qcol(C.GREEN, 200)
        elif z._drag_over:    border_col = qcol(C.PRI, 230)
        elif z._hovering:     border_col = qcol(C.BORDER_B, 200)
        else:                 border_col = qcol(C.BORDER, 160)

        pen = QPen(border_col, 1.5, Qt.PenStyle.DashLine)
        pen.setDashOffset(z._dash_offset)
        p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 6, 6)

        if z._current_file:   self._paint_file(p, W, H)
        elif z._drag_over:    self._paint_drag_over(p, W, H)
        else:                 self._paint_idle(p, W, H, z._hovering)

        p.end()

    def _paint_idle(self, p, W, H, hover):
        cx, cy = W / 2, H / 2
        col = qcol(C.PRI_DIM if not hover else C.PRI)
        p.setPen(QPen(col, 2)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(cx, cy - 14), QPointF(cx, cy + 4))
        p.drawLine(QPointF(cx - 8, cy - 6), QPointF(cx, cy - 14))
        p.drawLine(QPointF(cx + 8, cy - 6), QPointF(cx, cy - 14))
        p.drawLine(QPointF(cx - 14, cy + 4), QPointF(cx + 14, cy + 4))
        p.setFont(QFont("Courier New", 8))
        p.setPen(QPen(qcol(C.PRI_DIM if not hover else C.TEXT), 1))
        p.drawText(QRectF(0, cy + 8, W, 16), Qt.AlignmentFlag.AlignCenter,
                   "Drop file here  or  Click to Browse")
        p.setFont(QFont("Courier New", 7))
        p.setPen(QPen(qcol("#1a4a5a"), 1))
        p.drawText(QRectF(0, cy + 24, W, 14), Qt.AlignmentFlag.AlignCenter,
                   "Images · Video · Audio · PDF · Docs · Code · Data")

    def _paint_drag_over(self, p, W, H):
        cx, cy = W / 2, H / 2
        p.setFont(QFont("Courier New", 20))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(0, cy - 24, W, 32), Qt.AlignmentFlag.AlignCenter, "⬇")
        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(0, cy + 12, W, 16), Qt.AlignmentFlag.AlignCenter, "Release to load")

    def _paint_file(self, p, W, H):
        path = Path(self._z._current_file)
        cat  = _file_category(path)
        icon, icon_col = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size_str = _fmt_size(path.stat().st_size)
        ext_str  = path.suffix.upper().lstrip(".") or "FILE"

        block_x, block_w = 10, 60
        p.setFont(QFont("Segoe UI Emoji", 22) if _OS == "Windows" else QFont("Arial", 22))
        p.setPen(QPen(qcol(icon_col), 1))
        p.drawText(QRectF(block_x, 0, block_w, H), Qt.AlignmentFlag.AlignCenter, icon)

        tx = block_x + block_w + 6
        tw = W - tx - 38

        p.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.WHITE), 1))
        name = path.name if len(path.name) <= 34 else path.name[:31] + "..."
        p.drawText(QRectF(tx, H * 0.18, tw, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)

        p.setFont(QFont("Courier New", 7))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(QRectF(tx, H * 0.18 + 18, tw, 14),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   f"{ext_str}  ·  {size_str}")

        p.setFont(QFont("Courier New", 6))
        p.setPen(QPen(qcol("#1e5c6a"), 1))
        par = str(path.parent)
        if len(par) > 42: par = "…" + par[-41:]
        p.drawText(QRectF(tx, H * 0.18 + 34, tw, 12),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, par)

        p.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.RED, 180), 1))
        p.drawText(QRectF(W - 34, 0, 28, H), Qt.AlignmentFlag.AlignCenter, "✕")

    def mousePressEvent(self, e):
        z = self._z
        if z._current_file and e.pos().x() > self.width() - 34:
            z.clear_file()
        else:
            z.mousePressEvent(e)


class _CameraPreview(QWidget):
    """Floating overlay that briefly shows what the camera captured."""

    _W, _H = 244, 188

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            _CameraPreview {{
                background: rgba(0, 6, 10, 242);
                border: 1px solid {C.PRI};
                border-radius: 6px;
            }}
        """)
        self.setFixedWidth(self._W)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 5, 6, 6)
        lay.setSpacing(4)

        hdr = QHBoxLayout()
        title = QLabel("◈  VISUAL INPUT")
        title.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        hdr.addWidget(title)
        hdr.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(16, 16)
        close_btn.setFont(QFont("Courier New", 8))
        close_btn.setStyleSheet(
            f"color: {C.TEXT_DIM}; background: transparent; border: none;"
        )
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.hide)
        hdr.addWidget(close_btn)
        lay.addLayout(hdr)

        self._img_lbl = QLabel()
        self._img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_lbl.setStyleSheet("background: transparent;")
        lay.addWidget(self._img_lbl)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

        self.hide()

    def show_frame(self, img_bytes: bytes) -> None:
        px = QPixmap()
        px.loadFromData(img_bytes)
        if not px.isNull():
            max_w = self._W - 12
            scaled = px.scaled(
                max_w, 160,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._img_lbl.setPixmap(scaled)
            self._img_lbl.setFixedSize(scaled.width(), scaled.height())
            self.adjustSize()
        self.show()
        self.raise_()
        self._timer.start(6_000)   # auto-dismiss after 6 s


class SetupOverlay(QWidget):
    done = pyqtSignal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            SetupOverlay {{
                background: {C.PANEL};
                border: 1px solid {C.BORDER};
                border-radius: 20px;
            }}
        """)

        detected = {"darwin": "mac", "windows": "windows"}.get(
            _OS.lower(), "linux"
        )
        self._sel_os = detected

        layout = QVBoxLayout(self)
        layout.setContentsMargins(34, 28, 34, 28)
        layout.setSpacing(10)

        def _lbl(txt, font_size=9, bold=False, color=C.PRI,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(QFont("Segoe UI", font_size,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            return w

        layout.addWidget(_lbl("Mica einrichten", 18, True, color=C.TEXT))
        layout.addWidget(_lbl("Verbinde Mica sicher mit Gemini.", 10, color=C.TEXT_MED))
        layout.addSpacing(6)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};"); layout.addWidget(sep)
        layout.addSpacing(4)

        layout.addWidget(_lbl("Gemini API-Key", 9, True, color=C.TEXT,
                               align=Qt.AlignmentFlag.AlignLeft))
        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_input.setPlaceholderText("AIza…")
        self._key_input.setFont(QFont("Segoe UI", 10))
        self._key_input.setFixedHeight(44)
        self._key_input.setStyleSheet(f"""
            QLineEdit {{
                background: {C.PANEL2}; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 12px; padding: 7px 12px;
            }}
            QLineEdit:focus {{ border: 2px solid {C.PRI}; background: {C.PANEL}; }}
        """)
        layout.addWidget(self._key_input)
        layout.addWidget(_lbl(
            "Der Schlüssel wird nur lokal in deiner Mica-Konfiguration gespeichert.",
            8, color=C.TEXT_DIM, align=Qt.AlignmentFlag.AlignLeft,
        ))
        layout.addSpacing(12)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER};"); layout.addWidget(sep2)
        layout.addSpacing(4)

        layout.addWidget(_lbl("Betriebssystem", 9, True, color=C.TEXT,
                               align=Qt.AlignmentFlag.AlignLeft))
        det_name = {"windows": "Windows", "mac": "macOS", "linux": "Linux"}[detected]
        layout.addWidget(_lbl(f"Auto-detected: {det_name}", 8, color=C.ACC2,
                               align=Qt.AlignmentFlag.AlignLeft))

        os_row = QHBoxLayout(); os_row.setSpacing(6)
        self._os_btns: dict[str, QPushButton] = {}
        for key, label in [("windows", "Windows"), ("mac", "macOS"), ("linux", "Linux")]:
            btn = QPushButton(label)
            btn.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
            btn.setFixedHeight(38)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._sel(k))
            os_row.addWidget(btn)
            self._os_btns[key] = btn
        layout.addLayout(os_row)
        self._sel(detected)
        layout.addSpacing(12)

        init_btn = QPushButton("Mica starten")
        init_btn.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        init_btn.setFixedHeight(44)
        init_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        init_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C.PRI}; color: white;
                border: 1px solid {C.PRI}; border-radius: 12px;
            }}
            QPushButton:hover {{
                background: #397de8; border: 1px solid #397de8;
            }}
        """)
        init_btn.clicked.connect(self._submit)
        layout.addWidget(init_btn)

    def _sel(self, key: str):
        self._sel_os = key
        pal = {"windows": (C.PRI, "#ffffff"), "mac": (C.PRI, "#ffffff"),
               "linux": (C.PRI, "#ffffff")}
        for k, btn in self._os_btns.items():
            if k == key:
                fg, bg = pal[k]
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {fg}; color: {bg};
                        border: none; border-radius: 10px; font-weight: 600;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {C.PANEL2}; color: {C.TEXT_MED};
                        border: 1px solid {C.BORDER}; border-radius: 10px;
                    }}
                    QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
                """)

    def _submit(self):
        key = self._key_input.text().strip()
        if not key:
            self._key_input.setStyleSheet(
                self._key_input.styleSheet() +
                f" QLineEdit {{ border: 1px solid {C.RED}; }}"
            )
            return
        self.done.emit(key, self._sel_os)


class HueWheel(QWidget):
    """
    Dairesel renk seçici. Kullanıcı tutamacı (küçük beyaz daire) çarkın
    çevresinde sürükleyerek TÜM renk tonları arasından seçim yapar.
    Merkezdeki dolu daire seçilen rengin canlı önizlemesidir.
    """

    hue_picked    = pyqtSignal(str)   # sürükleme sırasında (canlı)
    hue_committed = pyqtSignal(str)   # tutamaç bırakıldığında

    _RING = 16   # halka kalınlığı (px)

    def __init__(self, initial_hex: str = DEFAULT_UI_COLOR, parent=None):
        super().__init__(parent)
        self.setFixedSize(148, 148)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hue  = 0.53
        self._drag = False
        self.set_color(initial_hex)

    # ── API ──────────────────────────────────────────────────────────────────
    def color(self) -> str:
        return QColor.fromHsvF(self._hue, 1.0, 1.0).name()

    def set_color(self, hex_str: str):
        c = QColor((hex_str or "").strip())
        if c.isValid() and c.hsvHueF() >= 0:
            self._hue = c.hsvHueF()
            self.update()

    # ── geometri yardımcıları ────────────────────────────────────────────────
    def _ring_rect(self) -> QRectF:
        m = self._RING / 2 + 3
        return QRectF(self.rect()).adjusted(m, m, -m, -m)

    def _hue_from_pos(self, pos: QPointF) -> float:
        c  = QRectF(self.rect()).center()
        dx = pos.x() - c.x()
        dy = c.y() - pos.y()          # ekran y'si aşağı — matematiksel eksene çevir
        ang = math.atan2(dy, dx)      # [-π, π], saat yönünün tersi
        return (ang / (2 * math.pi)) % 1.0

    # ── çizim ────────────────────────────────────────────────────────────────
    def paintEvent(self, _):
        p = QPainter(self)
        if not p.isActive():
            return
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect   = self._ring_rect()
        center = rect.center()

        grad = QConicalGradient(center, 0)
        for i in range(0, 361, 20):
            grad.setColorAt(i / 360.0, QColor.fromHsvF((i % 360) / 360.0, 1.0, 1.0))
        p.setPen(QPen(QBrush(grad), self._RING))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(rect)

        # merkez önizleme dairesi
        preview = QColor.fromHsvF(self._hue, 1.0, 1.0)
        inner   = rect.adjusted(30, 30, -30, -30)
        p.setPen(QPen(qcol(C.BORDER_B), 1))
        p.setBrush(QBrush(preview))
        p.drawEllipse(inner)

        # sürüklenen tutamaç
        r   = rect.width() / 2
        ang = self._hue * 2 * math.pi
        hx  = center.x() + r * math.cos(ang)
        hy  = center.y() - r * math.sin(ang)
        p.setPen(QPen(QColor("#00060a"), 2))
        p.setBrush(QBrush(QColor("#ffffff")))
        p.drawEllipse(QPointF(hx, hy), 7.5, 7.5)
        p.end()

    # ── fare ─────────────────────────────────────────────────────────────────
    def mousePressEvent(self, e):
        self._drag = True
        self._hue  = self._hue_from_pos(e.position())
        self.update()
        self.hue_picked.emit(self.color())

    def mouseMoveEvent(self, e):
        if self._drag:
            self._hue = self._hue_from_pos(e.position())
            self.update()
            self.hue_picked.emit(self.color())

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._drag = False
            self.hue_committed.emit(self.color())


class CustomizeOverlay(QWidget):
    """Floating overlay — change assistant name, user name, UI colour and voice."""

    saved = pyqtSignal(str, str, str, str)   # assistant_name, user_name, ui_color, voice
    _OW, _OH = 400, 588

    def __init__(self, assistant_name="Mica", user_name="",
                 ui_color=DEFAULT_UI_COLOR, voice="", parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            CustomizeOverlay {{
                background: {C.PANEL};
                border: 1px solid {C.BORDER};
                border-radius: 20px;
            }}
        """)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        lay.setSpacing(8)

        def _lbl(txt, fs=9, bold=False, color=C.PRI, align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt); w.setAlignment(align)
            w.setFont(QFont("Segoe UI", fs,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            return w

        _fs = (f"QLineEdit {{ background: {C.PANEL2}; color: {C.TEXT}; "
               f"border: 1px solid {C.BORDER}; border-radius: 10px; padding: 6px 10px; }}"
               f"QLineEdit:focus {{ border: 2px solid {C.PRI}; background: {C.PANEL}; }}")

        lay.addWidget(_lbl("Mica anpassen", 16, True, color=C.TEXT))
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep)

        lay.addWidget(_lbl("NAME DER ASSISTENTIN", 8, color=C.TEXT_DIM,
                            align=Qt.AlignmentFlag.AlignLeft))
        self._name_input = QLineEdit(assistant_name)
        self._name_input.setFont(QFont("Courier New", 10))
        self._name_input.setFixedHeight(32)
        self._name_input.setStyleSheet(_fs)
        lay.addWidget(self._name_input)

        lay.addSpacing(4)
        lay.addWidget(_lbl("DEIN NAME  (optional)", 8,
                            color=C.TEXT_DIM, align=Qt.AlignmentFlag.AlignLeft))
        self._user_input = QLineEdit(user_name)
        self._user_input.setPlaceholderText("Wie soll Mica dich ansprechen?")
        self._user_input.setFont(QFont("Courier New", 10))
        self._user_input.setFixedHeight(32)
        self._user_input.setStyleSheet(_fs)
        lay.addWidget(self._user_input)

        # ── Assistant voice — Gemini prebuilt voices ─────────────────────────
        # Names are language-neutral proper nouns, so the row reads the same in
        # every locale. Selecting one and applying rebuilds the Live session.
        from memory.config_manager import AVAILABLE_VOICES, DEFAULT_VOICE
        lay.addSpacing(4)
        lay.addWidget(_lbl("WEIBLICHE STIMME", 8, color=C.TEXT_DIM,
                            align=Qt.AlignmentFlag.AlignLeft))
        self._sel_voice   = (voice or DEFAULT_VOICE)
        if self._sel_voice not in AVAILABLE_VOICES:
            self._sel_voice = DEFAULT_VOICE
        self._voice_btns: dict[str, QPushButton] = {}
        voice_row = QHBoxLayout(); voice_row.setSpacing(4)
        for _v in AVAILABLE_VOICES:
            b = QPushButton(_v)
            b.setCheckable(True)
            b.setFixedHeight(28)
            b.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, name=_v: self._on_voice_pick(name))
            self._voice_btns[_v] = b
            voice_row.addWidget(b)
        lay.addLayout(voice_row)
        self._refresh_voice_btns()

        # ── UI colour — renk çarkı ───────────────────────────────────────────
        lay.addSpacing(4)
        clr_hdr = QHBoxLayout()
        clr_hdr.addWidget(_lbl("AKZENTFARBE  —  Regler ziehen", 8,
                               color=C.TEXT_DIM, align=Qt.AlignmentFlag.AlignLeft))
        clr_hdr.addStretch()
        df_btn = QPushButton("STANDARD")
        df_btn.setFixedSize(64, 20)
        df_btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        df_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        df_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        df_btn.clicked.connect(lambda: self._set_color(DEFAULT_UI_COLOR))
        clr_hdr.addWidget(df_btn)
        lay.addLayout(clr_hdr)

        self._initial_color = (ui_color or DEFAULT_UI_COLOR).strip().lower()
        self._sel_color     = self._initial_color
        self.on_preview     = None   # callable(hex) — canlı önizleme; MainWindow bağlar

        self._wheel = HueWheel(self._sel_color)
        wheel_row = QHBoxLayout()
        wheel_row.addStretch(); wheel_row.addWidget(self._wheel); wheel_row.addStretch()
        lay.addLayout(wheel_row)
        self._wheel.hue_picked.connect(self._on_wheel_pick)
        self._wheel.hue_committed.connect(self._on_wheel_commit)

        self._hex_input = QLineEdit(self._sel_color)
        self._hex_input.setPlaceholderText("#4f8ff7   (eigene Hex-Farbe)")
        self._hex_input.setFont(QFont("Courier New", 10))
        self._hex_input.setFixedHeight(28)
        self._hex_input.setStyleSheet(_fs)
        self._hex_input.textEdited.connect(self._on_hex_edited)
        lay.addWidget(self._hex_input)

        lay.addSpacing(6)
        btn_row = QHBoxLayout(); btn_row.setSpacing(8)

        save_btn = QPushButton("Änderungen anwenden")
        save_btn.setFixedHeight(34)
        save_btn.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
        """)
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)

        cancel_btn = QPushButton("Abbrechen")
        cancel_btn.setFixedHeight(34)
        cancel_btn.setFont(QFont("Courier New", 9))
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        cancel_btn.clicked.connect(self._cancel)
        btn_row.addWidget(cancel_btn)
        lay.addLayout(btn_row)

    # ── ses seçimi ───────────────────────────────────────────────────────────
    def _on_voice_pick(self, name: str):
        self._sel_voice = name
        self._refresh_voice_btns()

    def _refresh_voice_btns(self):
        """Highlight the selected voice pill; dim the rest."""
        for name, b in self._voice_btns.items():
            on = (name == self._sel_voice)
            b.setChecked(on)
            if on:
                b.setStyleSheet(f"""
                    QPushButton {{ background: {C.PRI_GHO}; color: {C.PRI};
                        border: 1px solid {C.PRI}; border-radius: 3px; }}
                """)
            else:
                b.setStyleSheet(f"""
                    QPushButton {{ background: transparent; color: {C.TEXT_MED};
                        border: 1px solid {C.BORDER}; border-radius: 3px; }}
                    QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
                """)

    # ── renk akışı ───────────────────────────────────────────────────────────
    def _set_color(self, hx: str, update_wheel: bool = True, preview: bool = True):
        """Seçili rengi günceller; hex kutusu + çark senkron kalır, tema canlı önizlenir."""
        self._sel_color = hx.strip().lower()
        self._hex_input.blockSignals(True)
        self._hex_input.setText(self._sel_color)
        self._hex_input.blockSignals(False)
        if update_wheel:
            self._wheel.set_color(self._sel_color)
        if preview and self.on_preview:
            self.on_preview(self._sel_color)

    def _on_wheel_pick(self, hx: str):
        # Sürükleme sırasında: hex kutusunu güncelle, temayı henüz uygulama
        self._sel_color = hx
        self._hex_input.blockSignals(True)
        self._hex_input.setText(hx)
        self._hex_input.blockSignals(False)

    def _on_wheel_commit(self, hx: str):
        # Tutamaç bırakıldı → tüm arayüzü canlı önizle
        self._set_color(hx, update_wheel=False)

    def _on_hex_edited(self, text: str):
        t = text.strip().lower()
        if t.startswith("#") and len(t) == 7:
            try:
                int(t[1:], 16)
            except ValueError:
                return
            self._set_color(t, update_wheel=True, preview=True)

    def _cancel(self):
        # Önizleme uygulandıysa açılıştaki renge geri dön
        if self.on_preview and self._sel_color != self._initial_color:
            self.on_preview(self._initial_color)
        self.hide()

    def _save(self):
        name = self._name_input.text().strip() or "Mica"
        user = self._user_input.text().strip()
        self.saved.emit(name, user, self._sel_color or DEFAULT_UI_COLOR, self._sel_voice)
        self.hide()


class PluginManagerOverlay(QWidget):
    """Floating overlay — lists discovered plugins with per-plugin ON/OFF toggles."""

    _OW = 420

    def __init__(self, plugins: list[dict], parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            PluginManagerOverlay {{
                background: {C.PANEL};
                border: 1px solid {C.BORDER};
                border-radius: 18px;
            }}
        """)
        self.setFixedWidth(self._OW)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(6)

        hdr = QLabel("🧩  PLUGIN MANAGER")
        hdr.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        lay.addWidget(hdr)
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep)

        if not plugins:
            empty = QLabel("No plugins found in /plugins.")
            empty.setFont(QFont("Courier New", 8))
            empty.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
            lay.addWidget(empty)

        for p in plugins:
            lay.addLayout(self._build_row(p))

        lay.addSpacing(4)
        close_btn = QPushButton("CLOSE")
        close_btn.setFixedHeight(30)
        close_btn.setFont(QFont("Courier New", 9))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        close_btn.clicked.connect(self.hide)
        lay.addWidget(close_btn)
        self.adjustSize()

    def _build_row(self, p: dict) -> QHBoxLayout:
        row = QHBoxLayout(); row.setSpacing(6)

        label_text = p["name"] if p["valid"] else f"{p['name']}  (⚠ {p['file']})"
        lbl = QLabel(label_text)
        lbl.setFont(QFont("Courier New", 8))
        lbl.setStyleSheet(f"color: {C.TEXT if p['valid'] else C.TEXT_DIM}; background: transparent;")
        lbl.setToolTip(p["description"] if p["valid"] else p["error"])
        lbl.setWordWrap(False)
        row.addWidget(lbl, stretch=1)

        btn = QPushButton()
        btn.setFixedSize(72, 24)
        btn.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        if not p["valid"]:
            btn.setText("BROKEN")
            btn.setEnabled(False)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {C.TEXT_DIM};
                    border: 1px solid {C.BORDER}; border-radius: 3px;
                }}
            """)
        else:
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._style_toggle(btn, p["enabled"])
            btn.clicked.connect(lambda _, name=p["name"], b=btn: self._toggle(name, b))
        row.addWidget(btn)
        return row

    def _style_toggle(self, btn: QPushButton, enabled: bool):
        if enabled:
            btn.setText("ON")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: #001a08; color: {C.GREEN};
                    border: 1px solid {C.GREEN_D}; border-radius: 3px;
                }}
                QPushButton:hover {{ background: #002010; }}
            """)
        else:
            btn.setText("OFF")
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {C.TEXT_DIM};
                    border: 1px solid {C.BORDER}; border-radius: 3px;
                }}
                QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
            """)

    def _toggle(self, name: str, btn: QPushButton):
        from memory.config_manager import get_plugin_enabled, save_plugin_enabled
        new_val = not get_plugin_enabled(name)
        save_plugin_enabled(name, new_val)
        self._style_toggle(btn, new_val)


class _HudOverlay(QWidget):
    """Base for the floating panels placed by hand over the HUD.

    They are children of the central widget but sit in no layout, so Qt never
    invalidates the region they occupy when they hide or shrink: the HUD keeps
    painting around them and their last frame stays on screen as a ghost. Any
    overlay positioned with _centre_overlay needs this."""

    def hideEvent(self, e):
        p = self.parentWidget()
        if p is not None:
            # Repaint exactly what we were covering, before we stop covering it.
            p.update(self.geometry())
        super().hideEvent(e)

    def closeEvent(self, e):
        p = self.parentWidget()
        if p is not None:
            p.update(self.geometry())
        super().closeEvent(e)


class ConfirmBanner(_HudOverlay):
    """The gate in front of an action that cannot be taken back.

    The old confirmation was a tool parameter the model filled in itself, which
    means it confirmed its own shutdown requests. This is the interface asking,
    and the answer travels from a human finger to core/confirm.py without the
    model in the loop. Nothing blocks while it is up: the assistant keeps
    talking, so this costs no latency — unlike the old gate, which spent two
    tool round trips on every power command."""

    answered = pyqtSignal(bool)
    _OW = 430

    def __init__(self, title: str, detail: str, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            ConfirmBanner {{
                background: {C.PANEL};
                border: 1px solid #f0c5cc;
                border-radius: 18px;
            }}
        """)
        self.setFixedWidth(self._OW)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(8)

        hdr = QLabel("Aktion bestätigen")
        hdr.setFont(QFont("Segoe UI", 13, QFont.Weight.DemiBold))
        hdr.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        lay.addWidget(hdr)

        ttl = QLabel(title)
        ttl.setWordWrap(True)
        ttl.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        ttl.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        lay.addWidget(ttl)

        if detail:
            dtl = QLabel(detail)
            dtl.setWordWrap(True)
            dtl.setFont(QFont("Segoe UI", 9))
            dtl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
            lay.addWidget(dtl)

        row = QHBoxLayout(); row.setSpacing(8)

        yes = QPushButton("Bestätigen")
        yes.setFixedHeight(38)
        yes.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        yes.setCursor(Qt.CursorShape.PointingHandCursor)
        yes.setStyleSheet(f"""
            QPushButton {{ background: {C.RED}; color: white;
                border: 1px solid {C.RED}; border-radius: 10px; }}
            QPushButton:hover {{ background: #c95e70; }}
        """)
        yes.clicked.connect(lambda: self.answered.emit(True))
        row.addWidget(yes)

        no = QPushButton("Abbrechen")
        no.setFixedHeight(38)
        no.setFont(QFont("Segoe UI", 9))
        no.setCursor(Qt.CursorShape.PointingHandCursor)
        no.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 10px; }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        no.clicked.connect(lambda: self.answered.emit(False))
        row.addWidget(no)
        lay.addLayout(row)

        # Default focus on CANCEL: if someone hits Enter without reading, the
        # safe answer wins.
        no.setDefault(True)
        no.setFocus()


class AudioDeviceOverlay(_HudOverlay):
    """Choose which microphone JARVIS listens to and which speakers it uses.

    Both audio streams used to open with no `device=` at all, so they always
    took the OS default — which on Windows moves by itself the moment a headset
    is plugged in. 'JARVIS can't hear me' is usually 'JARVIS is listening to the
    webcam'."""

    picked = pyqtSignal()      # emitted after Apply, when something changed
    _OW = 460

    def __init__(self, parent=None):
        super().__init__(parent)
        from core.audio_devices import list_devices, DEFAULT_LABEL
        from memory.config_manager import get_input_device, get_output_device

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            AudioDeviceOverlay {{
                background: {C.PANEL};
                border: 1px solid {C.BORDER};
                border-radius: 18px;
            }}
        """)
        self.setFixedWidth(self._OW)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)
        lay.setSpacing(6)

        hdr = QLabel("🎧  AUDIO DEVICES")
        hdr.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        lay.addWidget(hdr)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep)

        _combo_css = (
            f"QComboBox {{ background: {C.PANEL2}; color: {C.TEXT}; "
            f"border: 1px solid {C.BORDER}; border-radius: 10px; padding: 7px 10px; }}"
            f"QComboBox:hover {{ border-color: {C.BORDER_B}; }}"
            f"QComboBox QAbstractItemView {{ background: {C.PANEL}; color: {C.TEXT}; "
            f"selection-background-color: {C.PRI_GHO}; border: 1px solid {C.BORDER}; }}"
        )

        def _row(label: str, kind: str, current: str) -> QComboBox:
            cap = QLabel(label)
            cap.setFont(QFont("Courier New", 8))
            cap.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
            lay.addWidget(cap)

            box = QComboBox()
            box.setFont(QFont("Courier New", 9))
            box.setFixedHeight(30)
            box.setStyleSheet(_combo_css)
            # The list is served from a cache warmed on a background thread at
            # startup, so opening this panel never blocks the Qt thread on the
            # host audio API.
            box.addItem(DEFAULT_LABEL, "")
            for name in list_devices(kind):
                box.addItem(name, name)
            idx = box.findData(current) if current else 0
            box.setCurrentIndex(idx if idx >= 0 else 0)
            if current and idx < 0:
                # Saved device is not plugged in right now. Show it rather than
                # silently resetting the user's choice to default.
                box.addItem(f"{current}  (not connected)", current)
                box.setCurrentIndex(box.count() - 1)
            lay.addWidget(box)
            return box

        self._in_box  = _row("MICROPHONE — what JARVIS hears you with",
                             "input", get_input_device())
        lay.addSpacing(4)
        self._out_box = _row("SPEAKERS — what JARVIS talks through",
                             "output", get_output_device())

        note = QLabel("Applying reconnects the session. Your conversation is kept.")
        note.setWordWrap(True)
        note.setFont(QFont("Courier New", 7))
        note.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        lay.addSpacing(6)
        lay.addWidget(note)

        row = QHBoxLayout(); row.setSpacing(8)
        ok = QPushButton("▸  APPLY")
        ok.setFixedHeight(32)
        ok.setFont(QFont("Courier New", 9, QFont.Weight.Bold))
        ok.setCursor(Qt.CursorShape.PointingHandCursor)
        ok.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px; }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border-color: {C.PRI}; }}
        """)
        ok.clicked.connect(self._apply)
        row.addWidget(ok)

        cancel = QPushButton("CLOSE")
        cancel.setFixedHeight(32)
        cancel.setFont(QFont("Courier New", 9))
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px; }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        cancel.clicked.connect(self.hide)
        row.addWidget(cancel)
        lay.addLayout(row)

    def _apply(self):
        from memory.config_manager import (
            get_input_device, get_output_device,
            save_input_device, save_output_device,
        )
        new_in  = self._in_box.currentData()  or ""
        new_out = self._out_box.currentData() or ""
        changed = (new_in != get_input_device()) or (new_out != get_output_device())
        save_input_device(new_in)
        save_output_device(new_out)
        self.hide()
        # Only rebuild the session if something actually moved — a no-op Apply
        # should not cost a reconnect.
        if changed:
            self.picked.emit()


class MemoryOverlay(_HudOverlay):
    """Everything JARVIS has stored about you, and when it learned it.

    Memory used to be a 2200-character store that deleted its oldest entries
    when full and mentioned it only on stdout. The cap is gone; this panel is
    the other half of that change — a memory you cannot inspect is a memory you
    cannot trust, and 'delete' has to be something the person can do."""

    _OW = 520

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            MemoryOverlay {{
                background: {C.PANEL};
                border: 1px solid {C.BORDER};
                border-radius: 18px;
            }}
        """)
        self.setFixedWidth(self._OW)

        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(20, 16, 20, 16)
        self._lay.setSpacing(5)
        self._rebuild()

    def _clear_layout(self):
        """Take every item out of the layout and detach it from the widget tree
        in this call.

        deleteLater() on its own is not enough: it queues destruction for the
        next event-loop pass, and until then the old rows are still children of
        this widget and still paint — which is what drew half of the previous
        panel over the new one. setParent(None) removes them from the tree now;
        deleteLater() then frees them safely."""
        while self._lay.count():
            item = self._lay.takeAt(0)
            w = item.widget()
            if w is not None:
                # hide() stops it painting in this frame; deleteLater() frees it
                # safely afterwards. setParent(None) would also stop the paint,
                # but it turns the widget into a top-level window for the moment
                # between the two calls, which is not something to leave lying
                # around inside a click handler.
                w.hide()
                w.deleteLater()
                continue
            sub = item.layout()
            if sub is not None:
                while sub.count():
                    si = sub.takeAt(0)
                    sw = si.widget()
                    if sw is not None:
                        sw.hide()
                        sw.deleteLater()
                sub.deleteLater()

    def _settle(self, before):
        """Size the panel to its content, re-centre it, and repaint what the old
        size covered.

        The re-size has to happen here rather than at the end of _rebuild
        because Qt has not polished the freshly-created children at that point,
        so the size hint it would read is the empty-layout one. Measured: a
        first adjustSize() returned 32 px for a panel whose content needed 155,
        and a second call — after the same widgets had been through the event
        loop — returned 155. So this runs twice: once now, once on the next
        turn, from _rebuild.

        The re-centre and the repaint are needed because the overlay is placed
        by hand and is in no layout: shrinking it leaves it off-centre and
        leaves its former pixels on screen, since nothing tells the parent that
        region changed. The repaint has to cover the union of the old and new
        rectangles."""
        self._lay.invalidate()
        self._lay.activate()
        self.updateGeometry()
        self.adjustSize()

        p = self.parentWidget()
        if p is None:
            self.update()
            return
        self.move(max(0, (p.width()  - self.width())  // 2),
                  max(0, (p.height() - self.height()) // 2))
        p.update(before.united(self.geometry()))
        self.update()

    def _rebuild(self):
        before = self.geometry()
        self._clear_layout()

        from memory.memory_manager import all_entries_for_ui

        hdr = QLabel("🧠  WHAT JARVIS REMEMBERS")
        hdr.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        self._lay.addWidget(hdr)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        self._lay.addWidget(sep)

        rows = all_entries_for_ui()

        cap = QLabel(f"{len(rows)} stored facts — newest first. "
                     f"Nothing here is sent anywhere; it lives in "
                     f"memory/long_term.json on this machine.")
        cap.setWordWrap(True)
        cap.setFont(QFont("Courier New", 7))
        cap.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        self._lay.addWidget(cap)

        if not rows:
            empty = QLabel("Nothing stored yet.")
            empty.setFont(QFont("Courier New", 9))
            empty.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
            self._lay.addWidget(empty)
        else:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFixedHeight(min(420, 34 * len(rows) + 10))
            scroll.setStyleSheet(
                f"QScrollArea {{ border: 1px solid {C.BORDER}; border-radius: 3px; "
                f"background: transparent; }}"
            )
            inner = QWidget()
            ilay  = QVBoxLayout(inner)
            ilay.setContentsMargins(6, 6, 6, 6)
            ilay.setSpacing(3)

            for r in rows:
                line = QHBoxLayout(); line.setSpacing(6)
                txt = QLabel(f"<b>{r['key'].replace('_', ' ')}</b> "
                             f"<span style='color:{C.TEXT_MED}'>— {r['value']}</span>")
                txt.setWordWrap(True)
                txt.setFont(QFont("Courier New", 8))
                txt.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
                line.addWidget(txt, 1)

                meta = QLabel(f"{r['category'][:4]} · {r['updated'] or '—'}")
                meta.setFont(QFont("Courier New", 7))
                meta.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
                line.addWidget(meta)

                rm = QPushButton("✕")
                rm.setFixedSize(20, 20)
                rm.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
                rm.setCursor(Qt.CursorShape.PointingHandCursor)
                rm.setToolTip("Forget this")
                rm.setStyleSheet(f"""
                    QPushButton {{ background: transparent; color: {C.TEXT_DIM};
                        border: 1px solid {C.BORDER}; border-radius: 3px; }}
                    QPushButton:hover {{ color: {C.RED}; border-color: {C.RED}; }}
                """)
                rm.clicked.connect(
                    lambda _=False, c=r["category"], k=r["key"]: self._forget(c, k))
                line.addWidget(rm)

                holder = QWidget()
                holder.setLayout(line)
                ilay.addWidget(holder)

            ilay.addStretch()
            scroll.setWidget(inner)
            self._lay.addWidget(scroll)

        close = QPushButton("CLOSE")
        close.setFixedHeight(30)
        close.setFont(QFont("Courier New", 9))
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setStyleSheet(f"""
            QPushButton {{ background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px; }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        close.clicked.connect(self.hide)
        self._lay.addWidget(close)

        self._settle(before)
        # …and again once Qt has polished the new children, because the size
        # hint is not final until then. Harmless when the first pass already
        # got it right: _settle is idempotent.
        QTimer.singleShot(0, lambda g=before: self._settle(g))

    def _forget(self, category: str, key: str):
        from memory.memory_manager import forget
        forget(key, category)
        # Rebuild on the NEXT event-loop turn, not inside this click handler.
        # The rebuild destroys the very ✕ button that emitted this signal, and
        # Qt is entitled to touch the sender after a slot returns; tearing it
        # down mid-emission is how a widget ends up half-alive on screen.
        QTimer.singleShot(0, self._rebuild)


class ClipboardPanel(QWidget):
    """Floating panel shown when text is copied — offers quick Jarvis actions."""

    action_requested = pyqtSignal(str)
    _W, _H = 326, 112

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            ClipboardPanel {{
                background: rgba(0, 8, 14, 248);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)
        self.setFixedWidth(self._W)
        self._clip_text = ""

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 7)
        lay.setSpacing(4)

        hdr = QHBoxLayout(); hdr.setSpacing(4)
        icon_lbl = QLabel("◈  CLIPBOARD DETECTED")
        icon_lbl.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
        icon_lbl.setStyleSheet(f"color: {C.ACC2}; background: transparent;")
        hdr.addWidget(icon_lbl); hdr.addStretch()
        x_btn = QPushButton("✕")
        x_btn.setFixedSize(16, 16)
        x_btn.setFont(QFont("Courier New", 8))
        x_btn.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent; border: none;")
        x_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        x_btn.clicked.connect(self.hide)
        hdr.addWidget(x_btn)
        lay.addLayout(hdr)

        self._preview = QLabel()
        self._preview.setFont(QFont("Courier New", 8))
        self._preview.setStyleSheet(f"""
            color: {C.TEXT}; background: {C.PANEL2};
            border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 6px;
        """)
        self._preview.setWordWrap(False)
        self._preview.setFixedHeight(28)
        lay.addWidget(self._preview)

        btn_row = QHBoxLayout(); btn_row.setSpacing(4)
        _bs = (f"QPushButton {{ background: {C.PANEL2}; color: {C.TEXT_MED}; "
               f"border: 1px solid {C.BORDER}; border-radius: 2px; }}"
               f"QPushButton:hover {{ color: {C.PRI}; border-color: {C.BORDER_B}; }}")
        for label, cmd_fmt in [
            ("TRANSLATE", "Translate this text to English: {text}"),
            ("SUMMARISE", "Summarise this: {text}"),
            ("EXPLAIN",   "Explain this: {text}"),
            ("FIX",       "Fix grammar and spelling: {text}"),
        ]:
            b = QPushButton(label)
            b.setFixedHeight(22)
            b.setFont(QFont("Courier New", 7, QFont.Weight.Bold))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(_bs)
            b.clicked.connect(lambda _, c=cmd_fmt: self._trigger(c))
            btn_row.addWidget(b)
        lay.addLayout(btn_row)

        self._dismiss_timer = QTimer(self)
        self._dismiss_timer.setSingleShot(True)
        self._dismiss_timer.timeout.connect(self.hide)
        self.hide()

    def _trigger(self, cmd_fmt: str):
        if self._clip_text:
            self.action_requested.emit(cmd_fmt.format(text=self._clip_text[:800]))
        self.hide()

    def show_clipboard(self, text: str):
        self._clip_text = text
        preview = text[:58].replace('\n', ' ')
        if len(text) > 58:
            preview += "…"
        self._preview.setText(f'"{preview}"')
        self.show(); self.raise_()
        self._dismiss_timer.start(8000)


class RemoteKeyOverlay(QWidget):
    """Floating overlay — QR code for instant phone pairing + manual key fallback."""

    closed = pyqtSignal()

    _OW, _OH = 400, 465

    def __init__(self, url: str, key: str, auto_login_url: str = "",
                 manual_url: str = "", expiry_secs: int = 600, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            RemoteKeyOverlay {{
                background: {C.PANEL};
                border: 1px solid {C.BORDER};
                border-radius: 18px;
            }}
        """)
        self._expiry          = time.time() + expiry_secs
        self._on_new_key      = None
        self._auto_login_url  = auto_login_url
        self._manual_url      = manual_url or url

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 16, 24, 16)
        lay.setSpacing(5)

        def _lbl(txt, fs=9, bold=False, color=C.PRI,
                 align=Qt.AlignmentFlag.AlignCenter):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(QFont("Courier New", fs,
                            QFont.Weight.Bold if bold else QFont.Weight.Normal))
            w.setStyleSheet(f"color: {color}; background: transparent;")
            w.setWordWrap(True)
            return w

        lay.addWidget(_lbl("◈  REMOTE ACCESS", 12, True))
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 1px 0;")
        lay.addWidget(sep)

        # ── QR code ───────────────────────────────────────────────────────────
        self._qr_label = QLabel()
        self._qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_label.setFixedSize(176, 176)
        self._qr_label.setStyleSheet(
            "background: white; border-radius: 10px; padding: 4px;"
        )
        qr_row = QHBoxLayout()
        qr_row.addStretch()
        qr_row.addWidget(self._qr_label)
        qr_row.addStretch()
        lay.addLayout(qr_row)

        self._update_qr(auto_login_url)

        lay.addWidget(_lbl("Scan with phone camera to connect instantly", 8, color=C.TEXT_DIM))

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER}; margin: 1px 0;")
        lay.addWidget(sep2)

        lay.addWidget(_lbl("Or enter manually:", 7, color=C.TEXT_DIM,
                           align=Qt.AlignmentFlag.AlignLeft))

        self._url_lbl = QLabel(self._manual_url)
        self._url_lbl.setFont(QFont("Courier New", 8))
        self._url_lbl.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
        self._url_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._url_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self._url_lbl)

        self._key_lbl = QLabel(key)
        self._key_lbl.setFont(QFont("Courier New", 28, QFont.Weight.Bold))
        self._key_lbl.setStyleSheet(f"""
            color: {C.ACC};
            background: {C.PANEL2};
            border: 1px solid {C.BORDER_B};
            border-radius: 8px;
            padding: 6px 4px;
            letter-spacing: 10px;
        """)
        self._key_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._key_lbl)

        self._timer_lbl = QLabel()
        self._timer_lbl.setFont(QFont("Courier New", 8))
        self._timer_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._timer_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._timer_lbl)

        btn_row = QHBoxLayout(); btn_row.setSpacing(8)
        new_btn = QPushButton("NEW KEY")
        new_btn.setFixedHeight(32)
        new_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL}; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 5px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
        """)
        new_btn.clicked.connect(self._refresh_key)
        btn_row.addWidget(new_btn)

        close_btn = QPushButton("DISMISS")
        close_btn.setFixedHeight(32)
        close_btn.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 5px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
        """)
        close_btn.clicked.connect(self._do_close)
        btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)

        self._ctimer = QTimer(self)
        self._ctimer.timeout.connect(self._tick)
        self._ctimer.start(1000)
        self._tick()

    def set_new_key_callback(self, fn) -> None:
        self._on_new_key = fn

    def _update_qr(self, url: str) -> None:
        if not url:
            self._qr_label.setText("—")
            return
        try:
            import qrcode as _qrmod
            from io import BytesIO
            qr = _qrmod.QRCode(
                box_size=5, border=2,
                error_correction=_qrmod.constants.ERROR_CORRECT_M,
            )
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buf = BytesIO()
            img.save(buf, format="PNG")
            px = QPixmap()
            px.loadFromData(buf.getvalue())
            self._qr_label.setPixmap(
                px.scaled(170, 170,
                          Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
            )
        except ImportError:
            self._qr_label.setText("pip install\nqrcode[pil]")
            self._qr_label.setFont(QFont("Courier New", 8))
            self._qr_label.setStyleSheet(
                "color: #888; background: white; border-radius: 10px; padding: 4px;"
            )
        except Exception:
            self._qr_label.setText(url[:28])
            self._qr_label.setFont(QFont("Courier New", 7))
            self._qr_label.setStyleSheet(
                f"color: {C.PRI}; background: white; border-radius: 10px; padding: 4px;"
            )

    def _tick(self):
        remaining = max(0, int(self._expiry - time.time()))
        m, s = divmod(remaining, 60)
        self._timer_lbl.setText(f"Key expires in  {m:02d}:{s:02d}")
        if remaining == 0:
            self._do_close()

    def mark_connected(self) -> None:
        """Call from any thread when a phone successfully connects."""
        self._ctimer.stop()
        self._key_lbl.setText("CONNECTED")
        self._key_lbl.setStyleSheet(f"""
            color: {C.GREEN};
            background: rgba(34,197,94,0.08);
            border: 2px solid rgba(34,197,94,0.4);
            border-radius: 8px;
            padding: 6px 4px;
            letter-spacing: 4px;
        """)
        self._qr_label.setText("✓")
        self._qr_label.setFont(QFont("Courier New", 54, QFont.Weight.Bold))
        self._qr_label.setStyleSheet(
            "color: #00ff88; background: #001a0d; border-radius: 10px;"
        )
        self._timer_lbl.setText("Phone connected — JARVIS ready")
        self._timer_lbl.setStyleSheet(f"color: {C.GREEN}; background: transparent;")

    def _refresh_key(self):
        if self._on_new_key:
            result = self._on_new_key()
            if result:
                url    = result[0]
                key    = result[1]
                auto   = result[2] if len(result) >= 3 else ""
                manual = result[3] if len(result) >= 4 else url
                self._manual_url     = manual or url
                self._url_lbl.setText(self._manual_url)
                self._key_lbl.setText(key)
                self._auto_login_url = auto
                self._update_qr(auto or url)
                self._expiry = time.time() + 600
                self._key_lbl.setStyleSheet(f"""
                    color: {C.ACC};
                    background: {C.PANEL2};
                    border: 1px solid {C.BORDER_B};
                    border-radius: 8px;
                    padding: 6px 4px;
                    letter-spacing: 10px;
                """)
                self._timer_lbl.setStyleSheet(
                    f"color: {C.TEXT_MED}; background: transparent;"
                )
                self._ctimer.start(1000)
                self._tick()

    def _do_close(self):
        self._ctimer.stop()
        self.hide()
        self.closed.emit()


class MainWindow(QMainWindow):
    _log_sig        = pyqtSignal(str)
    _state_sig      = pyqtSignal(str)
    _audio_sig      = pyqtSignal(float)
    _content_sig    = pyqtSignal(str, str)   # (title, text) — thread-safe content display
    _reconfig_sig   = pyqtSignal()           # trigger setup overlay from any thread
    _camera_sig     = pyqtSignal(bytes)      # show camera frame preview (small overlay)
    _cam_stream_sig = pyqtSignal(bool)       # True=start live stream, False=stop
    _cam_frame_sig  = pyqtSignal(bytes)      # live camera frame → HUD area
    _clipboard_sig  = pyqtSignal(str)        # clipboard text changed (thread-safe)
    _confirm_sig    = pyqtSignal(str, str)   # (title, detail) — irreversible-action gate
    _confirm_hide_sig = pyqtSignal()

    def __init__(self, face_path: str):
        super().__init__()
        ensure_ui_font()
        self._face_path = face_path

        # Load customization from config
        _cfg = _read_full_config()
        self._assistant_name: str = (_cfg.get("assistant_name") or "Mica").strip()
        _display = self._assistant_name.upper()

        # Kayıtlı UI rengini panel/stylesheet'ler kurulmadan ÖNCE uygula
        _ui_color = (_cfg.get("ui_color") or "").strip()
        if _ui_color and _ui_color.lower() != DEFAULT_UI_COLOR:
            apply_ui_accent(_ui_color)

        self.setWindowTitle(f"{_display} — MICA")
        self.setMinimumSize(_MIN_W, _MIN_H)
        self.resize(_DEFAULT_W, _DEFAULT_H)

        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            (screen.width()  - _DEFAULT_W) // 2,
            (screen.height() - _DEFAULT_H) // 2,
        )

        self.on_text_command   = None
        self.on_remote_clicked = None   # callable: () -> (url, key) | None
        self.on_interrupt      = None   # callable: () -> None — stop JARVIS mid-speech
        self.on_push_to_talk_start = None  # callable: () -> None — begin local PCM capture
        self.on_push_to_talk_stop = None   # callable: () -> None — finalize local PCM capture
        self.on_mute_change     = None   # callable: (bool) -> None — suspend local listeners
        self.on_voice_change   = None   # callable: () -> None — rebuild session with new voice
        self.on_audio_device_change = None  # callable: () -> None — reopen audio streams
        self._confirm_overlay  = None   # live ConfirmBanner, if one is on screen
        self.get_plugins       = None   # callable: () -> list[dict], set by JarvisLive
        self._muted            = False
        self._current_file: str | None = None
        self._remote_overlay: RemoteKeyOverlay | None = None
        self._customize_overlay: CustomizeOverlay | None = None

        central = QWidget()
        central.setStyleSheet(f"background: {C.BG};")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._left_panel = self._build_left_panel()
        body.addWidget(self._left_panel, stretch=0)

        # Center column: HUD.  Results are shown in a floating card instead of
        # taking permanent vertical space (or ending up behind the composer).
        # Keep the rail brand uppercase, but speak the configured assistant
        # name with its natural casing in the central greeting.
        self.hud = HudCanvas(face_path, self._assistant_name)
        self.hud.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._content_panel = self._build_content_panel()

        # Live camera container — replaces HUD when camera stream is active
        _cam_cont = QWidget()
        _cam_cont.setStyleSheet("background: #000308;")
        _cam_v = QVBoxLayout(_cam_cont)
        _cam_v.setContentsMargins(0, 0, 0, 0)
        _cam_v.setSpacing(0)
        _cam_hdr = QHBoxLayout()
        _cam_hdr.setContentsMargins(8, 5, 8, 5)
        _cam_title = QLabel("◈  CAMERA FEED")
        _cam_title.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        _cam_title.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        _cam_hdr.addWidget(_cam_title)
        _cam_hdr.addStretch()
        _cam_x = QPushButton("✕  CLOSE")
        _cam_x.setFont(QFont("Courier New", 8, QFont.Weight.Bold))
        _cam_x.setCursor(Qt.CursorShape.PointingHandCursor)
        _cam_x.setStyleSheet(f"""
            QPushButton {{
                color: {C.TEXT_DIM}; background: transparent;
                border: none; padding: 2px 6px;
            }}
            QPushButton:hover {{ color: {C.PRI}; }}
        """)
        _cam_x.clicked.connect(self.stop_camera_stream)
        _cam_hdr.addWidget(_cam_x)
        _cam_v.addLayout(_cam_hdr)
        self._cam_live_lbl = QLabel()
        self._cam_live_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cam_live_lbl.setStyleSheet("background: transparent;")
        self._cam_live_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        _cam_v.addWidget(self._cam_live_lbl, stretch=1)

        # Stack: 0 = animated HUD, 1 = live camera
        self._hud_cam_stack = QStackedWidget()
        self._hud_cam_stack.addWidget(self.hud)
        self._hud_cam_stack.addWidget(_cam_cont)

        self._center_split = QSplitter(Qt.Orientation.Vertical)
        self._center_split.setStyleSheet(f"""
            QSplitter::handle {{
                background: {C.BORDER};
                height: 4px;
            }}
            QSplitter::handle:hover {{
                background: {C.PRI_DIM};
            }}
        """)
        self._center_split.addWidget(self._hud_cam_stack)
        self._center_split.setCollapsible(0, False)

        # Chat and history are real navigation states.  The detailed content
        # drawer remains available within chat but does not occupy the calm
        # reference layout until a tool actually has something to show.
        self._view_stack = QStackedWidget()
        self._view_stack.addWidget(self._center_split)
        self._history_page = self._build_history_page()
        self._view_stack.addWidget(self._history_page)
        self._reminders_page = self._build_reminders_page()
        self._view_stack.addWidget(self._reminders_page)
        self._memory_page = self._build_memory_page()
        self._view_stack.addWidget(self._memory_page)
        self._settings_page = self._build_settings_page()
        self._view_stack.addWidget(self._settings_page)
        body.addWidget(self._view_stack, stretch=5)

        self._right_panel = self._build_right_panel()
        body.addWidget(self._right_panel, stretch=0)

        root.addLayout(body, stretch=1)
        self._footer = self._build_footer()
        # The composer floats over the lower middle rather than consuming a
        # horizontal row.  This keeps both side columns full-height as in the
        # reference and leaves the HUD breathing room behind the input.
        self._footer.setParent(central)
        self._position_footer()

        # Result/chat content is deliberately an overlay: it appears only for
        # a real response and never shrinks the calm central HUD.
        self._content_panel.setParent(central)
        self._position_content_panel()

        # Quick-access drawer (floating overlay, built after central widget layout is done)
        self._quick_drawer = self._build_quick_drawer()
        self._update_autostart_btn(self._check_autostart())
        from memory.config_manager import get_brief_enabled as _gbe
        self._update_brief_btn(_gbe())

        # Context data is refreshed at a human pace.  Unlike the old system
        # metric rail, every displayed value has a direct source in Mica.
        self._metric_tmr = QTimer(self)
        self._metric_tmr.timeout.connect(self._update_metrics)
        self._metric_tmr.start(2000)
        self._update_metrics()

        self._log_sig.connect(self._append_log_and_refresh)
        self._state_sig.connect(self._apply_state)
        self._audio_sig.connect(self._apply_audio_level)
        self._content_sig.connect(self._show_content)
        self._reconfig_sig.connect(self._show_setup)
        self._camera_sig.connect(self._show_camera_frame)
        self._confirm_sig.connect(self._show_confirm_banner)
        self._confirm_hide_sig.connect(self._hide_confirm_banner)
        self._cam_stream_sig.connect(self._on_cam_stream)
        self._cam_frame_sig.connect(self._on_cam_frame)
        self._clipboard_sig.connect(self._show_clipboard_panel)
        self._cam_stop = threading.Event()

        # Camera preview overlay (child of central widget, positioned in resizeEvent)
        self._cam_preview = _CameraPreview(self.centralWidget())

        # Clipboard panel (child of central widget, bottom-center)
        self._clipboard_panel = ClipboardPanel(self.centralWidget())
        self._clipboard_panel.action_requested.connect(self._on_clipboard_action)
        QApplication.clipboard().dataChanged.connect(self._on_clipboard_changed)

        self._overlay: SetupOverlay | None = None
        self._ready = self._check_config()
        if not self._ready:
            self._show_setup()

        sc_mute = QShortcut(QKeySequence("F4"), self)
        sc_mute.activated.connect(self._toggle_mute)
        sc_full = QShortcut(QKeySequence("F11"), self)
        sc_full.activated.connect(self._toggle_fullscreen)
        sc_intr = QShortcut(QKeySequence("Escape"), self)
        sc_intr.activated.connect(self._do_interrupt)

    def _show_camera_frame(self, img_bytes: bytes):
        """Slot — display camera preview overlay (main thread)."""
        self._cam_preview.show_frame(img_bytes)
        cw = self.centralWidget()
        pw = _CameraPreview._W
        ph = self._cam_preview.height()
        self._cam_preview.setGeometry(
            cw.width() - _RIGHT_W - pw - 12,
            cw.height() - ph - 28,
            pw, ph,
        )

    # --- Live camera stream in HUD area ------------------------------------
    def _on_cam_stream(self, start: bool) -> None:
        if start:
            self._hud_cam_stack.setCurrentIndex(1)
        else:
            self._hud_cam_stack.setCurrentIndex(0)
            self._cam_live_lbl.clear()

    def _on_cam_frame(self, data: bytes) -> None:
        px = QPixmap()
        px.loadFromData(data)
        if not px.isNull():
            w, h = self._cam_live_lbl.width(), self._cam_live_lbl.height()
            if w > 1 and h > 1:
                self._cam_live_lbl.setPixmap(
                    px.scaled(w, h,
                              Qt.AspectRatioMode.KeepAspectRatio,
                              Qt.TransformationMode.SmoothTransformation)
                )

    def start_camera_stream(self) -> None:
        self._cam_stop.clear()
        self._cam_stream_sig.emit(True)
        t = threading.Thread(target=self._cam_loop, daemon=True, name="cam-stream")
        t.start()

    def _cam_loop(self) -> None:
        try:
            import cv2
            # Reuse camera index detected by screen_processor (cached in api_keys.json)
            cam_idx = 0
            try:
                import json as _j
                cfg = _j.loads((CONFIG_DIR / "api_keys.json").read_text())
                cam_idx = int(cfg.get("camera_index", 0))
            except Exception:
                pass
            try:
                backend = cv2.CAP_DSHOW if _OS == "Windows" else cv2.CAP_ANY
            except AttributeError:
                backend = 0
            cap = cv2.VideoCapture(cam_idx, backend)
            if not cap.isOpened():
                cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                return
            # warm-up frames
            for _ in range(5):
                cap.read()
            while not self._cam_stop.wait(0.033) and cap.isOpened():
                ret, frame = cap.read()
                if ret and frame is not None:
                    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 65])
                    self._cam_frame_sig.emit(buf.tobytes())
            cap.release()
        except Exception as e:
            print(f"[Camera] Stream error: {e}")
        finally:
            self._cam_stream_sig.emit(False)

    def stop_camera_stream(self) -> None:
        self._cam_stop.set()

    # ------------------------------------------------------------------
    # Icon generation — arc-reactor style, rendered with Pillow
    # ------------------------------------------------------------------
    @staticmethod
    def _build_jarvis_icon(out_path: Path) -> bool:
        """
        Render a JARVIS arc-reactor icon at 4× resolution and downsample
        for crisp results at all sizes. Saves a multi-res .ico to out_path.
        Returns True on success.
        """
        try:
            import math
            import PIL.Image
            import PIL.ImageDraw
            import PIL.ImageFilter
        except ImportError:
            return False

        CYAN   = (0, 212, 255)
        DIM    = (0, 100, 140)
        DARK   = (0, 6, 10)
        GLOW   = (0, 160, 200)
        WHITE  = (220, 240, 255)

        def _render(sz: int) -> PIL.Image.Image:
            S  = sz * 4                     # draw at 4× then downscale
            img = PIL.Image.new("RGBA", (S, S), (0, 0, 0, 0))
            d   = PIL.ImageDraw.Draw(img)
            cx = cy = S // 2

            # ── filled background circle ──────────────────────────────────
            R = S // 2 - 2
            d.ellipse([cx-R, cy-R, cx+R, cy+R], fill=(*DARK, 255))

            # ── outer border ring ─────────────────────────────────────────
            lw = max(2, S // 40)
            d.ellipse([cx-R, cy-R, cx+R, cy+R],
                      outline=(*CYAN, 220), width=lw)

            # ── mid decorative ring ───────────────────────────────────────
            R2 = int(R * 0.72)
            d.ellipse([cx-R2, cy-R2, cx+R2, cy+R2],
                      outline=(*DIM, 180), width=max(1, lw // 2))

            # ── 6 radial spokes (hex bolt) ────────────────────────────────
            R_inner = int(R * 0.30)
            R_outer = int(R * 0.62)
            spoke_w = max(1, S // 80)
            for i in range(6):
                angle = math.radians(i * 60 - 30)
                x1 = cx + int(R_inner * math.cos(angle))
                y1 = cy + int(R_inner * math.sin(angle))
                x2 = cx + int(R_outer * math.cos(angle))
                y2 = cy + int(R_outer * math.sin(angle))
                d.line([x1, y1, x2, y2], fill=(*GLOW, 200), width=spoke_w)

            # ── 6 tick marks on outer ring ────────────────────────────────
            for i in range(6):
                angle = math.radians(i * 60)
                for dr in range(lw * 2):
                    rx = (R - lw - dr)
                    d.point(
                        [cx + int(rx * math.cos(angle)),
                         cy + int(rx * math.sin(angle))],
                        fill=(*WHITE, 220),
                    )

            # ── inner glowing ring ────────────────────────────────────────
            Ri = int(R * 0.26)
            d.ellipse([cx-Ri, cy-Ri, cx+Ri, cy+Ri],
                      outline=(*CYAN, 255), width=max(2, lw))

            # ── bright glow soft blur applied before core ─────────────────
            # (draw a slightly larger cyan circle on a separate layer)
            glow_layer = PIL.Image.new("RGBA", (S, S), (0, 0, 0, 0))
            gd = PIL.ImageDraw.Draw(glow_layer)
            Rc = int(R * 0.13)
            gd.ellipse([cx-Rc*2, cy-Rc*2, cx+Rc*2, cy+Rc*2],
                       fill=(*CYAN, 110))
            glow_layer = glow_layer.filter(PIL.ImageFilter.GaussianBlur(S // 14))
            img = PIL.Image.alpha_composite(img, glow_layer)
            d   = PIL.ImageDraw.Draw(img)

            # ── core dot ──────────────────────────────────────────────────
            d.ellipse([cx-Rc, cy-Rc, cx+Rc, cy+Rc], fill=(*WHITE, 255))

            # ── downscale to target size ──────────────────────────────────
            return img.resize((sz, sz), PIL.Image.LANCZOS)

        try:
            sizes  = [256, 128, 64, 48, 32, 16]
            frames = [_render(s) for s in sizes]
            frames[0].save(
                out_path,
                format="ICO",
                append_images=frames[1:],
                sizes=[(s, s) for s in sizes],
            )
            return True
        except Exception as e:
            print(f"[Shortcut] ⚠️  Icon generation failed: {e}")
            return False

    @staticmethod
    def _create_lnk_windows(lnk: str, target: str, args: str,
                             work_dir: str, icon_loc: str) -> None:
        """
        Create a Windows .lnk shortcut WITHOUT launching PowerShell or cmd.
        Tries win32com (pywin32) first; falls back to wscript.exe + VBScript.
        wscript.exe is a GUI-mode host — it never opens a console window.
        """
        # ── Option 1: pywin32 (pure Python COM, zero subprocess) ──────────
        try:
            from win32com.client import Dispatch   # type: ignore
            sh = Dispatch("WScript.Shell")
            sc = sh.CreateShortCut(lnk)
            sc.TargetPath       = target
            sc.Arguments        = f'"{args}"'
            sc.WorkingDirectory = work_dir
            sc.Description      = "J.A.R.V.I.S AI Assistant"
            sc.IconLocation     = icon_loc
            sc.save()
            return
        except ImportError:
            pass

        # ── Option 2: wscript.exe + VBScript (always available on Windows,
        #    GUI-mode executable — never opens a console window) ────────────
        vbs = "\n".join([
            'Set ws = CreateObject("WScript.Shell")',
            f'Set sc = ws.CreateShortcut("{lnk}")',
            f'sc.TargetPath = "{target}"',
            f'sc.Arguments = Chr(34) & "{args}" & Chr(34)',
            f'sc.WorkingDirectory = "{work_dir}"',
            'sc.Description = "J.A.R.V.I.S AI Assistant"',
            f'sc.IconLocation = "{icon_loc}"',
            'sc.Save',
        ])
        import tempfile
        fd, tmp = tempfile.mkstemp(suffix=".vbs")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(vbs)
            proc = subprocess.Popen(
                ["wscript.exe", "/nologo", tmp],
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
            )
            proc.wait(timeout=10)
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass

    @staticmethod
    def _get_desktop_dir() -> Path:
        """
        Resolve the user's REAL desktop directory instead of assuming
        ~/Desktop, which breaks when:
          • OneDrive "Known Folder Move" relocates the desktop
            (C:/Users/x/OneDrive/Desktop) — very common on Win 10/11;
          • the XDG desktop is localized on Linux (~/Masaüstü,
            ~/Schreibtisch, ~/Bureau, …).
        Falls back to ~/Desktop only as a last resort.
        """
        home = Path.home()
        _os = platform.system()

        if _os == "Windows":
            # ── 1) SHGetKnownFolderPath(FOLDERID_Desktop) — the canonical
            #       answer; follows OneDrive redirection. No dependencies. ──
            try:
                import ctypes
                from ctypes import wintypes

                class _GUID(ctypes.Structure):
                    _fields_ = [("Data1", wintypes.DWORD),
                                ("Data2", wintypes.WORD),
                                ("Data3", wintypes.WORD),
                                ("Data4", ctypes.c_ubyte * 8)]

                # FOLDERID_Desktop {B4BFCC3A-DB2C-424C-B029-7FE99A87C641}
                fid = _GUID(0xB4BFCC3A, 0xDB2C, 0x424C,
                            (ctypes.c_ubyte * 8)(0xB0, 0x29, 0x7F, 0xE9,
                                                 0x9A, 0x87, 0xC6, 0x41))
                buf = ctypes.c_wchar_p()
                if ctypes.windll.shell32.SHGetKnownFolderPath(
                        ctypes.byref(fid), 0, None, ctypes.byref(buf)) == 0:
                    p = Path(buf.value)
                    ctypes.windll.ole32.CoTaskMemFree(buf)
                    if p.is_dir():
                        return p
            except Exception:
                pass

            # ── 2) Registry: User Shell Folders (may contain %VARS%) ──────
            try:
                import winreg
                with winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER,
                        r"Software\Microsoft\Windows\CurrentVersion"
                        r"\Explorer\User Shell Folders") as key:
                    val, _t = winreg.QueryValueEx(key, "Desktop")
                p = Path(os.path.expandvars(val))
                if p.is_dir():
                    return p
            except Exception:
                pass

        elif _os == "Linux":
            # ── xdg-user-dir honours localized names (~/Masaüstü, …) ──────
            try:
                out = subprocess.run(["xdg-user-dir", "DESKTOP"],
                                     capture_output=True, text=True, timeout=5)
                p = Path(out.stdout.strip())
                if out.stdout.strip() and p != home and p.is_dir():
                    return p
            except Exception:
                pass
            try:
                cfg = home / ".config" / "user-dirs.dirs"
                for line in cfg.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line.startswith("XDG_DESKTOP_DIR"):
                        val = line.split("=", 1)[1].strip().strip('"')
                        p = Path(val.replace("$HOME", str(home)))
                        if p != home and p.is_dir():
                            return p
            except Exception:
                pass

        # macOS: ~/Desktop is always the real path (localization is
        # display-only). Everything else lands here as a last resort.
        return home / "Desktop"

    def _create_desktop_shortcut(self):
        """
        Create a desktop shortcut on Windows / macOS / Linux.
        Never opens a terminal, console, or PowerShell window on any platform.
        """
        import stat as _stat
        script  = Path(__file__).resolve().parent / "main.py"
        python  = Path(sys.executable)
        desktop = self._get_desktop_dir()

        # Arc-reactor icon (.ico — also exported as .png for Linux/macOS)
        ico_path = Path(__file__).resolve().parent / "config" / "jarvis.ico"
        if not ico_path.exists():
            self._build_jarvis_icon(ico_path)

        try:
            _os = platform.system()

            # ── Windows ───────────────────────────────────────────────────────
            if _os == "Windows":
                pythonw  = python.parent / "pythonw.exe"
                target   = str(pythonw if pythonw.exists() else python)
                lnk      = str(desktop / "J.A.R.V.I.S.lnk")
                icon_loc = str(ico_path) if ico_path.exists() else f"{target},0"
                self._create_lnk_windows(lnk, target, str(script),
                                         str(script.parent), icon_loc)

            # ── macOS — proper .app bundle (no Terminal window) ───────────────
            elif _os == "Darwin":
                app     = desktop / "J.A.R.V.I.S.app"
                mac_dir = app / "Contents" / "MacOS"
                res_dir = app / "Contents" / "Resources"
                mac_dir.mkdir(parents=True, exist_ok=True)
                res_dir.mkdir(exist_ok=True)

                # Launcher executable (bash — runs as background process,
                # macOS does NOT open Terminal for executables inside .app bundles)
                launcher = mac_dir / "JARVIS"
                launcher.write_text(
                    "#!/usr/bin/env bash\n"
                    f'cd "{script.parent}"\n'
                    f'exec "{python}" "{script}"\n'
                )
                launcher.chmod(launcher.stat().st_mode
                               | _stat.S_IEXEC | _stat.S_IXGRP | _stat.S_IXOTH)

                # Minimal Info.plist (required for .app recognition)
                (app / "Contents" / "Info.plist").write_text(
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                    '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                    '<plist version="1.0"><dict>\n'
                    '  <key>CFBundleExecutable</key><string>JARVIS</string>\n'
                    '  <key>CFBundleIdentifier</key>'
                    '<string>com.jarvis.assistant</string>\n'
                    '  <key>CFBundleName</key><string>J.A.R.V.I.S</string>\n'
                    '  <key>CFBundlePackageType</key><string>APPL</string>\n'
                    '  <key>CFBundleVersion</key><string>1.0</string>\n'
                    '</dict></plist>\n'
                )

                # Optional: copy icon as .icns (skip silently if Pillow is missing)
                try:
                    import PIL.Image
                    icns = res_dir / "AppIcon.icns"
                    PIL.Image.open(ico_path).save(icns, format="ICNS")
                    # Inject icon reference into plist
                    plist = app / "Contents" / "Info.plist"
                    txt = plist.read_text()
                    plist.write_text(
                        txt.replace(
                            '</dict></plist>',
                            '  <key>CFBundleIconFile</key>'
                            '<string>AppIcon</string>\n</dict></plist>\n',
                        )
                    )
                except Exception:
                    pass  # icon is optional

            # ── Linux — .desktop file (Terminal=false, no console) ────────────
            else:
                # Export .ico → .png for better desktop integration
                png_path = ico_path.with_suffix(".png")
                if not png_path.exists() and ico_path.exists():
                    try:
                        import PIL.Image
                        PIL.Image.open(ico_path).resize(
                            (256, 256), PIL.Image.LANCZOS
                        ).save(png_path, format="PNG")
                    except Exception:
                        png_path = ico_path  # fallback to .ico

                icon_line = f"Icon={png_path}\n" if png_path.exists() else ""
                desk = desktop / "J.A.R.V.I.S.desktop"
                desk.write_text(
                    "[Desktop Entry]\n"
                    "Name=J.A.R.V.I.S\n"
                    f"Exec={python} {script}\n"
                    f"Path={script.parent}\n"
                    "Type=Application\n"
                    "Terminal=false\n"
                    "Categories=Utility;\n"
                    + icon_line
                )
                desk.chmod(desk.stat().st_mode | 0o755)

            self._log.append_log("SYS: Desktop shortcut created.")
        except Exception as e:
            self._log.append_log(f"ERR: Shortcut failed — {e}")

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_F8 and not event.isAutoRepeat():
            self._push_to_talk_start()
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_F8 and not event.isAutoRepeat():
            self._push_to_talk_stop()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cw = self.centralWidget()
        if hasattr(self, '_footer'):
            self._position_footer()
        if hasattr(self, '_content_panel') and self._content_panel.isVisible():
            self._position_content_panel()
        if self._overlay and self._overlay.isVisible():
            ow, oh = 460, 390
            self._overlay.setGeometry(
                (cw.width()  - ow) // 2,
                (cw.height() - oh) // 2,
                ow, oh,
            )
        if self._remote_overlay and self._remote_overlay.isVisible():
            ow, oh = RemoteKeyOverlay._OW, RemoteKeyOverlay._OH
            self._remote_overlay.setGeometry(
                (cw.width()  - ow) // 2,
                (cw.height() - oh) // 2,
                ow, oh,
            )
        if self._customize_overlay and self._customize_overlay.isVisible():
            ow, oh = CustomizeOverlay._OW, CustomizeOverlay._OH
            self._customize_overlay.setGeometry(
                (cw.width()  - ow) // 2,
                (cw.height() - oh) // 2,
                ow, oh,
            )
        # Camera preview — bottom-right corner of the center/HUD area
        pw = _CameraPreview._W
        ph = self._cam_preview.height() or _CameraPreview._H
        self._cam_preview.setGeometry(
            cw.width() - _RIGHT_W - pw - 12,
            cw.height() - ph - 28,
            pw, ph,
        )
        # Clipboard panel — bottom-center
        if hasattr(self, '_clipboard_panel') and self._clipboard_panel.isVisible():
            self._position_clipboard_panel()
        # Quick drawer — reposition if open
        if hasattr(self, '_quick_drawer') and self._quick_drawer.isVisible():
            self._position_quick_drawer()

    def _position_footer(self) -> None:
        cw = self.centralWidget()
        width = max(280, cw.width() - _LEFT_W - _RIGHT_W)
        self._footer.setGeometry(
            _LEFT_W,
            max(0, cw.height() - self._footer.height() - 72),
            width,
            self._footer.height(),
        )
        compact = width < 680
        if hasattr(self, '_composer_wave_left'):
            self._composer_wave_left.setVisible(not compact)
            self._composer_wave_right.setVisible(not compact)
        self._footer.raise_()

    def _position_content_panel(self) -> None:
        """Place response content as a compact card above the voice composer."""
        cw = self.centralWidget()
        available = max(280, cw.width() - _LEFT_W - _RIGHT_W)
        width = min(680, max(360, available - 72))
        height = min(300, max(190, cw.height() - self._footer.height() - 210))
        x = _LEFT_W + (available - width) // 2
        y = max(54, self._footer.y() - height - 18)
        self._content_panel.setGeometry(x, y, width, height)
        self._content_panel.raise_()

    def _update_metrics(self):
        reminder = next_reminder_context()
        if reminder:
            self._ctx_reminder_title.setText(reminder[0])
            self._ctx_reminder_body.setText(reminder[1])
        else:
            self._ctx_reminder_title.setText("Keine Erinnerung geplant")
            self._ctx_reminder_body.setText("Neue Erinnerungen erscheinen hier automatisch.")

        project = latest_project_context()
        if project:
            self._ctx_project_title.setText(project[0])
            self._ctx_project_body.setText(project[1])
        else:
            self._ctx_project_title.setText("Kein gespeichertes Projekt")
            self._ctx_project_body.setText(
                "Sobald Mica ein Projekt im Gedächtnis speichert, wird es hier gezeigt."
            )

        self._ctx_audio.set_level(self.hud._amp_disp)
        self._ctx_audio.set_muted(self._muted)


    def _build_header(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(64)
        w.setStyleSheet(f"background: {C.DARK}; border-bottom: 1px solid {C.BORDER};")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(20, 0, 20, 0)

        def _badge(txt, color=C.TEXT_MED):
            l = QLabel(txt)
            l.setFont(QFont("Courier New", 8))
            l.setStyleSheet(f"color: {color}; background: transparent;")
            return l

        lay.addWidget(_badge("MICA", C.PRI_DIM))
        lay.addSpacing(8)
        self._drawer_btn = QPushButton("⚙")
        self._drawer_btn.setFixedSize(26, 26)
        self._drawer_btn.setFont(QFont("Courier New", 11))
        self._drawer_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._drawer_btn.setToolTip("Settings & Controls")
        self._drawer_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL2}; color: {C.TEXT_DIM};
                border: 1px solid {C.BORDER}; border-radius: 13px;
            }}
            QPushButton:hover {{ color: {C.PRI}; border-color: {C.PRI_DIM}; }}
            QPushButton:checked {{ color: {C.PRI}; border-color: {C.PRI}; background: {C.PRI_GHO}; }}
        """)
        self._drawer_btn.setCheckable(True)
        self._drawer_btn.clicked.connect(self._toggle_drawer)
        lay.addWidget(self._drawer_btn)
        lay.addStretch()

        mid = QVBoxLayout(); mid.setSpacing(1)
        _disp = self._assistant_name.upper()
        self._title_lbl = QLabel(_disp)
        self._title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_lbl.setFont(QFont("Segoe UI", 17, QFont.Weight.DemiBold))
        self._title_lbl.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        mid.addWidget(self._title_lbl)
        _sub_text = ("Just A Rather Very Intelligent System"
                     if _disp in ("JARVIS", "J.A.R.V.I.S")
                     else "Personal AI Assistant")
        self._sub_lbl = QLabel(_sub_text)
        self._sub_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sub_lbl.setFont(QFont("Segoe UI", 8))
        self._sub_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        mid.addWidget(self._sub_lbl)
        lay.addLayout(mid)
        lay.addStretch()

        right_col = QVBoxLayout(); right_col.setSpacing(2)
        self._clock_lbl = QLabel("00:00:00")
        self._clock_lbl.setFont(QFont("Segoe UI", 13, QFont.Weight.DemiBold))
        self._clock_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._clock_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._clock_lbl)
        self._date_lbl = QLabel("")
        self._date_lbl.setFont(QFont("Segoe UI", 8))
        self._date_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        self._date_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._date_lbl)
        lay.addLayout(right_col)
        return w

    def _tick_clock(self):
        self._clock_lbl.setText(time.strftime("%H:%M:%S"))
        self._date_lbl.setText(time.strftime("%a %d %b %Y"))

    def _build_left_panel(self) -> QWidget:
        w = QWidget()
        w.setFixedWidth(_LEFT_W)
        w.setStyleSheet(f"background: {C.PANEL}; border-right: 1px solid {C.BORDER};")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(18, 56, 18, 24)
        lay.setSpacing(10)

        brand = QHBoxLayout()
        brand.setSpacing(8)
        brand_mark = QLabel()
        brand_mark.setFixedSize(31, 31)
        mark = QPixmap(str(BASE_DIR / "assets" / "mica-orb-v2.png"))
        if not mark.isNull():
            brand_mark.setPixmap(mark.scaled(31, 31, Qt.AspectRatioMode.KeepAspectRatio,
                                             Qt.TransformationMode.SmoothTransformation))
        brand.addWidget(brand_mark)
        self._brand_lbl = QLabel("MICA")
        self._brand_lbl.setFont(QFont("Segoe UI", 12, QFont.Weight.DemiBold))
        self._brand_lbl.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        brand.addWidget(self._brand_lbl)
        brand.addStretch()
        lay.addLayout(brand)
        # Keep every destination visible even at Mica's minimum window height.
        lay.addSpacing(40)

        self._nav_buttons: dict[str, QPushButton] = {}
        nav_specs = (("chat", "Chat"), ("history", "Verlauf"),
                     ("reminders", "Erinnerungen"), ("memory", "Gedächtnis"),
                     ("settings", "Einstellungen"))
        for index, (key, text) in enumerate(nav_specs):
            button = QPushButton(text)
            button.setIcon(_outline_nav_icon(key, C.TEXT_MED))
            button.setIconSize(QSize(24, 24))
            button.setFixedHeight(54)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFont(QFont("Segoe UI", 9, QFont.Weight.Medium))
            button.setToolTip(text)
            button.setAccessibleName(text)
            button.clicked.connect(lambda _checked=False, target=key: self._activate_navigation(target))
            self._nav_buttons[key] = button
            lay.addWidget(button)
            if index < len(nav_specs) - 1:
                lay.addSpacing(8)

        lay.addStretch()
        self._style_navigation("chat")
        return w

    def _style_navigation(self, active: str) -> None:
        for key, button in self._nav_buttons.items():
            selected = key == active
            button.setIcon(_outline_nav_icon(key, C.PRI if selected else C.TEXT_MED))
            button.setStyleSheet(f"""
                QPushButton {{
                    color: {C.PRI if selected else C.TEXT_MED}; background: {C.PRI_GHO if selected else 'transparent'};
                    border: 1px solid {C.BORDER if selected else 'transparent'}; border-radius: 14px;
                    text-align: center; padding: 9px 3px;
                }}
                QPushButton:hover {{ color: {C.PRI}; background: {C.PRI_GHO}; border-color: {C.BORDER}; }}
                QPushButton:focus {{ border-color: {C.PRI}; }}
            """)

    def _activate_navigation(self, target: str) -> None:
        self._quick_drawer.hide()
        self._view_stack.setCurrentIndex(
            {"chat": 0, "history": 1, "reminders": 2, "memory": 3, "settings": 4}.get(target, 0)
        )
        self._footer.setVisible(target == "chat")
        if target == "reminders":
            self._refresh_reminders_page()
        elif target == "memory":
            self._refresh_memory_page()
        self._style_navigation(target)

    def _build_history_page(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet(f"background: {C.BG};")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(46, 42, 46, 32)
        lay.setSpacing(14)
        title = QLabel("Verlauf")
        title.setFont(QFont("Segoe UI", 24, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        lay.addWidget(title)
        sub = QLabel("Reale Sitzungsereignisse, Antworten und geladene Dateien.")
        sub.setFont(QFont("Segoe UI", 10))
        sub.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        lay.addWidget(sub)
        self._log = LogWidget()
        self._log.setAccessibleName("Sitzungsverlauf")
        lay.addWidget(self._log, stretch=1)
        return page

    def _build_reminders_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("RemindersPage")
        page.setStyleSheet(f"background: {C.BG};")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(46, 42, 46, 32)
        lay.setSpacing(14)
        title = QLabel("Erinnerungen")
        title.setFont(QFont("Segoe UI", 24, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        lay.addWidget(title)
        sub = QLabel("Deine lokal geplanten Erinnerungen auf einen Blick.")
        sub.setFont(QFont("Segoe UI", 10))
        sub.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        lay.addWidget(sub)
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
            from actions.reminder import list_upcoming_reminders
            reminders = list_upcoming_reminders(limit=50)
        except Exception:
            reminders = []

        if not reminders:
            reminders = [{
                "when": "Noch nichts geplant",
                "message": "Bitte Mica im Chat, dich an etwas zu erinnern.",
            }]
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
        page = QWidget()
        page.setObjectName("MemoryPage")
        page.setStyleSheet(f"background: {C.BG};")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(46, 42, 46, 32)
        lay.setSpacing(14)

        title = QLabel("Gedächtnis")
        title.setFont(QFont("Segoe UI", 24, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        lay.addWidget(title)
        sub = QLabel("Lokal gespeicherte Informationen verwalten. Änderungen bleiben auf diesem PC.")
        sub.setFont(QFont("Segoe UI", 10))
        sub.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        lay.addWidget(sub)

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
        self._memory_category_input.addItems(["Notizen", "Vorlieben", "Identität", "Projekte", "Wünsche", "Beziehungen"])
        self._memory_category_input.setAccessibleName("Kategorie")
        self._memory_category_input.setFixedHeight(38)
        self._memory_key_input = QLineEdit()
        self._memory_key_input.setPlaceholderText("Titel, z. B. Lieblingsgetränk")
        self._memory_key_input.setAccessibleName("Titel der Information")
        self._memory_key_input.setFixedHeight(38)
        row.addWidget(self._memory_category_input)
        row.addWidget(self._memory_key_input, stretch=1)
        form.addLayout(row)

        self._memory_value_input = QTextEdit()
        self._memory_value_input.setPlaceholderText("Was soll Mica sich merken?")
        self._memory_value_input.setAccessibleName("Inhalt der Information")
        self._memory_value_input.setFixedHeight(72)
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
        self._memory_status.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
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
        from memory.memory_manager import all_entries_for_ui
        rows = all_entries_for_ui()
        self._memory_status.setText(f"{len(rows)} lokal gespeicherte Information{'en' if len(rows) != 1 else ''}")
        if not rows:
            empty = QLabel("Noch nichts gespeichert. Du kannst oben eine Information hinzufügen.")
            empty.setFont(QFont("Segoe UI", 10))
            empty.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent; padding: 14px;")
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
            meta = QLabel(f"{entry['category'].title()} · {entry['updated'] or 'lokal gespeichert'}")
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
            delete.clicked.connect(lambda _=False, c=entry["category"], k=entry["key"]: self._forget_memory_entry(c, k))
            row.addWidget(delete, alignment=Qt.AlignmentFlag.AlignTop)
            self._memory_entries_layout.addWidget(card)
        self._memory_entries_layout.addStretch()

    def _add_memory_entry(self) -> None:
        key = self._memory_key_input.text().strip()
        value = self._memory_value_input.toPlainText().strip()
        if not key or not value:
            self._memory_status.setText("Bitte gib einen Titel und eine Information ein.")
            self._memory_status.setStyleSheet(f"color: {C.RED}; background: transparent;")
            return
        categories = {"Notizen": "notes", "Vorlieben": "preferences", "Identität": "identity",
                      "Projekte": "projects", "Wünsche": "wishes", "Beziehungen": "relationships"}
        from memory.memory_manager import remember
        remember(key, value, categories[self._memory_category_input.currentText()])
        self._memory_key_input.clear()
        self._memory_value_input.clear()
        self._refresh_memory_page()
        self._memory_status.setStyleSheet(f"color: {C.GREEN}; background: transparent;")
        self._memory_status.setText("Lokal gespeichert.")
        self._update_metrics()

    def _forget_memory_entry(self, category: str, key: str) -> None:
        from memory.memory_manager import forget
        forget(key, category)
        self._refresh_memory_page()
        self._memory_status.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._memory_status.setText("Information gelöscht.")
        self._update_metrics()

    def _build_settings_page(self) -> QWidget:
        page = QWidget()
        page.setObjectName("SettingsPage")
        page.setStyleSheet(f"background: {C.BG};")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(46, 42, 46, 32)
        lay.setSpacing(12)
        title = QLabel("Einstellungen")
        title.setFont(QFont("Segoe UI", 24, QFont.Weight.DemiBold))
        title.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        lay.addWidget(title)
        sub = QLabel("Passe Mica, Audio, Gedächtnis und Fernzugriff an.")
        sub.setFont(QFont("Segoe UI", 10))
        sub.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        lay.addWidget(sub)
        for heading, detail, callback in (
            ("Mica anpassen", "Name, weibliche Stimme und Akzentfarbe", self._open_customize),
            ("Audio-Geräte", "Mikrofon und Lautsprecher auswählen", self._open_audio_devices),
            ("Gedächtnis", "Lokal gespeicherte Informationen ansehen", self._open_memory_panel),
            ("Erweiterungen", "Installierte Plugins verwalten", self._open_plugin_manager),
            ("Fernzugriff", "Sichere Verbindung für dein Telefon öffnen", self._open_remote),
        ):
            button = QPushButton(f"{heading}\n{detail}")
            button.setMinimumHeight(62)
            button.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setAccessibleName(heading)
            button.setStyleSheet(f"""
                QPushButton {{ background: {C.PANEL}; color: {C.TEXT};
                    border: 1px solid {C.BORDER}; border-radius: 14px;
                    text-align: left; padding: 9px 16px; }}
                QPushButton:hover {{ background: {C.PRI_GHO}; border-color: {C.BORDER_B}; }}
                QPushButton:focus {{ border: 2px solid {C.PRI}; }}
            """)
            button.clicked.connect(callback)
            lay.addWidget(button)
        lay.addStretch()
        return page

    def _build_right_panel(self) -> QWidget:
        w = QWidget()
        w.setFixedWidth(_RIGHT_W)
        w.setStyleSheet(f"background: {C.BG};")
        outer = QVBoxLayout(w)
        outer.setContentsMargins(18, 54, 18, 52)
        panel = QFrame()
        panel.setObjectName("ContextPanel")
        panel.setStyleSheet(f"""
            QFrame#ContextPanel {{
                background: {C.PANEL}; border: 1px solid {C.BORDER}; border-radius: 16px;
            }}
        """)
        outer.addWidget(panel)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(22, 28, 22, 22)
        lay.setSpacing(14)

        heading = QLabel("Kontext")
        heading.setFont(QFont("Segoe UI", 17, QFont.Weight.DemiBold))
        heading.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        lay.addWidget(heading)

        live, self._ctx_live_title, self._ctx_live_body = _context_card(
            QStyle.StandardPixmap.SP_DialogApplyButton, "Wird verbunden", "Mica bereitet sich vor.", w)
        lay.addWidget(live)

        audio_card = QFrame()
        audio_card.setObjectName("ContextCard")
        audio_card.setMinimumHeight(110)
        audio_card.setStyleSheet(f"QFrame#ContextCard {{ background: {C.PANEL}; border: 1px solid {C.BORDER}; border-radius: 12px; }}")
        audio_lay = QVBoxLayout(audio_card)
        audio_lay.setContentsMargins(14, 12, 14, 12)
        audio_lay.setSpacing(5)
        audio_title = QLabel("Audioeingang")
        audio_title.setFont(QFont("Segoe UI", 9, QFont.Weight.DemiBold))
        audio_title.setStyleSheet(f"color: {C.TEXT}; background: transparent;")
        audio_lay.addWidget(audio_title)
        self._ctx_audio = LiveWaveform(compact=True)
        self._ctx_audio.setAccessibleName("Mikrofonpegel")
        audio_lay.addWidget(self._ctx_audio)
        lay.addWidget(audio_card)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 8px 0;")
        lay.addWidget(sep)

        reminder, self._ctx_reminder_title, self._ctx_reminder_body = _context_card(
            QStyle.StandardPixmap.SP_FileDialogContentsView, "Keine Erinnerung geplant",
            "Neue Erinnerungen erscheinen hier automatisch.", w, 100)
        lay.addWidget(reminder)
        project, self._ctx_project_title, self._ctx_project_body = _context_card(
            QStyle.StandardPixmap.SP_FileIcon, "Kein gespeichertes Projekt",
            "Sobald Mica ein Projekt im Gedächtnis speichert, wird es hier gezeigt.", w, 118)
        lay.addWidget(project)
        lay.addStretch()

        return w

    def _build_quick_drawer(self) -> QWidget:
        """Floating settings drawer opened from the navigation rail."""
        _BTN_STYLE_PRI = f"""
            QPushButton {{
                background: {C.PRI_GHO}; color: {C.PRI};
                border: 1px solid #c9dcfb; border-radius: 8px;
                text-align: left; padding: 0 8px;
            }}
            QPushButton:hover {{ background: #dceaff; border-color: {C.PRI}; }}
        """
        _BTN_STYLE_DIM = f"""
            QPushButton {{
                background: {C.PANEL}; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 8px;
                text-align: left; padding: 0 8px;
            }}
            QPushButton:hover {{ color: {C.PRI}; border-color: {C.BORDER_B}; }}
        """

        w = QWidget(self.centralWidget())
        w.setObjectName("QuickDrawer")
        w.setStyleSheet(f"""
            QWidget#QuickDrawer {{
                background: {C.PANEL};
                border: 1px solid {C.BORDER_B};
                border-radius: 12px;
            }}
        """)
        w.hide()

        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 8, 10, 10)
        lay.setSpacing(5)

        hdr = QLabel("EINSTELLUNGEN")
        hdr.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        hdr.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent; "
                          f"border-bottom: 1px solid {C.BORDER}; padding-bottom: 4px;")
        lay.addWidget(hdr)

        remote_btn = QPushButton("Fernzugriff")
        remote_btn.setFixedHeight(30)
        remote_btn.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        remote_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remote_btn.setStyleSheet(_BTN_STYLE_PRI)
        remote_btn.clicked.connect(self._open_remote)
        lay.addWidget(remote_btn)

        fs_btn = QPushButton("Vollbild  [F11]")
        fs_btn.setFixedHeight(26)
        fs_btn.setFont(QFont("Segoe UI", 8))
        fs_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        fs_btn.setStyleSheet(_BTN_STYLE_DIM)
        fs_btn.clicked.connect(self._toggle_fullscreen)
        lay.addWidget(fs_btn)

        sc_btn = QPushButton("Desktop-Verknüpfung erstellen")
        sc_btn.setFixedHeight(26)
        sc_btn.setFont(QFont("Segoe UI", 8))
        sc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        sc_btn.setStyleSheet(_BTN_STYLE_DIM)
        sc_btn.clicked.connect(self._create_desktop_shortcut)
        lay.addWidget(sc_btn)

        self._autostart_btn = QPushButton("Automatischer Start: aus")
        self._autostart_btn.setFixedHeight(26)
        self._autostart_btn.setFont(QFont("Segoe UI", 8))
        self._autostart_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._autostart_btn.clicked.connect(self._toggle_autostart)
        lay.addWidget(self._autostart_btn)

        cust_btn = QPushButton("Mica anpassen")
        cust_btn.setFixedHeight(26)
        cust_btn.setFont(QFont("Segoe UI", 8))
        cust_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cust_btn.setStyleSheet(_BTN_STYLE_DIM)
        cust_btn.clicked.connect(self._open_customize)
        lay.addWidget(cust_btn)

        self._brief_btn = QPushButton()
        self._brief_btn.setFixedHeight(26)
        self._brief_btn.setFont(QFont("Segoe UI", 8))
        self._brief_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._brief_btn.clicked.connect(self._toggle_brief)
        lay.addWidget(self._brief_btn)

        self._motion_btn = QPushButton()
        self._motion_btn.setFixedHeight(26)
        self._motion_btn.setFont(QFont("Segoe UI", 7))
        self._motion_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._motion_btn.setStyleSheet(_BTN_STYLE_DIM)
        self._motion_btn.clicked.connect(self._toggle_reduced_motion)
        self._update_motion_btn()
        lay.addWidget(self._motion_btn)

        audio_btn = QPushButton("Audio-Geräte")
        audio_btn.setFixedHeight(26)
        audio_btn.setFont(QFont("Segoe UI", 8))
        audio_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        audio_btn.setStyleSheet(_BTN_STYLE_DIM)
        audio_btn.clicked.connect(self._open_audio_devices)
        lay.addWidget(audio_btn)

        mem_btn = QPushButton("Gedächtnis")
        mem_btn.setFixedHeight(26)
        mem_btn.setFont(QFont("Segoe UI", 8))
        mem_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        mem_btn.setStyleSheet(_BTN_STYLE_DIM)
        mem_btn.clicked.connect(self._open_memory_panel)
        lay.addWidget(mem_btn)

        plugin_btn = QPushButton("Erweiterungen")
        plugin_btn.setFixedHeight(26)
        plugin_btn.setFont(QFont("Segoe UI", 8))
        plugin_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        plugin_btn.setStyleSheet(_BTN_STYLE_DIM)
        plugin_btn.clicked.connect(self._open_plugin_manager)
        lay.addWidget(plugin_btn)

        w.adjustSize()
        return w

    def _toggle_drawer(self, checked: bool):
        if checked:
            self._position_quick_drawer()
            self._quick_drawer.show()
            self._quick_drawer.raise_()
        else:
            self._quick_drawer.hide()

    def _position_quick_drawer(self):
        if not hasattr(self, '_quick_drawer'):
            return
        _W = 220
        self._quick_drawer.setFixedWidth(_W)
        self._quick_drawer.adjustSize()
        self._quick_drawer.setGeometry(_LEFT_W + 12, 22, _W, self._quick_drawer.sizeHint().height())

    def _build_input_row(self) -> QHBoxLayout:
        row = QHBoxLayout(); row.setContentsMargins(12, 8, 12, 8); row.setSpacing(8)
        self._input = ComposerInput()
        self._input.setPlaceholderText("Sag etwas oder schreibe eine Nachricht …")
        self._input.setFont(QFont("Segoe UI", 10))
        self._input.setFixedHeight(48)
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: transparent; color: {C.WHITE};
                border: none; padding: 3px 9px;
            }}
            QLineEdit:focus {{ color: {C.TEXT}; outline: none; }}
        """)
        self._input.returnPressed.connect(self._send)
        self._input.file_dropped.connect(self._on_file_selected)
        row.addWidget(self._input)

        send = QPushButton()
        send.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowForward))
        send.setIconSize(QSize(25, 25))
        send.setAccessibleName("Nachricht senden")
        send.setToolTip("Nachricht senden")
        send.setFixedSize(48, 48)
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.PRI};
                border: none; border-radius: 24px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; }}
            QPushButton:focus {{ border: 1px solid {C.PRI}; }}
        """)
        send.clicked.connect(self._send)
        row.addWidget(send)
        return row

    def _build_content_panel(self) -> QWidget:
        """
        Floating response card for search results, news and briefings.
        It stays hidden until Mica has real content to show.
        """
        w = QWidget()
        w.setObjectName("ContentPanel")
        w.setStyleSheet(f"""
            QWidget#ContentPanel {{
                background: {C.PANEL};
                border: 1px solid {C.BORDER_B};
                border-radius: 18px;
            }}
        """)
        shadow = QGraphicsDropShadowEffect(w)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 10)
        shadow.setColor(qcol("#365c8c", 42))
        w.setGraphicsEffect(shadow)
        w.hide()

        lay = QVBoxLayout(w)
        lay.setContentsMargins(18, 14, 18, 16)
        lay.setSpacing(8)

        # ── header row ───────────────────────────────────────────────────────
        hdr = QHBoxLayout(); hdr.setSpacing(6)

        dot = QLabel("✦")
        dot.setFont(QFont("Segoe UI", 13, QFont.Weight.DemiBold))
        dot.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        hdr.addWidget(dot)

        self._content_title_lbl = QLabel("BRIEFING")
        self._content_title_lbl.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        self._content_title_lbl.setStyleSheet(
            f"color: {C.PRI}; background: transparent; letter-spacing: 1px;"
        )
        hdr.addWidget(self._content_title_lbl)
        hdr.addStretch()

        self._content_ts_lbl = QLabel("")
        self._content_ts_lbl.setFont(QFont("Segoe UI", 8))
        self._content_ts_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        hdr.addWidget(self._content_ts_lbl)

        dismiss = QPushButton("Schließen  ×")
        dismiss.setAccessibleName("Antwortfenster schließen")
        dismiss.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        dismiss.setFixedHeight(26)
        dismiss.setCursor(Qt.CursorShape.PointingHandCursor)
        dismiss.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL2}; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 10px; padding: 0 9px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; background: {C.PRI_GHO}; border-color: {C.PRI_DIM}; }}
        """)
        dismiss.clicked.connect(w.hide)
        hdr.addWidget(dismiss)
        lay.addLayout(hdr)

        # ── separator ─────────────────────────────────────────────────────────
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};"); lay.addWidget(sep)

        # ── text display ──────────────────────────────────────────────────────
        self._content_display = QTextEdit()
        self._content_display.setReadOnly(True)
        self._content_display.setFont(QFont("Segoe UI", 10))
        self._content_display.setMinimumHeight(100)
        self._content_display.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._content_display.setStyleSheet(f"""
            QTextEdit {{
                background: {C.PANEL2};
                color: {C.TEXT};
                border: none;
                border-radius: 12px;
                padding: 10px 12px;
                selection-background-color: {C.PRI_GHO};
            }}
            QScrollBar:vertical {{
                background: transparent; width: 6px; border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {C.BORDER_B}; border-radius: 3px; min-height: 16px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0; border: none;
            }}
        """)
        lay.addWidget(self._content_display)

        return w

    def _show_content(self, title: str, text: str):
        """Slot — runs on Qt main thread. Updates and shows the content panel."""
        import time as _time
        self._content_title_lbl.setText(title.upper()[:48])
        self._content_ts_lbl.setText(_time.strftime("%H:%M:%S"))
        self._content_display.setPlainText(text)
        self._content_display.moveCursor(
            self._content_display.textCursor().MoveOperation.Start
        )
        self._position_content_panel()
        self._content_panel.show()
        self._content_panel.raise_()

    def _build_footer(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(170)
        w.setStyleSheet(f"background: {C.BG};")
        lay = QHBoxLayout(w); lay.setContentsMargins(54, 12, 54, 20); lay.setSpacing(0)
        composer = QWidget()
        composer.setObjectName("VoiceComposer")
        composer.setMinimumWidth(0)
        composer.setMaximumWidth(850)
        composer.setStyleSheet(f"""
            QWidget#VoiceComposer {{
                background: {C.PANEL}; border: 1px solid {C.BORDER}; border-radius: 34px;
            }}
        """)
        shadow = QGraphicsDropShadowEffect(composer)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 8)
        shadow.setColor(qcol("#6c86aa", 34))
        composer.setGraphicsEffect(shadow)
        lay.addWidget(composer, stretch=1)
        inner = QHBoxLayout(composer)
        inner.setContentsMargins(24, 10, 24, 10)
        inner.setSpacing(12)
        self._composer_wave_left = LiveWaveform()
        self._composer_wave_left.setFixedWidth(180)
        self._composer_wave_right = LiveWaveform()
        self._composer_wave_right.setFixedWidth(150)
        inner.addWidget(self._composer_wave_left)
        self._mute_btn = QPushButton()
        self._mute_btn.setAccessibleName("Mikrofon ein- oder ausschalten")
        self._mute_btn.setToolTip("Mikrofon ein- oder ausschalten (F4)")
        self._mute_btn.setFixedSize(72, 72)
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.clicked.connect(self._toggle_mute)
        inner.addWidget(self._mute_btn)
        self._ptt_btn = QPushButton("HALTEN")
        self._ptt_btn.setAccessibleName("Zum Sprechen gedrueckt halten")
        self._ptt_btn.setToolTip("Zum Sprechen halten (F8)")
        self._ptt_btn.setFixedSize(92, 46)
        self._ptt_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ptt_btn.pressed.connect(self._push_to_talk_start)
        self._ptt_btn.released.connect(self._push_to_talk_stop)
        self._ptt_btn.setStyleSheet(f"""
            QPushButton {{ background: {C.PRI_GHO}; color: {C.PRI};
                border: 1px solid #c7ddfc; border-radius: 22px; font-weight: 700; }}
            QPushButton:pressed {{ background: {C.PRI}; color: white; }}
            QPushButton:disabled {{ color: {C.TEXT_DIM}; background: {C.PANEL2}; }}
        """)
        inner.addWidget(self._ptt_btn)
        inner.addWidget(self._composer_wave_right)
        divider = QFrame(); divider.setFrameShape(QFrame.Shape.VLine)
        divider.setStyleSheet(f"color: {C.BORDER};")
        inner.addWidget(divider)
        input_container = QWidget()
        input_container.setLayout(self._build_input_row())
        inner.addWidget(input_container, stretch=1)
        self._style_mute_btn()
        return w

    def _on_file_selected(self, path: str):
        self._current_file = path
        p    = Path(path)
        size = _fmt_size(p.stat().st_size)
        self._input.setPlaceholderText(f"Datei bereit: {p.name} · {size}")
        self._log.append_log(f"FILE: {p.name} ({size}) loaded")
        if self.on_text_command:
            msg = (
                f"[FILE_UPLOADED] path={path} | name={p.name} | "
                f"type={p.suffix.lstrip('.')} | size={size} | "
                f"Briefly tell the user you can see the file '{p.name}' "
                f"({size}) has been uploaded and ask what they'd like to do with it."
            )
            threading.Thread(target=self.on_text_command, args=(msg,), daemon=True).start()

    def notify_phone_connected(self) -> None:
        if self._remote_overlay and self._remote_overlay.isVisible():
            self._remote_overlay.mark_connected()

    def _open_remote(self):
        if not self.on_remote_clicked:
            self._log.append_log("SYS: Dashboard not running — remote unavailable.")
            return
        result = self.on_remote_clicked()
        if not result:
            self._log.append_log("SYS: Could not generate remote key.")
            return
        url    = result[0]
        key    = result[1]
        auto   = result[2] if len(result) >= 3 else ""
        manual = result[3] if len(result) >= 4 else url
        if self._remote_overlay:
            self._remote_overlay._do_close()
        cw  = self.centralWidget()
        ow, oh = RemoteKeyOverlay._OW, RemoteKeyOverlay._OH
        ov  = RemoteKeyOverlay(url, key, auto_login_url=auto, manual_url=manual,
                               expiry_secs=600, parent=cw)
        ov.set_new_key_callback(self.on_remote_clicked)
        ov.setGeometry(
            (cw.width()  - ow) // 2,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        ov.closed.connect(lambda: setattr(self, '_remote_overlay', None))
        ov.show()
        self._remote_overlay = ov
        self._log.append_log(f"SYS: Remote key generated — manual: {manual or url}")

    # ── Auto-start ──────────────────────────────────────────────────────────────

    def _check_autostart(self) -> bool:
        """Returns True if auto-start is currently registered on this OS."""
        try:
            if _OS == "Windows":
                import winreg
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ)
                try:
                    winreg.QueryValueEx(key, "JARVIS_AI")
                    return True
                except FileNotFoundError:
                    return False
                finally:
                    winreg.CloseKey(key)
            elif _OS == "Darwin":
                return (Path.home() / "Library" / "LaunchAgents"
                        / "com.jarvis.assistant.plist").exists()
            else:
                return (Path.home() / ".config" / "autostart" / "jarvis.desktop").exists()
        except Exception:
            return False

    def _toggle_autostart(self):
        currently_on = self._check_autostart()
        try:
            script = str(Path(__file__).resolve().parent / "main.py")
            if _OS == "Windows":
                import winreg
                reg = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_ALL_ACCESS)
                if currently_on:
                    winreg.DeleteValue(reg, "JARVIS_AI")
                else:
                    pythonw = Path(sys.executable).parent / "pythonw.exe"
                    exe = str(pythonw if pythonw.exists() else sys.executable)
                    winreg.SetValueEx(reg, "JARVIS_AI", 0, winreg.REG_SZ,
                                      f'"{exe}" "{script}"')
                winreg.CloseKey(reg)
            elif _OS == "Darwin":
                plist_dir = Path.home() / "Library" / "LaunchAgents"
                plist_dir.mkdir(parents=True, exist_ok=True)
                plist = plist_dir / "com.jarvis.assistant.plist"
                if currently_on:
                    plist.unlink(missing_ok=True)
                else:
                    plist.write_text(
                        '<?xml version="1.0" encoding="UTF-8"?>\n'
                        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                        '<plist version="1.0"><dict>\n'
                        '  <key>Label</key><string>com.jarvis.assistant</string>\n'
                        '  <key>ProgramArguments</key><array>\n'
                        f'    <string>{sys.executable}</string>\n'
                        f'    <string>{script}</string>\n'
                        '  </array>\n'
                        '  <key>RunAtLoad</key><true/>\n'
                        '</dict></plist>\n'
                    )
            else:
                desk_dir = Path.home() / ".config" / "autostart"
                desk_dir.mkdir(parents=True, exist_ok=True)
                desk = desk_dir / "jarvis.desktop"
                if currently_on:
                    desk.unlink(missing_ok=True)
                else:
                    desk.write_text(
                        "[Desktop Entry]\n"
                        f"Name={self._assistant_name}\n"
                        f"Exec={sys.executable} {script}\n"
                        "Type=Application\nTerminal=false\n"
                        "X-GNOME-Autostart-enabled=true\n"
                    )
            enabled = not currently_on
            self._update_autostart_btn(enabled)
            self._log.append_log(
                f"SYS: Auto-start {'enabled' if enabled else 'disabled'}.")
        except Exception as e:
            self._log.append_log(f"ERR: Auto-start failed — {e}")

    def _update_autostart_btn(self, enabled: bool):
        if not hasattr(self, '_autostart_btn'):
            return
        if enabled:
            self._autostart_btn.setText("Automatischer Start: an")
            self._autostart_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #001a08; color: {C.GREEN};
                    border: 1px solid {C.GREEN_D}; border-radius: 3px;
                }}
                QPushButton:hover {{ background: #002010; }}
            """)
        else:
            self._autostart_btn.setText("Automatischer Start: aus")
            self._autostart_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {C.TEXT_DIM};
                    border: 1px solid {C.BORDER}; border-radius: 3px;
                }}
                QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
            """)

    def _toggle_brief(self):
        from memory.config_manager import get_brief_enabled, save_brief_enabled
        new_val = not get_brief_enabled()
        save_brief_enabled(new_val)
        self._update_brief_btn(new_val)

    def _toggle_reduced_motion(self):
        self.hud.reduced_motion = not self.hud.reduced_motion
        try:
            cfg = _read_full_config()
            cfg["reduced_motion"] = self.hud.reduced_motion
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            API_FILE.write_text(json.dumps(cfg, indent=4), encoding="utf-8")
        except Exception:
            pass
        self._update_motion_btn()

    def _update_motion_btn(self):
        if not hasattr(self, '_motion_btn'):
            return
        self._motion_btn.setText(
            "Weniger Bewegung: an" if self.hud.reduced_motion else "Weniger Bewegung: aus"
        )

    def _update_brief_btn(self, enabled: bool):
        if not hasattr(self, '_brief_btn'):
            return
        if enabled:
            self._brief_btn.setText("Morgenüberblick: an")
            self._brief_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #001a08; color: {C.GREEN};
                    border: 1px solid {C.GREEN_D}; border-radius: 3px;
                    text-align: left; padding: 0 8px;
                }}
                QPushButton:hover {{ background: #002010; }}
            """)
        else:
            self._brief_btn.setText("Morgenüberblick: aus")
            self._brief_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {C.TEXT_DIM};
                    border: 1px solid {C.BORDER}; border-radius: 3px;
                    text-align: left; padding: 0 8px;
                }}
                QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
            """)

    # ── Customization ────────────────────────────────────────────────────────────

    def _open_customize(self):
        cfg = _read_full_config()
        if self._customize_overlay:
            self._customize_overlay.hide()
        cw = self.centralWidget()
        ov = CustomizeOverlay(
            cfg.get("assistant_name", "JARVIS") or "JARVIS",
            cfg.get("user_name", ""),
            cfg.get("ui_color", "") or DEFAULT_UI_COLOR,
            cfg.get("voice_name", ""),
            parent=cw,
        )
        ow, oh = CustomizeOverlay._OW, CustomizeOverlay._OH
        oh = min(oh, cw.height() - 16)
        ov.setGeometry(
            (cw.width()  - ow) // 2,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        ov.on_preview = self._preview_ui_color
        ov.saved.connect(self._apply_name_update)
        ov.show()
        self._customize_overlay = ov

    def _preview_ui_color(self, hex_color: str):
        """Canlı önizleme — tüm arayüzü yeni renge boyar (config'e YAZMAZ)."""
        old = current_palette()
        if apply_ui_accent(hex_color):
            retheme_all_widgets(old, current_palette())

    def _apply_name_update(self, name: str, user_name: str, ui_color: str = "",
                           voice: str = ""):
        """Update all name/theme-dependent UI elements and persist to config."""
        self._assistant_name = name.strip() or "JARVIS"
        display = self._assistant_name.upper()
        self.setWindowTitle(f"{display} — MICA")
        # MICA is the product mark; the configurable assistant name remains
        # visible in the centre state instead of replacing that brand mark.
        self._brand_lbl.setText("MICA")
        self._log._ai_name_lc = self._assistant_name.lower()
        self.hud._assistant_name = display

        color_changed = False
        if ui_color:
            old = current_palette()
            if apply_ui_accent(ui_color):
                # Tüm arayüzü (paneller, butonlar, kenarlıklar, HUD) canlı boya
                retheme_all_widgets(old, current_palette())
                color_changed = old["PRI"] != C.PRI

        # Voice change → persist and, if it actually changed, rebuild the Live
        # session so the new voice takes effect (it's fixed at connect time).
        voice_changed = False
        if voice:
            from memory.config_manager import get_voice, save_voice
            if voice != get_voice():
                save_voice(voice)
                voice_changed = True

        try:
            data = _read_full_config()
            data["assistant_name"] = self._assistant_name
            data["user_name"] = user_name.strip()
            if ui_color:
                data["ui_color"] = ui_color.strip().lower()
            API_FILE.write_text(json.dumps(data, indent=4), encoding="utf-8")
            self._log.append_log(f"SYS: Identity updated — {display}")
            if color_changed:
                self._log.append_log(f"SYS: UI colour applied — {ui_color}")
            if voice_changed:
                self._log.append_log(f"SYS: Voice set — {voice}")
        except Exception as e:
            self._log.append_log(f"ERR: Config save failed — {e}")

        if voice_changed and self.on_voice_change:
            self.on_voice_change()

    def _centre_overlay(self, ov) -> None:
        """Place a floating overlay in the middle of the HUD and show it."""
        cw = self.centralWidget()
        ov.adjustSize()
        ov.setGeometry(
            max(0, (cw.width()  - ov.width())  // 2),
            max(0, (cw.height() - ov.height()) // 2),
            ov.width(), ov.height(),
        )
        ov.show()
        ov.raise_()

    # ── Audio devices ────────────────────────────────────────────────────────

    def _open_audio_devices(self):
        ov = AudioDeviceOverlay(parent=self.centralWidget())
        ov.picked.connect(self._on_audio_devices_applied)
        self._centre_overlay(ov)
        self._audio_overlay = ov            # keep a reference so it isn't GC'd

    def _on_audio_devices_applied(self):
        self._log.append_log("SYS: Audio devices updated.")
        if self.on_audio_device_change:
            self.on_audio_device_change()

    # ── Memory panel ─────────────────────────────────────────────────────────

    def _open_memory_panel(self):
        ov = MemoryOverlay(parent=self.centralWidget())
        self._centre_overlay(ov)
        self._memory_overlay = ov

    # ── Irreversible-action confirmation ─────────────────────────────────────

    def _show_confirm_banner(self, title: str, detail: str):
        self._hide_confirm_banner()
        ov = ConfirmBanner(title, detail, parent=self.centralWidget())
        ov.answered.connect(self._on_confirm_answered)
        self._centre_overlay(ov)
        self._confirm_overlay = ov

    def _hide_confirm_banner(self):
        ov = getattr(self, "_confirm_overlay", None)
        if ov is not None:
            ov.hide()
            ov.deleteLater()
            self._confirm_overlay = None

    def _on_confirm_answered(self, accepted: bool):
        # Tear the banner down first: core.confirm.resolve() may be about to
        # shut the machine down, and a live widget mid-callback is not where you
        # want to be when that happens.
        self._hide_confirm_banner()
        try:
            from core.confirm import resolve
            resolve(bool(accepted))
        except Exception as e:
            self._log.append_log(f"ERR: Confirmation failed — {e}")

    def _open_plugin_manager(self):
        plugins = self.get_plugins() if self.get_plugins else []
        cw = self.centralWidget()
        ov = PluginManagerOverlay(plugins, parent=cw)
        ov.adjustSize()
        ov.setGeometry(
            (cw.width()  - ov.width())  // 2,
            (cw.height() - ov.height()) // 2,
            ov.width(), ov.height(),
        )
        ov.show()
        ov.raise_()
        self._plugin_manager_overlay = ov   # keep a reference so it isn't GC'd

    # ── Clipboard intelligence ───────────────────────────────────────────────────

    def _on_clipboard_changed(self):
        try:
            text = QApplication.clipboard().text().strip()
            if len(text) >= 10:
                self._clipboard_sig.emit(text)
        except Exception:
            pass

    def _show_clipboard_panel(self, text: str):
        self._clipboard_panel.show_clipboard(text)
        self._position_clipboard_panel()

    def _position_clipboard_panel(self):
        cw = self.centralWidget()
        pw = ClipboardPanel._W
        ph = self._clipboard_panel.sizeHint().height() or ClipboardPanel._H
        x = (cw.width() - pw) // 2
        y = cw.height() - ph - 6
        self._clipboard_panel.setGeometry(x, y, pw, ph)
        self._clipboard_panel.raise_()

    def _on_clipboard_action(self, cmd: str):
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(cmd,), daemon=True).start()

    # ────────────────────────────────────────────────────────────────────────────

    def _do_interrupt(self):
        if self.on_interrupt:
            self.on_interrupt()

    def _push_to_talk_start(self):
        if self._muted:
            self._log.append_log("SYS: Push-to-talk ist bei stummem Mikrofon deaktiviert.")
            return
        if self.on_push_to_talk_start:
            self.on_push_to_talk_start()

    def _push_to_talk_stop(self):
        if self.on_push_to_talk_stop:
            self.on_push_to_talk_stop()

    def _toggle_mute(self):
        self._muted = not self._muted
        self.hud.muted = self._muted
        self._ctx_audio.set_muted(self._muted)
        self._composer_wave_left.set_muted(self._muted)
        self._composer_wave_right.set_muted(self._muted)
        self._style_mute_btn()
        if self._muted:
            self._apply_state("MUTED")
            self._log.append_log("SYS: Microphone muted.")
        else:
            self._apply_state("LISTENING")
            self._log.append_log("SYS: Microphone active.")
        if self.on_mute_change:
            self.on_mute_change(self._muted)

    def _style_mute_btn(self):
        if self._muted:
            self._mute_btn.setIcon(QIcon(str(BASE_DIR / "assets" / "mica-microphone-muted.png")))
            self._mute_btn.setIconSize(QSize(34, 38))
            self._mute_btn.setToolTip("Mikrofon aktivieren (F4)")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: #fff4f5; color: {C.MUTED_C};
                    border: 1px solid #f0c5cc; border-radius: 36px;
                }}
                QPushButton:hover {{ background: #ffeaed; }}
                QPushButton:focus {{ border-color: {C.MUTED_C}; }}
            """)
        else:
            self._mute_btn.setIcon(QIcon(str(BASE_DIR / "assets" / "mica-microphone.png")))
            self._mute_btn.setIconSize(QSize(34, 38))
            self._mute_btn.setToolTip("Mikrofon stummschalten (F4)")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {C.PRI_GHO}; color: {C.PRI};
                    border: 1px solid #c7ddfc; border-radius: 36px;
                }}
                QPushButton:hover {{ background: #dceaff; }}
                QPushButton:focus {{ border-color: {C.PRI}; }}
            """)

    def _send(self):
        txt = self._input.text().strip()
        if not txt: return
        self._input.clear()
        self._log.append_log(f"You: {txt}")
        if self.on_text_command:
            threading.Thread(target=self.on_text_command, args=(txt,), daemon=True).start()

    def _apply_state(self, state: str):
        state = (state or "LISTENING").upper()
        self.hud.state    = state
        self.hud.speaking = (state == "SPEAKING")
        self.hud.presence_state = canonical_presence_state(
            state, speaking=self.hud.speaking, muted=self._muted,
        )
        self.hud.day_state = day_presence_state()
        if state == "MUTED":
            # set_state() is public and may be called from an audio worker,
            # so an externally reported mute must update every visible meter,
            # not merely the central canvas.
            self._muted = True
        elif not self._muted:
            self._muted = False
        self.hud.muted = self._muted
        self._ctx_audio.set_muted(self._muted)
        self._composer_wave_left.set_muted(self._muted)
        self._composer_wave_right.set_muted(self._muted)
        if hasattr(self, "_ptt_btn"):
            self._ptt_btn.setDisabled(self._muted)
        self._style_mute_btn()
        self._refresh_live_context(state)

    def _append_log_and_refresh(self, text: str) -> None:
        self._log.append_log(text)
        # A task may have just saved project memory or registered a reminder;
        # refreshing here makes the context panel catch it immediately.
        self._update_metrics()

    def _apply_audio_level(self, level: float) -> None:
        """Qt-thread slot: one audio value feeds every visible indicator."""
        self.hud.set_audio_level(level)
        self._ctx_audio.set_level(level)
        self._composer_wave_left.set_level(level)
        self._composer_wave_right.set_level(level)

    def _refresh_live_context(self, state: str | None = None) -> None:
        state = (state or self.hud.state).upper()
        if self._muted or state == "MUTED":
            title, detail = "Mikrofon pausiert", "Aktiviere es mit F4 oder der Mikrofon-Taste."
        elif not self._ready:
            title, detail = "Einrichtung erforderlich", "Mica wartet auf die lokale Konfiguration."
        elif state in ("INITIALISING", "CONNECTING"):
            title, detail = "Wird verbunden", "Mica stellt die Verbindung her."
        elif state in ("SLEEPING", "OFFLINE", "DISCONNECTED"):
            title, detail = "Nicht verbunden", "Mica versucht, die Verbindung wiederherzustellen."
        elif state == "SPEAKING":
            title, detail = "Mica spricht", "Die Ausgabe reagiert auf den aktuellen Pegel."
        elif state == "THINKING":
            title, detail = "Mica denkt nach", "Der nächste Schritt wird vorbereitet."
        elif state == "PROCESSING":
            title, detail = "Mica arbeitet", "Der Fortschritt erscheint im Verlauf."
        else:
            title, detail = "Live", "Mica hört zu"
        self._ctx_live_title.setText(title)
        self._ctx_live_body.setText(detail)

    def _check_config(self) -> bool:
        if os.environ.get("MICA_LOCAL_MODE") == "1":
            return True
        if not API_FILE.exists(): return False
        try:
            d = json.loads(API_FILE.read_text(encoding="utf-8"))
            return bool(d.get("gemini_api_key")) and bool(d.get("os_system"))
        except Exception:
            return False

    def _show_setup(self):
        ov = SetupOverlay(self.centralWidget())
        cw = self.centralWidget()
        ow, oh = 500, 450
        ov.setGeometry(
            (cw.width()  - ow) // 2,
            (cw.height() - oh) // 2,
            ow, oh,
        )
        ov.done.connect(self._on_setup_done)
        ov.show()
        self._overlay = ov

    def _on_setup_done(self, key: str, os_name: str):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        API_FILE.write_text(
            json.dumps({"gemini_api_key": key, "os_system": os_name}, indent=4),
            encoding="utf-8",
        )
        self._ready = True
        if self._overlay:
            self._overlay.hide()
            self._overlay = None
        # HudCanvas owns an opaque backing store. Explicitly requesting a
        # repaint ensures it is revealed immediately after setup closes.
        self.hud.update()
        self._apply_state("LISTENING")
        self._assistant_name = _read_full_config().get("assistant_name", "Mica") or "Mica"
        self._log.append_log(f"SYS: Initialised. OS={os_name.upper()}. {self._assistant_name} online.")

class _RootShim:
    def __init__(self, app: QApplication):
        self._app = app
    def mainloop(self):
        self._app.exec()
    def protocol(self, *_):
        pass


class JarvisUI:
    def __init__(self, face_path: str, size=None):
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._app.setStyle("Fusion")
        self._win = MainWindow(face_path)
        self._win.show()
        self.root = _RootShim(self._app)

    @property
    def muted(self) -> bool:
        return self._win._muted

    @muted.setter
    def muted(self, v: bool):
        if v != self._win._muted:
            self._win._toggle_mute()

    @property
    def current_file(self) -> str | None:
        return self._win._current_file

    @property
    def on_text_command(self):
        return self._win.on_text_command

    @on_text_command.setter
    def on_text_command(self, cb):
        self._win.on_text_command = cb

    @property
    def on_remote_clicked(self):
        return self._win.on_remote_clicked

    @on_remote_clicked.setter
    def on_remote_clicked(self, cb):
        self._win.on_remote_clicked = cb

    @property
    def on_interrupt(self):
        return self._win.on_interrupt

    @on_interrupt.setter
    def on_interrupt(self, cb):
        self._win.on_interrupt = cb

    @property
    def on_push_to_talk_start(self):
        return self._win.on_push_to_talk_start

    @on_push_to_talk_start.setter
    def on_push_to_talk_start(self, cb):
        self._win.on_push_to_talk_start = cb

    @property
    def on_push_to_talk_stop(self):
        return self._win.on_push_to_talk_stop

    @on_push_to_talk_stop.setter
    def on_push_to_talk_stop(self, cb):
        self._win.on_push_to_talk_stop = cb

    @property
    def on_mute_change(self):
        return self._win.on_mute_change

    @on_mute_change.setter
    def on_mute_change(self, cb):
        self._win.on_mute_change = cb

    @property
    def on_voice_change(self):
        return self._win.on_voice_change

    @on_voice_change.setter
    def on_voice_change(self, cb):
        self._win.on_voice_change = cb

    @property
    def on_audio_device_change(self):
        return self._win.on_audio_device_change

    @on_audio_device_change.setter
    def on_audio_device_change(self, cb):
        self._win.on_audio_device_change = cb

    def show_confirm(self, title: str, detail: str) -> None:
        """Thread-safe: raise the irreversible-action gate. Called from action
        handlers running in executor threads, so it goes through a signal."""
        self._win._confirm_sig.emit(str(title)[:120], str(detail)[:300])

    def hide_confirm(self) -> None:
        """Thread-safe: take the gate down."""
        self._win._confirm_hide_sig.emit()

    @property
    def get_plugins(self):
        return self._win.get_plugins

    @get_plugins.setter
    def get_plugins(self, cb):
        self._win.get_plugins = cb

    def set_audio_level(self, level: float) -> None:
        """Thread-safe: feed the same real audio value to every HUD meter."""
        try:
            self._win._audio_sig.emit(float(level))
        except Exception:
            pass

    def notify_phone_connected(self) -> None:
        self._win.notify_phone_connected()

    def set_state(self, state: str):
        self._win._state_sig.emit(state)

    def write_log(self, text: str):
        self._win._log_sig.emit(text)

    def wait_for_api_key(self):
        while not self._win._ready:
            time.sleep(0.1)

    def show_content(self, title: str, text: str):
        """Thread-safe: display content in the floating response card."""
        self._win._content_sig.emit(title[:48], text[:4000])

    def prompt_reconfig(self):
        """Thread-safe: show the API key setup overlay (e.g. after an auth error)."""
        self._win._ready = False
        self._win._reconfig_sig.emit()

    def show_camera_frame(self, img_bytes: bytes):
        """Thread-safe: show a webcam frame in the small overlay (screen captures)."""
        self._win._camera_sig.emit(img_bytes)

    def start_camera_stream(self) -> None:
        """Thread-safe: start live camera feed in the full HUD area."""
        self._win.start_camera_stream()

    def stop_camera_stream(self) -> None:
        """Thread-safe: stop the live camera feed."""
        self._win.stop_camera_stream()

    @property
    def assistant_name(self) -> str:
        return self._win._assistant_name

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("LISTENING")
