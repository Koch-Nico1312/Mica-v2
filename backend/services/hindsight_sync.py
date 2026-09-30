"""Dedicated optional worker; model ingestion never delays task scheduling."""
import os
import time

from services.common.brain import MarkdownBrain
from services.common.hindsight import HindsightMemory
from services.common.policy import PolicyEngine


def main():
    brain = MarkdownBrain()
    policy = PolicyEngine(os.getenv("APPROVAL_DB", "/data/approvals.sqlite3"))
    while True:
        if not policy.is_emergency_stopped():
            HindsightMemory(brain).sync(limit=1)
        time.sleep(15)


if __name__ == "__main__":
    main()
