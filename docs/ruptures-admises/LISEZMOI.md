# Ruptures admises du contrat OpenAPI

La nouvelle appli n'est pas en ligne : personne ne consomme encore `openapi.json`, et plusieurs tâches du plan 0.4bis
le rompent. Le job `contrat` de la CI accepte une rupture **sans s'affaiblir**, une fois, dans la demande de fusion
qui l'annonce. Après la bascule (variable à `non`), toute rupture exige `/v2` ou `Deprecation` et `Sunset`
(`docs/normes-api.md` § 3.9).

## Annoncer une rupture

1. Régénérer le contrat (`uv run python scripts/exporte_contrat.py`), puis récupérer celui de `main` :
   `git show origin/main:openapi.json > /tmp/openapi-main.json`.
2. Écrire le fichier, jamais à la main : `uv run python scripts/ruptures_admises.py genere --oasdiff <oasdiff>
   --base /tmp/openapi-main.json --raison "<pourquoi>" > docs/ruptures-admises/<AAAAMMJJ>-<sujet>.txt`
   (`<oasdiff>` : la version figée du job `contrat`, `OASDIFF_VERSION` de `ci.yml`).
3. Le titre de la demande porte `!` : `feat(contrat)!: <sujet>`.

Une ligne peut être suivie d'un commentaire, après deux espaces et un dièse. Une ligne qui commence par `#` est ignorée.

## Ce que la CI vérifie

- Seuls les fichiers **ajoutés par la demande** (`git diff --no-renames --diff-filter=A origin/main...HEAD`) comptent :
  un fichier déjà sur `main` documente, il ne s'applique plus jamais. Un fichier renommé compte comme ajouté.
- La raison est en tête du fichier (`# Raison : …`) ; les liens symboliques et les sous-dossiers sont refusés ou ignorés.
- Chaque rupture réelle (`oasdiff breaking`, niveau ERR) a sa ligne ; chaque ligne correspond à une rupture réelle
  (une acceptation périmée échoue) ; `oasdiff --fail-on ERR` rend le dernier mot.
- La variable de dépôt `CONTRAT_RUPTURES_ADMISES` vaut `oui` (l'orchestrateur la passe à `non` le jour J).
- Le nom `<AAAAMMJJ>-<sujet>.txt` et le titre en `!` sont des conventions que la relecture vérifie, pas la CI.
- `oasdiff` tourne dans un dossier temporaire avec deux noms relatifs constants (`base.json`, `revision.json`) :
  avec un chemin absolu, il ne fait pas correspondre les ruptures « supprimé » à la ligne d'exception.
