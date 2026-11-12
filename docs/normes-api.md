# Normes d'API

Les règles que suivent toutes les routes de `popote-api`, de l'étape 0.3 aux parcours suivants. Elles sont
extraites du § 3 de la [spec du socle](https://github.com/kamil-bentounes/popote-web/blob/main/docs/superpowers/specs/2026-11-12-socle-design.md), dont ce document garde la numérotation : un renvoi « § »
désigne la spec. La spec reste la référence en cas d'écart.

| Pour savoir | Aller à |
|---|---|
| Comment nommer une route, un champ | 3.1 |
| Quel code HTTP rendre | 3.2 |
| Comment rendre une erreur | 3.3 |
| Paginer, filtrer | 3.4 |
| Rendre une écriture sûre (idempotence, `ETag`) | 3.5 |
| Limites de débit, de taille, quotas | 3.6 |
| Opérations longues, temps réel | 3.7 |
| Dates, argent | 3.8 |
| Cache, versions, contrat OpenAPI | 3.9 |
| Ce qui est fermé par défaut | 3.10 |
| Journaux, traces, sondes | 3.11 |

Sécurité des sessions, des rôles et des données : [`securite.md`](securite.md). Exploitation : [`exploitation.md`](exploitation.md).
L'inventaire des appels actuels du front, qui donne la liste des routes de l'étape 0.5 : [`inventaire-surface.md`](inventaire-surface.md).

## 3.1 Ressources et adresses

- Toutes les routes sous `/api/v1`. Des noms au pluriel, en anglais, en minuscules avec tirets :
  `/api/v1/households/{household_id}/members`, `/api/v1/recipes`, `/api/v1/cycles/{cycle_id}`.
- Deux niveaux d'imbrication au plus. Au-delà, une ressource de premier niveau avec un filtre.
- Une action qui n'est pas un CRUD est une sous-ressource créée par `POST` :
  `POST /api/v1/cycles/{id}/transitions` avec `{"to": "courses"}`, `POST /api/v1/meals/{id}/eaten`.
- Identifiants : UUID, jamais d'entier séquentiel exposé.
- Champs JSON en `snake_case`, en anglais. Les textes destinés à l'écran (`title`, `detail` d'une erreur)
  sont en français.
- L'inventaire de la surface actuelle (173 appels `.from()`, 37 RPC, 8 fonctions, le temps réel, le stockage),
  table par table et écran par écran, est un livrable de l'étape 0.2 : il donne la liste des routes de 0.5.

## 3.2 Méthodes et codes (RFC 9110)

- `GET` sûr, `PUT` et `DELETE` idempotents, `POST` pour créer (`201` + `Location`) ou déclencher une action
  (`200`, ou `202` + `Location` si le travail continue), `PATCH` en JSON Merge Patch (RFC 7396).
- Codes : `200`, `201`, `202`, `204`, `304` ; `400` requête mal formée ; `401` pas de session ; `403` session
  valide mais geste interdit ; `404` absent **ou appartenant à un autre foyer** (on ne révèle pas qu'il existe) ;
  `409` conflit d'état (transition de cycle refusée, mois déjà clos) ; `412` version périmée (`If-Match`) ;
  `413` corps trop gros ; `415` type de contenu refusé ; `422` données invalides ; `428` `If-Match` manquant ;
  `429` trop de requêtes ; `500` erreur interne ; `502`, `503`, `504` pour un fournisseur en panne ou trop lent.

## 3.3 Erreurs (RFC 9457)

- Toute erreur répond en `application/problem+json` : `type` (URI stable,
  `https://notre-popote.fr/problemes/<code>`), `title` (court, français), `status`, `detail` (phrase lisible
  par la personne, sans détail technique), `instance` (identifiant de la requête), plus deux extensions : `code`
  (code machine stable, ex. `cycle_transition_refusee`) et `errors` (pour `422` : liste de `{pointer,
  message}`, où `pointer` est un JSON Pointer, RFC 6901).
- Jamais de trace, de requête SQL, de message de fournisseur ni de texte en anglais dans une réponse. L'erreur
  d'origine va au journal, reliée par `instance`.

## 3.4 Listes

- Pagination par curseur : `?limit=` (20 par défaut, 100 au plus) et `?cursor=` ; réponse
  `{"items": [...], "next_cursor": "…" | null}`. Jamais de troncature silencieuse.
- Filtres et tris explicites, sur des champs nommés dans le contrat.

## 3.5 Écritures sûres

- **Idempotence** (brouillon IETF `Idempotency-Key`, version 08) : en-tête obligatoire sur tout `POST` qui crée
  ou déclenche un effet (dépense, repas mangé, invitation, appel au modèle). La clé, l'empreinte du corps et la
  réponse sont gardées 24 h : un second envoi rend la même réponse sans refaire l'effet ; la même clé avec un
  autre corps rend `422` ; un second envoi pendant que le premier tourne rend `409` ; l'en-tête manquant rend
  `400`.
- **Concurrence** (RFC 9110, requêtes conditionnelles) : `ETag` tiré d'une colonne `version` (entier,
  incrémenté par déclencheur) sur chaque table que deux personnes peuvent éditer (charges, lignes du mois,
  recettes du foyer, réglages) ; `If-Match` obligatoire sur `PUT`, `PATCH` et `DELETE` de ces ressources :
  `412` si la version a changé, `428` s'il manque. Les colonnes `version` arrivent par les migrations de 0.5.

## 3.6 Limites

