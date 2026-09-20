.PHONY: doctor setup dev test e2e eval lint sample-audio test-provider-audio

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
	@command -v ffmpeg >/dev/null && echo "ffmpeg: OK ($$(ffmpeg -version | head -1))" || echo "ffmpeg: missing. Install with: sudo apt-get install -y ffmpeg"
	@command -v ffprobe >/dev/null && echo "ffprobe: OK" || echo "ffprobe: missing. Install with: sudo apt-get install -y ffmpeg"
	@command -v espeak-ng >/dev/null && echo "espeak-ng (offline TTS, optional): OK" || echo "espeak-ng (offline TTS, optional, for 'make sample-audio'): missing. Install with: sudo apt-get install -y espeak-ng"

sample-audio:
	python3 scripts/generate_sample_audio.py

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
	  ARIAD_DB_PATH=./apps/api/data/ariad.db ARIAD_AUDIO_DIR=./apps/api/data/audio \
	  ARIAD_SHERPA_MODELS_DIR=./apps/api/models \
	    apps/api/.venv/bin/uvicorn app.main:app --app-dir apps/api --reload --port 8000 & \
	  npm run dev --prefix apps/web -- --port 3000 & \
	  wait \
	)

test:
	apps/api/.venv/bin/python -m pytest -q
	npm test --prefix apps/web

e2e:
	rm -f apps/api/data/e2e.db
	rm -rf apps/api/data/e2e_audio
	npx playwright test

eval:
	apps/api/.venv/bin/python tests/evals/run_eval.py

lint:
	apps/api/.venv/bin/ruff check apps/api scripts
	npm run lint --prefix apps/web
	npm run typecheck --prefix apps/web

# Live smoke test against real providers -- NEVER part of `make test`/`make
# e2e`, and may incur real OpenAI cost if OPENAI_API_KEY is set (asks for
# confirmation before that step). Requires apps/api/.env.local with
# ARIAD_MODE=provider and downloaded sherpa-onnx models (see README.md).
test-provider-audio:
	apps/api/.venv/bin/python scripts/test_provider_audio.py
