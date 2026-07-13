.PHONY: install run cli reindex test lint format eval eval-answers

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

eval:
	python -m evals.run_eval

eval-answers:
	python -m evals.run_eval --answers
