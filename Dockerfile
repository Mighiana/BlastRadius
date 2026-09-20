FROM postgres:16.15-trixie@sha256:a3b7f434b2dc57ce85a67e171163eb8ab1a1ebcb39d27484661f26b1dfbe30d6 AS database
RUN apt-get purge --yes --auto-remove gnupg gnupg-l10n gpg gpg-agent gpgconf gpgsm dirmngr \
    && rm /usr/local/bin/gosu /etc/ssl/private/ssl-cert-snakeoil.key /etc/ssl/certs/ssl-cert-snakeoil.pem \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/*
USER postgres

FROM node:24.19.0-bookworm-slim@sha256:a9f5f7c91a432850b2a8a7797adf5eadb6c733ceed61167806cee7ea7fbc29df AS frontend
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run lint && npm run typecheck && npm run build

FROM python:3.12.14-alpine3.24@sha256:c4634f578a412db396771b61b064c6e546c9d6414c7fb5b1b05d5871f1885f7b AS python-build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY pyproject.toml README.md ./
COPY blastradius/ ./blastradius/
RUN python -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install "pip==26.2" \
    && /opt/venv/bin/python -m pip install ".[server]" \
    && /opt/venv/bin/python -m pip check \
    && /opt/venv/bin/python -m pip uninstall --yes pip

FROM python:3.12.14-alpine3.24@sha256:c4634f578a412db396771b61b064c6e546c9d6414c7fb5b1b05d5871f1885f7b AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/home/blastradius \
    BR_ENV=production \
    BR_AUTO_MIGRATE=false \
    BR_DATA_DIR=/app/.local \
    BR_STATIC_DIR=/app/web/dist \
    BLASTRADIUS_ALEMBIC_CONFIG=/app/alembic.ini
RUN /usr/local/bin/python -m pip uninstall --yes pip \
    && rm -rf /usr/local/lib/python3.12/ensurepip /root/.cache \
        /usr/local/include/python3.12 /usr/local/lib/python3.12/config-* \
    && addgroup -g 10001 blastradius \
    && adduser -D -u 10001 -G blastradius blastradius \
    && mkdir -p /app/.local \
    && chown blastradius:blastradius /app/.local
WORKDIR /app
COPY --from=python-build /opt/venv /opt/venv
COPY --from=frontend /build/web/dist ./web/dist
COPY alembic.ini ./
COPY scripts/container-entrypoint.sh ./scripts/container-entrypoint.sh
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; from urllib.parse import urlsplit; request = urllib.request.Request('http://127.0.0.1:8000/health/ready', headers={'Host': urlsplit(os.environ.get('BR_PUBLIC_URL', 'http://localhost:8000')).netloc}); urllib.request.urlopen(request, timeout=3).close()"]
ENTRYPOINT ["sh", "/app/scripts/container-entrypoint.sh"]
CMD ["serve"]
