from __future__ import annotations

from blastradius.server.beta import cleanup_commercial
from blastradius.server.db import Database
from blastradius.server.persistence import cleanup


def run_retention_sweep(db: Database, limit: int = 100) -> dict[str, int]:
    """Run bounded analysis and commercial cleanup until a pass removes nothing."""
    analyses = 0
    beta_interest = 0
    analysis_feedback = 0
    product_events = 0
    passes = 0
    for _ in range(50):
        removed = cleanup(db, limit)
        passes += 1
        analyses += removed
        if removed == 0:
            break
    for _ in range(50):
        counts = cleanup_commercial(db, limit)
        passes += 1
        beta_interest += counts["beta_interest"]
        analysis_feedback += counts["analysis_feedback"]
        product_events += counts["product_events"]
        if not any(counts.values()):
            break
    return {
        "analyses": analyses,
        "beta_interest": beta_interest,
        "analysis_feedback": analysis_feedback,
        "product_events": product_events,
        "passes": passes,
    }
