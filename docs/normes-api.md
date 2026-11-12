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
  message}` pour le corps, où `pointer` est un JSON Pointer RFC 6901, ou de `{parameter: {name, in}, message}`
  pour un paramètre).
- Jamais de trace, de requête SQL, de message de fournisseur ni de texte en anglais dans une réponse. L'erreur
  d'origine va au journal, reliée par `instance`.
- **Erreurs de la base** (`erreurs_base.py`, traduites une fois, à la frontière) : `23505` → `409 conflit` ;
  `23503`, `23514`, `22P02` → `422 donnees_invalides` sans pointeur ; `40001`, `40P01`, `55P03` → `503 reessayer`
  avec `Retry-After: 1` ; `57014` (`statement_timeout`, requête annulée) → `503 delai_depasse` ; pool épuisé,
  connexion coupée ou refusée → `503 base_indisponible` ; pas de pool `popote_internal` → `503
  service_indisponible`. `42501` (droit refusé) vaut `404 introuvable` seulement dans `refus_vaut_introuvable()`,
  autour d'une lecture ou d'une écriture ciblée d'un élément ; ailleurs c'est un droit manquant, donc
  `500 erreur_interne`. Dans tous les cas il est journalisé en avertissement avec l'objet (table ou fonction).
  Le journal reçoit `sqlstate`, contrainte et table, jamais le message de la base (son `DETAIL` recopie des
  valeurs). Les codes métier propres à une fonction SQL arrivent avec leur domaine (0.5).

## 3.4 Listes

- Pagination par curseur : `?limit=` (20 par défaut, 100 au plus) et `?cursor=` ; réponse
  `{"items": [...], "next_cursor": "…" | null}`. Jamais de troncature silencieuse.
- Filtres et tris explicites, sur des champs nommés dans le contrat.
- **Outillage** : `popote_api/pagination.py`. `parametres_de_page` (dépendance FastAPI) : `limit` de 1 à 100,
  20 par défaut ; au-delà ou en deçà, `422` (jamais de troncature silencieuse). `Page[T]` est le modèle de
  réponse, `{"items": [...], "next_cursor": str | null}` (les deux champs sont toujours présents). La route
  demande `limit + 1` lignes : la ligne en trop dit qu'il y a une suite (`construit_page`), sans `count`.
- **Pagination par clé, jamais par `offset`** : `clause_apres` écrit `(cle, id) > (%s, %s)` (`<` en ordre
  descendant) et `ordre` le `ORDER BY cle, id` ; l'identifiant départage les égalités, donc aucune ligne n'est
  sautée ni répétée quand la liste change entre deux pages. Un index `(cle, id)` sert la requête. La clé de tri
  et l'identifiant sont `not null` ; leurs noms sont écrits dans le code (`Tri`), jamais pris à la requête.
- **Le curseur est validé, pas signé.** Choix et raison : le périmètre d'une liste (foyer, personne) vient du
  `WHERE` de la route, pas du curseur, qui n'est qu'une position dans un ordre. Un curseur forgé ne peut donc
  que changer de page parmi des lignes que la personne lit déjà ; un test le montre sur Postgres (curseur
  pointant sur une ligne d'un autre foyer). Un HMAC n'ajouterait que l'intégrité de cette position, au prix
  d'un secret de plus à poser et à tourner dans chaque environnement (sans lui le conteneur ne démarre pas).
  Le décodage est complet : alphabet et taille bornés ; JSON d'un objet aux seules clés `v`, `t` (nom du tri),
  `k` (clé), `i` (UUID) ; version, nom du tri et type de la clé vérifiés (un curseur d'une autre liste est
  refusé) ; clé acceptée par Postgres (entier `bigint`, texte de 200 caractères au plus sans NUL, instant avec
  décalage) ; enfin le curseur doit se ré-encoder **à l'identique**, ce qui écarte toute forme que nous
  n'aurions pas écrite. Tout échec rend `400 curseur_invalide`. Conséquence : le curseur est lisible par le
  client (base64url d'un JSON) ; n'y mettre que la clé de tri d'une ligne qu'il a déjà reçue, et borner à 200
  caractères (`max_length`) tout texte qui sert de clé de tri.

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
- **Outillage** : `popote_api/conditionnel.py`. `etag_de_version(n)` rend `"v<n>"` ; `etag_de_contenu(octets)`
  un SHA-256 tronqué à 128 bits en base64url ; tous deux sont **forts**. `exige_if_match(request, etag_actuel)`
  garde l'écriture et `repond_ou_304(request, etag, corps)` la lecture, à appeler une fois la ressource trouvée
  et la personne autorisée (un `404` passe avant toute précondition). La RFC 9110 s'applique ainsi :
  - `If-Match` : comparaison **forte** (§ 8.8.3.2), donc un `W/"…"` ne correspond jamais ; `*` correspond à toute
    ressource existante ; une liste correspond si un membre correspond. Absent : `428
    precondition_requise`. Sans correspondance : `412 precondition_echouee`, avec l'`ETag` **actuel** en
    en-tête, pour que le client relise sans second aller-retour. Jamais le « succès » facultatif d'une écriture
    déjà appliquée (§ 13.1.1) : deux personnes du foyer qui éditent ensemble doivent voir le conflit.
  - `If-None-Match` : comparaison **faible** ; `*` correspond à toute ressource existante. Si la condition est
    fausse, `304` pour `GET` et `HEAD`, `412` pour les autres méthodes (§ 13.1.2). Le `304` n'a pas de corps et
    reprend `ETag` et `Cache-Control` du `200` (§ 15.4.5), plus `Vary`, `Content-Location` et `Expires` si la route
    les pose. `Date` vient du serveur.
  - Ordre (§ 13.2.2) : `If-Match`, puis `If-None-Match`. Un `If-Match` faux l'emporte sur un `304`.
  - Listes : plusieurs lignes d'un même en-tête valent une liste ; les éléments vides sont ignorés ; une virgule
    peut se trouver dans une étiquette (`"a,b"`), on lit donc étiquette par étiquette. Une valeur vide est une
    liste vide : aucune correspondance.
  - Un en-tête conditionnel **mal formé** (guillemets manquants, `w/` minuscule, `*` mêlé à une étiquette,
    deux étiquettes sans virgule) rend `400 requete_mal_formee`, jamais ignoré : ignorer un `If-Match` ouvrirait
    la mise à jour perdue.
  - `If-Modified-Since`, `If-Unmodified-Since`, `Range`, `If-Range` sont ignorés : pas de date de modification.
    `If-Unmodified-Since` ne remplace pas `If-Match` (`428`).
  - Le client fait ses lectures conditionnelles lui-même (l'`ETag` gardé en mémoire et renvoyé dans
    `If-None-Match`) : `Cache-Control: no-store` et `304` ne se contredisent pas.

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
- **Types à réutiliser** (`popote_api/formats.py`), dans tout modèle d'entrée ou de sortie :
  - `Instant` : texte RFC 3339 **avec** décalage (`Z` ou `+01:00`). Un instant sans décalage, un horodatage
    Unix, un espace à la place du `T`, un décalage sans deux-points, une seconde `60` sont refusés (`422`).
    En sortie, toujours en UTC avec le décalage écrit (`2026-11-12T09:00:00+00:00`) : l'écran convertit.
  - `Jour` : `YYYY-MM-DD` seul (un instant ou un `datetime` est refusé), au sens de `Europe/Paris`.
    `jour_a_paris(instant)` donne le jour de Paris d'un instant (heure d'été comprise : des journées de 23,
    24 ou 25 h) ; `aujourdhui_a_paris()` prend une horloge en paramètre pour les tests. Jamais `date.today()`,
    qui suit le fuseau du serveur.
  - `Montant` : `{"amount_cents": int, "currency": "EUR"}`. Entier strict (ni `12.5`, ni `12.0`, ni `"1250"`),
    de ±(2^53 − 1) (au-delà, un nombre JSON n'est plus exact dans le navigateur), négatif pour un avoir ;
    `currency` obligatoire et seulement `"EUR"` (casse comprise) ; champ inconnu refusé.

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
  vérifie en mémoire : aucun 5xx (sauf le `503` de `readyz`), schéma, type de contenu et statut documentés. Le contrat décrit l'API derrière le relais.

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
  La sonde ouvre une transaction, prend le rôle `authenticated` (`set local role`, car `popote_api` n'a aucun
  droit sur les tables) et lit une ligne de `public.instance_setting` : table de référence lisible sans foyer,
  semée par la migration 0009. Une table sans ligne lisible vaut « base indisponible ». Aucune donnée n'est rendue
  ni journalisée ; le résultat reste en cache 5 s, et connexion plus requête tiennent en 3 s.
