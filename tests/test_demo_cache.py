from __future__ import annotations

import json
import logging

from blastradius.server.config import Settings
from blastradius.server.demos import (
    build_demos,
    demo_fingerprint,
    load_demo_cache,
    write_demo_cache,
)

from test_server import demo_results


def test_demo_cache_miss_reasons_are_logged(tmp_path, demo_results, monkeypatch, caplog):
    settings = Settings(data_dir=tmp_path / "data")
    monkeypatch.setattr("blastradius.server.demos.build_demos", lambda _: demo_results)
    caplog.set_level(logging.INFO, logger="blastradius.server.demos")
    logger = logging.getLogger("blastradius.server.demos")
    logger.addHandler(caplog.handler)
    cache = tmp_path / "demos.json"
    try:
        write_demo_cache(cache, settings)
        assert len(load_demo_cache(cache, settings)) == 9
        assert json.loads(caplog.records[-1].getMessage()) == {
            "event": "demo.cache_loaded",
            "count": 9,
        }

        cache.write_text("not-json", encoding="utf-8")
        assert load_demo_cache(cache, settings) is None
        assert json.loads(caplog.records[-1].getMessage()) == {
            "event": "demo.cache_miss",
            "reason": "corrupt",
        }

        write_demo_cache(cache, settings)
        mismatched = Settings(data_dir=settings.data_dir, max_resources=settings.max_resources + 1)
        assert load_demo_cache(cache, mismatched) is None
        assert json.loads(caplog.records[-1].getMessage()) == {
            "event": "demo.cache_miss",
            "reason": "settings",
        }

        write_demo_cache(cache, settings)
        document = json.loads(cache.read_text(encoding="utf-8"))
        document["demos"][0][2] = {}
        cache.write_text(json.dumps(document), encoding="utf-8")
        assert load_demo_cache(cache, settings) is None
        assert json.loads(caplog.records[-1].getMessage()) == {
            "event": "demo.cache_miss",
            "reason": "corrupt",
        }

        write_demo_cache(cache, settings)
        document = json.loads(cache.read_text(encoding="utf-8"))
        document["fingerprint"] = "stale"
        cache.write_text(json.dumps(document), encoding="utf-8")
        assert load_demo_cache(cache, settings) is None
        assert json.loads(caplog.records[-1].getMessage()) == {
            "event": "demo.cache_miss",
            "reason": "stale",
        }

        document["fingerprint"] = demo_fingerprint()
        document["demos"].pop()
        cache.write_text(json.dumps(document), encoding="utf-8")
        assert load_demo_cache(cache, settings) is None
        assert json.loads(caplog.records[-1].getMessage()) == {
            "event": "demo.cache_miss",
            "reason": "incomplete",
        }

        cache.unlink()
        assert load_demo_cache(cache, settings) is None
        assert json.loads(caplog.records[-1].getMessage()) == {
            "event": "demo.cache_miss",
            "reason": "missing",
        }
        assert load_demo_cache(None, settings) is None
        assert json.loads(caplog.records[-1].getMessage()) == {
            "event": "demo.cache_miss",
            "reason": "unconfigured",
        }
    finally:
        logger.removeHandler(caplog.handler)


def test_build_demos_uses_a_separate_work_directory(tmp_path, monkeypatch):
    settings = Settings(data_dir=tmp_path / "data")
    work_dirs = []

    def fake_execute(_payload, _settings, work_dir=None):
        work_dirs.append(work_dir)
        return {
            "result": {
                "decision": "SAFE TO MERGE",
                "score": {"before": 100, "after": 100},
                "verdict": "NO_REGRESSION",
                "remediation": {"patched_files": {"main.tf": "patched"}},
            }
        }

    monkeypatch.setattr("blastradius.server.demos.execute", fake_execute)
    build_demos(settings)

    assert work_dirs
    assert {path for path in work_dirs} == {settings.data_dir / "demos"}
    assert not (settings.data_dir / "jobs").exists()
