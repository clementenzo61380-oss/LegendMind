# CLAUDE.md — Éclats d'Éther

> À relire au début de chaque session. Mettre à jour à la fin de chaque étape.

## Vision
RPG d'action en ligne en 3D, qui deviendra un MMORPG. Style **anime fantasy** coloré et lumineux
(cel-shading, contours noirs fins, bloom, particules). Pas de réalisme.
Combat **basé sur le skill** (esquive, parade, lecture des attaques annoncées), déplacements acrobatiques
(double saut, escalade, course sur les murs), poids de l'équipement, stats libres (niveau max 99),
compétences qui évoluent à l'usage, **monstres uniques** qui s'adaptent au style des joueurs.
Le cahier des charges complet a été fourni dans le premier message de la session
(sections 1 à 5) : le reprendre en référence pour chaque étape.

Nom provisoire : **Éclats d'Éther** (rappelle les fragments des monstres uniques).
Règle de création : aucun nom, personnage, lieu ou design repris d'une œuvre existante
(en particulier Shangri-La Frontier).

## Règles de travail
- Proposer un plan court, attendre la validation, puis coder.
- Petites étapes testables ; expliquer comment tester ; un commit par étape qui marche.
- Expliquer simplement (le porteur du projet n'est pas développeur de jeux pro).
- Demander avant tout choix important ou difficile à défaire.
- Pas de modèles 3D codés : formes simples + tenir `ASSETS.md` à jour.
- Toutes les valeurs de réglage dans `data/` (JSON), jamais en dur dans le code.

## Choix techniques
- **Godot 4.7** (version utilisée par le porteur du projet), **GDScript**, rendu Forward+.
- Multijoueur intégré de Godot, **serveur qui fait foi** (les joueurs n'envoient que leurs actions).
- Même projet lancé en **client** ou en **serveur dédié** (`core/boot.gd`).
- **Secrets côté serveur uniquement** : `server/` et `data/server_only/` sont exclus des builds joueur
  (`export_presets.cfg`). Le client ne charge jamais ces dossiers (vérifié par `tests/run_checks.gd`).
- Textes via le système de traduction de Godot (`i18n/strings.csv`, clés en MAJUSCULES, `tr("CLE")`).
  Français par défaut, anglais prêt.
- Touches définies par **position physique** (ZQSD en AZERTY = WASD en QWERTY).

## Architecture
```
core/        démarrage (boot), cycle jour/nuit — commun
client/      ce qui n'existe que chez le joueur (caméra, interface, effets)
server/      simulation qui fait foi, secrets — JAMAIS livré au joueur
  world/region_host.gd   une instance = une région simulée (futur découpage par machine)
shared/      code commun client/serveur (chargement des données, futures formules de stats)
rendering/   shader toon, contour, ciel, environnement global
data/        fichiers de réglage JSON
  world/       liste des régions, réglages du temps
  regions/<id>/palette.json   palette de couleurs de chaque région
  server_only/ configuration et secrets du serveur — JAMAIS livré
world/regions/<id>/   scènes d'une région côté joueur
i18n/        traductions
tests/       vérifications automatiques (sans fenêtre)
```

### Rendu
- `rendering/toon.gdshader` : ombres en 2 ou 3 niveaux nets, teinte d'ombre colorée,
  reflet tranché, liseré lumineux (rim). Ce qui est très lumineux (émission > 1) déclenche le bloom.
- `rendering/outline.gdshader` : contour par coque inversée, épaisseur constante en pixels.
  Limite connue : sur les cubes (arêtes vives), le contour peut avoir de petits trous aux coins ;
  les vrais modèles auront des normales lissées pour le contour.
- `rendering/toon_material.gd` : `ToonMaterial.make(couleur, options)` — à utiliser pour TOUT objet.
- `rendering/environment_builder.gd` : bloom, brouillard, lumière ambiante, couleurs.
- `rendering/sky_toon.gdshader` + `core/day_night.gd` : ciel stylisé, soleil/lune, étoiles, nuages,
  couleurs selon l'heure et la palette de la région. L'heure sera donnée par le serveur à l'étape 4.

## Commandes
- Jouer : ouvrir le projet dans Godot, F5.
- Serveur dédié : `godot --headless --path . -- --server`
  (option future : `--regions=plains_dawn` pour ne simuler que certaines régions).
- Tests : `godot --headless --path . --import` (une fois) puis
  `godot --headless --path . -s res://tests/run_checks.gd`

## État d'avancement
- [~] **Étape 1 — Base du projet** (codée, en attente du test visuel par le porteur du projet) : structure, shader toon + contour, environnement (bloom, brouillard,
  ciel, jour/nuit), zone de test des Plaines de l'Aube (formes simples, parcours d'acrobaties prévu
  pour l'étape 2), mode serveur dédié, traductions, tests automatiques.
  - Premier test (Godot 4.7) : le projet se lance sans erreur, ciel et nuages OK, mais tout était
    surexposé (éclairage du shader toon ×π² trop fort) → corrigé : LIGHT_COLOR / PI, comme Godot.
  - Leçon : dans light(), LIGHT_COLOR contient déjà le facteur π ; toujours diviser par PI.
- [ ] Étape 2 — Combat solo
- [ ] Étapes 3 à 10 (voir cahier des charges)

## Prochaine étape
**Étape 2 — Combat solo** : personnage à la 3ᵉ personne (caméra, déplacement, esquive avec
invincibilité, parade, attaques légère/lourde, endurance, double saut, escalade, course sur les murs)
contre un monstre de test qui annonce ses attaques. Le parcours `ParkourTest` de la zone de test
est déjà en place pour tester les acrobaties.
