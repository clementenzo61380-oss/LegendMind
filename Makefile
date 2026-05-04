.PHONY: install install-dev test run docker-up docker-down

install:
	pip install -r requirements.txt

install-dev:
	pip install -r requirements-dev.txt

test:
	pytest tests/ -q

run:
	python main.py

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down
