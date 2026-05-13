"""Centralised logging configuration for the bank-statement-analizer service.

Nodes and API routers import ``get_logger`` from this module instead of
calling ``logging.getLogger`` directly.  This guarantees a single
configuration point.
"""

from __future__ import annotations

import logging
import os
import sys

_CONFIGURED = False


def _configure() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    level_str = os.environ.get("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_str, logging.INFO)
    logging.basicConfig(
        level=level,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a configured ``logging.Logger`` for *name*.

    Call once per module at module level::

        logger = get_logger(__name__)
    """
    _configure()
    return logging.getLogger(name)
