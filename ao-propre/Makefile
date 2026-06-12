.PHONY: init run veille clean

VENV = .venv
PYTHON = $(VENV)/bin/python
PIP = $(VENV)/bin/pip
APP_DIR = ao-propre

init:
	@echo "==> Création de l'environnement virtuel..."
	python3 -m venv $(VENV)
	@echo "==> Installation des dépendances..."
	$(PIP) install --upgrade pip -q
	$(PIP) install -r requirements.txt -q
	@echo "==> Copie du fichier d'environnement..."
	@test -f .env || cp .env.example .env
	@echo "==> Initialisation de la base de données..."
	$(PYTHON) -c "from app.database import init_db; init_db()"
	@echo ""
	@echo "✓ Initialisation terminée."
	@echo "  Éditez .env pour renseigner votre ANTHROPIC_API_KEY."
	@echo "  Lancez ensuite : make run"

run:
	@echo "==> Démarrage du serveur AO-Propre..."
	$(VENV)/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

veille:
	@echo "==> Lancement de la veille BOAMP..."
	$(PYTHON) -m app.veille

clean:
	@echo "==> Suppression de l'environnement virtuel et de la base..."
	rm -rf $(VENV) aopropre.db
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
