"""Reusable voice canvas, inputs and media widgets."""
from __future__ import annotations
from collections import deque
import math
import platform
import random
import time
from pathlib import Path
from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QDragEnterEvent, QDropEvent, QFont, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient
from PyQt6.QtWidgets import QApplication, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QTextEdit, QVBoxLayout, QWidget, QStyle
from desktop.ui_support import BASE_DIR, _read_full_config, time_greeting
from desktop.ui_theme import C, qcol


class _AnimatedWidget(QWidget):
    """Run decorative animation only while its widget is actually visible."""

    def _set_animation_timer(self, timer: QTimer, interval_ms: int) -> None:
        self._animation_timer = timer
        self._animation_interval_ms = interval_ms
        if self.isVisible():
            timer.start(interval_ms)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._animation_timer.start(self._animation_interval_ms)

    def hideEvent(self, event) -> None:
        self._animation_timer.stop()
        super().hideEvent(event)
_OS = platform.system()


class HudCanvas(_AnimatedWidget):
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
        self._set_animation_timer(self._tmr, 16)

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
        # The reference uses a few quiet orbital traces, not a dense wireframe.
        for line in range(10):
            fraction = line / 9.0
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
            alpha = 10 + int(14 * (1 - abs(fraction - .5) * 1.5))
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
        cx, cy = W / 2, H * .34
        fw = min(W, H)
        # Match the reference hierarchy: Mica is the central hero, not a
        # toolbar-sized icon.
        r_orb = fw * .22
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
            # image-1 contains the translucent outer shell as well as the face.
            fsz    = int(r_orb * 2.35 * self._scale)
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
            txt, sub, col = time_greeting(), "Wie kann ich dir helfen?", qcol(C.TEXT)
        else:
            txt, sub, col = time_greeting(), "Wie kann ich dir helfen?", qcol(C.TEXT)

        # The reference uses a confident, dark display line rather than an
        # accent-coloured caption.  State colour remains visible in the aura,
        # portrait rings and waveform, while the primary message stays calm
        # and readable at both the reference and minimum window sizes.
        p.setPen(QPen(col, 1)); p.setFont(QFont("Segoe UI", 27, QFont.Weight.DemiBold))
        p.drawText(QRectF(0, sy, W, 48), Qt.AlignmentFlag.AlignCenter, txt)
        p.setPen(QPen(qcol(C.TEXT_MED), 1)); p.setFont(QFont("Segoe UI", 11))
        p.drawText(QRectF(0, sy + 48, W, 24), Qt.AlignmentFlag.AlignCenter, sub)

        if self.state == "LISTENING" and not self.muted and not self.speaking:
            # The supplied ready-state reference uses a compact status pill.
            pill = QRectF(cx - 53, sy + 84, 106, 34)
            p.setBrush(QBrush(qcol("#ffffff", 235)))
            p.setPen(QPen(qcol(C.BORDER, 245), 1))
            p.drawRoundedRect(pill, 17, 17)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol("#42c86a")))
            p.drawEllipse(QPointF(pill.left() + 22, pill.center().y()), 6, 6)
            p.setPen(QPen(qcol(C.TEXT_MED), 1))
            p.setFont(QFont("Segoe UI", 10, QFont.Weight.Medium))
            p.drawText(QRectF(pill.left() + 34, pill.top(), 58, pill.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, "Bereit")
        else:
            # Active states use a waveform driven by the smoothed audio level.
            wy = sy + 105
            N, bw = 31, 7
            wx0 = (W - N * bw) / 2
            amp = self._amp_disp
            mid = (N - 1) / 2.0
            for i in range(N):
                if self.muted:
                    hgt, cl = 2, qcol(C.MUTED_C)
                else:
                    env = (1.0 - abs(i - mid) / mid) ** 0.7
                    shimmer = 0.55 + 0.45 * math.sin(self._tick * 0.18 + i * 0.7)
                    idle = 3.0 + 2.0 * math.sin(self._tick * 0.09 + i * 0.6)
                    hgt = int(max(2, min(18, idle + amp * 17.0 * env * shimmer)))
                    cl = qcol(C.PRI) if amp > 0.05 and hgt > 12 else qcol(C.PRI_DIM)
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
        self._queue: deque[str] = deque()
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
        self._text   = self._queue.popleft()
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

class LiveWaveform(_AnimatedWidget):
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
        self._set_animation_timer(self._timer, 33)

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
