from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from blastradius.server.config import Settings

logger = logging.getLogger("blastradius.http")
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]{1,40}$")
_UUID_SEGMENT = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_HEX_SEGMENT = re.compile(r"^[0-9a-fA-F]{32,}$")
_DETAIL = re.compile(r"^[a-z_]{1,64}$")


def _sanitized_path(path: str) -> str:
    segments = []
    for segment in path.split("/"):
        if not segment:
            continue
        if (
            not _SAFE_SEGMENT.fullmatch(segment)
            or _UUID_SEGMENT.fullmatch(segment)
            or _HEX_SEGMENT.fullmatch(segment)
            or len(segment) > 40
        ):
            segments.append("*")
        else:
            segments.append(segment)
    return "/" + "/".join(segments)


def _error_detail(body: bytearray, too_large: bool) -> str | None:
    if too_large:
        return None
    try:
        detail = json.loads(body)
    except (UnicodeDecodeError, TypeError, ValueError):
        return None
    value = detail.get("detail") if isinstance(detail, dict) else None
    return value if isinstance(value, str) and _DETAIL.fullmatch(value) else None


class GuardMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings):
        self.app = app
        self.settings = settings
        self.buckets: dict[tuple[str, str], tuple[float, int]] = {}
        self.submissions: dict[str, tuple[float, int]] = {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.monotonic()
        request_id = str(uuid.uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        status = 500
        response_started = False
        error_body = bytearray()
        error_body_too_large = False

        async def safe_send(message: Message) -> None:
            nonlocal error_body_too_large, status, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status = message["status"]
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Cache-Control"] = "no-store"
                headers["Referrer-Policy"] = "no-referrer"
                headers["X-Frame-Options"] = "DENY"
                if self.settings.production:
                    headers["Strict-Transport-Security"] = "max-age=31536000"
            elif message["type"] == "http.response.body" and status >= 400:
                body = message.get("body", b"")
                remaining = 512 - len(error_body)
                if not error_body_too_large:
                    if len(body) > remaining:
                        error_body.extend(body[:remaining])
                        error_body_too_large = True
                    else:
                        error_body.extend(body)
                        if message.get("more_body") and len(error_body) >= 512:
                            error_body_too_large = True
            await send(message)

        async def error(code: int, detail: str) -> None:
            await JSONResponse({"detail": detail}, status_code=code)(scope, receive, safe_send)

        try:
            headers = Headers(scope=scope)
            if headers.get("content-encoding", "identity") != "identity":
                await error(415, "content_encoding_unsupported")
                return
            path = scope["path"]
            submission = (
                "beta"
                if path.rstrip("/") == "/api/beta-interest" and scope["method"] == "POST"
                else "feedback"
                if path.startswith("/api/analyses/")
                and path.rstrip("/").endswith("/feedback")
                and scope["method"] == "PUT"
                else None
            )
            category = (
                submission
                if submission
                else "auth"
                if path.startswith("/api/auth/")
                else "demo"
                if path.startswith("/api/demo")
                else "api"
            )
            client = scope.get("client")
            key = (client[0] if client else "unknown", category)
            now = time.monotonic()
            self.buckets = {k: v for k, v in self.buckets.items() if now - v[0] < 60}
            limit = {
                "auth": self.settings.auth_rate_limit,
                "demo": self.settings.demo_rate_limit,
                "api": self.settings.rate_limit,
                "beta": 5,
                "feedback": 30,
            }[category]
            window, count = self.buckets.get(key, (now, 0))
            if count >= limit or (key not in self.buckets and len(self.buckets) >= 10000):
                await error(429, "rate_limit_exceeded")
                return
            self.buckets[key] = (window, count + 1)
            if submission:
                global_window, global_count = self.submissions.get(submission, (now, 0))
                if now - global_window >= 60:
                    global_window, global_count = now, 0
                if global_count >= {"beta": 60, "feedback": 120}[submission]:
                    await error(429, "rate_limit_exceeded")
                    return
                self.submissions[submission] = (global_window, global_count + 1)
            body_limit = min(
                self.settings.max_body_bytes,
                {"beta": 8192, "feedback": 4096}.get(
                    submission or "", self.settings.max_body_bytes
                ),
            )
            try:
                length = int(headers.get("content-length", "0"))
            except ValueError:
                await error(400, "invalid_content_length")
                return
            if length < 0 or length > body_limit:
                await error(413, "body_too_large")
                return
            body = bytearray()
            try:
                async with asyncio.timeout(15):
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            return
                        body.extend(message.get("body", b""))
                        if len(body) > body_limit:
                            await error(413, "body_too_large")
                            return
                        if not message.get("more_body", False):
                            break
            except TimeoutError:
                await error(408, "request_timeout")
                return
            delivered = False

            async def replay() -> Message:
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {
                        "type": "http.request",
                        "body": bytes(body),
                        "more_body": False,
                    }
                return await receive()

            try:
                await self.app(scope, replay, safe_send)
            except Exception as exc:
                logger.warning(
                    json.dumps({"request_id": request_id, "event": "unhandled_exception"}),
                    exc_info=(type(exc), type(exc)(), None),
                )
                if not response_started:
                    await error(500, "internal_error")
        finally:
            route = scope.get("route")
            event = {
                "request_id": request_id,
                "method": scope["method"],
                "status": status,
                "duration_ms": round((time.monotonic() - start) * 1000, 2),
            }
            endpoint = getattr(route, "path", None)
            if endpoint:
                event["endpoint"] = endpoint
            else:
                event["path"] = _sanitized_path(scope["path"])
            try:
                analysis_id = scope.get("path_params", {}).get("analysis_id")
                event["analysis_id"] = str(uuid.UUID(analysis_id))
            except (AttributeError, TypeError, ValueError):
                pass
            if status >= 400:
                detail = _error_detail(error_body, error_body_too_large)
                if detail:
                    event["error"] = detail
            logger.log(
                logging.WARNING if status >= 500 else logging.INFO,
                json.dumps(event),
            )
