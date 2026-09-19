"""Staging-only child process used to prove Not-Aus process-tree termination."""
from __future__ import annotations

import os
from pathlib import Path
import time


marker = Path(os.environ["MICA_PROCESS_PROBE_PID"])
marker.write_text(str(os.getpid()), encoding="ascii")
time.sleep(60)
