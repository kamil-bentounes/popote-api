# Sécurité

Connexion, sessions, rôles de base de données, photos et sécurité de l'API de `popote-api`. Extraits des
§ 4, § 5.1, § 6 et § 7 de la [spec du socle](https://github.com/kamil-bentounes/popote-web/blob/main/docs/superpowers/specs/2026-11-12-socle-design.md), dont ce document garde la numérotation : un renvoi « § »
désigne la spec, qui reste la référence en cas d'écart. Les règles de forme des routes sont dans
[`normes-api.md`](normes-api.md).

| Pour savoir | Aller à |
|---|---|
| Comment on se connecte, ce que garde le navigateur | 4 |
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

## 5.1 Qui exécute quoi (extrait du § 5)

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
  modèles, envoi de mails) avec leurs conditions de conservation vérifiées.
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
