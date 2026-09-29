from blastradius.server.github_service import DispatchStatus
from blastradius.server.models import (
    AnalysisStatus,
    ConnectionStatus,
    DeliveryStatus,
    InstallationStatus,
    RunStatus,
)


def test_persisted_status_values_are_stable():
    assert [s.value for s in AnalysisStatus] == ["queued", "running", "succeeded", "failed"]
    assert [s.value for s in InstallationStatus] == ["active", "suspended", "deleted"]
    assert [s.value for s in ConnectionStatus] == ["active", "revoked", "disconnected"]
    assert [s.value for s in DeliveryStatus] == [
        "pending",
        "queued",
        "retryable",
        "rejected",
        "handled",
        "ignored",
    ]
    assert [s.value for s in RunStatus] == ["pending", "ready", "published", "expired"]


def test_dispatch_statuses_are_a_distinct_vocabulary():
    assert [s.value for s in DispatchStatus] == [
        "queued",
        "handled",
        "ignored",
        "rejected",
        "deferred",
        "duplicate",
    ]
    assert {DeliveryStatus.PENDING, DeliveryStatus.RETRYABLE}.isdisjoint(set(DispatchStatus))
