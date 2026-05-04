# Commandes Discord

Permissions indiquées pour la guild ; les DM d'alertes suivent `user_preferences`.

## Tiers Legend (Avril 2026 — refonte Ranked Mode Supercell)

Supercell a découpé Legend League en 3 tiers, **détectés par rang** (pas par
trophées). Le bot traite chaque tier différemment :

| Tier | Population | Format | Batailles | Polling | `/ping` |
|------|------------|--------|-----------|---------|---------|
| 🥇 Legend I | top 12 500 mondial | 4-week tournament | 8 / jour, reset 22h UTC | toutes les **3 min** | DM par défense + recap auto |
| 🥈 Legend II | rangs 12 501 – 62 500 | weekly tournament | **30 / semaine** | toutes les **30 min** | recap hebdo dimanche 22h UTC |
| 🥉 Legend III | reste des Legend | weekly tournament | **24 / semaine** | toutes les **30 min** | recap hebdo dimanche 22h UTC |

> **Pourquoi déclaratif ?** L'API publique CoC n'expose `currentSeason.rank`
> que pour le **top 200 mondial**. Pour tout le reste (~99 % des joueurs
> Legend), impossible de deviner le tier ⇒ on demande à l'utilisateur de
> le déclarer au `/setup` (Select Légende I / II / III). Modifiable plus
> tard via `/tier`.

## Plans

| Plan | Comptes liés | `/ping` (DM défense) | Trial 7 j | Source de vérité |
|------|--------------|----------------------|-----------|------------------|
| Free | 1 max | 50 / mois calendaire UTC | n/a | `subscriptions.plan='free'` |
| Trial | 3 max | illimité | activé auto à `/setup` | `subscriptions.plan='trial'` |
| Premium | 3 max | illimité | n/a (Stripe) | `subscriptions.plan='premium'` |

## Utilisateur

| Commande | Free | Premium / Trial | Description |
|----------|------|-----------------|-------------|
| `/setup tag:#TAG` | ✅ | ✅ | Lie un compte Legend (vérifie l’id ligue Légende, ex. `105000036`). Active l'essai 7 j si pas déjà consommé. **Demande ensuite ton tier (Legend I/II/III)** via Select. |
| `/tier [tag:#TAG]` | ✅ | ✅ | Met à jour le tier déclaré pour un compte (Legend I → II → III). |
| `/premium` | ✅ | ✅ | Active l'essai 7 j si non consommé, sinon ouvre Stripe Checkout. |
| `/accounts` | ✅ (1 max) | ✅ (3 max) | Liste les comptes liés + tier + boutons ✖ pour retirer. |
| `/ping actif:` | ✅ (50/mois, **Legend I uniquement**) | ✅ illimité | Active/désactive le DM auto à chaque défense (Legend I). Le DM affiche les trophées perdus + une **estimation des étoiles et de la destruction** (déduite du delta trophy ; l'API CoC publique n'expose pas le détail des défenses). En Legend II/III : recap hebdo automatique. |
| `/digest actif: heure_utc:` | ✅ | ✅ | **Digest quotidien automatique** (1 DM/jour, heure UTC au choix) : enchaîne pour chaque compte lié le même contenu que `/daily` + `/predict` + `/score` (selon le tier). Activé par défaut après le **Select tier** du `/setup` ; désactivable avec `/digest actif:False`. **Hors quota** `/ping`. |
| `/daily` | ✅ | ✅ | **Legend I** : briefing daily (trophées, attaques restantes 8/jour, heure favorite). **Legend II/III** : briefing hebdo (X/30 ou X/24 batailles). |
| `/predict` | ✅ | ✅ | **Tous tiers** : trophées projetés + **rang mondial actuel et projeté** (estimés via régression log-linéaire sur le top 200 officiel Supercell, extrapolés au-delà). Affiche le R² et l'âge de la donnée pour transparence. |
| `/score` | ✅ | ✅ | **Legend I** : % jours avec 8/8 attaques. **Legend II/III** : % semaines avec quota hebdo complété. |
| `/dashboard` | ✅ | ✅ | 3 vues : synthèse / historique / objectifs. |
| `/compare` | ✅ | ✅ | Comparer avec un membre. |
| `/carnet` | ✅ | ✅ | Carnet d'erreurs hebdo. |
| `/classement` | ✅ | ✅ | Top serveur ; option **ligue** (Toutes / III / II / I). |
| `/mvp_semaine` | ✅ | ✅ | MVP gain trophées ~7 j. |
| `/metriques` | ✅ | ✅ | Agrégats deltas 24 h (table joueur). |
| `/saison` | ✅ | ✅ | Saison active + dernier rang figé. |
| `/saison_historique` | ✅ | ✅ | Liste des saisons fermées. |
| `/historique` | ✅ | ✅ | Historique personnel ou `[tag]`. |

## Serveur (`manage_guild` ou config affichée)

| Commande | Description |
|----------|-------------|
| `/admin setup` | Assistant **4 étapes** : salon alertes → salon classement auto → rôle admin bot → rôles ligue (optionnels). |
| `/serveur_config voir` | Réglages classement / salons / rôles. |
| `/serveur_config classement` | Limite, public, filtre Légende. |

## Admin bot (`administrator`, `admin_role_id`, ou propriétaire)

| Commande | Description |
|----------|-------------|
| `/bot_stats` | Latences, file, mémoire, alertes. |
| `/admin set-channel` | Configure salon `alerts` ou `leaderboard`. |
| `/admin set-role` | Configure rôle `admin`, `legend_i`, `legend_ii`, `legend_iii`. |
| `/admin force-poll` | Force un cycle API immédiat. |
| `/admin reset-cooldowns` | Vide `alert_history` pour un tag. |
| `/admin stats-polling` | Résumé technique du polling. |
| `/admin_force_poll`, `/admin_stats_polling`, `/admin_reset_cooldowns` | Alias plats (rétro-compat). |
| `/admin_saison_cloturer` | Clôture saison + résultats. |

Embeds : voir `constants.py` (titres / couleurs) et `services/alerts.py` (`_STYLE`).

## Configuration Stripe

Voir `docs/STRIPE_SETUP.md` pour le pas-à-pas (Cloudflare Tunnel + Dashboard).
