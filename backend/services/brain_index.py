from __future__ import annotations

import time

from services.common.brain import MarkdownBrain
from services.common.health import reset, touch


if __name__ == "__main__":
    brain = MarkdownBrain()
    reset("brain-index")
    while True:
        brain.reindex()
        # The Compose probe is a fresh-iteration proof, not merely PID 1.
        touch("brain-index")
        time.sleep(15)
