PY  = backend/venv/bin/python
PIP = backend/venv/bin/pip

.PHONY: install backend frontend run test sample validate creation-gate help

help:
	@echo "Targets:"
	@echo "  make install        Create backend venv + install deps; npm install frontend"
	@echo "  make backend        Run the API (uvicorn) on :8000"
	@echo "  make frontend       Run the React dev server on :3000"
	@echo "  make run            Run backend + frontend via docker compose"
	@echo "  make test           Run backend (pytest) and frontend tests"
	@echo "  make sample         Run the synthetic end-to-end reconcile"
	@echo "  make validate FILE=path/to/contract.yaml   Validate a contract YAML"
	@echo "  make creation-gate  Run CI creation CLI gate (op_id flow)"

install:
	python3 -m venv backend/venv
	$(PIP) install --upgrade pip
	$(PIP) install -r backend/requirements.txt
	cd frontend && npm install

backend:
	cd backend && venv/bin/uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

frontend:
	cd frontend && npm start

run:
	docker compose up --build

test:
	cd backend && venv/bin/pytest -q
	cd frontend && CI=true npm test

sample:
	cd backend && venv/bin/python scripts/test_run.py

validate:
	@test -n "$(FILE)" || (echo "usage: make validate FILE=path/to/contract.yaml" && exit 2)
	$(PY) backend/cli.py validate-contract --file $(FILE)

creation-gate:
	backend/scripts/ci_creation_gate.sh
