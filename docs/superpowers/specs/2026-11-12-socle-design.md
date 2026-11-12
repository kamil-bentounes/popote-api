# Le socle de Popote : architecture et règles (étape 0.1)

Écrit le 12/11/2026, après l'audit (page : https://claude.ai/artifact/QsbhzDqhoUvCHZAeShYa3j ; rapports dans
`~/PERSO/sauvegardes-popote/audit-2026-11-12/`). Plan validé par Kamil le même jour : étape 0 = le socle, sans
changement visible ; étapes 1 à 13 = les parcours, un par un. Revu deux fois par un agent adverse le 12/11 ;
ses dix-sept défauts bloquants sont traités dans cette version (stratégie de bascule, origine unique, relais,
connexion verrouillée, rôles séparés, photos, temps réel, migrations, tests, sauvegardes, retour arrière,
ancienne adresse).

Ce document est la référence des étapes 0.2 à 0.8 et des parcours qui suivent. Il sera découpé à l'étape 0.2 :
les normes d'API et la sécurité dans `popote-api/docs/`, les conventions du front dans `popote-web/docs/`.
Les décisions qui reviennent à Kamil sont listées au § 12 et lui sont posées en conversation, une à la fois.

---

## 1. But, stratégie, sortie

**But.** Remplacer l'accès direct du navigateur à Supabase par une API qui suit les normes, refaire la
connexion, poser des contrôles automatiques, et prouver la sécurité, le contrat et la tenue en charge, sans
changer les écrans.

**Stratégie : construire à côté, basculer une fois.** L'appli actuelle reste en ligne, intacte, pendant toute
l'étape 0. La nouvelle (API + front rebranché) se construit et se teste en local et sur l'environnement
d'essai, puis remplace l'ancienne en une bascule répétée à l'avance (§ 11). Pourquoi pas domaine par domaine en
prod : il faudrait faire cohabiter deux connexions (jeton Supabase pour les domaines pas encore migrés, cookie
pour les autres) et laisser le navigateur ouvert sur la base jusqu'au bout. Pour un foyer de deux personnes,
avec 34 parcours e2e comme filet, une bascule répétée est plus simple et plus sûre.

**Hors périmètre.** Le design, les nouveaux parcours, la réécriture des prompts. L'IA est seulement déplacée
derrière l'API (0.6), journalisée et bornée.

