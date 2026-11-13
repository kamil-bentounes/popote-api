# AGENTS.md

Règles pour toute session d'agent sur `popote-api` (base Supabase, fonctions, ingestion ; le front est dans `popote-web`).

## Commandes

- Pile locale : `npx supabase start` · `.env` local : `bash ops/env-local.sh` · Installer : `npm ci`
- Référentiels : `npm run seed` · Tests : `npm test` (Vitest, contre la pile locale)
- Fonctions Edge : `npx supabase functions serve` doit tourner pour `tests/db/invitation.test.ts`.
- Avant de proposer un commit, la suite complète `npm test` doit passer.
- Contrat : `uv run python scripts/exporte_contrat.py` régénère `openapi.json` après tout changement de route, de modèle ou de réponse d'erreur ; un conflit sur ce fichier se règle en le régénérant, jamais à la main.

## Règles

- Ce dépôt est le seul propriétaire des migrations (depuis le 12/11/2026). Jamais de `db push` ni de `link` vers la prod.
- Ne jamais lancer `supabase db reset` sur la pile locale sans l'avoir décidé : d'autres bancs s'en servent.
- `tests/db/front-fige/` est une copie figée du front : ne pas la modifier (retirée en 0.5).
- Aucun secret dans un fichier versionné ; le `.env` local ne porte que les clés de démonstration.
- Routes qui écrivent : `async def`, jamais `def` (le délai de 25 s ne peut pas annuler un fil) ; tout travail bloquant a un délai interne plus court que 25 s.
- Commits Conventional Commits en français, sans ligne de co-auteur. Remote : alias SSH `github-perso` uniquement.
- Erreurs de l'API : une route ou une dépendance lève `Probleme` ; un middleware rend `reponse(...)` au lieu de lever (une exception de middleware finit en 500). Authentification : dépendance FastAPI. Débit : par adresse, un middleware pur (exception assumée : il refuse avant de lire le corps et compte aussi les 404, 405 et 422) ; par personne, une dépendance (voir `docs/normes-api.md` § 3.6).
- Une migration écrit ses `grant` et ses `revoke` explicitement, pour chaque objet qu'elle crée (table, vue, séquence, fonction) et pour chaque rôle concerné : un projet Supabase hébergé neuf n'a pas les privilèges par défaut de la pile locale, et l'objet y naît sans droits (voir `ops/aligne_droits.py`). Le job `migre-essai` compare les droits de l'essai à ceux d'une pile locale neuve et échoue sur un écart.
- Une migration dit en commentaire comment revenir en arrière (le SQL inverse, ou « irréversible : corriger en avant » avec la raison). Elle part sur l'essai avant le code qui l'utilise : elle doit rester compatible avec l'appli qui tourne encore (expand, puis contract une version plus tard). Une migration déjà fusionnée ne se modifie jamais.
- Base (`infra/db.py`) : une route n'ouvre une transaction que par `base.personne(id)` ; `base.service()` et `base.connexion()` (le rôle `popote_api` nu, pour les fonctions `security definer` qu'il est seul à pouvoir exécuter) sont réservés aux listes fermées de `tests/unit/test_architecture.py`. Jamais de `set role` ni de `set` hors `local`. Une erreur de la base n'est pas attrapée en route (traduite à la frontière, `erreurs_base.py`) ; seule une lecture ou une écriture ciblée l'entoure de `refus_vaut_introuvable()`.
- Verrous de base : l'ordre est foyer, puis invitation du foyer, puis personne (`private.verrouille_la_personne`, la même clé que `cree_session`), puis lignes. Une fonction SQL qui écrit `login_session.revoked_at` ou supprime des sessions prend la personne en premier (`tests/unit/test_architecture.py` le vérifie sur les migrations ; exceptions écrites avec leur raison). Voir `docs/securite.md` § 4.14.
