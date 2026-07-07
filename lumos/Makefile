.PHONY: install run test lint format

install:
	python -m pip install -e ".[dev]"

run:
	python -m lumos

test:
	pytest -q

lint:
	ruff check .

format:
	ruff format .
