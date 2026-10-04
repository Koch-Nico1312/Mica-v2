from __future__ import annotations

import time

from backend.services.common.brain import MarkdownBrain
from backend.services.common.health import reset, touch
from backend.services.common.storage_lock import StorageLease, StorageBusy


if __name__ == "__main__":
    brain = MarkdownBrain()
    reset("brain-index")
    while True:
        try:
            with StorageLease(brain.root.parent, timeout=2):
                if not (brain.root.parent / '.restore-incomplete').exists():
                    brain.reindex(force=False)
                    touch("brain-index")
        except StorageBusy:
            pass
        time.sleep(15)
