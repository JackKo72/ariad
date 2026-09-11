.PHONY: doctor setup dev test e2e eval lint

doctor:
	@echo "Checking required tools..."
	@command -v python3 >/dev/null || (echo "python3 not found" && exit 1)
	@command -v node >/dev/null || (echo "node not found" && exit 1)
	@command -v npm >/dev/null || (echo "npm not found" && exit 1)
	@python3 --version
	@node --version
	@npm --version
	@test -d apps/api/.venv && echo "apps/api/.venv: OK" || echo "apps/api/.venv: missing (run 'make setup')"
	@test -d apps/web/node_modules && echo "apps/web/node_modules: OK" || echo "apps/web/node_modules: missing (run 'make setup')"
	@test -d node_modules && echo "root node_modules (playwright): OK" || echo "root node_modules: missing (run 'make setup')"

setup:
	python3 -m venv apps/api/.venv
	apps/api/.venv/bin/pip install --upgrade pip -q
	apps/api/.venv/bin/pip install -r apps/api/requirements-dev.txt -q
	npm install --prefix apps/web
	npm install

dev:
	@echo "Starting API on :8000 and web on :3000 (Ctrl+C to stop both)"
	@( \
	  trap 'kill 0' EXIT; \
	  ARIAD_DB_PATH=./data/ariad.db apps/api/.venv/bin/uvicorn app.main:app --app-dir apps/api --reload --port 8000 & \
	  npm run dev --prefix apps/web -- --port 3000 & \
	  wait \
	)

test:
	apps/api/.venv/bin/python -m pytest -q
	npm test --prefix apps/web

e2e:
	rm -f apps/api/data/e2e.db
	npx playwright test

eval:
	apps/api/.venv/bin/python tests/evals/run_eval.py

lint:
	apps/api/.venv/bin/ruff check apps/api
	npm run lint --prefix apps/web
	npm run typecheck --prefix apps/web
