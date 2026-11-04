.PHONY: setup voice certs run test lint check smoke

VENV ?= .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

setup:            ## create venv and install backend + piper + dev deps
	python3 -m venv $(VENV)
	$(PIP) install -U pip
	$(PIP) install -e "backend[piper,dev]"
	@test -f .env || cp .env.example .env
	@echo "Done. Next: make voice && make check && make run"

voice:            ## download the default German Piper voice (thorsten-high)
	bash scripts/get_voice.sh

certs:            ## create local CA + server cert for HTTPS on the LAN
	bash scripts/make_certs.sh

run:              ## start Kerstin on 127.0.0.1:8770 (see .env)
	cd backend && ../$(PY) -m kerstin

test:             ## run unit tests (no GPU / network needed)
	cd backend && KERSTIN_TTS_BACKEND=none ../$(PY) -m pytest -q

lint:
	$(VENV)/bin/ruff check backend scripts

check:            ## check Ollama, STT server, voice file, GPU temperature
	bash scripts/check_env.sh

smoke:            ## run the headless end-to-end test (server must be running)
	$(PY) scripts/smoke_test.py
