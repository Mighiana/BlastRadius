from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

from blastradius.server.config import Settings


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "time": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
        }
        message = record.getMessage()
        try:
            decoded = json.loads(message)
        except (TypeError, ValueError):
            decoded = None
        if isinstance(decoded, dict):
            payload.update(decoded)
        else:
            payload["message"] = message
        if record.exc_info:
            exception_type = record.exc_info[0]
            if exception_type is not None:
                payload["exception"] = exception_type.__name__
        return json.dumps(payload, default=str, sort_keys=True)


def configure_logging(settings: Settings) -> None:
    logger = logging.getLogger("blastradius")
    logger.setLevel(settings.log_level)
    logger.propagate = False
    if not any(handler.name == "blastradius-json" for handler in logger.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.name = "blastradius-json"
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
