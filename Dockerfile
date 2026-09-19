FROM node:22.23.2-bookworm-slim@sha256:48e4b67d85f87bd551df43704e24d252f56cc5f8e9718841aace50f19948f0f9 AS frontend
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run lint && npm run typecheck && npm run build

FROM python:3.12.14-slim-trixie@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9 AS python-build
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY pyproject.toml README.md ./
COPY blastradius/ ./blastradius/
RUN python -m venv /opt/venv \
    && /opt/venv/bin/python -m pip install "pip==26.2" \
    && /opt/venv/bin/python -m pip install ".[server]" \
    && /opt/venv/bin/python -m pip check \
    && /opt/venv/bin/python -m pip uninstall --yes pip

FROM python:3.12.14-slim-trixie@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9 AS runtime
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/home/blastradius
RUN /usr/local/bin/python -m pip uninstall --yes pip \
    && rm -rf /usr/local/lib/python3.12/ensurepip \
    && groupadd --gid 10001 blastradius \
    && useradd --uid 10001 --gid blastradius --create-home blastradius \
    && mkdir -p /app/.local \
    && chown blastradius:blastradius /app/.local
WORKDIR /app
COPY --from=python-build /opt/venv /opt/venv
COPY --from=frontend /build/web/dist ./web/dist
COPY --chown=blastradius:blastradius . .
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; from urllib.parse import urlsplit; request = urllib.request.Request('http://127.0.0.1:8000/health/ready', headers={'Host': urlsplit(os.environ.get('BR_PUBLIC_URL', 'http://localhost:8000')).netloc}); urllib.request.urlopen(request, timeout=3).close()"]
ENTRYPOINT ["sh", "/app/scripts/container-entrypoint.sh"]
CMD ["serve"]
