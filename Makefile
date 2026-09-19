PYTHON ?= python3.12
VENV ?= .venv
PY ?= $(VENV)/bin/python
NPM ?= npm

.PHONY: help install install-core dev start legacy frontend test lint typecheck audit check docs integration-check migrate compose-up compose-down

help:
	@printf '%s\n' \
	  'make dev          Install and start the integrated local app (Python 3.12, Node 22)' \
	  'make install-core Install CLI, legacy demo and test/quality tools' \
	  'make legacy       Start the legacy bundled Streamlit demo' \
	  'make check        Tests, Python lint/types and local documentation links' \
	  'make frontend     npm ci, lint, typecheck and production build' \
	  'make audit        Audit installed Python and locked frontend dependencies' \
	  'make migrate      Run the configured Alembic migration once' \
	  'make compose-up   Build/start the local PostgreSQL and app containers'

$(PY):
	$(PYTHON) -m venv "$(VENV)"

install-core: $(PY)
	$(PY) -m pip install ".[ui,dev]" -r requirements.txt -r requirements-dev.txt

integration-check: $(PY)
	$(PY) scripts/check_integration.py

install: integration-check
	$(PY) -m pip install ".[server,ui,dev]" -r requirements.txt -r requirements-dev.txt
	$(MAKE) frontend

frontend:
	$(NPM) --prefix web ci
	$(NPM) --prefix web run lint
	$(NPM) --prefix web run typecheck
	$(NPM) --prefix web run build

dev: install
	$(MAKE) start

start: integration-check
	@test -f .env || { echo 'Copy .env.example to .env and configure the documented server settings.'; exit 2; }
	@set -a; . ./.env; set +a; exec $(PY) -m uvicorn blastradius.server.app:app --host 127.0.0.1 --port "$${BLASTRADIUS_PORT:-8000}"

legacy: install-core
	$(PY) -m streamlit run app.py --server.address 127.0.0.1

test:
	$(PY) -m pytest
	$(PY) -m pytest -o addopts='' -q scripts/test_release_tooling.py

lint:
	$(PY) -m ruff check blastradius app.py scripts
	$(PY) -m ruff check --select E4,E7,E9,F scripts
	@if test -d blastradius/server; then $(PY) -m ruff check --select E4,E7,E9,F blastradius/server; fi

typecheck:
	$(PY) -m mypy scripts
	@if test -d blastradius/server; then $(PY) -m mypy blastradius/server; fi

docs:
	$(PY) scripts/check_docs.py

check: test lint typecheck docs

audit:
	$(PY) -m pip_audit --skip-editable
	$(NPM) --prefix web audit --audit-level=moderate

migrate:
	@test -f .env || { echo 'Copy and configure .env first.'; exit 2; }
	@set -a; . ./.env; set +a; PATH="$(abspath $(VENV))/bin:$$PATH" sh scripts/container-entrypoint.sh migrate

compose-up:
	docker compose up --build -d --wait

compose-down:
	docker compose down
