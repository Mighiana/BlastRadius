from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.routing import Match, Mount
from starlette.types import Scope


class FrontendMount(Mount):
    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        if scope["type"] in {"http", "websocket"}:
            path = scope["path"].removeprefix(scope.get("root_path", "")).lstrip("/")
            if path.split("/", 1)[0] in {"api", "health"}:
                return Match.NONE, {}
        return super().matches(scope)


class FrontendFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        if path in {
            ".",
            "demo",
            "dashboard",
            "history",
            "pricing",
            "billing",
            "beta",
            "operator",
            "guide",
            "account",
            "settings",
            "team",
            "integrations",
            "security",
            "privacy",
            "terms",
            "invitations/accept",
        }:
            path = "index.html"
        return await super().get_response(path, scope)
