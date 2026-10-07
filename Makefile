.PHONY: doctor setup dev test e2e eval lint sample-audio vital-signs-audio test-provider-audio benchmark-audio diagnose-asr compare-asr-accuracy detect-asr-hardware compare-asr-engines check-faster-whisper-accuracy parallel-asr-diarization parallel-asr-diarization-mp compare-diarization-engines

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

# tasks/06_ASR_OUTPUT_VERIFICATION.md leading-keyword-anchor research: a
# separate synthetic fixture (not sample_consultation) covering varied
# vital-sign dictation patterns (BP, weight, glucose, pulse, two-vitals-
# one-sentence, a decimal temperature). Regenerates tests/fixtures/audio/
# vital_signs_dictation.wav + .transcript.json. Run compare-asr-accuracy
# against it on real hardware with AUDIO=.../vital_signs_dictation.wav
# GROUND_TRUTH=.../vital_signs_dictation.transcript.json.
vital-signs-audio:
	python3 scripts/generate_vital_signs_fixture.py

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
	  if [ -f apps/api/.env.local ]; then ENV_FILE_ARGS="--env-file apps/api/.env.local"; else ENV_FILE_ARGS=""; fi; \
	  ARIAD_DB_PATH=./apps/api/data/ariad.db ARIAD_AUDIO_DIR=./apps/api/data/audio \
	  ARIAD_SHERPA_MODELS_DIR=./apps/api/models \
	    apps/api/.venv/bin/uvicorn app.main:app --app-dir apps/api --reload --port 8000 $$ENV_FILE_ARGS & \
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
	apps/api/.venv/bin/python scripts/eval_clinical_enrichment.py

lint:
	apps/api/.venv/bin/ruff check apps/api scripts
	npm run lint --prefix apps/web
	npm run typecheck --prefix apps/web

# Live smoke test against real providers -- NEVER part of `make test`/`make
# e2e`, and may incur real OpenAI cost if OPENAI_API_KEY is set (asks for
# confirmation before that step). Requires apps/api/.env.local with
# ARIAD_MODE=provider and downloaded sherpa-onnx models (see README.md).
# ARIAD_SHERPA_MODELS_DIR is set here (not left to .env.local) for the same
# reason `dev` sets it: these scripts run with cwd = repo root, so the path
# must be repo-root-relative, matching `dev`'s convention exactly.
test-provider-audio:
	ARIAD_SHERPA_MODELS_DIR=./apps/api/models apps/api/.venv/bin/python scripts/test_provider_audio.py

# tasks/03_SPEAKER_MERGE_AND_LATENCY.md Phase 1 baseline/benchmark. Same
# cost/scope rules as test-provider-audio above -- opt-in only, never part
# of `make test`/`make e2e`. Usage: make benchmark-audio AUDIO=path RUNS=3
benchmark-audio:
	ARIAD_SHERPA_MODELS_DIR=./apps/api/models apps/api/.venv/bin/python scripts/benchmark_audio.py

# Per-turn diarize/auto-decode/ko-fallback breakdown on one warm ASR run,
# separate from benchmark-audio above. Free (local ASR only). Usage:
# make diagnose-asr AUDIO=path
diagnose-asr:
	ARIAD_SHERPA_MODELS_DIR=./apps/api/models apps/api/.venv/bin/python scripts/diagnose_asr_stages.py

# tasks/03_SPEAKER_MERGE_AND_LATENCY.md item 4: compares ko_mode candidates
# (default: auto_then_ko,ko_only) on sample_consultation's ground truth --
# medication name/dose, negation, date, speaker assignment -- not just RTF.
# Same cost/scope rules as the commands above: opt-in, free, never part of
# `make test`/`make e2e`. Usage: make compare-asr-accuracy [KO_MODES=...]
compare-asr-accuracy:
	ARIAD_SHERPA_MODELS_DIR=./apps/api/models apps/api/.venv/bin/python scripts/compare_asr_accuracy.py

# tasks/05_ASR_HARDWARE_SPEEDUP.md: CPU/GPU/model-quantization/faster-whisper
# capability report. No real audio or models needed -- seconds, always safe
# to run. Usage: make detect-asr-hardware
detect-asr-hardware:
	apps/api/.venv/bin/python scripts/detect_asr_hardware.py

# tasks/05_ASR_HARDWARE_SPEEDUP.md: fair same-machine comparison of ASR
# engine/provider candidates (sherpa-onnx Whisper cpu/cuda, sherpa-onnx
# SenseVoice cpu/cuda, faster-whisper cpu-int8/cuda-fp16), with concurrent
# GPU/CPU utilization sampling. Skips whatever isn't installed/available on
# this machine, with a clear reason. Opt-in, free (no OpenAI call), never
# part of `make test`/`make e2e`. Usage:
# make compare-asr-engines AUDIO=path [ENGINES=sherpa_whisper_cpu,...]
compare-asr-engines:
	ARIAD_SHERPA_MODELS_DIR=./apps/api/models apps/api/.venv/bin/python scripts/compare_asr_engines.py

# tasks/05_ASR_HARDWARE_SPEEDUP.md: speed alone must not decide the ASR
# engine. Runs faster-whisper against sample_consultation.wav's existing
# ground truth (medication name/dose/negation/date) and compares against
# `make compare-asr-accuracy`'s sherpa-onnx numbers on the same anchors.
# Requires faster-whisper (pip install faster-whisper). Synthetic fixture
# only, opt-in, never part of `make test`/`make e2e`.
check-faster-whisper-accuracy:
	apps/api/.venv/bin/python scripts/check_faster_whisper_accuracy.py

# tasks/05_ASR_HARDWARE_SPEEDUP.md conclusion 2's untested hypothesis:
# running ASR (faster-whisper, GPU) and diarization (sherpa-onnx, CPU)
# concurrently instead of sequentially should get wall time closer to
# max(asr, diarize) instead of their sum. Actually tries it (threading)
# and reports whether real overlap happens, rather than assuming it does.
# Requires faster-whisper. Usage: make parallel-asr-diarization AUDIO=path
parallel-asr-diarization:
	ARIAD_SHERPA_MODELS_DIR=./apps/api/models apps/api/.venv/bin/python scripts/parallel_asr_diarization.py

# Real measurement on make parallel-asr-diarization showed threads give
# ~1.00x speedup (the GIL appears to serialize sherpa-onnx's diarization
# call against faster-whisper's progress). This retries with separate OS
# processes (no shared GIL) instead. Usage:
# make parallel-asr-diarization-mp AUDIO=path
parallel-asr-diarization-mp:
	ARIAD_SHERPA_MODELS_DIR=./apps/api/models apps/api/.venv/bin/python scripts/parallel_asr_diarization_mp.py

# tasks/05_ASR_HARDWARE_SPEEDUP.md Path C: compares the sherpa-onnx
# diarization baseline (already measured as NOT accelerated by
# provider=cuda) against pyannote.audio (PyTorch-based -- may get real CUDA
# support). Requires pyannote.audio + a HuggingFace token with the gated
# models' license accepted -- see scripts/compare_diarization_engines.py's
# own docstring for exact steps. Opt-in, free (no OpenAI call), never part
# of `make test`/`make e2e`. Usage:
# make compare-diarization-engines AUDIO=path [ENGINES=sherpa_cpu,...]
compare-diarization-engines:
	ARIAD_SHERPA_MODELS_DIR=./apps/api/models apps/api/.venv/bin/python scripts/compare_diarization_engines.py
