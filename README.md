# Éclats d'Éther

RPG d'action en ligne en 3D (futur MMORPG), style anime fantasy, fait avec **Godot 4**.

## Lancer le jeu
1. Ouvre Godot 4 (version 4.5 ou plus récente, version standard, pas « .NET »).
2. **Importer** → choisis le fichier `project.godot` de ce dossier.
3. Appuie sur **F5** (ou le bouton ▶ en haut à droite).

## Lancer le serveur dédié
```
godot --headless --path . -- --server
```

## Lancer les vérifications automatiques
```
godot --headless --path . --import
godot --headless --path . -s res://tests/run_checks.gd
```

Voir `CLAUDE.md` pour l'architecture et l'état d'avancement, et `ASSETS.md` pour les graphismes à trouver.
