from __future__ import annotations

import json
import logging
import sys

import pytest

from blastradius.server.config import Settings
from blastradius.server.observability import JsonFormatter, configure_logging, log_event


def test_json_formatter_merges_json_and_sanitizes_exceptions():
    formatter = JsonFormatter()
    merged = json.loads(
        formatter.format(
            logging.LogRecord(
                "blastradius.test",
                logging.INFO,
                __file__,
                1,
                '{"event":"request.completed","status":200}',
                (),
                None,
            )
        )
    )
    assert merged["event"] == "request.completed"
    assert merged["status"] == 200
    assert merged["level"] == "INFO"
    assert merged["logger"] == "blastradius.test"
    assert "time" in merged

    plain = json.loads(
        formatter.format(
            logging.LogRecord(
                "blastradius.test", logging.INFO, __file__, 1, "plain message", (), None
            )
        )
    )
    assert plain["message"] == "plain message"

    try:
        raise ValueError("private-secret")
    except ValueError:
        record = logging.LogRecord(
            "blastradius.test", logging.WARNING, __file__, 1, '{"event":"failed"}', (), sys.exc_info()
        )
    formatted = json.loads(formatter.format(record))
    assert formatted["exception"] == "ValueError"
    assert "private-secret" not in formatter.format(record)
    assert "Traceback" not in formatter.format(record)


def test_log_event_emits_a_json_event_line_at_the_requested_level(caplog):
    logger = logging.getLogger("blastradius.test.log_event")
    logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.INFO, logger=logger.name):
            log_event(logger, logging.WARNING, "service.lease_released", held=True, duration_ms=3)
            log_event(logger, logging.INFO, "service.ready")
    finally:
        logger.removeHandler(caplog.handler)
    first, second = caplog.records
    assert first.levelno == logging.WARNING
    assert json.loads(first.getMessage()) == {
        "event": "service.lease_released",
        "held": True,
        "duration_ms": 3,
    }
    assert first.funcName == "test_log_event_emits_a_json_event_line_at_the_requested_level"
    assert json.loads(second.getMessage()) == {"event": "service.ready"}
    merged = json.loads(JsonFormatter().format(first))
    assert merged["event"] == "service.lease_released"
    assert merged["level"] == "WARNING"


def test_configure_logging_is_idempotent():
    logger = logging.getLogger("blastradius")
    old_handlers = list(logger.handlers)
    for handler in old_handlers:
        if handler.name == "blastradius-json":
            logger.removeHandler(handler)
    try:
        settings = Settings(log_level="DEBUG")
        configure_logging(settings)
        configure_logging(settings)
        tagged = [handler for handler in logger.handlers if handler.name == "blastradius-json"]
        assert len(tagged) == 1
        assert logger.level == logging.DEBUG
        assert logger.propagate is False
    finally:
        for handler in list(logger.handlers):
            if handler.name == "blastradius-json":
                logger.removeHandler(handler)
        for handler in old_handlers:
            if handler not in logger.handlers:
                logger.addHandler(handler)
