# popote-api

La base (migrations Supabase), les fonctions Edge, l'analyseur d'ingestion (`worker/src`) et les tests de base de
Popote. **Seul propriétaire des migrations depuis le 12/11/2026** : l'ancien dépôt est gelé côté base (plus aucun
`db push` ni déploiement de fonction depuis lui). Le front est dans `popote-web`.

## Lancer en local
1. `npx supabase start` (la pile locale, projet `smart-receipe-scheduler`).
2. `bash ops/env-local.sh` : écrit `.env` depuis la pile locale (clés de démonstration, pas des secrets).
3. `npm ci && npm run seed` : référentiels (aliments, conversions).
4. L'API Python (`uv run uvicorn popote_api.main:app --port 8000`) arrive avec la tâche 8 du plan 0.2.

## Tests
- Base et ingestion : `npm test` (Vitest, `tests/db` et `worker/test`, contre la pile locale ; `npx supabase
  functions serve` doit tourner pour `tests/db/invitation.test.ts`).
- Python : `uv run pytest` (à venir avec le squelette de l'API).

## Reprise de l'ancien dépôt
- `tests/db/front-fige/` : copie figée du front (parité front ↔ base), retirée en 0.5.
- `tests/db/parite/` : tests du front qui lisent `supabase/`.
- `docs/inventaire-surface.md` : ce que le front appelait avant le socle (`node ops/inventaire.mjs <src>`).
