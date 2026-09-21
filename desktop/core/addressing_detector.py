"""Re-export or standalone AddressingDetector for Desktop MICA runtime."""
from __future__ import annotations

import sys
from pathlib import Path

# Try to import from the backend service package first.
try:
    from backend.services.common.addressing import AddressDecision, AddressingDetector
except ImportError:
    # Add the repository backend directory for standalone script use.
    _BACKEND_DIR = Path(__file__).resolve().parents[2] / "backend"
    if str(_BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(_BACKEND_DIR))
    from services.common.addressing import AddressDecision, AddressingDetector

__all__ = ["AddressDecision", "AddressingDetector"]
