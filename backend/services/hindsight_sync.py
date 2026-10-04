"""Dedicated optional worker; model ingestion never delays task scheduling."""
import os
import time

from backend.services.common.brain import MarkdownBrain
from backend.services.common.hindsight import HindsightMemory
from backend.services.common.policy import PolicyEngine
from backend.services.common.storage_lock import StorageLease, StorageBusy


def main():
    brain = MarkdownBrain()
    policy = PolicyEngine(os.getenv("APPROVAL_DB", "/data/approvals.sqlite3"))
    while True:
        if not policy.is_emergency_stopped():
            try:
                with StorageLease(brain.root.parent, timeout=2):
                    if not (brain.root.parent / '.restore-incomplete').exists():
                        HindsightMemory(brain).sync(limit=1)
            except StorageBusy:
                pass
        time.sleep(15)


if __name__ == "__main__":
    main()
