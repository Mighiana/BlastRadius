from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="install .[server,dev] for static routing tests")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from blastradius.server.static import FrontendFiles, FrontendMount


@pytest.fixture
def static_client(tmp_path: Path):
    (tmp_path / "index.html").write_text("<html>Application</html>", encoding="utf-8")
    (tmp_path / "api").mkdir()
    (tmp_path / "api" / "private.json").write_text("not-an-api-response", encoding="utf-8")
    app = FastAPI()

    @app.get("/api/known")
    def known_route():
        return {"ok": True}

    app.router.routes.append(FrontendMount("/", app=FrontendFiles(directory=tmp_path)))
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/demo",
        "/dashboard",
        "/history",
        "/pricing",
        "/billing",
        "/guide",
        "/account",
        "/settings",
        "/team",
        "/integrations",
        "/security",
        "/privacy",
        "/terms",
        "/invitations/accept",
    ],
)
def test_direct_navigation_to_product_routes(static_client, path):
    response = static_client.get(path)
    assert response.status_code == 200
    assert response.text == "<html>Application</html>"
    assert static_client.head(path).status_code == 200


@pytest.mark.parametrize("method", ["get", "post", "put", "patch", "delete"])
@pytest.mark.parametrize(
    "path",
    ["/api", "/api/private.json", "/api/billing/webhook", "/health/missing"],
)
def test_unknown_api_routes_cannot_fall_through_to_static_files(static_client, method, path):
    response = static_client.request(method, path)
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_static_fallback_is_allowlisted(static_client):
    assert static_client.get("/not-a-product-route").status_code == 404
    assert static_client.post("/dashboard").status_code == 405
    assert static_client.get("/api/known").json() == {"ok": True}
    assert static_client.post("/api/known").status_code == 405


@pytest.mark.parametrize("path", ["/beta", "/operator"])
def test_commercial_routes_support_cold_navigation_without_api_fallback(static_client, path):
    response = static_client.get(path)
    assert response.status_code == 200
    assert response.text == "<html>Application</html>"
    assert static_client.head(path).status_code == 200
    assert static_client.post(path).status_code == 405
    assert static_client.get("/api" + path).status_code == 404
