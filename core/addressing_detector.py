"""Re-export or standalone AddressingDetector for Desktop MICA runtime."""
from __future__ import annotations

import sys
from pathlib import Path

# Try to import from mica_core.services.common.addressing first
try:
    from mica_core.services.common.addressing import AddressDecision, AddressingDetector
except ImportError:
    # Add mica_core to sys.path
    _CORE_DIR = Path(__file__).resolve().parents[1] / "mica_core"
    if str(_CORE_DIR) not in sys.path:
        sys.path.insert(0, str(_CORE_DIR))
    from services.common.addressing import AddressDecision, AddressingDetector

__all__ = ["AddressDecision", "AddressingDetector"]
