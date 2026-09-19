PYTHON ?= python3.12
VENV ?= .venv
PY ?= $(VENV)/bin/python
NPM ?= npm
TRIVY ?= trivy
IMAGE ?= blastradius:local
DB_IMAGE ?= blastradius-postgres:local
AUDIT_DIR ?= .local/audit

.PHONY: help install install-core dev start legacy frontend test lint typecheck audit check docs integration-check migrate compose-up compose-down wheel image container-audit promotion-check secret-audit

help:
	@printf '%s\n' \
	  'make dev          Install and start the integrated local app (Python 3.12, Node 24)' \
	  'make install-core Install CLI, legacy demo and test/quality tools' \
	  'make legacy       Start the legacy bundled Streamlit demo' \
	  'make check        Tests, Python lint/types and local documentation links' \
	  'make frontend     npm ci, lint, typecheck, unit tests and production build' \
	  'make audit        Audit installed Python and locked frontend dependencies' \
	  'make migrate      Run the configured Alembic migration once' \
	  'make compose-up   Build/start the local PostgreSQL and app containers' \
	  'make wheel        Build and check all packaged server modules/migrations' \
	  'make container-audit  Record all image findings (does not approve promotion)' \
	  'make promotion-check  Block promotion on HIGH/CRITICAL vulnerabilities or secrets'

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
	$(NPM) --prefix web test
	$(NPM) --prefix web run build

dev: install
	$(MAKE) start

start: integration-check
	@test -f .env || { echo 'Copy .env.example to .env and configure the documented server settings.'; exit 2; }
	@set -a; . ./.env; set +a; $(PY) -m blastradius.server.migrate && exec $(PY) -m uvicorn blastradius.server.app:app --host 127.0.0.1 --port "$${BLASTRADIUS_PORT:-8000}" --workers 1 --no-access-log --no-proxy-headers

legacy: install-core
	$(PY) -m streamlit run app.py --server.address 127.0.0.1

test:
	$(PY) -m pytest
	$(PY) -m pytest -o addopts='' -q scripts/test_release_*.py

lint:
	$(PY) -m ruff check blastradius app.py scripts
	$(PY) -m ruff check --select E4,E7,E9,F scripts
	@if test -d blastradius/server; then $(PY) -m ruff check --select E4,E7,E9,F blastradius/server; fi

typecheck:
	$(PY) -m mypy --strict scripts
	@if test -d blastradius/server; then $(PY) -m mypy blastradius/server; fi
	$(PY) -m mypy blastradius/parser blastradius/graph blastradius/security app.py blastradius/session_storage.py

docs:
	$(PY) scripts/check_docs.py

check: test lint typecheck docs

audit:
	$(PY) -m pip_audit --skip-editable
	$(NPM) --prefix web audit --audit-level=moderate

wheel: integration-check
	$(PY) -m pip wheel . --no-deps --wheel-dir dist
	$(PY) scripts/check_integration.py --wheel

image:
	docker compose build app db

secret-audit:
	mkdir -p "$(AUDIT_DIR)"
	$(TRIVY) fs --scanners secret --exit-code 1 --format json --output "$(AUDIT_DIR)/secrets.json" .

container-audit:
	mkdir -p "$(AUDIT_DIR)"
	$(TRIVY) image --scanners vuln,secret --format json --output "$(AUDIT_DIR)/app.json" "$(IMAGE)"
	$(TRIVY) image --scanners vuln,secret --format json --output "$(AUDIT_DIR)/database.json" "$(DB_IMAGE)"
	$(TRIVY) convert --format sarif --output "$(AUDIT_DIR)/app.sarif" "$(AUDIT_DIR)/app.json"
	$(TRIVY) convert --format sarif --output "$(AUDIT_DIR)/database.sarif" "$(AUDIT_DIR)/database.json"
	$(TRIVY) version --format json > "$(AUDIT_DIR)/scanner.json"
	$(TRIVY) image --scanners secret --exit-code 1 "$(IMAGE)"
	$(TRIVY) image --scanners secret --exit-code 1 "$(DB_IMAGE)"

promotion-check:
	@status=0; \
	$(TRIVY) image --scanners vuln,secret --severity HIGH,CRITICAL --exit-code 1 "$(IMAGE)" || status=1; \
	$(TRIVY) image --scanners vuln,secret --severity HIGH,CRITICAL --exit-code 1 "$(DB_IMAGE)" || status=1; \
	exit $$status

migrate:
	@test -f .env || { echo 'Copy and configure .env first.'; exit 2; }
	@set -a; . ./.env; set +a; PATH="$(abspath $(VENV))/bin:$$PATH" sh scripts/container-entrypoint.sh migrate

compose-up:
	docker compose build app db
	docker compose up -d --wait db
	docker compose run --rm migrate
	docker compose up -d --wait app

compose-down:
	docker compose down
