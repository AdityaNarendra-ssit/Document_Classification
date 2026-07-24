"""src package: reusable components for the policy knowledge graph.

This module configures the shared `loguru` logger used across all
policy-knowledge-graph modules. Importing any submodule triggers this
configuration exactly once because Python caches the package.
"""

import os
import sys
from pathlib import Path

from loguru import logger


def configure_logger() -> None:
    """Configure loguru sinks for console and rotating file output.

    The log level is read from the ``LOG_LEVEL`` environment variable and
    defaults to ``INFO``. Logs are written to stderr with colorized output
    and to a rotating file at ``logs/app.log`` (5 MB rotation, 7 day retention).

    Returns:
        None
    """
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    # Remove the default loguru sink so we can install our own.
    logger.remove()

    # Pretty console output.
    logger.add(
        sink=sys.stderr,
        level=level,
        colorize=True,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
    )

    # Persistent rotating file output.
    logger.add(
        sink=str(log_dir / "app.log"),
        level=level,
        rotation="5 MB",
        retention="7 days",
        encoding="utf-8",
        format=(
            "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | "
            "{name}:{function}:{line} - {message}"
        ),
    )


# Configure once when the package is first imported.
configure_logger()
