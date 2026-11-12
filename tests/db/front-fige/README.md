# Copie figée du front (12/11/2026)

Les modules du front que lisent les tests de base et les scripts (`scripts/recalcule.mjs`, `tests/db/helpers/db.ts`),
copiés tels quels de `popote-web` au 12/11/2026. Ils servent la **parité front ↔ base** (mêmes règles de calcul
des deux côtés). Ne pas les modifier : ils sont retirés à l'étape 0.5, quand le front ne calcule plus rien.
`App.tsx` n'est lu que comme texte (routes déclarées, test de l'aide).
Dépendance de test : `@tanstack/react-query`, tiré par `lib/donnees/*`.
