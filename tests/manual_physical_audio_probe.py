"""Short, privacy-preserving physical microphone to HUD acceptance probe.

Only per-block RMS/level numbers are retained. PCM bytes are discarded as
soon as each block has been measured and are never written to disk.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from unittest.mock import patch

import sounddevice as sd
from PyQt6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ui import JarvisUI, MainWindow


def _level_from_pcm(raw: bytes) -> tuple[float, float]:
    samples = memoryview(raw).cast("h")
    if not samples:
        return 0.0, 0.0
    rms = math.sqrt(sum(int(sample) * int(sample) for sample in samples) / len(samples))
    level = 0.0 if rms <= 60.0 else min(1.0, (rms - 60.0) / (2600.0 - 60.0))
    return rms, level


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--duration", type=float, default=3.0)
    parser.add_argument("--output", type=Path, default=Path("artifacts/mica-hud-physical-mic.png"))
    args = parser.parse_args()

    input_device = int(sd.default.device[0])
    info = sd.query_devices(input_device, "input")
    sample_rate = 16000
    blocksize = 1024
    blocks = max(1, math.ceil(max(0.25, args.duration) * sample_rate / blocksize))
    levels: list[float] = []
    rms_values: list[float] = []
    overflows = 0
    with sd.RawInputStream(
        samplerate=sample_rate, channels=1, dtype="int16",
        blocksize=blocksize, device=input_device,
    ) as stream:
        for _ in range(blocks):
            raw, overflowed = stream.read(blocksize)
            overflows += int(bool(overflowed))
            rms, level = _level_from_pcm(bytes(raw))
            rms_values.append(rms)
            levels.append(level)

    peak_level = max(levels, default=0.0)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with patch.object(MainWindow, "_check_config", return_value=True):
        ui = JarvisUI("assets/mica-orb-v2.png")
        ui.set_state("LISTENING")
        ui._app.processEvents()
        ui.set_audio_level(peak_level)
        for _ in range(4):
            ui._win.hud._step()
            ui._win._ctx_audio._step()
            ui._win._composer_wave_left._step()
            ui._win._composer_wave_right._step()
            ui._app.processEvents()
        if not ui._win.grab().save(str(args.output)):
            raise RuntimeError("HUD screenshot could not be saved")
        ui._win.close()

    print(json.dumps({
        "device_index": input_device,
        "device_name": str(info["name"]),
        "sample_rate": sample_rate,
        "blocks": blocks,
        "overflow_blocks": overflows,
        "nonzero_level_blocks": sum(level > 0.0 for level in levels),
        "max_rms": round(max(rms_values, default=0.0), 3),
        "max_hud_level": round(peak_level, 6),
        "raw_audio_saved": False,
        "screenshot": str(args.output.resolve()),
    }, ensure_ascii=False, indent=2))
    return 0 if peak_level > 0.0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
