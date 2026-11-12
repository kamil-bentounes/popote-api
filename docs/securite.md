# Sécurité

Connexion, sessions, rôles de base de données, photos et sécurité de l'API de `popote-api`. Extraits des
§ 4, § 5.1, § 6 et § 7 de la [spec du socle](https://github.com/kamil-bentounes/popote-web/blob/main/docs/superpowers/specs/2026-11-12-socle-design.md), dont ce document garde la numérotation : un renvoi « § »
désigne la spec, qui reste la référence en cas d'écart. Les règles de forme des routes sont dans
[`normes-api.md`](normes-api.md).

| Pour savoir | Aller à |
|---|---|
| Comment on se connecte, ce que garde le navigateur | 4 |
| Les règles de mot de passe, la liste de fuites, leurs sources et leurs écarts | 4.1 |
| Quel rôle de base exécute quelle requête | 5.1 |
| Où vont les photos, comment les images sont servies | 6 |
| Les parades OWASP, la CSP, les secrets, la chaîne d'approvisionnement, le RGPD | 7 |
| Ce qui est prouvé aujourd'hui sur les rôles | « État au 12/11/2026 », en bas |

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
- **Lire la session (0.3, migration 0133).** Table `public.login_session` (`login_session` : `session` désigne
  déjà la séance de cuisine et `auth.sessions` celle de GoTrue) : `token_hash` (SHA-256 des 32 octets, unique),
  `person_id` (cascade à la suppression du compte), `created_at`, `last_seen_at`, `expires_at` (glissante),
  `absolute_expires_at` (90 jours), `revoked_at`. RLS activée sans politique, aucun droit à personne. La colonne
  d'appareil arrive en 0.4 avec la création des sessions. `public.session_personne(p_hash bytea)` est
  `security definer`, `search_path = ''`, exécutable par `popote_api` **seul** (`revoke` explicite à `public`,
  `anon`, `authenticated`, `service_role`) ; elle rend la personne ou `null` (inconnue, échue, révoquée, au bout
  des 90 jours, `banned_until` futur, `deleted_at` posé). Elle repousse l'échéance
  (`least(now() + 30 jours, absolute_expires_at)`) et `last_seen_at` **au plus une fois toutes les 5 minutes** :
  une lecture n'est pas une écriture à chaque requête. L'API l'appelle en `popote_api`, avant d'emprunter
  `authenticated`, dans la **même transaction** que le reste de la requête.
- **Le cookie** ne porte que le jeton : 43 caractères base64url (32 octets), décodage strict. Hors local son nom
  est `__Host-popote_session` et un autre nom est refusé au démarrage.
- **Falsification de requête (CSRF).** `SameSite=Lax`, plus, sur toute méthode qui écrit : `Origin` égale à
  l'origine attendue, `Sec-Fetch-Site: same-origin`, et un en-tête propre à l'appli (guide OWASP sur le CSRF).
- **Mots de passe** (NIST SP 800-63B-4) : 15 caractères au moins quand le mot de passe est le seul facteur ;
  au plus 64 caractères et 72 octets une fois normalisé en NFKC (bcrypt ne lit pas au-delà) ; aucune règle de
  composition ; aucun changement imposé ; refus des mots de passe déjà fuités (requête par plage de hachage,
  sans envoyer le mot de passe ; liste indisponible : accepté et journalisé, voir 4.1). La règle vaut pour tout nouveau mot de passe ; les actuels restent valables
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

### 4.1 Règles de mot de passe et liste de fuites (code : `security/mots_de_passe.py`, `infra/fuites.py`)

Sources relues à la source le 12/11/2026 : NIST SP 800-63B-4, [§ 3.1.1.2 « Password Verifiers »](https://pages.nist.gov/800-63-4/sp800-63b.html)
(les références ci-dessous sont des items de cette section), et la documentation de l'API [Pwned Passwords](https://haveibeenpwned.com/API/v3#PwnedPasswords).

| Règle | Source | Réalisation |
|---|---|---|
| 15 caractères au moins quand le mot de passe est le seul facteur (8 seulement avec un second facteur : sans objet, il n'y en a pas) | NIST 3.1.1.2, 1er item, « SHALL » | `LONGUEUR_MINIMALE = 15` |
| Un point de code compte pour un caractère | NIST 3.1.1.2, « SHALL » | longueur prise en `len()` après normalisation |
| Permettre 64 caractères au moins | NIST 3.1.1.2, « SHOULD » | `LONGUEUR_MAXIMALE = 64`, plus 72 octets UTF-8 (écart 2) |
| Aucune règle de composition, espaces et Unicode acceptés | NIST 3.1.1.2, « SHALL NOT » / « SHOULD » | aucune règle ; espaces conservés, jamais rognés |
| Ne pas tronquer | NIST 3.1.1.2, « SHALL verify the entire submitted password » | trop long : refusé à la création ; à la connexion, le candidat de plus de 72 octets est **écarté**, jamais coupé |
| Comparer à une liste de blocage (mots de passe fuités), mot de passe entier | NIST 3.1.1.2, « SHALL » | Pwned Passwords, ci-dessous |
| Normaliser avant de hacher | NIST 3.1.1.2, « SHOULD » (forme NFC) | NFKC (écart 1) |

Écarts assumés :

1. **NFKC et non NFC.** NIST écrit NFC (sa version 800-63B-3 écrivait NFKC ou NFKD). NFKC compose comme NFC et
   ramène en plus les formes de compatibilité (lettres pleine largeur, ligatures) à leur équivalent : un clavier
   japonais ou un correcteur qui produit `ＡＢＣ` donne le même mot de passe que `ABC`. Les anciens mots de
   passe ont été hachés bruts par GoTrue : à la connexion, on essaie la forme normalisée puis la forme brute
   (`candidats_de_connexion`).
2. **72 octets.** bcrypt (pgcrypto, GoTrue) ne lit pas au-delà de 72 octets. Plutôt que de tronquer (deux
   mots de passe distincts seraient acceptés l'un pour l'autre), on refuse. Conséquence : en dessous des 64
   caractères que NIST demande de permettre, un mot de passe d'accents ou d'idéogrammes plus long que 72 octets
   (36 caractères de deux octets, 24 de trois) est refusé avec un message qui le dit.

**Liste de fuites.** API « range » : `GET https://api.pwnedpasswords.com/range/{5 premiers caractères du SHA-1}`
(§ « Searching by hash range using k-anonymity ») ; réponse `SUFFIXE:COMPTE` par ligne, la comparaison du suffixe
se fait chez nous, sans casse. L'en-tête `Add-Padding: true` (§ « Introducing padding ») fait renvoyer 800 à
1 000 lignes quel que soit le préfixe, les lignes de bourrage ayant un compte de 0 : on les ignore. L'API exige un
agent utilisateur (§ « Specifying the user agent », absence : `403`) : nous envoyons `popote`, sans version ni nom
d'hôte. Pas de clé ni de limite de débit (§ « Authorisation », § « Rate limiting »). Notre appel : adresse et hôte
constants en `https`, redirections refusées, délai total de 3 s lecture comprise, corps lu par morceaux et
abandonné au-delà de 1 Mio, toute ligne mal formée (ou un corps vide) rend la réponse suspecte.

**Quand la liste est indisponible** (décision du 12/11/2026, B23 du plan 0.4) : le mot de passe est **accepté**
et l'indisponibilité journalisée par l'appelant (événement de sécurité `verification_fuites_indisponible` et un
avertissement, avec la seule cause : `delai`, `reseau`, `redirection`, `statut`, `trop_gros` ou `mal_forme`),
pour tous les parcours. Raison : un foyer de deux personnes ne doit pas être bloqué hors de son compte par la
panne d'un service tiers, et les règles de longueur restent appliquées. Risque accepté : pendant une panne, un
mot de passe fuité peut passer ; l'événement permet de le voir. `PwnedPasswords.verifie` ne lève jamais pour
cela : il rend un `ResultatFuite`. Rien du mot de passe, de son empreinte ni de sa plage n'est journalisé
(httpx écrit pourtant l'adresse à `INFO` : le module fait taire ce journal).

**Réglage.** `POPOTE_BREACH_CHECK` : `hibp` (défaut) ou `off`. `off` n'est permis qu'en local ; `essai` et `prod`
refusent de démarrer avec autre chose que `hibp`.

## 5.1 Qui exécute quoi (extrait du § 5)

| Contexte | Rôle de connexion | Rôle emprunté | Identité posée | Sert à |
|---|---|---|---|---|
| Personne | `popote_api` | `set local role authenticated` | `request.jwt.claims` = `{"sub": <personne>, "role": "authenticated"}` | toute requête d'une personne connectée ; la RLS et les gardes (`tg_saisie_garde`, `tg_depense_garde`…) s'appliquent |
| Service | `popote_internal` | `set local role service_role` | `{"role": "service_role"}` | seulement les routes `/internal/*`, l'acceptation d'une invitation et les purges ; liste fermée, chaque usage relu |
| Connexion | `popote_api` | aucun : fonction `security definer` privée | aucune | vérifier un mot de passe ; lire la session (`session_personne`), avant d'emprunter `authenticated` dans la même transaction |
| Sauvegarde | `postgres`, hors API | — | — | `pg_dump` lancé par GitHub Actions |

- **Deux rôles de connexion, deux pools.** `popote_api` n'est membre que d'`authenticated`, `popote_internal`
  que de `service_role`, tous deux `NOINHERIT` et sans super-utilisateur. Le pool de `popote_internal` n'est
  monté que par le code des routes internes, de l'invitation et des purges. Un `set role` oublié ou une
  injection dans une requête de personne ne peut donc pas atteindre le contournement de la RLS.
- **Un contexte = une transaction.** `Base.personne(id)` et `Base.service()` (`infra/db.py`) ouvrent chacun une
  transaction dans le bon rôle ; tout y est posé par `set local` ou `set_config(…, true)` et meurt au `commit`
  ou au `rollback` (aussi sur une annulation côté client : la connexion rendue au pool est propre).
  `POPOTE_DATABASE_URL` est le rôle `popote_api`, exigé hors local ; `POPOTE_DATABASE_URL_INTERNAL`, le rôle
  `popote_internal`, est facultative pour l'instant : sans elle l'application démarre avec un avertissement et
  `Base.service()` lève `ServiceIndisponibleError`, rendue `503 service_indisponible`.
- **Délais côté base** (migration `0132`), parce que l'annulation côté client ne coupe pas la requête sous
  Supavisor : `popote_api` 8 s de requête, 5 s d'attente de verrou, 15 s de transaction inactive ;
  `popote_internal` 30 s, 10 s, 15 s. `set role` n'applique pas les réglages du rôle emprunté : le code répète les
  mêmes valeurs par `set local` à chaque transaction (un test compare les deux).
- La clé secrète Supabase (API d'administration d'Auth et Storage) vit dans le gestionnaire de secrets, lue
  seulement par les modules de connexion et de photos.
- **Revendications posées par le contexte personne** : `sub`, `role = authenticated` et `iss`
  (`<POPOTE_SUPABASE_URL>/auth/v1`), les trois seules que le SQL lit (inventaire des migrations :
  `auth.uid()` lit `sub` ; `is_service_role()` et `auth.role()` lisent `role` ; `tg_recipe_photo` lit `iss`
  pour reconnaître l'adresse d'une photo du projet). PostgREST pose le JWT entier de GoTrue (`aud`, `exp`, `iat`,
  `email`, `phone`, `app_metadata`, `user_metadata`, `aal`, `amr`, `session_id`, `is_anonymous` en plus) : aucune
  requête ne lit ces autres champs. `tests/unit/test_revendications.py` échoue si une migration lit une
  revendication de plus. Sans `POPOTE_SUPABASE_URL` (facultative), `iss` manque et `tg_recipe_photo` refuse
  toute photo : elle devient nécessaire avec les photos de recettes (0.5).
- **La porte du service ne se fie plus à une revendication** (migration `0131`). `is_service_role()` lit
  `session_user`, le rôle de connexion, que ni un `set role`, ni une fonction `security definer`, ni un
  paramètre ne changent. Vraie pour `popote_internal` et, **jusqu'à la fermeture (J+2)**, pour `authenticator`
  (PostgREST) avec la revendication `service_role` dont il a vérifié la signature : le chemin des Edge Functions
  actuelles. Tout autre rôle (`popote_api`, `postgres`…) est refusé, même avec la revendication : un
  `set_config` injecté dans le pool « personne » n'ouvre plus rien. `execute` sur les fonctions réservées
  (`rappels_a_envoyer`, `reserve_rappel`, `libere_rappel`, `prepare_les_rappels`, `note_la_passe`…) : `service_role`
  seul. Tests : `tests/integration/test_porte_du_service.py`.
- L'étape 0.3 prouve tout cela par des tests sur une base locale, à travers le pooler en mode transaction :
  `set local` ne vit que le temps de la transaction ; une connexion rendue au pool ne garde ni rôle ni identité ;
  le pool « personne » qui pose la revendication `service_role` échoue sur `rappels_a_envoyer`.

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
  modèles, envoi de mails, Pwned Passwords) avec leurs conditions de conservation vérifiées.
- **Pwned Passwords** (`api.pwnedpasswords.com`, service de Have I Been Pwned) : reçoit les 5 premiers
  caractères hexadécimaux du SHA-1 d'un nouveau mot de passe, l'adresse IP du serveur de l'API et l'agent
  `popote`. Il ne reçoit ni e-mail, ni identifiant, ni compte, ni le mot de passe, ni le reste de l'empreinte :
  aucune donnée d'une personne identifiable, d'où aucune conservation à convenir. À confirmer : la
  localisation du service (hors Union européenne ou non) et son éventuel statut de sous-traitant ne sont pas
  établis par ce document ; à faire valider avant la bascule (0.8).
- Conservation : journaux applicatifs 30 jours, journal de sécurité 1 an, journal des appels au modèle 90 jours,
  photos de saisie 30 jours.
- Export et suppression du compte restent des routes de l'API.

## État au 12/11/2026 (étape 0.2)

| Fait | Détail |
|---|---|
| Rôles créés | `popote_api` et `popote_internal` existent (migration `0130_roles_api.sql`), `login noinherit nosuperuser`, droits d'emprunt par `grant … with inherit false, set true`. |
| Preuve 3 | Les quatre emprunts de rôle (et l'absence de droit sans emprunt) donnent le même résultat en direct sur Postgres et à travers Supavisor, en mode transaction. Détail et commandes : [`preuves-0.2.md`](preuves-0.2.md). |
| Règle sur le pooler | `SET ROLE` de session fuit entre clients du pooler en mode transaction : un client qui le lance laisse le serveur sous ce rôle pour les connexions suivantes. Seul `SET LOCAL ROLE` est permis ; jamais de `SET` sans `LOCAL`. |
| `execute` hérité de `PUBLIC` | 21 fonctions de déclencheur (`tg_*`) de `public` gardent le droit `execute` de `PUBLIC`. Elles ne s'appellent pas directement : l'exposition réelle est nulle aujourd'hui. À fermer à l'étape 0.7 (§ 5.2). |
| Projet d'essai | Il est en `eu-west-1`, alors que la prod est en `eu-west-3`. Le § 5.1 vaut dans les deux régions. |

Le contrôle `xfail(strict=True)` du test sur `execute` fera échouer la suite le jour où la migration de
fermeture retirera ce droit : il faudra alors retirer le `xfail`.
