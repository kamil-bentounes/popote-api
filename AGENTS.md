# AGENTS.md

Règles pour toute session d'agent sur `popote-api` (base Supabase, fonctions, ingestion ; le front est dans `popote-web`).

## Commandes

- Pile locale : `npx supabase start` · `.env` local : `bash ops/env-local.sh` · Installer : `npm ci`
- Référentiels : `npm run seed` · Tests : `npm test` (Vitest, contre la pile locale)
- Fonctions Edge : `npx supabase functions serve` doit tourner pour `tests/db/invitation.test.ts`.
- Avant de proposer un commit, la suite complète `npm test` doit passer.

## Règles

- Ce dépôt est le seul propriétaire des migrations (depuis le 12/11/2026). Jamais de `db push` ni de `link` vers la prod.
- Ne jamais lancer `supabase db reset` sur la pile locale sans l'avoir décidé : d'autres bancs s'en servent.
- `tests/db/front-fige/` est une copie figée du front : ne pas la modifier (retirée en 0.5).
- Aucun secret dans un fichier versionné ; le `.env` local ne porte que les clés de démonstration.
- Routes qui écrivent : `async def`, jamais `def` (le délai de 25 s ne peut pas annuler un fil) ; tout travail bloquant a un délai interne plus court que 25 s.
- Commits Conventional Commits en français, sans ligne de co-auteur. Remote : alias SSH `github-perso` uniquement.
- Erreurs de l'API : une route ou une dépendance lève `Probleme` ; un middleware rend `reponse(...)` au lieu de lever (une exception de middleware finit en 500). Authentification : dépendance FastAPI. Débit : par adresse, un middleware pur (exception assumée : il refuse avant de lire le corps et compte aussi les 404, 405 et 422) ; par personne, une dépendance (voir `docs/normes-api.md` § 3.6).
