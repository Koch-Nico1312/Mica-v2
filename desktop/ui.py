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

_PROJECT_DIR = Path(__file__).resolve().parents[1]
if str(_PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(_PROJECT_DIR))


# Launcher contract: generation 2 is the reference-aligned PyQt interface.
# Keeping this marker in the UI module prevents an outdated checkout from
# silently opening the former interface.
MICA_UI_GENERATION = 2

# Must run before importing PyQt6.  If Windows (or a launcher) already chose a
# process DPI context, Qt must not try to set it a second time.
from desktop.core.windows_dpi import configure_qt_dpi_startup

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
    QGraphicsDropShadowEffect, QGridLayout,
)

from desktop.ui_pages import LocalPagesMixin
from desktop.ui_support import (
    API_FILE, BASE_DIR, CONFIG_DIR, PRESENCE_STATES, _base_dir, _read_full_config, canonical_presence_state, day_presence_state, latest_project_context, next_reminder_context, time_greeting
)


_DEFAULT_W, _DEFAULT_H = 1600, 900
_MIN_W,     _MIN_H     = 960, 680
_LEFT_W  = 210
_RIGHT_W = 350
_SHELL_MARGIN = 14
_SHELL_GAP = 10

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"


from desktop.ui_theme import style_toggle_button
from desktop.ui_theme import (
    C, DEFAULT_UI_COLOR, _HUE_LINKED, _PALETTE_DEFAULTS, _UI_FONT_REGISTERED, _outline_nav_icon, apply_ui_accent, current_palette, ensure_ui_font, qcol, retheme_all_widgets
)


# Ana renge (accent) bağlı anahtarlar — durum renkleri (ACC, GREEN, RED…) sabit kalır


# ── Windows GPU via NVML DLL (no subprocess, no console window) ──────────────


from desktop.ui_widgets import (
    ComposerInput, FileDropZone, HudCanvas, LiveWaveform, LogWidget, MetricBar, _CameraPreview, _DropCanvas, _EXT_TO_CAT, _FILE_ICONS, _context_card, _file_category, _fmt_size
)


from desktop.ui_appearance import CustomizeOverlay, HueWheel, SetupOverlay


from desktop.ui_panels import ClipboardPanel, PluginManagerOverlay, RemoteKeyOverlay


from desktop.ui_settings import AudioDeviceOverlay, ConfirmBanner, FeatureSettingsOverlay, MemoryOverlay, ProviderSettingsOverlay, _HudOverlay