- **Débit** (brouillon IETF `RateLimit` ; `429` : RFC 6585) : lecture 120/min et écriture 30/min par session,
  comptées en mémoire par instance (approximatif, suffisant pour un foyer) ; les limites qui protègent un
  compte sont comptées en base, donc justes quelle que soit l'instance : connexion 5 essais par compte et
  20 par IP en 15 min avec attente croissante, réinitialisation 3 par heure et par compte, invitations
  10 par jour. En-têtes `RateLimit-Policy` et `RateLimit` ; `429` avec `Retry-After`.
- **Modèles** : quotas par foyer et par usage, décomptés de façon atomique en base
  (`update … where appels < quota returning …`) AVANT l'appel ; plafond en euros appliqué.
- **Tailles et délais** : corps JSON 1 Mo au plus ; photos à part (§ 6.1) ; délai serveur 30 s, sauf les
  appels au modèle traités en travail asynchrone (§ 3.7).
- La « dernière activité » d'une session et les compteurs ne s'écrivent pas plus d'une fois toutes les
  5 minutes par session : une lecture ne devient pas une écriture.

## 3.7 Opérations longues et temps réel

- Un appel au modèle de plus de quelques secondes devient une ressource de travail : `POST` → `202` +
  `Location: /api/v1/jobs/{id}`, puis lecture de l'état.
- Les graphes de l'IA (étapes 1 à 13) exposeront des fils : `POST /api/v1/threads/{id}/messages` reprend un
  graphe arrêté sur une question. Hors étape 0.
- **Temps réel de la session de cuisine** : aujourd'hui Supabase Realtime depuis le navigateur. À l'étape 0,
  les téléphones relisent l'état de la session toutes les 3 secondes pendant qu'elle est ouverte, avec un `ETag`
  calculé sur tout l'état de la session (tâches et convives, pas une seule ligne) et `304` quand rien n'a
  changé. C'est sans état, compatible avec plusieurs instances et avec le pooler. Un flux poussé (SSE) ne sera
  envisagé qu'au parcours « La session du dimanche », s'il apporte quelque chose.

## 3.8 Formats

- Instants en RFC 3339 avec décalage ; jours du calendrier en `YYYY-MM-DD`, toujours au sens de
  `Europe/Paris` ; argent en centimes entiers avec `currency: "EUR"` ; quantités avec leur unité.

## 3.9 Cache, versions, contrat

- Données privées : `Cache-Control: no-store`. Référentiels publics (catalogue, aliments) : `ETag` et
  `Cache-Control: private, max-age=…`.
- Seuls des ajouts compatibles dans `/v1`. Une rupture ouvre `/v2`. Une route retirée annonce `Deprecation`
  (RFC 9745) et `Sunset` (RFC 8594) au moins 30 jours avant.
- Le contrat est produit par le code (FastAPI, OpenAPI 3.1), exporté dans `openapi.json` et versionné dans
  `popote-api`. L'intégration continue compare chaque branche à `main` (`oasdiff`) et refuse une rupture non
  annoncée. `popote-web` fixe une version du contrat et régénère son client ; un écart fait échouer son
  intégration continue.
- Régénérer le contrat : `uv run python scripts/exporte_contrat.py` (application construite en `local`, sans base ;
  clés triées, fin de ligne finale). `openapi.json` est marqué `linguist-generated` : il ne s'écrit jamais à la
  main, et en cas de conflit on le régénère. Chaque route porte un `operation_id` stable et un `summary`.
- Les erreurs d'une route sont déclarées avec `responses=reponses_erreur(404, 409)` (`errors.py`) : le contrat
  les publie en `application/problem+json`, schéma `ProblemDetails` (la forme que `reponse()` produit).
  `readyz` déclare aussi `503`.
- Gardes de la CI (job `contrat`) : le contrat régénéré doit être celui qui est versionné ; `oasdiff breaking`
  compare à `origin/main:openapi.json` et échoue sur une rupture (niveau `ERR`) ; retirer une route sans
  l'avoir marquée `deprecated: true` avec `x-sunset` (date au moins 30 jours après) est une rupture. Tant que
  `main` n'a pas de contrat, le contrôle le dit et passe. `tests/contract/` (Schemathesis, version figée)
  vérifie en mémoire : pas de 5xx non documenté, schéma, type de contenu et statut documentés.

## 3.10 Par défaut, fermé

- Toute route exige une session, sauf une liste écrite : connexion, lecture et acceptation d'une invitation,
  demande et usage d'une réinitialisation, `/api/healthz`, `/api/readyz`.
- Les routes `/internal/*` (rappels, purges) n'acceptent ni cookie ni session : seulement une signature
  HMAC de la requête, avec horodatage (5 minutes de validité), clé propre à chaque environnement.
- Les modèles d'entrée refusent les champs inconnus (`extra="forbid"`) ; les modèles de sortie ne listent que
  les champs à montrer.
- Pas de CORS : une seule origine. Une écriture dont l'`Origin` n'est pas celle de l'environnement est refusée ;
  sur l'essai, la liste admet aussi le motif des adresses d'aperçu.

## 3.11 Suivi

- En-tête `traceparent` (W3C Trace Context) accepté et propagé ; journaux JSON sur la sortie standard, avec
  l'identifiant de trace ; aucune donnée personnelle dans les journaux (pas de montant, pas de prénom, pas
  d'e-mail en clair).
- `/api/healthz` (le processus vit) et `/api/readyz` (la base répond), publics et sans donnée. Le réveil
  quotidien de chaque projet Supabase (prod et essai) passe par une vraie requête de l'API sur `/api/readyz`.
