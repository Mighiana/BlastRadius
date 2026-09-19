from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from blastradius.server.config import Settings

logger = logging.getLogger("blastradius.http")


class GuardMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings):
        self.app = app
        self.settings = settings
        self.buckets: dict[tuple[str, str], tuple[float, int]] = {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = time.monotonic()
        request_id = str(uuid.uuid4())
        status = 500
        response_started = False

        async def safe_send(message: Message) -> None:
            nonlocal status, response_started
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
            await send(message)

        async def error(code: int, detail: str) -> None:
            await JSONResponse({"detail": detail}, status_code=code)(
                scope, receive, safe_send
            )

        try:
            headers = Headers(scope=scope)
            if headers.get("content-encoding", "identity") != "identity":
                await error(415, "content_encoding_unsupported")
                return
            path = scope["path"]
            category = (
                "auth"
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
            }[category]
            window, count = self.buckets.get(key, (now, 0))
            if count >= limit or (
                key not in self.buckets and len(self.buckets) >= 10000
            ):
                await error(429, "rate_limit_exceeded")
                return
            self.buckets[key] = (window, count + 1)
            try:
                length = int(headers.get("content-length", "0"))
            except ValueError:
                await error(400, "invalid_content_length")
                return
            if length < 0 or length > self.settings.max_body_bytes:
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
                        if len(body) > self.settings.max_body_bytes:
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
            except Exception:
                if not response_started:
                    await error(500, "internal_error")
        finally:
            logger.info(
                json.dumps(
                    {
                        "request_id": request_id,
                        "method": scope["method"],
                        "status": status,
                        "duration_ms": round((time.monotonic() - start) * 1000, 2),
                    }
                )
            )
