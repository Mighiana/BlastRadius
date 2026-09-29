from __future__ import annotations

from enum import StrEnum


class FailureCode(StrEnum):
    """Terminal analysis error codes persisted on failed analyses."""

    ANALYSIS_FAILED = "analysis_failed"
    ANALYSIS_TIMEOUT = "analysis_timeout"
    DISPATCH_FAILED = "dispatch_failed"
    GITHUB_ANALYSIS_FAILED = "github_analysis_failed"
    INVALID_ANALYSIS_INPUT = "invalid_analysis_input"
    INVALID_WORKER_RESULT = "invalid_worker_result"
    RESOURCE_LIMIT_EXCEEDED = "resource_limit_exceeded"
    RESULT_TOO_LARGE = "result_too_large"
    SERVER_RESTARTED = "server_restarted"
    SERVICE_LEASE_LOST = "service_lease_lost"
    WORKER_FAILED = "worker_failed"
