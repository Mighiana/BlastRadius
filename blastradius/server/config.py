from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Settings:
    environment: str = "development"
    database_url: str = "sqlite:///./.blastradius/server.db"
    data_dir: Path = Path(".blastradius")
    public_url: str = "http://localhost:8000"
    session_secret: str = field(default_factory=lambda: secrets.token_urlsafe(48))
    auth_mode: str = "disabled"
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_pro: str = ""
    stripe_price_team: str = ""
    max_body_bytes: int = 1_048_576
    max_files: int = 30
    max_resources: int = 300
    max_jobs: int = 8
    workers: int = 2
    job_timeout_seconds: int = 30
    session_ttl_seconds: int = 28_800
    rate_limit: int = 180
    auth_rate_limit: int = 15
    demo_rate_limit: int = 60
    auto_migrate: bool = True

    @property
    def production(self) -> bool:
        return self.environment == "production"

    @property
    def billing_enabled(self) -> bool:
        return bool(self.stripe_secret_key)

    def validate(self) -> None:
        if self.environment not in {"development", "test", "production"}:
            raise ValueError("BR_ENV must be development, test or production")
        if self.auth_mode not in {"disabled", "demo", "oidc"}:
            raise ValueError("BR_AUTH_MODE must be disabled, demo or oidc")
        if len(self.session_secret) < 32:
            raise ValueError("Session secret must contain at least 32 characters")
        if not self.database_url.startswith(("sqlite:///", "postgresql+psycopg://")):
            raise ValueError("Use SQLite or PostgreSQL with psycopg")
        url = urlsplit(self.public_url)
        if (
            url.scheme not in {"http", "https"}
            or not url.netloc
            or url.path not in {"", "/"}
            or url.query
            or url.fragment
            or url.username
        ):
            raise ValueError(
                "BR_PUBLIC_URL must be an origin without credentials or path"
            )
        if self.production and (
            self.auth_mode != "oidc"
            or len(self.session_secret) < 32
            or not self.database_url.startswith("postgresql+psycopg://")
            or url.scheme != "https"
            or self.auto_migrate
        ):
            raise ValueError(
                "Production requires OIDC, PostgreSQL, HTTPS, a session secret and explicit migrations"
            )
        if self.auth_mode == "oidc":
            issuer = urlsplit(self.oidc_issuer)
            if (
                issuer.scheme != "https"
                or not issuer.hostname
                or issuer.username
                or issuer.query
                or issuer.fragment
                or len(self.oidc_issuer) > 512
                or not self.oidc_client_id
                or not self.oidc_client_secret
            ):
                raise ValueError(
                    "OIDC requires HTTPS issuer, client ID and client secret"
                )
        billing = (
            self.stripe_secret_key,
            self.stripe_webhook_secret,
            self.stripe_price_pro,
            self.stripe_price_team,
        )
        if any(billing) and not all(billing):
            raise ValueError(
                "Billing requires test secret, webhook secret and both price IDs"
            )
        if self.stripe_secret_key and not self.stripe_secret_key.startswith("sk_test_"):
            raise ValueError("Only Stripe test secret keys are accepted")
        if self.stripe_webhook_secret and not self.stripe_webhook_secret.startswith(
            "whsec_"
        ):
            raise ValueError("Invalid Stripe webhook secret")
        if self.billing_enabled and (
            not self.stripe_price_pro.startswith("price_")
            or not self.stripe_price_team.startswith("price_")
            or self.stripe_price_pro == self.stripe_price_team
        ):
            raise ValueError("Distinct allowlisted Stripe prices are required")
        if (
            min(
                self.max_body_bytes,
                self.max_files,
                self.max_resources,
                self.max_jobs,
                self.workers,
                self.job_timeout_seconds,
                self.session_ttl_seconds,
                self.rate_limit,
                self.auth_rate_limit,
                self.demo_rate_limit,
            )
            < 1
        ):
            raise ValueError("Limits must be positive")
        if self.workers > self.max_jobs:
            raise ValueError("Workers cannot exceed job capacity")

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        production = env.get("BR_ENV") == "production"
        settings = cls(
            environment=env.get("BR_ENV", "development"),
            database_url=env.get(
                "BR_DATABASE_URL", "sqlite:///./.blastradius/server.db"
            ),
            data_dir=Path(env.get("BR_DATA_DIR", ".blastradius")),
            public_url=env.get("BR_PUBLIC_URL", "http://localhost:8000").rstrip("/"),
            session_secret=env.get(
                "BR_SESSION_SECRET", "" if production else secrets.token_urlsafe(48)
            ),
            auth_mode=env.get("BR_AUTH_MODE", "disabled"),
            oidc_issuer=env.get("BR_OIDC_ISSUER", ""),
            oidc_client_id=env.get("BR_OIDC_CLIENT_ID", ""),
            oidc_client_secret=env.get("BR_OIDC_CLIENT_SECRET", ""),
            stripe_secret_key=env.get("BR_STRIPE_SECRET_KEY", ""),
            stripe_webhook_secret=env.get("BR_STRIPE_WEBHOOK_SECRET", ""),
            stripe_price_pro=env.get("BR_STRIPE_PRICE_PRO", ""),
            stripe_price_team=env.get("BR_STRIPE_PRICE_TEAM", ""),
            max_body_bytes=int(env.get("BR_MAX_BODY_BYTES", "1048576")),
            max_files=int(env.get("BR_MAX_FILES", "30")),
            max_resources=int(env.get("BR_MAX_RESOURCES", "300")),
            max_jobs=int(env.get("BR_MAX_JOBS", "8")),
            workers=int(env.get("BR_WORKERS", "2")),
            job_timeout_seconds=int(env.get("BR_JOB_TIMEOUT", "30")),
            session_ttl_seconds=int(env.get("BR_SESSION_TTL", "28800")),
            rate_limit=int(env.get("BR_RATE_LIMIT", "180")),
            auth_rate_limit=int(env.get("BR_AUTH_RATE_LIMIT", "15")),
            demo_rate_limit=int(env.get("BR_DEMO_RATE_LIMIT", "60")),
            auto_migrate=env.get("BR_AUTO_MIGRATE", "false" if production else "true")
            == "true",
        )
        settings.validate()
        return settings
