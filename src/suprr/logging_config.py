from __future__ import annotations

import logging
import os


def configure_logging() -> None:
    level = os.getenv("SUPRR_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
