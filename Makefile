.PHONY: setup voice certs run test test-js lint check smoke bench persona-eval feedback-eval hint-eval exam-eval score-eval

VENV ?= .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
BENCH_ARGS ?=
EVAL_ARGS ?=
FEEDBACK_ARGS ?=
HINT_ARGS ?=
EXAM_ARGS ?=
SCORE_ARGS ?=

setup:            ## create venv and install backend + piper + dev deps
	python3 -m venv $(VENV)
	$(PIP) install -U pip
	$(PIP) install -e "backend[piper,dev]"
	@test -f .env || cp .env.example .env
	@echo "Done. Next: make voice && make check && make run"

voice:            ## download the default German Piper voice (thorsten-medium; `bash scripts/get_voice.sh high` for high)
	bash scripts/get_voice.sh

certs:            ## create local CA + server cert for HTTPS on the LAN (CERTS_ARGS="--dns host.fritz.box")
	bash scripts/make_certs.sh $(CERTS_ARGS)

run:              ## start Kerstin on 127.0.0.1:8770 (see .env)
	cd backend && ../$(PY) -m kerstin

test:             ## run unit tests (no GPU / network needed)
	cd backend && KERSTIN_TTS_BACKEND=none ../$(PY) -m pytest -q
	@if command -v node >/dev/null 2>&1; then node --test frontend/tests/*.test.js; else echo "skip JS tests (no node)"; fi

test-js:          ## frontend unit tests (node --test, no deps)
	node --test frontend/tests/*.test.js

lint:
	$(VENV)/bin/ruff check backend scripts

check:            ## check Ollama, STT server, voice file, GPU temperature
	bash scripts/check_env.sh

smoke:            ## run the headless end-to-end test (server must be running)
	$(PY) scripts/smoke_test.py

bench:            ## latency baseline (server must be running)
	$(PY) scripts/latency_bench.py $(BENCH_ARGS)

persona-eval:     ## scripted text-only persona eval (30 turns; needs Ollama)
	$(PY) scripts/persona_eval.py $(EVAL_ARGS)

feedback-eval:    ## feedback quality eval (5 cases × 2 languages; needs Ollama)
	$(PY) scripts/feedback_eval.py $(FEEDBACK_ARGS)

hint-eval:        ## hint quality eval (20 hold-out cases; needs Ollama)
	$(PY) scripts/hint_eval.py $(HINT_ARGS)

exam-eval:        ## B2 exam engine eval (both presets; needs Ollama)
	$(PY) scripts/exam_eval.py $(EXAM_ARGS)

score-eval:      ## exam rubric calibration eval (needs Ollama); hold-out: make score-eval SCORE_ARGS="--cases scripts/score_holdout.json"
	$(PY) scripts/score_eval.py $(SCORE_ARGS)
