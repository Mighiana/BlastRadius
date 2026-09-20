from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_render_blueprint_has_production_single_instance_contract():
    blueprint = yaml.safe_load((ROOT / "render.yaml").read_text(encoding="utf-8"))
    service = blueprint["services"][0]
    values = {item["key"]: item for item in service["envVars"]}

    assert service["numInstances"] == 1
    assert service["healthCheckPath"] == "/health/live"
    assert values["BR_ENV"]["value"] == "production"
    assert values["BR_AUTH_MODE"]["value"] == "oidc"
    assert values["BR_AUTO_MIGRATE"]["value"] == "false"
    assert values["BR_SESSION_SECRET"]["generateValue"] is True
    assert values["BR_DATABASE_URL"]["fromDatabase"]["name"] == "blastradius-db"
    for key in ("BR_PUBLIC_URL", "BR_OIDC_ISSUER", "BR_OIDC_CLIENT_ID", "BR_OIDC_CLIENT_SECRET"):
        assert values[key]["sync"] is False

    for item in service["envVars"]:
        assert "secret" not in item
        if item["key"] in {"BR_SESSION_SECRET", "BR_DATABASE_URL"}:
            continue
        assert "value" not in item or not any(
            marker in str(item["value"]).lower() for marker in ("password", "secret", "token")
        )


def test_container_entrypoint_opts_into_proxy_headers_only_for_render():
    entrypoint = (ROOT / "scripts/container-entrypoint.sh").read_text(encoding="utf-8")

    assert '[ "${BR_TRUST_PROXY_HEADERS:-false}" = "true" ]' in entrypoint
    assert "--proxy-headers --forwarded-allow-ips='*'" in entrypoint
    assert "--no-proxy-headers" in entrypoint