class MainWindow(LocalPagesMixin, QMainWindow):
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
    _backend_update_sig = pyqtSignal(str, bool, str)
    _workspace_sig = pyqtSignal(str)
    _project_resume_sig = pyqtSignal(str)
    _project_sig = pyqtSignal(str)
    _memory_project_sig = pyqtSignal(str)
    _document_changes_sig = pyqtSignal()
    _window_help_sig = pyqtSignal(str)
    _preference_offer_sig = pyqtSignal(dict)
    _routine_documents_sig = pyqtSignal(list)
    _routine_draft_sig = pyqtSignal(dict)
    _document_drafts_sig = pyqtSignal(str, str)
    _review_cards_sig = pyqtSignal()
    _dictation_sig = pyqtSignal()
    _reminder_sig = pyqtSignal(dict)
    _task_planning_sig = pyqtSignal(str, str)
    _outcome_sig = pyqtSignal()

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
        self.on_feature_change  = None   # callable: (str, bool) -> None — live desktop features
        self.on_voice_change   = None   # callable: () -> None — rebuild session with new voice
        self.on_audio_device_change = None  # callable: () -> None — reopen audio streams
        self._confirm_overlay  = None   # live ConfirmBanner, if one is on screen
        self.get_plugins       = None   # callable: () -> list[dict], set by JarvisLive
        self._muted            = False
        from desktop.core.preferences import remember_conversations
        self.remember_conversations = remember_conversations()
        self._current_file: str | None = None
        self._attachment_overlay = None
        self.on_new_conversation = None
        self.on_workspace_operation = None
        self._workspace_sig.connect(self._open_workspace)
        self._project_resume_sig.connect(self._resume_project)
        self._project_sig.connect(lambda name: self._open_workspace('workspace_resume', project=name))
        self._memory_project_sig.connect(self._open_project_memory)
        self._document_changes_sig.connect(self._open_document_changes)
        self._window_help_sig.connect(self._request_window_help)
        self.on_preference_confirmation = None
        self._preference_offer_sig.connect(self._offer_preference)
        self._routine_documents_sig.connect(self._set_routine_documents)
        self._routine_draft_sig.connect(self._open_routine_draft)
        self._document_drafts_sig.connect(self._open_document_drafts)
        self._review_cards_sig.connect(self._open_flashcards)
        self._dictation_sig.connect(self._open_dictation)
        self._reminder_sig.connect(self._show_reminder_notification)
        self._task_planning_sig.connect(self._open_task_planning)
        self._outcome_sig.connect(self._open_outcome_check)
        self._remote_overlay: RemoteKeyOverlay | None = None
        self._customize_overlay: CustomizeOverlay | None = None
        self._provider_backend_busy = False
        self._pending_backend_updates: list[tuple[str, str]] = []
        self._backend_update_sig.connect(self._on_backend_update_result)

        central = QWidget()
        central.setStyleSheet(f"background: {C.BG};")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QHBoxLayout()
        body.setContentsMargins(_SHELL_MARGIN, _SHELL_MARGIN,
                                _SHELL_MARGIN, _SHELL_MARGIN)
        body.setSpacing(_SHELL_GAP)

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
        from desktop.control_center import ControlCenter
        self._control_center = ControlCenter()
        self._control_center.open_settings.connect(lambda: self._activate_navigation('settings'))
        self._control_center.restore_busy.connect(lambda busy: self.centralWidget().setEnabled(not busy))
        self._view_stack.addWidget(self._control_center)
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
        from desktop.memory.config_manager import get_brief_enabled as _gbe
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
        script  = Path(__file__).resolve().parent / "local_main.py"
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
            ow, oh = SetupOverlay._OW, SetupOverlay._OH
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
        center_x = _SHELL_MARGIN + _LEFT_W + _SHELL_GAP
        width = max(280, cw.width() - center_x - _RIGHT_W - _SHELL_MARGIN - _SHELL_GAP)
        columns = 5 if width >= 850 else 3 if width >= 680 else 2
        tool_count = len(getattr(self, '_composer_tool_buttons', (None,) * 5))
        self._footer.setFixedHeight(152 + (math.ceil(tool_count / columns) - 1) * 28)
        if hasattr(self, '_composer_tools') and columns != getattr(self, '_composer_tool_columns', None):
            while self._composer_tools.count():
                self._composer_tools.takeAt(0)
            for index, button in enumerate(self._composer_tool_buttons):
                self._composer_tools.addWidget(button, index // columns, index % columns)
            for index in range(6):
                self._composer_tools.setColumnStretch(index, 0)
            self._composer_tools.setColumnStretch(columns, 1)
            self._composer_tool_columns = columns
        self._footer.setGeometry(
            center_x,
            max(0, cw.height() - self._footer.height() - 22),
            width,
            self._footer.height(),
        )
        compact = width < 680
        margin = 16 if compact else 70
        self._footer.layout().setContentsMargins(margin, 10, margin, 10)
        if hasattr(self, '_composer_wave_left'):
            self._composer_wave_left.hide()
            self._composer_wave_right.setVisible(not compact)
        self._footer.raise_()

    def _position_content_panel(self) -> None:
        """Place response content as a compact card above the voice composer."""
        cw = self.centralWidget()
        center_x = _SHELL_MARGIN + _LEFT_W + _SHELL_GAP
        available = max(280, cw.width() - center_x - _RIGHT_W - _SHELL_MARGIN - _SHELL_GAP)
        width = min(680, max(360, available - 72))
        height = min(300, max(190, cw.height() - self._footer.height() - 210))
        x = center_x + (available - width) // 2
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
        w.setObjectName("NavigationPanel")
        w.setFixedWidth(_LEFT_W)
        w.setStyleSheet(f"""
            QWidget#NavigationPanel {{
                background: {C.PANEL}; border: 1px solid {C.BORDER};
                border-radius: 20px;
            }}
        """)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(18, 38, 18, 24)
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
        lay.addSpacing(34)

        self._nav_buttons: dict[str, QPushButton] = {}
        nav_specs = (("chat", "Chat"), ("history", "Verlauf"),
                     ("reminders", "Erinnerungen"), ("memory", "Gedächtnis"),
                     ("settings", "Einstellungen"), ("operations", "Betrieb"))
        for index, (key, text) in enumerate(nav_specs):
            button = QPushButton(text)
            button.setIcon(_outline_nav_icon(key, C.TEXT_MED))
            button.setIconSize(QSize(24, 24))
            button.setFixedHeight(50)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
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
                    text-align: left; padding: 9px 14px;
                }}
                QPushButton:hover {{ color: {C.PRI}; background: {C.PRI_GHO}; border-color: {C.BORDER}; }}
                QPushButton:focus {{ border-color: {C.PRI}; }}
            """)

    def _activate_navigation(self, target: str) -> None:
        self._quick_drawer.hide()
        self._right_panel.setVisible(target != 'operations' and not (target == 'memory' and hasattr(self, '_backend_memory_page')))
        self._view_stack.setCurrentIndex(
            {"chat": 0, "history": 1, "reminders": 2, "memory": 3, "settings": 4, "operations": 5}.get(target, 0)
        )
        self._footer.setVisible(target == "chat")
        if target == "reminders":
            self._refresh_reminders_page()
        elif target == "memory":
            if hasattr(self, "_backend_memory_page"):
                self._backend_memory_page.refresh()
            else:
                self._refresh_memory_page()
        elif target == "operations":
            self._control_center.refresh()
        self._style_navigation(target)


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
        sub = QLabel("Passe Mica, Funktionen, KI-Anbieter und Geräte an.")
        sub.setFont(QFont("Segoe UI", 10))
        sub.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        lay.addWidget(sub)
        for heading, detail, callback in (
            ("Mica anpassen", "Name, weibliche Stimme und Akzentfarbe", self._open_customize),
            ("Audio-Geräte", "Mikrofon und Lautsprecher auswählen", self._open_audio_devices),
            ("Gedächtnis", "Lokal gespeicherte Informationen ansehen", self._open_memory_panel),
            ("Funktionen", "Mica-Features einzeln aktivieren oder deaktivieren", self._open_feature_settings),
            ("KI-Anbieter & Modelle", "Anbieter, Modelle und API-Schlüssel verwalten", self._open_provider_settings),
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
        w.setStyleSheet("background: transparent;")
        outer = QVBoxLayout(w)
        outer.setContentsMargins(0, 0, 0, 0)
        panel = QFrame()
        panel.setObjectName("ContextPanel")
        panel.setStyleSheet(f"""
            QFrame#ContextPanel {{
                background: {C.PANEL}; border: 1px solid {C.BORDER}; border-radius: 20px;
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
        self._attachments_button = QPushButton("Dateien")
        self._attachments_button.setToolTip("Dateien für dieses Gespräch auswählen oder entfernen")
        self._attachments_button.clicked.connect(self._open_attachments)
        self._routine_button = QPushButton("Abläufe")
        self._routine_button.setToolTip("Arbeitsmodus mit Programmen, Fokus-Timer und Mica-Ruhezeit festlegen")
        self._routine_button.clicked.connect(self._open_work_routine)
        self._screen_help_button = QPushButton("Fensterhilfe")
        self._screen_help_button.setToolTip("Zuletzt verwendetes Fenster einmalig erfassen und als Gesprächskontext auswählen")
        self._screen_help_button.clicked.connect(self._capture_window_help)
        from desktop.core.screen_help import ForegroundTracker
        self._foreground_tracker = ForegroundTracker(self)
        self._foreground_tracker.captured.connect(self._preview_window_help)
        self._foreground_tracker.failed.connect(lambda error: self._log.append_log("ERR: " + error))

        row.addWidget(self._composer_wave_right)

        send = QPushButton()
        send.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowForward))
        send.setIconSize(QSize(25, 25))
        send.setAccessibleName("Nachricht senden")
        send.setToolTip("Nachricht senden")
        send.setFixedSize(52, 52)
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.setStyleSheet(f"""
            QPushButton {{
                background: {C.PRI}; color: white;
                border: none; border-radius: 26px;
            }}
            QPushButton:hover {{ background: #397de8; }}
            QPushButton:focus {{ border: 2px solid {C.TEXT}; }}
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
        w.setFixedHeight(152)
        w.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(w); lay.setContentsMargins(70, 10, 70, 10); lay.setSpacing(0)
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
        inner.setContentsMargins(18, 10, 18, 10)
        inner.setSpacing(14)
        self._composer_wave_left = LiveWaveform()
        self._composer_wave_left.setFixedWidth(0)
        self._composer_wave_left.hide()
        self._composer_wave_right = LiveWaveform()
        self._composer_wave_right.setFixedWidth(150)
        self._mute_btn = QPushButton()
        self._mute_btn.setAccessibleName("Mikrofon ein- oder ausschalten")
        self._mute_btn.setToolTip("Mikrofon ein- oder ausschalten (F4)")
        self._mute_btn.setFixedSize(64, 64)
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
        # F8 still exposes push-to-talk without crowding the reference composer.
        self._ptt_btn.hide()
        input_container = QWidget()
        input_container.setObjectName("ComposerInputPanel")
        input_container.setStyleSheet(f"""
            QWidget#ComposerInputPanel {{
                background: {C.PANEL2}; border: 1px solid {C.BORDER};
                border-radius: 24px;
            }}
        """)
        input_row = self._build_input_row()
        input_layout = QVBoxLayout(input_container)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(0)
        input_layout.addLayout(input_row)
        tools = QGridLayout()
        self._composer_tools = tools
        tools.setContentsMargins(12, 0, 12, 6)
        tools.setSpacing(8)
        self._workspace_button = QPushButton('Arbeitsstand')
        self._workspace_button.clicked.connect(lambda: self._open_workspace('workspace_save'))
        self._resume_project_button = QPushButton('Projekt fortsetzen')
        self._resume_project_button.setToolTip('Zuletzt gespeichertes Projekt samt Dokumenten, letzter Arbeit und nächster Aufgabe öffnen')
        self._resume_project_button.clicked.connect(lambda: self._resume_project(''))
        self._selection_button = QPushButton('Textauswahl')
        self._selection_button.setToolTip('Strg+Alt+M im gewünschten Programm: markierten Text prüfen und bearbeiten')
        from PyQt6.QtWidgets import QMenu
        from desktop.core.text_selection import SelectionCapture, SelectionShortcut
        self._selection_capture = SelectionCapture(self)
        self._selection_capture.selected.connect(self._preview_selection)
        self._selection_capture.failed.connect(lambda text: self._log.append_log('SYS: ' + text))
        self._selection_shortcut = SelectionShortcut(self)
        self._selection_shortcut.triggered.connect(self._selection_capture.capture)
        QApplication.instance().aboutToQuit.connect(lambda: self._selection_shortcut.enable(False))
        menu = QMenu(self._selection_button)
        preview = menu.addAction('Kopierten Text prüfen und bearbeiten')
        preview.triggered.connect(lambda: self._preview_selection(QApplication.clipboard().text()))
        dictate = menu.addAction('Diktieren und korrigieren')
        dictate.triggered.connect(self._open_dictation)
        shortcut = menu.addAction('Globales Tastenkürzel Strg+Alt+M')
        shortcut.setCheckable(True)
        from desktop.core.local_state import DATA_DIR, read_json
        try:
            enabled = read_json(DATA_DIR / 'selection-shortcut.json').get('enabled') is True
        except (OSError, ValueError, AttributeError):
            enabled = True
        shortcut.setChecked(self._selection_shortcut.enable(enabled))
        self._selection_shortcut_action = shortcut
        shortcut.setText('Globales Tastenkürzel ' + self._selection_shortcut.label)
        self._selection_button.setToolTip(self._selection_shortcut.label + ' im gewünschten Programm: markierten Text prüfen und bearbeiten')
        if enabled and not shortcut.isChecked():
            self._selection_button.setToolTip('Strg+Alt+M konnte nicht registriert werden. Das Kürzel ist möglicherweise schon belegt; kopierten Text über das Menü verwenden.')
        shortcut.toggled.connect(self._toggle_selection_shortcut)
        self._selection_button.setMenu(menu)
        self._planning_button = QPushButton('Tagesplanung')
        self._planning_button.clicked.connect(lambda: self._open_task_planning('plan'))
        self._outcome_button = QPushButton('Ergebnis prüfen')
        self._outcome_button.clicked.connect(self._open_outcome_check)
        self._composer_tool_buttons = (self._attachments_button, self._routine_button, self._screen_help_button, self._workspace_button, self._resume_project_button, self._selection_button, self._planning_button, self._outcome_button)
        for index, button in enumerate(self._composer_tool_buttons):
            button.setFont(QFont("Segoe UI", 8))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setMinimumWidth(button.fontMetrics().horizontalAdvance(button.text()) + 18)
            button.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
            tools.addWidget(button, 0, index)
        input_layout.addLayout(tools)
        inner.addWidget(input_container, stretch=1)
        self._style_mute_btn()
        return w

    def _on_file_selected(self, path: str):
        self._current_file = path
        self._input.setPlaceholderText(f"Datei lesen: {Path(path).name}")
        self._open_attachments()
        self._attachment_overlay.add_file(path)

    def _open_work_routine(self):
        from desktop.work_routine_dialog import WorkRoutineDialog
        WorkRoutineDialog(self).exec()

    def _open_routine_draft(self, draft):
        from desktop.work_routine_dialog import WorkRoutineDialog
        documents = self._attachment_overlay.checkpoint_documents() if self._attachment_overlay else []
        WorkRoutineDialog(self, draft=draft, documents=documents).exec()

    def _open_document_drafts(self, kind='tasks', instruction=''):
        from desktop.document_drafts_dialog import DocumentDraftsDialog
        documents = self._attachment_overlay.checkpoint_documents() if self._attachment_overlay else []
        DocumentDraftsDialog(self, documents, getattr(self, 'on_document_drafts', None), kind=kind, instruction=instruction).exec()

    def _open_flashcards(self):
        if not self.remember_conversations:
            self._log.append_log('SYS: Lernkarten benötigen den Modus mit Speicherung.')
            return
        from desktop.flashcards_dialog import FlashcardsDialog
        FlashcardsDialog(self).exec()

    def _open_task_planning(self, page='tasks', title=''):
        if not self.remember_conversations:
            self._log.append_log('SYS: Lokale Aufgaben und Tagesplanung benötigen den Modus mit Speicherung.')
            return
        operation = getattr(self, 'on_task_planning', None)
        if not operation:
            return
        try:
            from desktop.task_planning_dialog import TaskPlanningDialog
            dialog = TaskPlanningDialog(self, operation, page='plan' if page == 'adjust' else page, adjustment=title if page == 'adjust' else '')
            if title and page != 'adjust':
                dialog.title.setText(title)
            dialog.exec()
        except (OSError, ValueError) as error:
            self._log.append_log('ERR: Aufgabenstand nicht lesbar: ' + str(error))

    def _open_outcome_check(self):
        from desktop.outcome_dialog import OutcomeDialog
        OutcomeDialog(self, getattr(self, '_foreground_tracker', None)).exec()

    def _open_dictation(self):
        prepare = getattr(self, 'on_dictation_state', None)
        if prepare:
            try:
                prepare(True)
            except ValueError as error:
                self._log.append_log('SYS: ' + str(error))
                return
        from desktop.dictation_dialog import DictationDialog
        try:
            from desktop.core.dictation import record_clip
            self._dictation_dialog = DictationDialog(self, getattr(self, 'on_dictation', None), getattr(self, 'on_text_transform', None),
                recording=getattr(self, 'on_dictation_record', record_clip))
            self._dictation_dialog.exec()
        finally:
            self._dictation_dialog = None
            if prepare:
                prepare(False)

    def _show_reminder_notification(self, record):
        from desktop.reminder_notification import ReminderNotification
        popup = ReminderNotification(record, getattr(self, 'on_reminder_snooze', None), client=getattr(self, 'reminder_client', None), parent=self)
        popup.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        popup.show()

    def _resume_project(self, project=''):
        from desktop.core.workspace import ProjectWorkspaceStore
        try:
            if not project:
                projects = ProjectWorkspaceStore().all()
                versions = [(datetime.fromisoformat(data[-1]['saved_at']), name) for name, data in projects.items() if data]
                if not versions:
                    raise ValueError('Zuerst einen Projektstand unter Arbeitsstand speichern.')
                project = max(versions)[1]
            self._open_workspace('workspace_continue', project=project)
        except (OSError, ValueError, KeyError) as error:
            self._log.append_log('SYS: Projekt nicht fortgesetzt: ' + str(error))

    def _open_workspace(self, kind, project=None):
        if not self.remember_conversations:
            self._log.append_log('SYS: Arbeitsstände benötigen den Modus mit Speicherung.')
            return
        if not self.on_workspace_operation:
            return
        from desktop.workspace_dialog import WorkspaceDialog
        documents = self._attachment_overlay.checkpoint_documents() if self._attachment_overlay else []
        dialog = WorkspaceDialog(self, self.on_workspace_operation, documents, prefer_load=kind in {'workspace_resume', 'workspace_continue'}, project=project)
        if kind == 'workspace_continue' and dialog.saved:
            QTimer.singleShot(0, lambda: dialog.run('load'))
        dialog.exec()

    def _open_project_memory(self, query):
        if hasattr(self, '_backend_memory_page'):
            self._backend_memory_page.certainty_filter.setCurrentIndex(0)
            self._backend_memory_page.search.setText(query)
            self._activate_navigation('memory')

    def _open_document_changes(self):
        from desktop.document_changes_dialog import DocumentChangesDialog
        documents = self._attachment_overlay.checkpoint_documents() if self._attachment_overlay else []
        DocumentChangesDialog(self, documents, getattr(self, 'on_text_transform', None)).exec()

    def _request_window_help(self, question):
        self._input.setText(question)
        self._capture_window_help()

    def _offer_preference(self, draft):
        if not self.remember_conversations or not self.on_preference_confirmation:
            return
        from desktop.preference_dialog import PreferenceDialog
        PreferenceDialog(self, draft, self.on_preference_confirmation).exec()

    def _set_routine_documents(self, documents):
        self._open_attachments()
        self._attachment_overlay.replace_documents(documents)
        self._attachment_overlay.hide()

    def _toggle_selection_shortcut(self, enabled):
        from desktop.core.local_state import DATA_DIR, write_json
        active = self._selection_shortcut.enable(enabled)
        self._selection_shortcut_action.setText('Globales Tastenkürzel ' + self._selection_shortcut.label)
        self._selection_button.setToolTip(self._selection_shortcut.label + ' im gewünschten Programm: markierten Text prüfen und bearbeiten')
        try:
            write_json(DATA_DIR / 'selection-shortcut.json', {'enabled': enabled})
        except OSError as error:
            self._log.append_log('ERR: Tastenkürzel-Einstellung konnte nicht gespeichert werden: ' + str(error))
        if enabled and not active:
            self._log.append_log('SYS: Strg+Alt+M ist nicht verfügbar; kopierten Text über Textauswahl verwenden.')

    def _preview_selection(self, text):
        operation = getattr(self, 'on_text_transform', None)
        if not operation:
            self._log.append_log('SYS: Textbearbeitung benötigt den lokalen Core.')
            return
        if not text.strip() or len(text) > 16000:
            self._log.append_log('SYS: Bitte Text mit höchstens 16.000 Zeichen markieren oder kopieren.')
            return
        from desktop.text_selection_dialog import TextSelectionDialog
        TextSelectionDialog(self, text, operation).exec()

    def _capture_window_help(self):
        self._foreground_tracker.capture_async()

    def _preview_window_help(self, target, image):
        from desktop.screen_help_dialog import ScreenHelpDialog
        dialog = ScreenHelpDialog(target, image, self)
        if dialog.exec():
            self._open_attachments()
            self._attachment_overlay.add_capture(image, target["title"], target.get('controls', {}).get('text', '') if dialog.use_controls.isChecked() else '')

    def _open_attachments(self):
        if self._attachment_overlay is None:
            from desktop.attachment_overlay import AttachmentOverlay
            self._attachment_overlay = AttachmentOverlay(parent=self.centralWidget())
            self._attachment_overlay.changed.connect(self._attachments_changed)
            self._attachment_overlay.new_conversation.connect(self._new_conversation)
            self._attachment_overlay.modified.connect(self._documents_modified)
            self._attachment_overlay.capture_ready.connect(self._window_text_ready)
            self._attachment_overlay.compare_requested.connect(self._open_document_changes)
            self._attachment_overlay.tasks_requested.connect(lambda: self._open_document_drafts('tasks'))
            self._attachment_overlay.cards_requested.connect(lambda: self._open_document_drafts('cards'))
            self._attachment_overlay.review_requested.connect(self._open_flashcards)
        self._centre_overlay(self._attachment_overlay)

    def _attachments_changed(self, documents):
        changed = self._attachment_overlay.changed_titles() if self._attachment_overlay else []
        text = f"Dateien ({len(documents)})" if documents else "Dateien"
        self._attachments_button.setText(text + (" · Geändert" if changed else ""))
        tooltip = "Im Gespräch ausgewählt: " + ", ".join(doc["title"] for doc in documents) if documents else "Keine Dateien ausgewählt"
        if changed:
            tooltip += "\nGeändert: " + ", ".join(changed) + ". Unter Dateien ausdrücklich neu einlesen."
        self._attachments_button.setToolTip(tooltip)

    def _documents_modified(self, titles):
        self._attachments_changed(self.selected_documents())
        if titles:
            self._log.append_log("SYS: Datei geändert: " + ", ".join(titles) + ". Unter Dateien kannst du sie neu einlesen.")

    def selected_documents(self):
        return self._attachment_overlay.snapshot() if self._attachment_overlay else []

    def _window_text_ready(self, title):
        if not self._input.text().strip():
            self._input.setText(f"Erkläre die Fehlermeldung in „{title}“ und mögliche nächste Schritte.")

    def _new_conversation(self):
        if self.on_new_conversation:
            threading.Thread(target=self.on_new_conversation, daemon=True).start()

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
            script = str(Path(__file__).resolve().parent / "local_main.py")
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
        from desktop.memory.config_manager import get_brief_enabled, save_brief_enabled
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
            from desktop.memory.config_manager import get_voice, save_voice
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
        ov.voice_settings_requested.connect(self._open_voice_settings)
        self._centre_overlay(ov)
        self._audio_overlay = ov            # keep a reference so it isn't GC'd

    def _open_voice_settings(self):
        from desktop.voice_settings_overlay import VoiceSettingsOverlay
        previous = getattr(self, "_voice_overlay", None)
        if previous is not None:
            self._centre_overlay(previous)
            return
        ov = VoiceSettingsOverlay(parent=self.centralWidget(),
                                  can_record=getattr(self, "voice_ready_for_calibration", lambda: True))
        ov.busy_changed.connect(self._voice_calibration_changed)
        self._voice_overlay = ov
        self._centre_overlay(ov)

    def _voice_calibration_changed(self, busy):
        callback = getattr(self, "on_voice_calibration_change", None)
        if callback:
            callback(busy)

    def _on_audio_devices_applied(self):
        self._log.append_log("SYS: Audio devices updated.")
        if self.on_audio_device_change:
            self.on_audio_device_change()

    # ── Memory panel ─────────────────────────────────────────────────────────

    def _open_memory_panel(self):
        ov = MemoryOverlay(parent=self.centralWidget())
        self._centre_overlay(ov)
        self._memory_overlay = ov

    def _open_feature_settings(self):
        ov = FeatureSettingsOverlay(parent=self.centralWidget())
        ov.feature_changed.connect(self._on_feature_changed)
        self._centre_overlay(ov)
        self._feature_settings_overlay = ov

    def _open_provider_settings(self):
        ov = ProviderSettingsOverlay(parent=self.centralWidget())
        ov.activation_requested.connect(self._apply_provider_backend)
        self._centre_overlay(ov)
        self._provider_settings_overlay = ov

    def _on_feature_changed(self, key: str, enabled: bool, needs_backend: bool) -> None:
        if self.on_feature_change:
            self.on_feature_change(key, enabled)
        if needs_backend:
            self._start_backend_update("feature", key)

    def _apply_provider_backend(self, action: str, profile_name: str) -> None:
        self._start_backend_update("provider", f"{action}:{profile_name}")

    def _start_backend_update(self, source: str, detail: str) -> None:
        if self._provider_backend_busy:
            self._pending_backend_updates.append((source, detail))
            action = detail.split(":", 1)[0]
            if source == "provider" and action in {"key_updated", "key_removed", "credential_failure"}:
                self._stop_cloud_backend_urgent()
            overlay = getattr(
                self,
                "_feature_settings_overlay" if source == "feature" else "_provider_settings_overlay",
                None,
            )
            if overlay is not None:
                overlay.backend_activation_queued(
                    "Gespeichert. Wartet auf die laufende Backend-Aktualisierung …"
                )
            return
        self._provider_backend_busy = True

        def worker() -> None:
            action = detail.split(":", 1)[0]
            if source == "provider" and action == "credential_failure":
                try:
                    from desktop.core.settings_store import stop_cloud_backend
                    stop_cloud_backend()
                except Exception as error:
                    message = (
                        f"{error} Stoppe das MICA-Backend manuell, damit kein alter Schlüssel "
                        "in einem laufenden Container verbleibt."
                    )
                else:
                    message = (
                        "Schlüsseländerung fehlgeschlagen; API- und Sprachcontainer wurden "
                        "vorsichtshalber gestoppt."
                    )
                self._backend_update_sig.emit(source, False, message)
                return
            if source == "provider" and action in {"key_updated", "key_removed"}:
                try:
                    from desktop.core.settings_store import stop_cloud_backend
                    stop_cloud_backend()
                except Exception as error:
                    self._backend_update_sig.emit(
                        source,
                        False,
                        f"{error} Das MICA-Backend konnte vor der Schlüsseländerung nicht sicher gestoppt werden.",
                    )
                    return
            try:
                from desktop.core.settings_store import apply_backend_configuration
                apply_backend_configuration()
            except Exception as error:
                if source == "provider" and action in {"key_updated", "key_removed"}:
                    try:
                        from desktop.core.settings_store import stop_cloud_backend
                        stop_cloud_backend()
                    except Exception:
                        message = (
                            f"{error} Der alte Schlüssel könnte noch in laufenden Containern liegen; "
                            "stoppe das MICA-Backend bis der Neustart gelingt."
                        )
                    else:
                        message = (
                            f"{error} API- und Sprachcontainer wurden vorsichtshalber gestoppt, "
                            "damit kein alter Schlüssel weiterverwendet wird."
                        )
                else:
                    message = str(error)
                self._backend_update_sig.emit(source, False, message)
                return
            if source == "feature":
                message = "Funktion gespeichert und MICA-Backend erfolgreich aktualisiert."
            else:
                action = detail.split(":", 1)[0]
                message = {
                    "key_updated": "API-Schlüssel aktualisiert und Cloud-Container sicher neu erstellt.",
                    "key_removed": "API-Schlüssel entfernt und Cloud-Container ohne alten Schlüssel neu erstellt.",
                }.get(action, "Anbieter aktiviert und MICA-Backend erfolgreich neu gestartet.")
            self._backend_update_sig.emit(source, True, message)

        threading.Thread(target=worker, name="mica-backend-update", daemon=True).start()

    def _stop_cloud_backend_urgent(self) -> None:
        """Immediately revoke running cloud containers while an update is queued."""
        def worker() -> None:
            try:
                from desktop.core.settings_store import stop_cloud_backend
                stop_cloud_backend()
            except Exception as error:
                self._log_sig.emit(f"ERR: Cloud-Container konnten nicht sofort gestoppt werden: {error}")
            else:
                self._log_sig.emit("SYS: Cloud-Container wegen Schlüsseländerung sofort gestoppt.")

        threading.Thread(target=worker, name="mica-credential-revoke", daemon=True).start()

    def _on_backend_update_result(self, source: str, success: bool, message: str) -> None:
        self._provider_backend_busy = False
        overlay = getattr(
            self,
            "_feature_settings_overlay" if source == "feature" else "_provider_settings_overlay",
            None,
        )
        source_still_queued = any(item_source == source for item_source, _ in self._pending_backend_updates)
        if overlay is not None and source_still_queued:
            overlay.backend_activation_queued(
                "Eine weitere gespeicherte Änderung wartet auf die Backend-Aktualisierung …"
            )
        elif overlay is not None:
            overlay.backend_activation_finished(success, message)
        self._log.append_log(f"SYS: {message}" if success else f"ERR: {message}")
        if self._pending_backend_updates:
            next_source, next_detail = self._pending_backend_updates.pop(0)
            self._start_backend_update(next_source, next_detail)

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
            from desktop.core.confirm import resolve
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
        if getattr(getattr(self, '_selection_capture', None), 'busy', False):
            return
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
            icon_path = BASE_DIR / "assets" / "mica-microphone-muted.png"
            icon = QIcon(str(icon_path)) if icon_path.exists() else self.style().standardIcon(
                QStyle.StandardPixmap.SP_MediaVolumeMuted
            )
            self._mute_btn.setIcon(icon)
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
            icon_path = BASE_DIR / "assets" / "mica-microphone.png"
            icon = QIcon(str(icon_path)) if icon_path.exists() else self.style().standardIcon(
                QStyle.StandardPixmap.SP_MediaVolume
            )
            self._mute_btn.setIcon(icon)
            self._mute_btn.setIconSize(QSize(62, 62) if icon_path.exists() else QSize(34, 38))
            self._mute_btn.setToolTip("Mikrofon stummschalten (F4)")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent; color: {C.PRI};
                    border: none; border-radius: 32px;
                }}
                QPushButton:hover {{ background: {C.PRI_GHO}; }}
                QPushButton:focus {{ border: 1px solid {C.PRI}; }}
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
        ow, oh = SetupOverlay._OW, SetupOverlay._OH
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
    def remember_conversations(self) -> bool:
        return self._win.remember_conversations

    def use_backend_memory(self, session_provider=None):
        from desktop.control_center import BackendMemoryPage
        window = self._win
        previous = window._view_stack.currentIndex()
        old = window._memory_page
        window._view_stack.removeWidget(old)
        page = BackendMemoryPage()
        if session_provider is not None:
            from desktop.cognition_panel import open_cognition_dialog
            page.cognition_button = QPushButton('Aufmerksamkeit und Zustand')
            page.cognition_button.clicked.connect(lambda: open_cognition_dialog(window, session_provider))
            page.layout().insertWidget(2, page.cognition_button)
        page.private.setChecked(not window.remember_conversations)
        def set_preference(value):
            from desktop.core.preferences import set_remember_conversations
            previous = window.remember_conversations
            try:
                set_remember_conversations(value)
            except OSError as error:
                page.private.blockSignals(True)
                page.private.setChecked(not previous)
                page.private.blockSignals(False)
                page.status.setText('Einstellung konnte nicht gespeichert werden: ' + str(error))
                return
            window.remember_conversations = value
        page.remember_changed.connect(set_preference)
        window._backend_memory_page = page
        window._memory_page = page
        window._view_stack.insertWidget(3, page)
        window._view_stack.setCurrentIndex(previous)
        old.deleteLater()

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
    def on_feature_change(self):
        return self._win.on_feature_change

    @on_feature_change.setter
    def on_feature_change(self, cb):
        self._win.on_feature_change = cb

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
