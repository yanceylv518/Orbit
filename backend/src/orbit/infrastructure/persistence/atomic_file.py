from __future__ import annotations

import os
from pathlib import Path
import time


def replace_with_retry(
    source: Path,
    destination: Path,
    *,
    attempts: int = 20,
    delay_seconds: float = 0.05,
) -> None:
    """Atomically replace a file despite brief Windows reader contention."""
    if attempts < 1:
        raise ValueError("attempts must be positive")
    for attempt in range(attempts):
        try:
            os.replace(source, destination)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay_seconds)
