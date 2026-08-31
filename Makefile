.PHONY: setup test run-web fetch-all backfill lint
PY ?= python

setup:
	$(PY) -m venv .venv
	.venv/bin/pip install -U pip
	.venv/bin/pip install -r requirements.txt

test:
	$(PY) -m pytest -q

run-web:
	$(PY) -m uvicorn web.app:app --reload --port 8000

fetch-all:
	$(PY) -m fetchers.calendar_skeleton
	$(PY) -m fetchers.ff_sync
	$(PY) -m fetchers.fred_actuals
	$(PY) -m fetchers.prices_daily
	$(PY) -m fetchers.reminders

backfill:
	$(PY) -m fetchers.prices_daily --backfill-years 10