**Seuls changements visibles admis** : la nouvelle adresse `notre-popote.fr`, une reconnexion le jour de la
bascule, la réinstallation de l'appli sur l'écran d'accueil du téléphone, la disparition de « Première
connexion » (lien magique ; décision du 19/10 : l'invitation suffit), et des erreurs écrites en français.

**L'étape 0 est finie quand :**
1. le navigateur ne parle plus qu'à `notre-popote.fr` : plus aucune clé Supabase dans le front ; les clés
   historiques (`anon`, `service_role`) sont désactivées ; l'API de données, GraphQL et Realtime sont fermés ;
   les inscriptions publiques et le lien magique sont coupés dans Supabase Auth ;
2. tout ce que l'appli fait aujourd'hui passe par l'API, et les specs e2e (adaptées à la nouvelle connexion)
   sont vertes en local, sur l'essai et sur la prod après la bascule ;
3. la session tient dans un cookie `HttpOnly` : aucun jeton lisible par le JavaScript ;
4. les deux dépôts ont une intégration continue bloquante et ne se déploient que par elle ;
5. le contrat OpenAPI est publié et toute rupture est détectée avant la fusion ;
6. les tests de charge tiennent les objectifs du § 9.3, les scans de sécurité ne laissent aucun constat haut ou
   critique, et la liste ASVS niveau 2 du § 7.6 est vérifiée (exceptions écrites et justifiées) ;
7. une sauvegarde chiffrée existe chaque nuit et a été restaurée au moins une fois sur l'essai ;
8. l'ancienne adresse renvoie vers la nouvelle (§ 11).

---

## 2. Architecture cible

```
navigateur ── HTTPS ──▶ notre-popote.fr (Cloudflare : fichiers du front + relais)
                          ├── /            fichiers statiques de popote-web
                          └── /api/*  ──▶  popote-api (conteneur, Paris)
                                             ├──▶ Postgres Supabase (Paris) : données, règles d'argent en SQL, RLS
                                             ├──▶ Supabase Auth (admin) : comptes existants
                                             ├──▶ Supabase Storage (clé secrète) : photos
                                             ├──▶ fournisseurs de modèles (texte, vision)
                                             └──▶ fournisseur de mails (rappels, réinitialisation)
pg_cron ── appel signé ──▶ popote-api /internal/* (rappels, purges)
GitHub Actions ── la nuit ──▶ pg_dump chiffré ──▶ stockage objet en Europe
```

**Une seule origine.** Le front et l'API sont servis sous `notre-popote.fr` : l'hôte du front relaie `/api/*`
vers le conteneur de l'API. Le cookie de session est donc un cookie propriétaire de l'hôte qui sert la page,
sur la prod (`notre-popote.fr`), l'essai (`essai.notre-popote.fr`), les aperçus de fusion et le poste local
(proxy de Vite) : pas de cookie tiers, pas de CORS, une CSP en `'self'`.

**Le relais** est un Worker Cloudflare qui sert les fichiers et transmet `/api/*` sans cache (`no-store`
respecté). Palier gratuit : 100 000 requêtes par jour ; un dimanche de cuisine à deux téléphones relisant toutes
les 3 secondes pendant 4 heures en fait moins de 10 000. Le conteneur garde une adresse publique ; ce qui le
protège :
- le relais ajoute un en-tête secret, comparé en temps constant par l'API, propre à chaque environnement et
  changé tous les 90 jours ; sans lui, l'API répond `404` à toute route `/api/*` ;
- les routes `/internal/*` ne passent pas par le relais (`pg_cron` les appelle directement) : elles sont
  exemptées de l'en-tête secret et n'acceptent qu'une signature HMAC (§ 3.10) ;
- l'adresse IP de la personne n'est lue dans `CF-Connecting-IP` que si l'en-tête secret est valide ; sinon,
  l'adresse de la connexion.

Le service worker du front exclut `/api/*` de son repli de navigation et de ses caches.

**Principes.**
- Le front ne connaît que le contrat de l'API. Aucun SDK Supabase dans le front.
- L'API est sans état : sessions, clés d'idempotence et compteurs vivent en base (Twelve-Factor : configuration
  par l'environnement, journaux sur la sortie standard). Plusieurs instances peuvent tourner.
- Les règles d'argent et du cycle déjà éprouvées restent en SQL (fonctions, déclencheurs, et leurs tests) ;
  l'API les appelle. Elles ne passent en Python que lorsqu'un parcours le demande, tests compris.
- La RLS reste le dernier rempart : les requêtes d'une personne s'exécutent sous le rôle `authenticated` avec
  son identité (§ 5.1). Une erreur d'autorisation dans le code Python ne suffit donc pas à fuiter.
- Un environnement = un projet Supabase + un déploiement de l'API + un déploiement du front.

**Les deux dépôts** (choix de Kamil : deux dépôts, reliés seulement par le contrat).
- `popote-web` : reprend l'historique du dépôt actuel (`batchcooking`), poussé dans un nouveau dépôt ; l'ancien
  continue de servir l'appli en ligne jusqu'à la bascule. On en retire `supabase/`, `worker/`, les scripts de
  base et les tests de base, qui partent dans l'API. Il contient aussi le petit relais Cloudflare.
- `popote-api` : nouveau. Il devient dès l'étape 0.2 le **seul propriétaire des migrations** ; l'ancien dépôt
  est gelé côté base (plus aucun `db push` ni déploiement de fonction depuis lui). Il reçoit
  `supabase/migrations` (historique gardé), la logique des Edge Functions portée en Python, les tests de base
  (§ 9.1) et l'analyseur déterministe d'ingestion (`worker/src`), porté en Python à l'étape 0.6 avec ses cas de
  test actuels comme référence.

**La pile.**
- API : Python 3.13, FastAPI, Pydantic v2, Uvicorn ; psycopg 3 asynchrone avec un pool, branché sur le
  pooler Supabase en mode transaction (`prepare_threshold=None`) ; SQL explicite et paramétré dans des dépôts
  de requêtes, pas d'ORM ; migrations SQL gérées par la CLI Supabase.
- Front : React 19, Vite, TypeScript strict, TanStack Router (routes typées) et TanStack Query ; client
  généré depuis le contrat avec `openapi-typescript` et `openapi-fetch` ; Tailwind 4 ; Motion ; PWA.
- Outils : `uv`, `ruff`, `mypy --strict`, `pytest` côté API ; `oxlint`, `tsc`, `vitest`, Playwright côté front.

---

## 3. Normes d'API

### 3.1 Ressources et adresses
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

### 3.2 Méthodes et codes (RFC 9110)
- `GET` sûr, `PUT` et `DELETE` idempotents, `POST` pour créer (`201` + `Location`) ou déclencher une action
  (`200`, ou `202` + `Location` si le travail continue), `PATCH` en JSON Merge Patch (RFC 7396).
- Codes : `200`, `201`, `202`, `204`, `304` ; `400` requête mal formée ; `401` pas de session ; `403` session
  valide mais geste interdit ; `404` absent **ou appartenant à un autre foyer** (on ne révèle pas qu'il existe) ;
  `409` conflit d'état (transition de cycle refusée, mois déjà clos) ; `412` version périmée (`If-Match`) ;
  `413` corps trop gros ; `415` type de contenu refusé ; `422` données invalides ; `428` `If-Match` manquant ;
  `429` trop de requêtes ; `500` erreur interne ; `502`, `503`, `504` pour un fournisseur en panne ou trop lent.

### 3.3 Erreurs (RFC 9457)
- Toute erreur répond en `application/problem+json` : `type` (URI stable,
  `https://notre-popote.fr/problemes/<code>`), `title` (court, français), `status`, `detail` (phrase lisible
  par la personne, sans détail technique), `instance` (identifiant de la requête), plus deux extensions : `code`
  (code machine stable, ex. `cycle_transition_refusee`) et `errors` (pour `422` : liste de `{pointer,
  message}`, où `pointer` est un JSON Pointer, RFC 6901).
- Jamais de trace, de requête SQL, de message de fournisseur ni de texte en anglais dans une réponse. L'erreur
  d'origine va au journal, reliée par `instance`.

### 3.4 Listes
- Pagination par curseur : `?limit=` (20 par défaut, 100 au plus) et `?cursor=` ; réponse
  `{"items": [...], "next_cursor": "…" | null}`. Jamais de troncature silencieuse.
- Filtres et tris explicites, sur des champs nommés dans le contrat.

### 3.5 Écritures sûres
- **Idempotence** (brouillon IETF `Idempotency-Key`, version 08) : en-tête obligatoire sur tout `POST` qui crée
  ou déclenche un effet (dépense, repas mangé, invitation, appel au modèle). La clé, l'empreinte du corps et la
  réponse sont gardées 24 h : un second envoi rend la même réponse sans refaire l'effet ; la même clé avec un
  autre corps rend `422` ; un second envoi pendant que le premier tourne rend `409` ; l'en-tête manquant rend
  `400`.
- **Concurrence** (RFC 9110, requêtes conditionnelles) : `ETag` tiré d'une colonne `version` (entier,
  incrémenté par déclencheur) sur chaque table que deux personnes peuvent éditer (charges, lignes du mois,
  recettes du foyer, réglages) ; `If-Match` obligatoire sur `PUT`, `PATCH` et `DELETE` de ces ressources :
  `412` si la version a changé, `428` s'il manque. Les colonnes `version` arrivent par les migrations de 0.5.

### 3.6 Limites
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

### 3.7 Opérations longues et temps réel
- Un appel au modèle de plus de quelques secondes devient une ressource de travail : `POST` → `202` +
  `Location: /api/v1/jobs/{id}`, puis lecture de l'état.
- Les graphes de l'IA (étapes 1 à 13) exposeront des fils : `POST /api/v1/threads/{id}/messages` reprend un
  graphe arrêté sur une question. Hors étape 0.
- **Temps réel de la session de cuisine** : aujourd'hui Supabase Realtime depuis le navigateur. À l'étape 0,
  les téléphones relisent l'état de la session toutes les 3 secondes pendant qu'elle est ouverte, avec un `ETag`
  calculé sur tout l'état de la session (tâches et convives, pas une seule ligne) et `304` quand rien n'a
  changé. C'est sans état, compatible avec plusieurs instances et avec le pooler. Un flux poussé (SSE) ne sera
  envisagé qu'au parcours « La session du dimanche », s'il apporte quelque chose.

### 3.8 Formats
- Instants en RFC 3339 avec décalage ; jours du calendrier en `YYYY-MM-DD`, toujours au sens de
  `Europe/Paris` ; argent en centimes entiers avec `currency: "EUR"` ; quantités avec leur unité.

### 3.9 Cache, versions, contrat
- Données privées : `Cache-Control: no-store`. Référentiels publics (catalogue, aliments) : `ETag` et
  `Cache-Control: private, max-age=…`.
- Seuls des ajouts compatibles dans `/v1`. Une rupture ouvre `/v2`. Une route retirée annonce `Deprecation`
  (RFC 9745) et `Sunset` (RFC 8594) au moins 30 jours avant.
- Le contrat est produit par le code (FastAPI, OpenAPI 3.1), exporté dans `openapi.json` et versionné dans
  `popote-api`. L'intégration continue compare chaque branche à `main` (`oasdiff`) et refuse une rupture non
  annoncée. `popote-web` fixe une version du contrat et régénère son client ; un écart fait échouer son
  intégration continue.

### 3.10 Par défaut, fermé
- Toute route exige une session, sauf une liste écrite : connexion, lecture et acceptation d'une invitation,
  demande et usage d'une réinitialisation, `/api/healthz`, `/api/readyz`.
- Les routes `/internal/*` (rappels, purges) n'acceptent ni cookie ni session : seulement une signature
  HMAC de la requête, avec horodatage (5 minutes de validité), clé propre à chaque environnement.
- Les modèles d'entrée refusent les champs inconnus (`extra="forbid"`) ; les modèles de sortie ne listent que
  les champs à montrer.
- Pas de CORS : une seule origine. Une écriture dont l'`Origin` n'est pas celle de l'environnement est refusée ;
  sur l'essai, la liste admet aussi le motif des adresses d'aperçu.

### 3.11 Suivi
- En-tête `traceparent` (W3C Trace Context) accepté et propagé ; journaux JSON sur la sortie standard, avec
  l'identifiant de trace ; aucune donnée personnelle dans les journaux (pas de montant, pas de prénom, pas
  d'e-mail en clair).
- `/api/healthz` (le processus vit) et `/api/readyz` (la base répond), publics et sans donnée. Le réveil
  quotidien de chaque projet Supabase (prod et essai) passe par une vraie requête de l'API sur `/api/readyz`.

---

## 4. Connexion et sessions

S'inspire du modèle « backend for frontend » décrit par la RFC 10017 (BCP 212, août 2026) pour les clients
OAuth : le navigateur ne détient aucun jeton, seulement un cookie de session ; ce qui donne accès reste sur le
serveur. Popote n'est pas un client OAuth ; c'est le principe qui est repris.

- **Comptes.** Les comptes et les hachages de mots de passe restent dans Supabase Auth : personne ne recrée son
  compte, personne ne change son mot de passe à la bascule.
- **Vérifier un mot de passe** se fait dans la base, par une fonction `security definer` privée qui compare
  avec `crypt()` le hachage bcrypt de `auth.users` (prouvé en local le 12/11 sur des comptes réels de banc :
  bon mot de passe accepté, mauvais refusé). L'API n'appelle donc pas le point de connexion public de Supabase
  Auth : ni ses limites par IP partagées, ni des jetons à révoquer. La fonction :
  - refuse un compte sans hachage, banni (`banned_until` dans le futur) ou supprimé (`deleted_at`), et tout
    hachage qui ne commence pas par `$2a$` ou `$2b$` ;
  - compare contre un hachage factice quand l'e-mail est inconnu, pour un temps de réponse identique ;
  - reçoit un mot de passe déjà borné à 72 octets par l'API (pgcrypto ne lit pas au-delà).
- **Comptes sans mot de passe** (nés d'un lien magique, qui disparaît) : ils passent par « mot de passe
  oublié » pour en choisir un. Leur nombre est compté sur la copie de la prod pendant la répétition, et Kamil
  est prévenu s'il y en a dans le foyer.
- **Écrire un compte ou un mot de passe** (création à l'invitation, changement, réinitialisation, suppression)
  passe par l'API d'administration de Supabase Auth avec la clé secrète, après nos propres contrôles.
- **Session.** À la connexion, l'API crée un identifiant aléatoire de 256 bits, n'en garde que l'empreinte
  (table `session` : personne, appareil, création, dernière activité, échéance) et pose le cookie
  `__Host-popote_session` : `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`, sans `Domain`. En local, où le
  préfixe `__Host-` et `Secure` ne passent pas partout sur `http://localhost`, le nom et les attributs viennent
  de la configuration.
- **Durée.** 30 jours glissants, 90 jours au plus ; l'identifiant change à la connexion et à chaque changement
  de mot de passe.
- **Falsification de requête (CSRF).** `SameSite=Lax`, plus, sur toute méthode qui écrit : `Origin` égale à
  l'origine attendue, `Sec-Fetch-Site: same-origin`, et un en-tête propre à l'appli (guide OWASP sur le CSRF).
- **Mots de passe** (NIST SP 800-63B-4) : 15 caractères au moins quand le mot de passe est le seul facteur ;
  au plus 64 caractères et 72 octets une fois normalisé en NFKC (bcrypt ne lit pas au-delà) ; aucune règle de
  composition ; aucun changement imposé ; refus des mots de passe déjà fuités (requête par plage de hachage,
  sans envoyer le mot de passe). La règle vaut pour tout nouveau mot de passe ; les actuels restent valables
  jusqu'à leur prochain changement. Message unique en cas d'échec (« e-mail ou mot de passe incorrect »).
  Voir D3.
- **Réinitialisation.** Notre propre jeton (256 bits, gardé haché, usage unique, 30 minutes) dans une table
  dédiée ; le lien part par le fournisseur de mails (D6), depuis une adresse de `notre-popote.fr` avec SPF,
  DKIM et DMARC ; il ferme toutes les autres sessions. Le parcours de récupération de Supabase Auth n'est plus
  utilisé.
- **Invitation.** L'hôte crée un lien sans saisir d'e-mail ; jeton aléatoire de 256 bits gardé haché, valable
  7 jours, à usage unique (consommé de façon atomique), révocable, listé tant qu'il attend. L'invitée y saisit
  son e-mail et son mot de passe ; si l'e-mail a déjà un compte, l'invitation refuse et l'invite à se connecter
  (plus de reprise d'un compte existant). Son compte et sa session naissent ensemble. Risque accepté : ce refus
  apprend à qui tient un lien valide qu'une adresse a un compte ; seul un invité du foyer peut le savoir.
- **Appareils.** `GET /api/v1/me/sessions` liste les appareils (navigateur, système, dernière activité, sans
  localisation) ; on en ferme un, ou tous sauf celui-ci.
- **Gestes sensibles.** Supprimer son compte, changer d'e-mail ou de mot de passe demandent le mot de passe,
  saisi depuis moins de 5 minutes.
- **Supabase Auth verrouillé** (à la fermeture, § 11) : inscriptions publiques coupées, lien magique et code à
  usage unique coupés, longueur minimale alignée sur la nôtre, changement de mot de passe avec
  réauthentification, clés historiques désactivées, aucune clé publiable servie au navigateur. Ce qui n'est pas
  écrit dans la documentation de Supabase est prouvé sur l'essai à l'étape 0.2, et le résultat écrit dans la
  fiche de bascule : désactiver puis réactiver les clés historiques ; déposer et lire une photo, créer, modifier
  et supprimer un compte avec la seule clé secrète (`sb_secret`, passée dans `apikey`) ; savoir si la clé
  publiable par défaut peut être supprimée. Si elle ne le peut pas, `/auth/v1` ne tient que par les réglages
  ci-dessus, et c'est écrit.
- **Journal de sécurité.** Connexions réussies et ratées, déconnexions, changements et réinitialisations de mot
  de passe, invitations créées, acceptées ou révoquées, sessions fermées, comptes supprimés. Gardé un an.

---

## 5. Données et base

### 5.1 Qui exécute quoi
| Contexte | Rôle de connexion | Rôle emprunté | Identité posée | Sert à |
|---|---|---|---|---|
| Personne | `popote_api` | `set local role authenticated` | `request.jwt.claims` = `{"sub": <personne>, "role": "authenticated"}` | toute requête d'une personne connectée ; la RLS et les gardes (`tg_saisie_garde`, `tg_depense_garde`…) s'appliquent |
| Service | `popote_internal` | `set local role service_role` | `{"role": "service_role"}` | seulement les routes `/internal/*`, l'acceptation d'une invitation et les purges ; liste fermée, chaque usage relu |
| Connexion | `popote_api` | aucun : fonction `security definer` privée | aucune | vérifier un mot de passe |
| Sauvegarde | `postgres`, hors API | — | — | `pg_dump` lancé par GitHub Actions |

- **Deux rôles de connexion, deux pools.** `popote_api` n'est membre que d'`authenticated`, `popote_internal`
  que de `service_role`, tous deux `NOINHERIT` et sans super-utilisateur. Le pool de `popote_internal` n'est
  monté que par le code des routes internes, de l'invitation et des purges. Un `set role` oublié ou une
  injection dans une requête de personne ne peut donc pas atteindre le contournement de la RLS.
- La clé secrète Supabase (API d'administration d'Auth et Storage) vit dans le gestionnaire de secrets, lue
  seulement par les modules de connexion et de photos.
- `auth.uid()` lit `request.jwt.claims` : le contexte « personne » le satisfait.
- **La porte du service ne se fie plus à une revendication.** Aujourd'hui `is_service_role()` accepte
  `current_user = 'service_role'` ou la revendication `role = 'service_role'` de `request.jwt.claims` (parce que,
  dans une fonction `security definer`, `current_user` devient le propriétaire). Or cette revendication n'est
  qu'un paramètre de session : dans le pool « personne », un `set_config` injecté ouvrirait `rappels_a_envoyer`,
  `reserve_rappel` et les exemptions des gardes. Une migration compatible (avant 0.5) la réécrit :
  `session_user = 'popote_internal'` (le rôle de connexion, que ni une fonction `security definer` ni un
  paramètre ne changent), ou, jusqu'à la fermeture seulement, `session_user = 'authenticator'` avec la
  revendication `service_role` (le chemin des Edge Functions actuelles, dont PostgREST a vérifié la signature).
  La seconde branche part à J+2. `execute` sur les fonctions réservées au service est retiré à `authenticated`.
- L'étape 0.3 prouve tout cela par des tests sur une base locale, à travers le pooler en mode transaction :
  `set local` ne vit que le temps de la transaction ; une connexion rendue au pool ne garde ni rôle ni identité ;
  le pool « personne » qui pose la revendication `service_role` échoue sur `rappels_a_envoyer`.

### 5.2 Fermeture (préparée en 0.7, appliquée à J+2)
- Tous les droits retirés à `anon`. Ceux d'`authenticated` restent, puisque l'API les emprunte, mais plus aucun
  chemin du navigateur vers eux : API de données fermée (aucun schéma exposé), `pg_graphql` retiré, tables
  retirées de la publication `supabase_realtime`, politiques de `storage.objects` réduites au rôle de service.
- Les fonctions `security definer` restent dans `public` : la consigne de Supabase vise les schémas exposés, et
  `public` ne l'est plus. `execute` est retiré à `PUBLIC` et à `anon`, gardé à `authenticated` (que l'API
  emprunte) et à `service_role`. Les 41 clés étrangères sans index sont indexées, les politiques réécrites en
  `(select auth.uid())` (lint 0003), le linter Supabase ramené à zéro.
- Les rappels : la tâche `pg_cron` lit son adresse et son secret dans Vault ; une migration par environnement
  les repointe vers `/internal/reminders`. L'API répond vite (`202`) et fait le travail sous son délai ; la
  réservation existante (`reserve_rappel`) garde l'envoi unique.

### 5.3 Migrations
- En SQL, vers l'avant seulement, relues, appliquées par l'intégration continue de `popote-api` sur l'essai,
  puis sur la prod après une sauvegarde ; chaque migration dit comment revenir en arrière.
- Avant la bascule, seules des migrations **compatibles avec l'appli actuelle** touchent la prod (nouvelles
  tables : `session`, `idempotency_key`, `password_reset`, `llm_call`, `security_event` ; colonnes `version`) ;
  celles qui ferment l'accès partent le jour de la bascule.

### 5.4 Sauvegardes
- Chaque nuit, GitHub Actions (avec `postgresql-client-17`, par le pooler en mode session, en IPv4, rôle
  `postgres`) :
  - `pg_dump` des schémas `public`, `auth` et `storage`, plus la liste des rôles applicatifs et de leurs droits ;
  - copie des fichiers des seaux (photos, images des recettes) : le dump du schéma `storage` n'en garde que la
    description ;
  - chiffrement avec `age`, dépôt dans un stockage objet en Europe, gardé 30 jours.
- La clé privée `age` n'est jamais sur un serveur : Kamil la garde (gestionnaire de mots de passe), une copie
  hors ligne. Voir D5.
- La fiche de restauration part d'un projet Supabase **vide** : schéma par les migrations, rôles, puis données
  (celles d'`auth` en données seules, ses tables appartenant à `supabase_auth_admin`), fichiers des seaux,
  secrets de `vault` et tâches `cron` reposés à la main depuis la fiche. Restauration essayée une fois par mois.

---

## 6. Données sensibles et photos

### 6.1 Photos du frigo, des tickets, des étiquettes
- Aujourd'hui : des `data:` URL jusqu'à 6 Mo, jusqu'à 3 par appel, dans le JSON. Demain : le navigateur
  réduit chaque photo à 2 Mo au plus (déjà la limite du seau), l'envoie à l'API en `multipart/form-data`
  (3 photos et 8 Mo au plus pour ces routes), l'API la range dans un seau privé avec la clé secrète, puis
  l'envoie au modèle de vision.
- Une photo de saisie est effacée au bout de 30 jours, sauf si elle illustre une barquette ou une recette ; la
  suppression du compte efface les siennes.

### 6.2 Images des recettes
- `recipe.image_url` contient aujourd'hui des URL publiques du seau ou des sites d'origine, et le déclencheur
  `tg_recipe_photo` n'accepte que ce format. Une migration compatible ajoute `image_path` (chemin d'objet),
  rempli à côté d'`image_url` ; le déclencheur accepte les deux. La nouvelle appli ne lit que `image_path`,
  mais remplit encore les deux pour toute nouvelle photo jusqu'à la fermeture ; `image_url` n'est retirée
  qu'après (§ 11), pour que l'ancienne appli reste entière pendant la fenêtre de retour arrière.
- L'API sert les images par un relais `GET /api/v1/images/{id}` : photos du seau privé, et images des sites
  d'origine copiées une fois dans le seau, depuis une liste blanche d'hôtes (le relais n'est pas un SSRF
  ouvert). Cache côté navigateur par `ETag`, pas de cache disque dans le conteneur.

---

## 7. Sécurité

### 7.1 Le Top 10 OWASP des API (2023), point par point
| Risque | Parade dans Popote |
|---|---|
| API1 Autorisation au niveau objet | Requêtes bornées au foyer de la session, RLS en double, et une matrice de tests : chaque route × {mon foyer, un autre foyer, sans session} |
| API2 Authentification | Sessions côté serveur (§ 4), limites comptées en base, mots de passe NIST, réinitialisation à usage unique, Supabase Auth fermé au navigateur |
| API3 Autorisation au niveau propriété | Modèles d'entrée fermés, modèles de sortie explicites |
| API4 Consommation sans limite | Débit, tailles, pagination plafonnée, quotas atomiques, plafond en euros, délais |
| API5 Autorisation au niveau fonction | Routes `/internal/*` signées à part, contexte service en liste fermée (§ 5.1) |
| API6 Flux métier sensibles | Connexion, réinitialisation, invitations et appels au modèle freinés |
| API7 SSRF | Import par lien et relais d'images : `https` seulement, liste blanche pour le relais, refus des adresses privées après résolution DNS, redirections contrôlées, taille et délai bornés |
| API8 Mauvaise configuration | En-têtes de sécurité, origine unique, erreurs normalisées, TLS seulement, HSTS, en-tête secret du relais |
| API9 Inventaire | Le contrat OpenAPI est l'inventaire ; essai et prod séparés ; Edge Functions et clés historiques supprimées à la bascule |
| API10 Consommation d'API tierces | Réponses des modèles et des fournisseurs validées par schéma, délais, coupe-circuit ; une sortie de modèle ne décide jamais d'un droit ni d'une requête |

### 7.2 L'IA (Top 10 OWASP des applications à base de modèles, 2025)
- Le texte de la personne et les contenus importés vont dans des blocs délimités, jamais dans les consignes.
- Un modèle n'agit sur les données que par des outils bornés au foyer, et tout geste qui écrit demande la
  confirmation de la personne (humain dans la boucle).
- On envoie le minimum : ni prénom, ni identifiant, ni montant quand ce n'est pas nécessaire.
- Chaque appel est journalisé (usage, modèle, durée, jetons, coût, résultat, erreur), sans les photos.

### 7.3 Le front
- CSP : `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:;
  connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self';
  upgrade-insecure-requests`.
- HSTS avec `preload`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`,
  `Permissions-Policy` réduite (appareil photo pour l'appli seulement), `Cross-Origin-Opener-Policy:
  same-origin`. Posés par l'hôte du front.
- Polices servies par notre domaine (plus d'appel à Google Fonts).

### 7.4 Secrets
- Dans le gestionnaire de secrets de l'hébergeur, jamais dans un dépôt ; `gitleaks` à chaque envoi.
- Déploiement par identité fédérée (OIDC) quand l'hébergeur le permet ; sinon une clé limitée au projet, à
  durée courte, renouvelée. Procédure écrite pour changer chaque secret.

### 7.5 Chaîne d'approvisionnement
- Versions figées (`uv.lock`, `package-lock.json`), mises à jour hebdomadaires automatiques et relues ;
  `pip-audit` et `npm audit` bloquants sur les failles hautes ; actions GitHub figées par empreinte, droits
  minimaux par workflow ; image du conteneur minimale, sans root, scannée (Trivy) ; SBOM CycloneDX produit.

### 7.6 Vérification : OWASP ASVS niveau 2
Le niveau 2 vise les applications qui tiennent des données personnelles et financières : c'est le cas. À
l'étape 0.8, chaque exigence applicable est cochée avec sa preuve (test, configuration ou revue), les
exceptions écrites. Chapitres prioritaires : authentification, sessions, contrôle d'accès, validation, API,
configuration, journalisation, protection des données.

### 7.7 RGPD
- Données et traitements en Europe ; liste des sous-traitants tenue (Supabase, hébergeurs, fournisseurs de
  modèles, envoi de mails) avec leurs conditions de conservation vérifiées.
- Conservation : journaux applicatifs 30 jours, journal de sécurité 1 an, journal des appels au modèle 90 jours,
  photos de saisie 30 jours.
- Export et suppression du compte restent des routes de l'API.

---

## 8. Conventions de code

### 8.1 Communes
- Identifiants du code et de l'API en anglais ; textes de l'écran, documentation et messages de commit en
  français.
- Commits Conventional Commits (`feat`, `fix`, `refactor`, `test`, `docs`, `chore`), description en français,
  sans ligne de co-auteur. Branches `type/sujet`. Demandes de fusion courtes (400 lignes visées), gabarit à
  quatre parties (quoi, pourquoi, comment vérifié, risques).
- `main` protégée : fusion seulement avec l'intégration continue verte et la revue faite.
- Chaque étape se ferme par une revue adverse (agent à l'œil frais), les tests par mutation sur la logique
  d'argent et de cycle, et un essai au navigateur avec captures regardées.

### 8.2 `popote-api`
```
src/popote_api/
  main.py          fabrique de l'application, middlewares
  config.py        réglages lus de l'environnement (pydantic-settings)
  api/             un routeur par domaine : auth, households, recipes, cycles, meals, stock, budget, reminders,
                   ai, images, internal
  schemas/         modèles Pydantic d'entrée et de sortie
  domain/          règles pures, sans entrée-sortie
  infra/           base (pool, transactions par contexte), dépôts de requêtes SQL, admin Supabase Auth, stockage,
                   passerelle des modèles, mails
  security/        sessions, mots de passe, CSRF, limites de débit, idempotence, signature des routes internes
  errors.py        Problem Details
tests/             unit, integration (vraie base locale), contract, authz (matrice), db (repris de l'ancien dépôt)
supabase/          migrations et configuration de la CLI
load/              scénarios k6
docs/              normes d'API, sécurité, exploitation, fiche de bascule
```
- Pas de logique métier dans un routeur ; tout est typé (`mypy --strict`) ; aucune réponse en `dict` brut ;
  SQL toujours paramétré ; transactions explicites, ouvertes dans le bon contexte (§ 5.1) ; une erreur de la base
  devient un Problem Details.

### 8.3 `popote-web`
- TypeScript strict ; routes typées (TanStack Router) avec chargement à la demande par route ; une frontière
  d'erreur par route ; données seulement par le client généré et des hooks TanStack Query par ressource, avec
  des clés précises (plus d'invalidation globale) ; aucun `fetch` hors de la couche API.
- Le relais Cloudflare (fichiers + `/api/*`) vit dans ce dépôt, avec l'adresse de l'API de chaque
  environnement en configuration.
- Suivi des erreurs du navigateur (D4) et budgets de performance (Lighthouse) dans l'intégration continue.

---

## 9. Tests et preuves

### 9.1 Ce qui part où
- Les tests de base actuels (`tests/`, 76 fichiers, environ 1 100 cas : RLS, isolation des foyers,
  déclencheurs, budget) partent dans `popote-api/tests/db/`. Ils passent par PostgREST avec `supabase-js`.
- La CI de `popote-api` monte donc **deux états** de la même base locale, aux mêmes migrations :
  - **ouvert** : `public` exposé à PostgREST, pour les tests de base repris tels quels (les fonctions restent
    dans `public`, § 5.2, donc leurs `.rpc()` marchent) ;
  - **fermé** : identique à la prod (aucun schéma exposé, droits d'`anon` retirés), pour la matrice
    d'autorisation, les tests de l'API et les e2e.
  Les tests de base sont portés en Python au fil des parcours, quand on touche à leur domaine ; l'état
  « ouvert » disparaît avec le dernier.
- Les tests purs du front (`src/**/*.test.ts`) restent dans `popote-web` ; les specs Playwright aussi, jouées
  contre une pile locale complète (base, API, front).

### 9.2 Ce qui tourne à chaque envoi
| Dépôt | Contrôles |
|---|---|
| `popote-api` | ruff, mypy, pytest (unit, integration sur une base Supabase locale, matrice d'autorisation, tests de base repris), Schemathesis sur le contrat, oasdiff, pip-audit, gitleaks, Semgrep, construction et scan de l'image |
| `popote-web` | oxlint, tsc, vitest, génération du client (écart = échec), build, npm audit, gitleaks, Playwright sur une pile locale complète |

### 9.3 Tenue en charge (k6), sur l'essai
- Charge : 50 utilisateurs virtuels pendant 10 minutes (25 fois l'usage réel) : lectures p95 < 300 ms,
  écritures p95 < 500 ms (hors appels au modèle), moins de 0,5 % d'erreurs, instance déjà chaude (D1).
- Pic : 200 utilisateurs pendant 1 minute : aucune panne, des `429` propres.
- Endurance : 10 utilisateurs pendant 1 heure : mémoire stable.
- Course aux quotas : 50 appels simultanés au modèle pour un quota de 10 : exactement 10 acceptés.
- Ouverture à froid de l'accueil : temps mesuré, nombre de requêtes compté.

### 9.4 Définition de « fini » d'une étape
Tests verts, intégration continue verte, revue adverse faite et ses constats traités, essai au navigateur avec
captures regardées, documentation à jour, déployé sur l'essai.

---

## 10. Environnements et exploitation

| | Base | API | Front |
|---|---|---|---|
| Local | `supabase start` | `uv run` | Vite, avec un proxy `/api` vers l'API locale |
| Essai | second projet Supabase (l'offre gratuite en permet deux), réveillé chaque jour | déploiement d'essai | `essai.notre-popote.fr`, et un aperçu par demande de fusion qui relaie vers l'API d'essai |
| Prod | projet actuel (`mjlxfffdirlqmmjzhorg`, Paris) | déploiement de prod | `notre-popote.fr` |

- `main` part sur l'essai automatiquement ; la prod part sur un tag, avec une approbation.
- Suivi : journaux de l'hébergeur, traces OpenTelemetry, erreurs du front et de l'API (D4), sonde de
  disponibilité toutes les 5 minutes, alertes par mail.
- Fiches d'exploitation : panne de la base, base en pause, fournisseur de modèle en panne, secret à changer,
  restauration d'une sauvegarde, bascule et retour arrière.

**Preuves à faire dès l'étape 0.2, sur l'essai** (ce que la documentation ne garantit pas) :
1. clés historiques : désactiver, travailler avec la seule clé secrète (Storage, administration d'Auth),
   réactiver ; suppression possible ou non de la clé publiable par défaut ; peut-on couper la connexion par
   mot de passe de GoTrue (`/auth/v1/token`) tout en gardant son administration (`createUser`, `updateUser`) ?
   Sinon, ce point d'entrée reste un chemin de force brute pour qui connaît une clé publiable : c'est écrit, et
   la clé n'est jamais publiée (§ 4) ;
2. réveil : lancée **au premier jour de 0.2**, car elle demande plus de 7 jours d'inactivité mesurée. Une
   requête de l'API sur `/api/readyz`, qui lit une vraie table, suffit-elle à garder le projet éveillé ? Si
   non, le recours est un appel planifié par un chemin que Supabase compte comme activité, ou l'offre payante
   (D5). L'ancien réveil (`reveil.yml`, par la clé historique) reste en place jusqu'à J+2, où son remplaçant le
   relaie (§ 11) ;
3. rôles : `popote_api` et `popote_internal` créés sur l'essai, connexion par Supavisor (`rôle.<réf>`) et
   `set local role` vérifiés ailleurs que sur le pooler local ;
4. relais Cloudflare : cookie `__Host-` posé à travers le relais, `no-store` respecté, en-tête secret, IP lue ;
5. démarrage à froid du conteneur mesuré (pour D1) ;
6. sauvegarde puis restauration complète dans un projet vide (§ 5.4).

**L'ordre de l'étape 0.**

| Étape | Contenu | Ce que Kamil voit |
|---|---|---|
| 0.1 | Ce document | Rien |
| 0.2 | Deux dépôts, intégration continue, trois environnements, domaine, hébergement ; inventaire des routes ; sauvegarde nocturne et sa restauration, avant toute migration en prod ; preuves ci-dessus lancées (le réveil dès le premier jour) | Rien |
| 0.3 | Cœur de l'API : erreurs, journal, traces, limites, idempotence, ETag, contrat, contextes d'exécution et leurs tests, nouvelle porte du service, `/api/v1/me` | Rien |
| 0.4 | Connexion : sessions, mots de passe, invitation, réinitialisation, appareils, suppression, journal de sécurité | Rien (elle ne sert qu'à la nouvelle appli, pas encore en ligne) |
| 0.5 | Domaines branchés un par un dans la nouvelle appli : foyer et réglages → recettes → cycle, courses, plan, session, dressage → semaine, repas, frigo, stock → budget → rappels ; photos et relais d'images | Rien |
| 0.6 | IA derrière l'API : passerelle des modèles, journal, quotas atomiques, erreurs normalisées ; analyseur d'ingestion porté en Python | Rien |
| 0.7 | Fermeture préparée et essayée sur l'essai : droits, API de données, Auth verrouillé, index, linter à zéro ; répétition de la bascule | Rien |
| 0.8 | Preuves (ASVS, ZAP, charge, contrat) ; bascule au jour J, fermeture à J+2 (§ 11) | La nouvelle adresse, une reconnexion, l'appli à réinstaller |

Chaque domaine de 0.5 suit la même boucle : routes et tests dans l'API → hooks du front basculés → e2e vertes
en local et sur l'essai. L'appli en prod ne change qu'au jour J ; avant, seules des migrations compatibles
touchent sa base, chacune après la sauvegarde (§ 5.3).

---

## 11. La bascule, puis la fermeture

**La répétition.** Sur l'essai, avec la CI d'essai suspendue : une copie de la prod y est chargée le temps de
la répétition seulement, puis effacée, et l'essai est réensemencé avec des données fictives (pas de données ni
de hachages réels dans un projet servi aux e2e et à k6). On y compte aussi les comptes sans mot de passe (§ 4).

**Avant le jour J.** La dernière version de l'ancien site est publiée et essayée sur un téléphone où la PWA est
installée : elle désinscrit son service worker, vide son cache et renvoie vers `notre-popote.fr` avec un
bandeau « Popote a déménagé » (GitHub Pages ne sait pas rediriger). Elle n'est activée que le jour J.

**Jour J, la bascule (réversible).**
1. Sauvegarde de la prod, vérifiée.
2. Migrations compatibles restantes ; déploiement de l'API et du front de prod ; e2e de fumée sur
   `notre-popote.fr`.
3. Activation du renvoi sur l'ancien site.
4. Kamil et Thauba se reconnectent avec leur mot de passe habituel et réinstallent l'appli sur l'écran
   d'accueil (une PWA est liée à son adresse ; ce qui était gardé dans le navigateur ne suit pas).
Tant que la fermeture n'est pas faite, la base reste ouverte comme aujourd'hui : retour arrière = désactiver le
renvoi de l'ancien site.

**J+2, la fermeture (sans retour arrière).** Après deux jours d'usage normal : le réveil de la base passe au
remplaçant prouvé en 0.2 (et `reveil.yml` est retiré de l'ancien dépôt), puis migrations de fermeture
(§ 5.2), retrait de la branche `authenticator` d'`is_service_role()` (§ 5.1), verrouillage de Supabase Auth
(§ 4), désactivation des clés historiques, suppression des Edge Functions ; une semaine plus tard, retrait
d'`image_url`. Au-delà, on corrige en avant. Ce qui rend ce point sûr : la répétition, les preuves de 0.2, et
la sauvegarde du matin même.

---

## 12. Décisions qui reviennent à Kamil (posées une à une, en conversation)

| # | Question | Quand | Recommandation à vérifier avant de la poser |
|---|---|---|---|
| D1 | Où héberger l'API, et faut-il une instance toujours chaude | 0.2 | Scaleway Serverless Containers à Paris (société française, palier gratuit, domaine et TLS gérés). Une instance toujours chaude coûte de l'ordre de 5 € par mois et supprime les démarrages à froid ; sans elle, gratuit, mais une première ouverture plus lente. |
| D2 | Où héberger le front et le relais | 0.2 | Cloudflare (fichiers + relais `/api`, en-têtes, aperçus) ; le DNS de `notre-popote.fr` passe chez Cloudflare, OVHcloud reste le registraire |
| D3 | Mot de passe de 15 caractères, ou clé d'accès (empreinte, visage) | 0.4 | Les clés d'accès de Supabase sont en bêta depuis le 28/05/2026 : à évaluer |
| D4 | Suivi des erreurs | 0.3 | Un service hébergé en Europe, palier gratuit |
| D5 | Sauvegardes : les nôtres (gratuit) ou l'offre payante de Supabase (25 $/mois : sauvegardes et plus de pause) ; et qui garde la clé de chiffrement | 0.2 | Les nôtres, tant que l'usage reste celui d'un foyer ; la clé chez Kamil |
| D6 | Fournisseur de mails (réinitialisation, rappels), depuis `notre-popote.fr` | 0.4 | Un fournisseur européen avec un palier gratuit ; aujourd'hui les rappels partent du Gmail de Popote par SMTP |

---

## 13. Sources officielles

- RFC 9110, HTTP Semantics : https://www.rfc-editor.org/rfc/rfc9110.html
- RFC 9457, Problem Details for HTTP APIs : https://www.rfc-editor.org/rfc/rfc9457.html
- RFC 10017 (BCP 212), OAuth 2.0 for Browser-Based Applications : https://datatracker.ietf.org/doc/rfc10017/
- RFC 6265, cookies : https://www.rfc-editor.org/rfc/rfc6265.html ; préfixe `__Host-` : brouillon RFC 6265bis
- RFC 6585 (429), RFC 7396 (JSON Merge Patch), RFC 6901 (JSON Pointer), RFC 8594 (`Sunset`), RFC 9745 (`Deprecation`)
- Brouillon IETF Idempotency-Key : https://datatracker.ietf.org/doc/draft-ietf-httpapi-idempotency-key-header/
- Brouillon IETF RateLimit : https://datatracker.ietf.org/doc/draft-ietf-httpapi-ratelimit-headers/
- OpenAPI Specification : https://spec.openapis.org/oas/latest.html
- OWASP API Security Top 10 (2023) : https://owasp.org/API-Security/editions/2023/en/0x11-t10/
- OWASP Top 10 for LLM Applications (2025) : https://genai.owasp.org/llm-top-10/
- OWASP ASVS : https://owasp.org/www-project-application-security-verification-standard/
- OWASP, guides session et CSRF : https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html ,
  https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html
- NIST SP 800-63B-4 : https://pages.nist.gov/800-63-4/sp800-63b/authenticators
- W3C Trace Context : https://www.w3.org/TR/trace-context/ ; OpenTelemetry : https://opentelemetry.io/docs/
- Twelve-Factor App : https://12factor.net/fr/
- Supabase : sécurité de l'API https://supabase.com/docs/guides/api/securing-your-api ; RLS
  https://supabase.com/docs/guides/database/postgres/row-level-security ; linter
  https://supabase.com/docs/guides/database/database-linter ; mise en production
  https://supabase.com/docs/guides/platform/going-into-prod ; JWT https://supabase.com/docs/guides/auth/jwts ;
  clés d'accès https://supabase.com/docs/guides/auth/passkeys
- Scaleway, domaine personnalisé d'un conteneur :
  https://www.scaleway.com/en/docs/serverless-containers/how-to/add-a-custom-domain-to-a-container/
