# Configuration du Premium (Stripe + Cloudflare Tunnel)

Ce guide met le paiement en place **de zéro** sur ton Mac/Linux, sans serveur dédié.

## 1. Créer le produit dans Stripe (mode Test d'abord)

1. Crée un compte Stripe : https://dashboard.stripe.com/register
2. Bascule sur **Test mode** (interrupteur en haut à droite).
3. **Products → Add product**
   - Nom : `LegendMind Premium`
   - Prix : récurrent **mensuel**, **2,99 €** (dans le Dashboard Stripe : `2.99 EUR / month`).
   - Sauvegarde et **copie le Price ID** (commence par `price_…`).
4. **Developers → API keys** → copie la **Secret key** (commence par `sk_test_…`).

## 2. Exposer le webhook avec Cloudflare Tunnel (gratuit, zéro config DNS)

Cloudflare Tunnel donne une URL HTTPS publique pointant vers ton port local — pas de domaine ni de port forwarding requis.

### Installation (macOS)

```bash
brew install cloudflared
```

Linux :

```bash
# Voir https://github.com/cloudflare/cloudflared/releases
```

### Lancer le tunnel

Dans un terminal **séparé** (à laisser tourner pendant que le bot tourne) :

```bash
cloudflared tunnel --url http://localhost:8000
```

Tu obtiens en sortie une URL du type :

```
https://random-words-1234.trycloudflare.com
```

C'est ton **endpoint public**. L'URL change à chaque redémarrage du tunnel — pour figer l'URL il faut un compte Cloudflare gratuit + tunnel nommé (voir doc Cloudflare). Pour un dev rapide, l'URL temporaire suffit.

## 3. Déclarer le webhook côté Stripe

1. Stripe Dashboard → **Developers → Webhooks → Add endpoint**.
2. URL : `https://random-words-1234.trycloudflare.com/stripe/webhook`
3. **Events to send** (cocher au moins) :
   - `checkout.session.completed`
   - `customer.subscription.created`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
4. Crée l'endpoint ; copie le **Signing secret** (commence par `whsec_…`).

## 4. Renseigner le `.env`

```env
STRIPE_API_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_ID_MONTHLY=price_...
STRIPE_SUCCESS_URL=https://discord.com/channels/@me
STRIPE_CANCEL_URL=https://discord.com/channels/@me

WEBHOOK_HOST=0.0.0.0
WEBHOOK_PORT=8000
```

## 5. Tester de bout en bout

```bash
PYTHONPATH=. python main.py
# Dans un autre terminal :
cloudflared tunnel --url http://localhost:8000
```

Sur Discord :

1. `/setup tag:#TONTAG` → essai 7 j auto si Legend.
2. `/premium` → réponse "essai actif".
3. Force l'expiration côté Stripe (Test clocks) ou attend 7 j, puis `/premium` → bouton **Ouvrir Stripe Checkout**.
4. Paye avec la carte test `4242 4242 4242 4242`, n'importe quelle date future, n'importe quel CVC.
5. Le webhook arrive : tu vois dans le log du bot `Subscription updated for user … status=active`.

## 6. Passer en Live

1. Bascule Stripe en **Live mode**, recrée le produit/prix.
2. Récupère la **Live Secret key**, le nouveau **Price ID**, le **Live Webhook Signing secret**.
3. Mets à jour le `.env` avec ces valeurs et redémarre le bot.
4. Pour la prod : remplace l'URL `trycloudflare.com` aléatoire par un vrai domaine (Cloudflare Tunnel nommé ou reverse proxy Caddy/nginx en façade).

## Annexe : désactiver Stripe

Tu peux laisser `STRIPE_API_KEY` vide. Dans ce mode :

- `/premium` répond "le paiement n'est pas configuré sur cette instance".
- Le serveur webhook tourne quand même mais répond `503` aux requêtes Stripe.
- L'essai 7 j auto à `/setup` continue de fonctionner (entièrement local, sans Stripe).
