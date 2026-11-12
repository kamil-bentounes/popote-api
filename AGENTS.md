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
- Commits Conventional Commits en français, sans ligne de co-auteur. Remote : alias SSH `github-perso` uniquement.
- Erreurs de l'API : une route ou une dépendance lève `Probleme` ; un middleware rend `reponse(...)` au lieu de lever (une exception de middleware finit en 500). Authentification et limite de débit : dépendances FastAPI.
- Une migration écrit ses `grant` et ses `revoke` explicitement, pour chaque objet qu'elle crée (table, vue, séquence, fonction) et pour chaque rôle concerné : un projet Supabase hébergé neuf n'a pas les privilèges par défaut de la pile locale, et l'objet y naît sans droits (voir `ops/aligne_droits.py`). Le job `migre-essai` compare les droits de l'essai à ceux d'une pile locale neuve et échoue sur un écart.
- Une migration dit en commentaire comment revenir en arrière (le SQL inverse, ou « irréversible : corriger en avant » avec la raison). Elle part sur l'essai avant le code qui l'utilise : elle doit rester compatible avec l'appli qui tourne encore (expand, puis contract une version plus tard). Une migration déjà fusionnée ne se modifie jamais.
- Base (`infra/db.py`) : une route n'ouvre une transaction que par `base.personne(id)` ; `base.service()` est réservé à la liste fermée de `tests/unit/test_architecture.py`. Jamais de `set role` ni de `set` hors `local`. Une erreur de la base n'est pas attrapée en route (traduite à la frontière, `erreurs_base.py`) ; seule une lecture ou une écriture ciblée l'entoure de `refus_vaut_introuvable()`.
