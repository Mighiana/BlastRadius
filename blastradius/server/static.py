from fastapi.staticfiles import StaticFiles
from starlette.responses import Response
from starlette.types import Scope


class FrontendFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        if path in {".", "demo", "dashboard", "history", "pricing", "billing", "guide"}:
            path = "index.html"
        return await super().get_response(path, scope)
