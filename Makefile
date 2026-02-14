.PHONY: venv install migrate test

venv:
	python3.11 -m venv .venv
	. .venv/bin/activate

install:
	. .venv/bin/activate && pip install -r requirements.txt
	. .venv/bin/activate && pip install -e "./client[pretty]"

migrate:
	. .venv/bin/activate && DATABASE_URL=sqlite:///./app.db alembic upgrade head

test:
	. .venv/bin/activate && pytest -q
	. .venv/bin/activate && pytest -q client/tests
