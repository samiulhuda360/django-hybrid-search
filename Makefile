PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: setup demo test lint eval

setup:  ## Create the virtual environment and install everything
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install -r requirements-dev.txt

demo:  ## Crawl the bundled docs site, build the index and serve http://127.0.0.1:8000/
	$(BIN)/python manage.py demo

test:
	$(BIN)/pytest

lint:
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .
	$(BIN)/mypy .

eval:  ## Needs an index: run `make demo` (or manage.py demo --no-serve) first
	$(BIN)/python manage.py evaluate
