from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID


@dataclass(frozen=True)
class Settings:
    environment: str = "development"
    database_url: str = "sqlite:///./.blastradius/server.db"
    data_dir: Path = Path(".blastradius")
    static_dir: Path = Path("web/dist")
    public_url: str = "http://localhost:8000"
    session_secret: str = field(default_factory=lambda: secrets.token_urlsafe(48))
    auth_mode: str = "disabled"
    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    admin_enabled: bool = False
    web_admin_user_ids: tuple[str, ...] = ()
    github_app_id: int = 0
    github_app_slug: str = ""
    github_private_key_file: Path | None = field(default=None, repr=False)
    github_webhook_secret: str = field(default="", repr=False)
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
    def secure_cookies(self) -> bool:
        return self.production or urlsplit(self.public_url).scheme == "https"

    @property
    def billing_enabled(self) -> bool:
        return False

    @property
    def github_enabled(self) -> bool:
        return bool(
            self.github_app_id
            and self.github_app_slug
            and self.github_private_key_file
            and self.github_webhook_secret
        )

    def validate(self) -> None:
        if len(self.web_admin_user_ids) > 50 or any(
            str(UUID(value)) != value for value in self.web_admin_user_ids
        ):
            raise ValueError("BR_WEB_ADMIN_USER_IDS requires at most 50 canonical user UUIDs")
        if self.github_app_id < 0:
            raise ValueError("BR_GITHUB_APP_ID must be nonnegative (0 disables integration)")
        if self.github_webhook_secret and len(self.github_webhook_secret) < 32:
            raise ValueError("GitHub webhook secret must contain at least 32 characters")
        if self.github_app_slug and (
            len(self.github_app_slug) > 100
            or not all(c in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in self.github_app_slug)
        ):
            raise ValueError("Invalid GitHub App slug")
        if self.environment not in {"development", "test", "preview", "production"}:
            raise ValueError("BR_ENV must be development, test, preview or production")
        if self.auth_mode not in {"disabled", "demo", "oidc"}:
            raise ValueError("BR_AUTH_MODE must be disabled, demo or oidc")
        if len(self.session_secret) < 32:
            raise ValueError("Session secret must contain at least 32 characters")
        if not self.database_url.startswith(("sqlite:///", "postgresql+psycopg://")):
            raise ValueError("Use SQLite or PostgreSQL with psycopg")
        url = urlsplit(self.public_url)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.path not in {"", "/"}
            or url.query
            or url.fragment
            or url.username is not None
            or "*" in url.netloc
            or "\\" in self.public_url
            or any(c.isspace() for c in self.public_url)
        ):
            raise ValueError("BR_PUBLIC_URL must be an origin without credentials or path")
        if url.port == 0:
            raise ValueError("BR_PUBLIC_URL must use a valid port")
        if self.environment in {"preview", "production"} and url.scheme != "https":
            raise ValueError("Preview and production require an explicit HTTPS BR_PUBLIC_URL")
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
                raise ValueError("OIDC requires HTTPS issuer, client ID and client secret")
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
            database_url=env.get("BR_DATABASE_URL", "sqlite:///./.blastradius/server.db"),
            data_dir=Path(env.get("BR_DATA_DIR", ".blastradius")),
            static_dir=Path(env.get("BR_STATIC_DIR", "web/dist")),
            public_url=env.get(
                "BR_PUBLIC_URL",
                "" if env.get("BR_ENV") in {"preview", "production"} else "http://localhost:8000",
            ).rstrip("/"),
            session_secret=env.get(
                "BR_SESSION_SECRET", "" if production else secrets.token_urlsafe(48)
            ),
            auth_mode=env.get("BR_AUTH_MODE", "disabled"),
            oidc_issuer=env.get("BR_OIDC_ISSUER", ""),
            oidc_client_id=env.get("BR_OIDC_CLIENT_ID", ""),
            oidc_client_secret=env.get("BR_OIDC_CLIENT_SECRET", ""),
            admin_enabled=env.get("BR_ADMIN_ENABLED") == "true",
            web_admin_user_ids=tuple(
                value.strip()
                for value in env.get("BR_WEB_ADMIN_USER_IDS", "").split(",")
                if value.strip()
            ),
            github_app_id=int(env.get("BR_GITHUB_APP_ID", "0")),
            github_app_slug=env.get("BR_GITHUB_APP_SLUG", ""),
            github_private_key_file=(
                Path(env["BR_GITHUB_PRIVATE_KEY_FILE"])
                if env.get("BR_GITHUB_PRIVATE_KEY_FILE")
                else None
            ),
            github_webhook_secret=env.get("BR_GITHUB_WEBHOOK_SECRET", ""),
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
            auto_migrate=env.get("BR_AUTO_MIGRATE", "false" if production else "true") == "true",
        )
        settings.validate()
        return settings
