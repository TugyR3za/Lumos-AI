.PHONY: install run cli reindex test lint format

install:
	python -m pip install -e ".[dev]"

run:
	python -m lumos

cli:
	python -m lumos cli

reindex:
	python -m lumos reindex

test:
	pytest -q

lint:
	ruff check .

format:
	ruff format .
