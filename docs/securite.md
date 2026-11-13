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
  - refuse sans exception et sans dire pourquoi : adresse inconnue, deux comptes pour la même adresse (à la casse
    près), compte SSO ou anonyme, banni (`banned_until` dans le futur), supprimé (`deleted_at`), hachage vide, nul ou
    mal formé, adresse non confirmée (`email_confirmed_at` nul : GoTrue refuse aussi cette connexion, et sans cela
    une inscription avec l'adresse d'un tiers ouvrirait la porte), mot de passe vide, nul ou de plus de 72 octets ;
    un compte supprimé ne compte pas dans le doublon d'adresse ;
  - **n'accepte que `$2a$`** (B15, migration 0137) : pgcrypto ne reconnaît pas `$2b$` ni `$2y$` et, devant un préfixe
    inconnu, retombe sur l'ancien `crypt` DES sans erreur (vérifié). Un compte à un autre préfixe passe par « mot
    de passe oublié » (il a un profil) ; les préfixes **et les coûts** (`$2a$10$`) des hachages de la prod sont comptés à la répétition de la bascule : le
    hachage factice a le coût 10, un autre coût en prod ferait dire au temps que le compte existe ;
  - fait **exactement un `crypt()` dans toutes les branches** : le vrai hachage, ou un hachage factice de même
    coût (`$2a$10$`) pour un compte inconnu, banni, supprimé, sans hachage ou mal formé. Mesuré en local le 12/11 :
    58,7 ms pour un compte connu et un mauvais mot de passe, 59,5 ms pour une adresse inconnue (médiane de 25) ;
  - reçoit un mot de passe déjà borné à 72 octets par l'API (`candidats_de_connexion`) et le refuse au-delà, **sans
    le tronquer** (une troncature accepterait un mot de passe qui n'est pas le bon) ;
  - cherche l'e-mail sous la forme de l'API (`email_normalise`, la même que la clé de limite : B24), en égalité
    après `lower(btrim())`, jamais en motif (`ilike`) ;
  - `popote_api` seul l'exécute (`Base.connexion()`) ; la variante `verifie_mot_de_passe_de(personne, mot de
    passe)` sert la réauthentification. Une fonction interne (`private.mot_de_passe_correspond`) porte le `crypt()`.
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
  `absolute_expires_at` (90 jours), `revoked_at`. RLS activée sans politique, aucun droit à aucun rôle de l'application (les rôles de maintenance de Supabase,
  qui contournent la RLS, peuvent la lire : elle ne garde que des empreintes SHA-256 de jetons de 256 bits). La colonne
  d'appareil arrive en 0.4 avec la création des sessions. `public.session_personne(p_hash bytea)` est
  `security definer`, `search_path = ''`, exécutable par `popote_api` **seul** (`revoke` explicite à `public`,
  `anon`, `authenticated`, `service_role`) ; elle rend la personne ou `null` (inconnue, échue, révoquée, au bout
  des 90 jours, `banned_until` futur, `deleted_at` posé). Elle repousse l'échéance
  (`least(now() + 30 jours, absolute_expires_at)`) et `last_seen_at` **au plus une fois toutes les 5 minutes** :
  une lecture n'est pas une écriture à chaque requête. L'API l'appelle en `popote_api`, avant d'emprunter
  `authenticated`, dans la **même transaction** que le reste de la requête. Le verrou de la ligne tient jusqu'à la
  fin de la requête : `for update skip locked` évite que deux requêtes simultanées s'attendent (la seconde lit
  l'ancienne valeur, encore valide).
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
  de passe, invitations créées, acceptées ou révoquées, sessions fermées, comptes supprimés. Gardé un an, sauf les
  échecs et blocages de connexion (90 jours) ; voir 4.2.

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
(httpx écrit pourtant l'adresse à `INFO` : `journal.configure()` fait taire ce journal, sans dépendre de
l'import de ce module).

**Réglage.** `POPOTE_BREACH_CHECK` : `hibp` (défaut) ou `off`. `off` n'est permis qu'en local ; `essai` et `prod`
refusent de démarrer avec autre chose que `hibp`.

### 4.2 Journal de sécurité et clés HMAC (0.4, migration 0136 ; code : `security/journal_securite.py`, `security/empreintes.py`)

- **Table `public.security_event`** : `id`, `occurred_at`, `kind` (liste fermée par CHECK : `connexion_reussie`,
  `connexion_ratee`, `connexion_bloquee`, `deconnexion`, `reauthentification_reussie`, `reauthentification_ratee`,
  `session_fermee`, `mot_de_passe_change`, `reinitialisation_demandee`, `reinitialisation_utilisee`,
  `invitation_creee`, `invitation_acceptee`, `invitation_revoquee`, `compte_supprime`, `compte_repris`,
  `verification_fuites_indisponible`, `code_demande` ; un test compare cette liste à l'énumération `Evenement`), `person_id`
  (`on delete set null`), `session_id` et `invitation_id` (sans clé étrangère : la session ou le lien peut être
  purgé avant l'événement), `account_key` et `ip_hash` (32 octets), `request_id` (32 caractères hexadécimaux, celui
  de l'API). **Rien d'autre** : ni e-mail, ni IP, ni agent utilisateur, ni champ libre. RLS activée et forcée, aucune
  politique, aucun droit à aucun rôle de l'application.
- **Clés HMAC.** `account_key` = HMAC-SHA256 du poivre sur l'e-mail normalisé (`email_normalise` : NFKC, minuscules,
  espaces de bord retirés : la forme unique, aussi pour la recherche en base et la création du compte) ; `ip_hash` =
  HMAC-SHA256 de l'IP canonique : IPv4 entière, `::ffff:a.b.c.d` ramenée à l'IPv4, **IPv6 réduite à son /64**, requête
  sans adresse = une clé commune « sans-ip ». Chaque clé a son étiquette : une clé de compte n'est jamais une clé
  d'IP. Le poivre (`POPOTE_IDENTITY_PEPPER`, 32 caractères au moins) n'apparaît dans aucun `repr` ni journal.
- **Sans poivre** (le conteneur d'essai ne l'a pas encore) : hors local, `cle_compte` et `cle_ip` rendent `None`,
  l'événement s'écrit **sans clés** (on perd le lien entre événements, pas l'événement) et un avertissement part au
  démarrage. Un appelant qui compte par clé (les limites de connexion) refuse au lieu de compter sans clé. En local
  le poivre est tiré au hasard par processus.
- **Conservation.** `connexion_ratee`, `connexion_bloquee` et `code_demande` (0147), liées à une clé de compte et non à une personne :
  **90 jours** ; tout le reste **1 an**. Purge par lots de 5 000, idempotente, qui rend un nombre de lignes et jamais
  une valeur ; tâche `pg_cron` quotidienne (`journal-securite-purge`, 03 h 41 UTC) en SQL pur, gardée comme celle des
  rappels (sans l'extension, la migration passe et avertit).
- **Droits.** Le schéma `private` naît fermé (`revoke all`, aucun rôle n'a `usage`) : les aides internes
  (`private.ecrit_evenement`) et les variantes à horloge (`private.purge_journal_securite(p_now, p_lot)`) y vivent. Une
  fonction exécutable par `authenticated` n'a jamais de paramètre d'horloge (une personne choisirait sa date ; un test
  de surface le garde). `public.journalise` est exécutable par `popote_api` (contexte connexion) **et** `service_role`
  (contexte service, où le rôle COURANT est `service_role`), jamais par `authenticated` ni `popote_internal` : une
  personne ne forge pas d'événement. Le droit se lit sur le rôle courant : les tests jouent `set local role`.

### 4.3 Limites de connexion comptées en base (0.4, migration 0138 ; code : `security/limites_base.py`)

- **Une fonction atomique.** `public.prend_les_creneaux(compte, ip)` : l'IP d'abord, le compte ne compte que si l'IP
  passe (une IP bloquée n'épuise pas les créneaux d'un compte). Les deux lignes de `login_throttle` se verrouillent
  toujours dans cet ordre : aucun interblocage entre deux connexions croisées.
- **Valeurs** (`config.py`) : 5 essais par compte et 20 par IP en 15 min ; au créneau de trop, blocage de 15 min, puis
  30, puis 60 (plafond) ; les crans retombent après 24 h sans blocage. Bloqué, la fonction rend l'attente **sans
  compter** : insister ne prolonge rien. Un succès remet le compte à zéro (`libere_compte`), jamais l'IP.
- **Réinitialisation** (route retirée en 0.4bis S3, scope `reset` retiré en S15) : 3 par heure et par couple **(e-mail, IP)**
  (`Empreintes.cle_reinitialisation`), sans escalade.
- **Clés** : HMAC de 32 octets (poivre), l'e-mail sous sa forme `email_normalise`, l'IPv6 regroupée par /64 ; jamais
  d'adresse en base. Une clé de compte inconnue se comporte comme une connue (la fonction ne lit pas `auth.users`).
- **Journal** : `prend_les_creneaux` rend aussi quelle clé vient de passer en blocage ; seul ce drapeau déclenche
  `connexion_bloquee` : un événement par (clé, fenêtre de blocage), pas un par essai refusé.
- **Bornes** : la base refuse une limite nulle ou hors bornes (limite 1 à 10 000, fenêtre 1 à 86 400 s, plafond entre la
  fenêtre et 86 400 s) : un appelant ne désactive pas une limite. `config.py` refuse un plafond sous la fenêtre.
- **Droits** : `popote_api` et `service_role` seulement ; l'horloge (`p_now`) n'existe que dans `private`. Purge
  nocturne (`limites-de-connexion-purge`, 03 h 47 UTC) des lignes sans activité depuis 24 h.
- **Risque accepté : blocage par un tiers (B5).** Qui connaît l'adresse d'une personne peut ralentir **sa** connexion en
  épuisant ses 5 essais : au plus 60 min par blocage (plafond), « mot de passe oublié » restant ouvert jusqu'à S5 (code par mail). Accepté pour
  un foyer de deux personnes ; l'alternative (ne pas limiter par compte) laisserait la force brute ouverte.

### 4.4 Sessions côté base (0.4, migration 0139 ; code : `security/sessions_base.py`, `security/appareil.py`)

- **Une règle de lecture, deux portes.** `private.session_valide` (échue, révoquée, 90 jours, personne bannie ou
  supprimée, activité écrite au plus toutes les 5 minutes) sert `session_personne` et `session_courante` (qui rend aussi
  l'identifiant de session et `reauth_at`).
- **Créer.** `public.cree_session` : au plus 10 sessions actives par personne (la 11e ferme la plus ancienne par
  dernière activité ; les créations d'une même personne se sérialisent par verrou consultatif). Une connexion réussie
  **révoque la session présentée** si elle est valide (événement `session_fermee`) ; un cookie invalide est ignoré. Une personne bannie ou supprimée n'ouvre pas de session.
- **Faire tourner, fermer.** `fait_tourner_session` change l'empreinte (l'ancienne meurt aussitôt ; une session morte
  ne tourne pas) ; `ferme_session` est idempotente ; `marque_reauth` exige la session ET la personne.
- **Appareil.** `browser` et `os` : des familles courtes bornées par CHECK, résumées de l'en-tête `User-Agent` par
  `resume_agent`. Ni le texte de l'agent, ni l'IP, ni une localisation n'est gardé avec la session.
- **Droits.** `popote_api` (contexte connexion) et `service_role` (contexte service), jamais `authenticated` ni
  `popote_internal` ; l'horloge n'existe que dans les variantes de `private`.
- **Purge.** Sessions échues ou révoquées depuis plus de 30 jours, par lots ; `pg_cron` chaque nuit
  (`login-session-purge`, 03 h 53 UTC).


### 4.5 La connexion (0.4, `POST /api/v1/sessions` ; code : `security/connexion.py`, `security/cookie.py`, `api/connexion.py`)

- **Ordre, qui est la sécurité de la route.** Corps validé (e-mail 254, mot de passe 256, champs inconnus refusés)
  -> clés HMAC (`email_normalise`, B24) -> `prend_les_creneaux` (IP d'abord, B6) -> `verifie_mot_de_passe` pour
  chaque candidat de `candidats_de_connexion`. Un créneau refusé (`429` + `Retry-After`) n'appelle **jamais** la
  vérification : aucun `crypt()` pour qui martèle. Un mot de passe sans candidat (plus de 72 octets) échoue sans
  appel à la base. Sans poivre, la route répond `503` : on ne compte pas sans clé.
- **Une seule transaction** (`base.connexion()`), validée aussi sur un refus : le compteur et l'événement d'un
  échec ne s'annulent pas avec lui.
- **Un seul refus.** `401 identifiants_incorrects`, « E-mail ou mot de passe incorrect. », que le compte soit
  inconnu, banni, supprimé, sans hachage, en `$2y$` ou que le mot de passe soit faux ; même corps, mêmes en-têtes,
  aucun `Set-Cookie`. Un compte inconnu prend créneau, `crypt()` factice et événement comme un compte connu
  (temps comparable, mesuré). Le message ne dit rien de la limite par compte ou par IP.
- **Jeton.** Tiré par le serveur (`jeton_neuf`, 32 octets) ; celui d'un cookie du client n'est jamais adopté. La
  base ne garde que l'empreinte. Le corps de la réponse (`{"id"}`) ne porte pas le jeton.
- **Cookie** (`security/cookie.py`, seul endroit qui écrit ses attributs) : `__Host-popote_session`, `HttpOnly`,
  `Secure`, `SameSite=Lax`, `Path=/`, sans `Domain`, `Max-Age` 90 jours (le serveur tient les 30 jours glissants).
  Hors local, démarrer avec un autre nom ou sans `Secure` (`POPOTE_SESSION_COOKIE_SECURE=false`) est refusé.
- **Cookie déjà présent (B22).** Une connexion réussie révoque la session présentée si elle est valide (événement
  `session_fermee`, écrit par la base) ; un cookie invalide est ignoré. Un échec ne ferme rien.
- **Journal.** `connexion_reussie` (personne et session), `connexion_ratee` (clé de compte seule), `connexion_bloquee`
  (la clé qui vient de bloquer : celle du compte, ou celle de l'IP quand c'est l'IP ; jamais e-mail, IP ni agent en
  clair). Il s'écrit une fois par fenêtre de blocage et par clé (B21) : au plus deux événements par rafale.
- **Rafales et verrous (revue).** Un mot de passe qui change à la normalisation coûte deux `crypt()` pour un créneau ;
  les lignes de limite restent verrouillées pendant la vérification (les connexions d'une même IP ou d'un même
  compte passent en série) ; un relais sans `X-Popote-IP` met tout le monde dans la clé commune `sans-ip`.
  Acceptés pour un foyer de deux personnes ; à revoir si la charge change.
- **Pas d'`Idempotency-Key`** (exemption écrite) : route publique, sans personne ; rejouer une réponse garderait
  un jeton en base ; chaque succès ouvre une session neuve, chaque échec se compte.
- **Risque accepté (B5).** Un tiers qui connaît l'adresse peut ralentir la connexion de cette personne, au plus
  60 minutes ; le code par mail (S5) reste ouvert (foyer de deux personnes).

### 4.6 Les appareils et la déconnexion (0.4, migration 0140 ; code : `api/appareils.py`, `security/cookie.py`)

- **`GET /api/v1/me/sessions`** : les sessions actives de la personne (ni révoquées, ni échues), la plus récemment
  active d'abord, curseur sur (dernière activité, id). Champs : `id`, `browser`, `os`, `created_at`, `last_seen_at`,
  `current` (une seule par page, calculée en Python : `id == session courante`). Jamais d'empreinte, d'IP ni de
  texte d'agent.
- **`DELETE /api/v1/me/sessions/{id}`** : `id` est un UUID ou `current`. Autre personne ou inconnue : le même `404
  session_introuvable` (on ne révèle rien) et la session de l'autre reste valide. Déjà fermée : `204`. `current` (ou
  son propre UUID) est la déconnexion : `204`, cookie vidé (`Max-Age=0`, mêmes attributs que la pose), événement
  `deconnexion` ; une seconde déconnexion, ou une déconnexion simultanée perdue, rend `401`.
- **`DELETE /api/v1/me/sessions?scope=others`** : `scope` obligatoire, une seule valeur (`others`) ; absent ou autre
  rend `422`, rien n'est fermé. Garde la courante ; un événement `session_fermee` par session fermée.
- **Contexte « personne »** : trois fonctions `security definer` (`mes_sessions`, `ferme_un_appareil`,
  `ferme_les_autres_appareils`), exécutables par `authenticated` seul (B3) ; la personne vient de `auth.uid()`, jamais
  d'un paramètre. Les événements s'écrivent dans la même transaction que la fermeture. Sans `Idempotency-Key` :
  un `DELETE` est idempotent par nature.

### 4.7 La réauthentification (0.4 T10 ; code : `api/reauthentification.py`, `security/connexion.py`, `security/reauth.py`)

- **`POST /api/v1/me/reauthentication`** `{password}` : la route lit l'adresse de la personne sous sa session
  (`mon_email()`, comme `GET /me`) ; elle ne vient jamais du client. `tente_la_reauthentification` prend les
  **mêmes créneaux que la connexion** (`_prend_les_creneaux` : l'IP d'abord, puis le compte de la personne, clé issue de
  son e-mail normalisé ; un blocage s'écrit une seule fois par fenêtre, B21), puis appelle
  `verifie_mot_de_passe_de` avec les mêmes candidats que la connexion (T2) : un seul `crypt()` par candidat, aucun
  pour un créneau refusé. Une session volée ne peut donc pas forcer le mot de passe : cinq essais faux bloquent aussi
  la connexion de ce compte (risque accepté, comme B5).
- **Succès** : `libere_compte` (le compte, jamais l'IP), `marque_reauth` sur **sa** session seulement (la fonction
  vérifie la session ET la personne), événement `reauthentification_reussie`, `204`. **Échec** : événement
  `reauthentification_ratee` (clé de compte, jamais l'IP), `403 mot_de_passe_incorrect`. Bloqué : `429` + `Retry-After`.
- **Deux transactions** : la dépendance de session garde sa transaction « personne » (lecture de l'adresse), la
  vérification et les écritures passent par `base.connexion()` et se valident aussi sur un refus (compteur et
  événement). Entorse à « une transaction par requête » (A16) : `verifie_mot_de_passe_de` n'est exécutable que par
  `popote_api`. Une requête tient donc deux connexions du pool un instant ; sous charge l'attente du pool finit en
  `503`, sans interblocage durable.
- **`exige_reauth`** : lit `reauth_at` de la session déjà lue (aucun appel de plus) ; à plus de 300 s de
  `app.state.horloge()` : `403 reauthentification_requise`. 300 s exactement passe. Posé par la connexion, donc un
  changement juste après la connexion n'exige rien. Aucune route ne l'utilise encore (T11, T14).

### 4.8 Changer son mot de passe (0.4 T11, migration 0141 ; code : `api/moi.py`, `security/connexion.py`)

`PUT /api/v1/me/password` `{new_password}`, derrière `exige_reauth`. L'ordre est celui qui laisse l'état le plus sûr
après un échec à n'importe quelle étape :

1. **Avant tout changement d'état** : normalisation NFKC, règles NIST (§ 4.1), liste de fuites. Refus : `422`, pointeur
   `/new_password`, aucun appel à Auth, rien d'écrit. **Liste indisponible (B23) : le mot de passe est accepté**,
   l'événement `verification_fuites_indisponible` est écrit et un avertissement est journalisé (cause seule : ni
   valeur, ni empreinte).
2. **Une transaction SQL** (`public.fait_tourner_et_ferme_les_autres`, exécutable par `popote_api` seul) : change
   l'empreinte de la session courante (la rotation sert de verrou : un second changement simultané qui arrive avec
   l'ancien cookie ne trouve plus de session et reçoit `401` sans `Set-Cookie`, sans jamais atteindre Auth), ferme
   toutes les autres sessions (un `session_fermee` chacune) et supprime les lignes `auth.sessions` et
   `auth.refresh_tokens` de la personne (B9, `private.ferme_les_sessions_auth`).
3. **Auth** (`change_mot_de_passe`, forme NFKC, un seul appel). Échec : `503` **avec le nouveau cookie** (la session
   a déjà tourné), les autres sessions restent fermées par précaution, le mot de passe n'a pas changé (sur un
   délai d'Auth il a pu l'être : le message dit « n'a pas pu être confirmé »). Toute erreur imprévue à cette étape
   rend la même réponse : après la rotation, le client reçoit toujours son cookie.
4. **Succès** : `password_set` à vrai (l'ancienne appli en dépend pendant la fenêtre de retour), événement
   `mot_de_passe_change` (jamais avant), **seconde fermeture des autres sessions** (une connexion faite avec l'ancien
   mot de passe pendant l'appel à Auth ne survit pas), `204` et nouveau `Set-Cookie`. Un échec de la base à cette étape
   est journalisé (`error`) mais ne retire pas son cookie à la personne : le mot de passe est déjà changé.

Cas acceptés : une déconnexion simultanée qui arrive avec l'ancien cookie APRÈS la rotation ne trouve rien et la session
survit sous son nouveau cookie ; une suppression de compte simultanée rend `503` (Auth répond `404`) avec le cookie d'un
compte supprimé, sans effet.

Sans `Idempotency-Key` : un `PUT` est idempotent par nature, et la réponse rejouée garderait en base un mot de passe.
Le mot de passe ne figure ni dans un journal, ni dans une réponse, ni dans le `repr` du modèle d'entrée.

Limite connue (B9) : la force brute par le point `/auth/v1/token` de Supabase Auth, que le front n'utilise plus, n'est
**couverte qu'après 0.7** (verrouillage de Supabase Auth) ; d'ici là elle n'est comptée par aucune de nos limites.
Un second verrou de lignes n'est pas à craindre : la route n'est ouverte qu'à une session réauthentifiée depuis moins de
5 minutes, donc vue depuis moins de 5 minutes, et `session_courante` ne verrouille la ligne que passé ce délai.

### 4.13 Code par mail : la demande (0.4bis S5, migration 0147 ; code : `api/codes.py`, `security/code_de_connexion.py`, `security/codes.py`)

- **Table `public.login_code`** : le HMAC du code (jamais le code), 10 minutes au plus (`CHECK`), 5 essais, usage unique,
  révocable ; **un seul code actif par clé de compte** (index unique partiel : une demande révoque la précédente).
  `id` est l'identifiant de demande (`code_request_id`) : pas un secret, le code est protégé par le poivre. `person_id` est
  nul pour une **ligne factice** (adresse inconnue, bannie, supprimée ou sans profil) : même insertion, même durée, aucun mail.
  RLS forcée, aucun droit. Purge à l'échéance + 1 jour (`login-code-purge`, 03 h 43 UTC).
- **`demande_un_code`** (`popote_api` seul) : le même travail pour une adresse connue et inconnue (verrou sur la clé du
  compte, puis sur la personne pour un compte réel : la même clé que `cree_session`). **Un code de moins de 60 s n'est pas
  remplacé** (même identifiant rendu, `nouveau` faux, donc pas de mail : un double clic ne tue pas le code déjà parti) ;
  un code mort (5 essais) se remplace. `code_demande` ne s'écrit que pour un compte réel : une IP ne remplit pas le journal.
- **Créneaux** (`prend_les_creneaux_de_demande`) : IP (10), (adresse, IP) (3), adresse (6 par heure), dans cet ordre ;
  **un refus n'use pas les suivants** ; sans escalade (le créneau de trop attend la fin de la fenêtre, ne compte pas, ne
  prolonge rien). **Aucun créneau global à la demande** : dix adresses bidon depuis une IP l'auraient épuisé pour tous.
  Le **coupe-circuit global** (`prend_un_envoi`, 60 mails par heure) se prend à l'envoi réel, après la réponse, pour un compte
  réel seulement : il protège le quota du fournisseur. Une adresse inventée n'envoie rien, donc n'y compte pas ; un anonyme ne
  l'atteint qu'en connaissant **au moins 10 comptes réels** (6 demandes par heure chacun) : le foyer en compte deux.
- **Risques acceptés** (plan, risque 6) : qui connaît une adresse peut user ses 6 demandes par heure depuis une seule IP (3 par
  15 minutes) et priver la personne de **code** jusqu'à une heure ; la clé d'accès n'est pas touchée. Les fenêtres sont fixes :
  jusqu'au double de la limite peut passer à cheval sur deux fenêtres (12 demandes d'une adresse, 120 envois globaux).
  Le coupe-circuit, qui ne compte que les comptes réels, est observable : qui a déjà fait partir 59 envois (donc détient au
  moins 10 comptes réels) voit, à l'absence du 60e mail, qu'une adresse sondée existe. Un quota global dur ne peut pas être à la fois
  indépendant de l'existence et inépuisable ; accepté pour un foyer de deux personnes, sur invitation (l'inscription est
  fermée). Un compte réel prend en plus le verrou de la personne et écrit un événement : sous contention de cette personne, sa
  demande est plus lente ; S5b traduit les délais et erreurs de la même façon et mesure les médianes. Une panne ou un verrou propre
  à `security_event` seule ne toucherait qu'un compte réel (`503` pour lui, `202` pour une adresse inconnue) : accepté, c'est une panne
  partielle de la base, que la route ne peut pas masquer sans écrire aussi un événement pour les adresses inconnues (journal plein d'IP).
- **Recherche du compte** : elle passe par `users_instance_id_email_idx (instance_id, lower(email))` ; sans `instance_id`, un
  parcours de la table arrêté à la première ligne trouvée ferait répondre une adresse connue plus vite qu'une inconnue (mesuré :
  4 ms contre 12 ms pour 20 000 comptes). Un test garde la requête et, sur une base fournie, la médiane des durées.
- **Ordre des verrous**, que S7 reprend : clé de compte, puis personne (la clé de `cree_session`), puis `auth.users` en `for key share`
  (le compte se relit une fois le verrou de la personne pris), puis les lignes `login_code`. `for key share` n'empêche pas un
  bannissement simultané : la vérification (S7) relit l'état du compte.
- **La route `POST /api/v1/login-codes`** `{email}` (publique, `ROUTES_PUBLIQUES`). Ordre, qui est la sécurité de la route :
  corps validé (e-mail 254, champs inconnus refusés) -> clés HMAC (sans poivre : `503`, rien ne se compte ni ne s'écrit sans
  clé) -> code (`secrets.randbelow(10**6)`, six chiffres) et son empreinte (HMAC d'une clé dérivée du poivre, étiquette
  `login-code/v1`, sur identifiant de demande, clé du compte et code : une empreinte ne vaut que pour sa demande) tirés **avant**
  la base, que le compte existe ou non -> une transaction (`base.connexion()`, validée aussi sur un refus : le compteur reste) :
  `prend_les_creneaux_de_demande`, puis `demande_un_code`. **Toujours `202 {code_request_id, expires_in_s: 600,
  resend_after_s: 60, message}`**, même statut, même corps hors identifiant, mêmes en-têtes. Un refus de limite est `429` +
  `Retry-After` pour tous, connus ou non. Une erreur de la base donne `503`, jamais `500`.
- **L'échéance du mail** : `Courrier.expire_le` = l'instant de la demande (`app.state.horloge()`, pris avant la base) + 10 minutes. Celle de la
  base (`now()` + 10 minutes) ne peut pas être plus tôt : un code n'est jamais livré après l'avoir été. `demande_un_code` ne rend pas
  `expires_at` (0147 est fusionnée) ; le destinataire est la forme normalisée, en minuscules.
- **Le mail** part APRÈS la réponse (`BackgroundTasks`), pour une personne réelle et un code neuf seulement : coupe-circuit global
  (`prend_un_envoi`) puis `envoie_sans_remonter`. Un coupe-circuit ouvert ou illisible jette le mail (le code reste valable ; la
  clé d'accès fonctionne) et se journalise sans adresse ni code ; un envoi qui échoue se journalise par son type seul.
  À surveiller en exploitation : une alerte sur « Mail (code) non envoyé » (coupe-circuit ouvert, base indisponible, fournisseur en
  panne) : la réponse est `202`, la personne ne reçoit rien et ne peut pas redemander avant 60 s. Le code existe en clair dans deux
  variables locales (`demande_le_code`, `envoie_le_courrier`) : le suivi D4 (Sentry) devra désactiver ou masquer les variables locales.
  L'adresse est refusée en `422` si sa forme normalisée dépasse 254 **octets** (« é » en pèse deux ; NFKC peut allonger) : la base
  compte des octets et un refus de sa part annulerait aussi les créneaux déjà pris.
  Le code n'est ni dans une colonne (seul son HMAC l'est), ni dans un événement, ni dans un journal, ni dans l'objet du mail.
  Sans `Idempotency-Key` : route publique, rejouer une réponse garderait un identifiant de demande.
- Tests : `tests/integration/test_demande_de_code_base.py` (la base : 50 demandes simultanées, un test de dérive entre les portées du
  `CHECK` et celles des fonctions), `test_demande_de_code.py` (la route : réponse et durée comparables, limites, coupe-circuit, journaux),
  `tests/unit/test_codes.py` (code, empreinte, clés, envoi) et `test_surface.py`. Mutations rejouées : mail pour une adresse inconnue,
  code en clair, même empreinte pour deux demandes, identifiant non effectif, créneaux seulement pour un compte connu, ordre des clés,
  coupe-circuit retiré, code ou adresse dans un journal, validité, paire sans IP.

### 4.14 Le verrou de personne et l'activité des sessions (0.4bis S6, migration 0148 ; code : `infra/db.py`, `tests/integration/_course.py`)

- **Le défaut (leçon 1).** Une connexion en vol (preuve vérifiée, session pas encore créée) survit à la fermeture de toutes les
  sessions si la preuve et la session sont deux instructions sans verrou commun. On pose le verrou **une fois** :
  `private.verrouille_la_personne(personne)` est le verrou consultatif de transaction que `cree_session` posait en ligne (même clé,
  `hashtextextended(personne::text, 0)`), nommé ; `public.verrouille_la_personne` est son chemin Python (`popote_api`, `service_role`).
  Une personne nulle est refusée (le verrou serait un « rien »).
- **Ordre des verrous, partout : foyer, puis invitation du foyer, puis personne, puis lignes** (session, code, clé). Les routes publiques
  prennent avant la personne leurs compteurs de limite (`login_throttle`) et, pour la demande de code, le verrou de la clé de compte ;
  aucune fonction qui tient une personne ne touche ces lignes, donc aucun chemin inverse (hiérarchie : limites et clé de compte, foyer,
  invitation, personne, lignes). `efface_mes_donnees` (prend le foyer, jamais la personne) et la cascade de `delete_my_account` restent
  hors règle jusqu'à S14, qui leur donne les trois verrous et empêche une session après la suppression du profil. Tout code qui ouvre une session, en ferme
  plusieurs, révoque ou consomme un code, ajoute ou retire une clé ou supprime un compte prend d'abord la personne. `cree_session`,
  `ferme_les_autres_sessions`, `ferme_les_autres_appareils`, `fait_tourner_et_ferme_les_autres` et
  `confirme_le_changement_de_mot_de_passe` la prennent **avant toute écriture** (un test regarde, dans `pg_locks`, que B attend sans avoir
  encore d'identifiant de transaction). `ferme_les_autres_sessions` et `ferme_les_autres_appareils` **révoquent aussi les codes en attente**
  de la personne : un code demandé avant la fermeture ne rouvre rien après. Un test d'architecture lit les migrations : toute fonction qui
  écrit `login_session.revoked_at` ou supprime des lignes de `login_session` appelle `verrouille_la_personne`, sauf quatre exceptions écrites
  avec leur raison (`ferme_session`, `ferme_un_appareil` : une seule session désignée ; la purge ; `efface_mes_donnees` jusqu'à S14).
- **L'activité d'une session (amendement A2).** `private.session_valide` écrivait `last_seen_at` en tenant la ligne jusqu'à la fin de la
  requête, **avant** que la route prenne la personne ou le foyer : deux onglets d'un même navigateur s'interbloquent (`40P01`) et l'ordre
  foyer, invitation, personne serait inversé. Désormais `Base.session` **lit** la session sans écrire ni verrouiller (`lit_la_session`, qui dit si
  l'activité a plus de 5 minutes) ; si elle est périmée, la transaction de lecture est abandonnée, l'activité s'écrit dans **sa propre
  transaction courte** (`note_l_activite_de_la_session` : la personne, puis la ligne, conditions relues sous le verrou), **validée avant**
  que la route ouvre la sienne, puis la requête recommence. Dans le cas courant (activité récente) il n'y a toujours qu'une transaction.
  À l'entrée de la route, aucun verrou de personne ni aucune écriture ne sont tenus (testé). La validité de la session n'est pas relue
  après : une fermeture validée entre la lecture et le premier effet de la route laisse finir une requête déjà authentifiée (écart accepté,
  borné par les délais de 8 s). Conséquence : l'activité s'écrit même si
  la route échoue (la session a bien servi). `session_valide`, `session_courante` et `session_personne` ne sont pas touchées : l'API ne
  les appelle plus, elles ne servent qu'au code déjà déployé pendant la fenêtre de déploiement.
- **La preuve et la session (leçon 1, chemin mot de passe).** `tente_la_connexion` vérifie le mot de passe, prend le verrou de la
  personne, puis **refait** la vérification avant d'ouvrir la session : un changement de mot de passe validé entre les deux la rend
  fausse, la connexion est refusée (un test glisse le changement entre les deux par une barrière). Coût : un second `crypt()` sur le
  seul chemin de succès, jusqu'à S7 qui retire le mot de passe (S7 et S9 relisent leur preuve sous le verrou par construction).
- **Deux personnes, un navigateur.** `cree_session` révoque la session PRÉSENTÉE (B22), qui peut être celle d'une autre personne : les deux
  personnes se verrouillent toujours dans le même ordre (l'identifiant le plus petit d'abord), donc deux connexions croisées ne
  s'attendent jamais en cercle. C'est `verrouille_la_personne(personne, session_présentée)` qui ordonne, que l'appelant soit `cree_session` ou
  la connexion qui prend le verrou avant de refaire sa preuve (tests : ordre par `cree_session` et par la connexion, croisement avec dix
  sessions chacune).
- **Fenêtre de déploiement.** Les migrations passent avant le code : l'ancien code tourne quelques minutes sur cette base. Au lieu de
  deux migrations, `session_valide` (que `session_courante` et `session_personne` appellent) est devenue une lecture : l'ancien code ne
  tient plus de ligne de session, donc aucun cycle avec les fermetures qui prennent la personne d'abord (testé : l'ancien chemin, une
  reconnexion et une fermeture en parallèle). Prix : pendant la fenêtre, l'ancien code ne repousse plus l'activité (30 jours glissants).
- **L'activité est au mieux** : si le verrou ne lâche pas en 1 s, en cas d'interblocage ou de délai de requête, la requête (session
  valide) continue sans écrire l'activité, journalisée par le type ; la suivante réessaie. `tente_la_connexion` prend les créneaux (des
  compteurs) avant le verrou de la personne : l'ordre limites, puis personne est celui de toutes les routes publiques (`demande_un_code`
  aussi), sans cycle ; le second `crypt()` se fait sous le verrou.
- **Courses déterministes** (`tests/integration/_course.py`) : A prend le verrou sans valider, B démarre, le test attend B dans
  `pg_stat_activity` (le backend que le pid exact de A fait attendre, pas un autre), A valide, on lit le sort de B ; jamais un `sleep` comme preuve. Les entrelacements (200 opérations de création et
  de fermeture, 100 requêtes à activité périmée contre reconnexions et fermetures, connexions croisées de deux personnes) ne donnent aucun `40P01`. Un `40P01` reste traduit en
  `503` + `Retry-After: 1` (`erreurs_base.py`) comme filet.

## 5.1 Qui exécute quoi (extrait du § 5)

| Contexte | Rôle de connexion | Rôle emprunté | Identité posée | Sert à |
|---|---|---|---|---|
| Personne | `popote_api` | `set local role authenticated` | `request.jwt.claims` = `{"sub": <personne>, "role": "authenticated"}` | toute requête d'une personne connectée ; la RLS et les gardes (`tg_saisie_garde`, `tg_depense_garde`…) s'appliquent |
| Service | `popote_internal` | `set local role service_role` | `{"role": "service_role"}` | seulement les routes `/internal/*`, l'acceptation d'une invitation et les purges ; liste fermée, chaque usage relu |
| Connexion | `popote_api` | aucun : fonction `security definer` privée (`Base.connexion()`) | aucune | vérifier un mot de passe, limites, sessions, journal ; lire la session (`session_courante`, depuis 0.4 T8), avant d'emprunter `authenticated` dans la même transaction ; liste fermée, comme le service |
| Sauvegarde | `postgres`, hors API | — | — | `pg_dump` lancé par GitHub Actions |

- **Deux rôles de connexion, deux pools.** `popote_api` n'est membre que d'`authenticated`, `popote_internal`
  que de `service_role`, tous deux `NOINHERIT` et sans super-utilisateur. Le pool de `popote_internal` n'est
  monté que par le code des routes internes, de l'invitation et des purges. Un `set role` oublié ou une
  injection dans une requête de personne ne peut donc pas atteindre le contournement de la RLS.
- **Un contexte = une transaction.** `Base.personne(id)`, `Base.connexion()` (le rôle `popote_api` nu, sans `set role`) et `Base.service()`
  (`infra/db.py`) ouvrent chacun une transaction dans le bon rôle ; tout y est posé par `set local` ou `set_config(…, true)` et meurt au `commit`
  ou au `rollback` (aussi sur une annulation côté client : la connexion rendue au pool est propre).
  `POPOTE_DATABASE_URL` est le rôle `popote_api`, exigé hors local ; `POPOTE_DATABASE_URL_INTERNAL`, le rôle
  `popote_internal`, est facultative pour l'instant : sans elle l'application démarre avec un avertissement et
  `Base.service()` lève `ServiceIndisponibleError`, rendue `503 service_indisponible`.
- **Délais côté base** (migration `0132`), parce que l'annulation côté client ne coupe pas la requête sous
  Supavisor : `popote_api` 8 s de requête, 5 s d'attente de verrou, 15 s de transaction inactive ;
  `popote_internal` 30 s, 10 s, 15 s. `set role` n'applique pas les réglages du rôle emprunté : le code répète les
  mêmes valeurs par `set local` à chaque transaction (un test compare les deux), sauf le contexte
  `Base.service()` : sa requête est coupée à 20 s, sous les 25 s de l'API (`limites.Delai`), pour que la base
  ne continue pas le travail après la `503` (le rôle garde ses 30 s : pas de nouvelle migration).
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
| API8 Mauvaise configuration | En-têtes de sécurité, origine unique, erreurs normalisées, TLS seulement, HSTS, en-tête secret du relais ; sous `/api/v1/`, `404`, `405` et `422` précoces rendent `401` tant que la session n'est pas validée (`normes-api.md` § 3.10) |
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

- Clé des routes internes : `POPOTE_INTERNAL_SECRET` (et `POPOTE_INTERNAL_SECRET_PRECEDENT` pendant une
  rotation), propre à chaque environnement, 32 caractères ASCII au moins, posée comme variable secrète du
  conteneur. Sans elle, `/internal/*` répond `404` à tout. Format et règles : `normes-api.md` § 3.10.
- Dans le gestionnaire de secrets de l'hébergeur, jamais dans un dépôt ; `gitleaks` à chaque envoi.
- Déploiement par identité fédérée (OIDC) quand l'hébergeur le permet ; sinon une clé limitée au projet, à
  durée courte, renouvelée. Procédure écrite pour changer chaque secret.

#### Administration de Supabase Auth (`src/popote_api/infra/auth_admin.py`)

Le seul module qui écrit un compte : `cree_compte`, `change_mot_de_passe`, `supprime_compte`. Réglages
`POPOTE_SUPABASE_URL` (une seule adresse, qui sert aussi à `iss` : https, origine seule, hôte vérifié ;
http seulement vers l'hôte local, en local ; vide vaut absente) et `POPOTE_SUPABASE_SECRET_KEY` (`SecretStr`),
**facultatifs pour l'instant**. L'adresse seule est valide ; la clé sans l'adresse est refusée au démarrage ;
l'administration exige les deux : sinon l'application démarre avec un avertissement et chaque opération rend
`503 auth_indisponible`.

- **Clé dans `apikey` seul** (preuve 1 : acceptée seule ou doublée d'`Authorization`). Un seul en-tête, une
  seule place où elle voyage ; `Authorization` attend un JWT, et cette clé n'en est pas un.
- **Délais finis** : connexion 3 s, lecture 10 s, échéance totale 15 s. **Aucune reprise** : un `cree_compte`
  rejoué pourrait créer un compte que l'appelant ne connaît pas. Redirections refusées : la clé ne suit pas un
  `Location`. `trust_env=False` : ni `HTTP(S)_PROXY` ni `SSL_CERT_*` du poste ne détournent la clé. Réponse
  bornée à 64 Kio, sans décompression demandée.
- **Un succès se reconnaît à son corps** : la création rend l'identifiant, le changement rend le compte
  (même identifiant), la suppression rend un objet JSON ou rien ; une page de mandataire répondue en `200`
  est une erreur, pas un succès. Clé et adresse de base sont validées au démarrage (en-tête transmissible,
  nom d'hôte ou IP littérale, port 1 à 65535) et la clé à la construction du client.
- **Le message d'Auth n'est jamais gardé ni journalisé** (il recopie l'adresse). Une exception ne porte que le
  statut HTTP et le `error_code` d'Auth, et seulement s'il a la forme d'un code (`[a-z][a-z0-9_]{0,63}`).
- **Erreurs** : `email_exists` / `user_already_exists` → `CompteDejaExistant` (`409 compte_existant`) ;
  `weak_password`, ou mot de passe non transmissible (plus de 72 octets, nul, substitut isolé, refusé avant tout
  appel) → `MotDePasseRefuseParAuth` ; tout le reste, panne, délai, statut ou corps imprévu →
  `AuthIndisponible` (`503`). `supprime_compte` tient pour un succès le seul `404 user_not_found`.
- L'identifiant d'un compte entre dans l'adresse sous forme d'`UUID` seulement ; la clé n'apparaît ni dans un
  `repr`, ni dans les réglages sérialisés, ni dans un journal.

### 7.5 Chaîne d'approvisionnement

- Versions figées (`uv.lock`, `package-lock.json`), mises à jour hebdomadaires automatiques et relues ;
  `pip-audit` et `npm audit` bloquants sur les failles hautes ; actions GitHub figées par empreinte, droits
  minimaux par workflow ; image du conteneur minimale, sans root, scannée (Trivy) ; SBOM CycloneDX produit.
- **Clés d'accès (0.4bis S8a) : `webauthn` 3.0.1** (py_webauthn, Duo Labs), seule dépendance ajoutée, figée par `==`.
  Relu à la source le 13/11/2026 :
  - licence **BSD-3-Clause** (PyPI `license_expression` et dépôt) ; publiée le 25/09/2026, donc au-delà du délai de Dependabot (7 jours)
    et de `exclude-newer` ; dépôt non archivé, dernier envoi le 08/10/2026 ; aucune faille connue (OSV, `pip-audit`) ;
  - **OpenSSF Scorecard 3,3 sur 10** (9/11/2026 : Maintained 4, Code-Review 0, Branch-Protection 0, SAST 0, Security-Policy 0,
    Fuzzing 0 ; Dangerous-Workflow, Binary-Artifacts et License à 10) : le score est bas, la bibliothèque est petite et typée,
    et ses entrées sont les octets d'un navigateur : `infra/webauthn.py` les entoure (refus de tout ce que la bibliothèque ne
    lit pas comme prévu, 750 réponses abîmées dans `tests/unit/test_webauthn.py`). Écartées : `fido2` (BSD-2-Clause avec des
    parties Apache-2.0 et MPL-2.0), les clés d'accès de Supabase Auth (« experimental ») ;
  - dépendances qu'elle fait venir (versions de `uv.lock`) : `cryptography` 50.0.2 (Apache-2.0 OR BSD-3-Clause, option
    BSD-3-Clause), `pyOpenSSL` 26.4.0 (Apache-2.0), `cbor2` 6.1.5 (MIT), `pyasn1` 0.6.5 (BSD-2-Clause), `pyasn1-modules` 0.4.2
    (BSD-2-Clause d'après son fichier de licence ; PyPI écrit « BSD »), `cffi` 2.1.1 (**MIT-0**, venu avec `cryptography`),
    `pycparser` 3.12 (BSD-3-Clause). MIT-0 admise le 13/11/2026 : permissive, sans obligation.

### 7.6 Vérification : OWASP ASVS niveau 2

Le niveau 2 vise les applications qui tiennent des données personnelles et financières : c'est le cas. À
l'étape 0.8, chaque exigence applicable est cochée avec sa preuve (test, configuration ou revue), les
exceptions écrites. Chapitres prioritaires : authentification, sessions, contrôle d'accès, validation, API,
configuration, journalisation, protection des données.

### 7.7 RGPD

- Données et traitements en Europe ; liste des sous-traitants tenue (Supabase, hébergeurs, fournisseurs de
  modèles, envoi de mails, Pwned Passwords) avec leurs conditions de conservation vérifiées.
- **Scaleway Transactional Email** (sous-traitant, Paris, S4) : reçoit l'adresse du destinataire, l'objet, le texte (code ou lien
  d'invitation) et l'adresse IP émettrice. Selon la documentation de Scaleway (relue le 13/11/2026) : le contenu est effacé à
  l'acceptation par le serveur du destinataire, au premier rebond dur ou après 36 heures d'échecs, avec des sauvegardes chiffrées de
  7 jours ; les métadonnées (dont l'adresse IP émettrice) sont gardées tant que le domaine d'envoi est actif. Le code n'est jamais dans
  l'objet. Sources : `docs/exploitation.md`, « L'envoi réel ».
- **Pwned Passwords** (`api.pwnedpasswords.com`, service de Have I Been Pwned) : reçoit les 5 premiers
  caractères hexadécimaux du SHA-1 d'un nouveau mot de passe, l'adresse IP du serveur de l'API et l'agent
  `popote`. Il ne reçoit ni e-mail, ni identifiant, ni compte, ni le mot de passe, ni le reste de l'empreinte :
  aucune donnée d'une personne identifiable, d'où aucune conservation à convenir. À confirmer : la
  localisation du service (hors Union européenne ou non) et son éventuel statut de sous-traitant ne sont pas
  établis par ce document ; à faire valider avant la bascule (0.8).
- Conservation : journaux applicatifs 30 jours, journal de sécurité 1 an (échecs et blocages de connexion : 90 jours), journal des appels au modèle 90 jours,
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

### 4.9 Créer, lister et révoquer un lien d'invitation (0.4 T12, migrations 0142 et 0143)

- **`POST /api/v1/me/invitations`** : le jeton fait 256 bits (`secrets.token_urlsafe(32)`, 43 caractères), tiré par l'API ;
  **seul son SHA-256 (32 octets) va en base** (`invite_link.token_hash`). Il est rendu une seule fois. Il n'entre dans
  aucune adresse d'API (la `Location` porte l'identifiant), aucun journal, aucun `repr` (`repr=False` sur le champ), aucun
  événement de sécurité, et **pas dans `idempotency_key`** : `champs_secrets` le remet à `null` avant l'écriture ; un
  rejeu rend `token: null`, l'hôte révoque et recrée si la réponse d'origine s'est perdue.
- **Quota** : 10 par 24 h glissantes et par foyer, révoqués compris, sous un verrou consultatif du foyer (attendu) : quinze
  créations parallèles en laissent passer exactement dix. L'horloge (`p_now`) n'existe que dans `private.cree_invitation`,
  fermée à `authenticated` : une personne ne choisit pas sa date (B19).
- **Droits** : table sans aucun droit, RLS forcée sans politique ; `public.cree_invitation(bytea)` exécutable par
  `authenticated` seul (jamais `anon`, `service_role`, `popote_api`). Une personne sans profil (donc sans foyer) : `403`.
- **Limite assumée (B3)** : `public.cree_invitation(bytea)` est une fonction de `public` exécutable par `authenticated` :
  un membre du foyer qui l'appellerait directement (PostgREST, si exposé) créerait un lien dont il choisit l'empreinte,
  donc dont il connaît le jeton. Il n'en tire rien qu'il n'ait déjà (invitation de SON foyer, quota inchangé, événement
  écrit) ; la voie normale reste la route, qui tire le jeton.
- **Personnes** : un compte supprimé laisse le lien (`created_by`, `accepted_by` passent à `null`) ; ses lignes
  d'idempotence partent avec lui (cascade). Purge : fin de vie + 30 jours, par lots, `pg_cron` `invite-link-purge`.
- **Liste et révocation (0143)** : `public.mes_invitations(p_limit, p_after_created, p_after_id)` et
  `public.revoque_invitation(p_id)`, `security definer`, `search_path = ''`, `execute` à `authenticated` **seul**, sans
  `p_now` (B19). Le foyer est celui de `auth.uid()` : aucun paramètre ne désigne une personne ou un foyer. La liste ne
  rend que `id`, `created_at`, `expires_at` des liens en attente du foyer. La révocation rend `revoquee`, `deja` (déjà
  révoqué ou échu), `utilisee` (`409`) ou `inconnue` (`404` : autre foyer ou rien, sans effet, sans événement) ;
  l'événement `invitation_revoquee` n'est écrit que lorsqu'un lien passe réellement à révoqué, dans la même transaction.
- **Compatibilité avec l'appli en ligne** : table et fonctions neuves ; `invitation`, `invite` et `accept-invite` intacts.

### 4.10 Lire et accepter une invitation (0.4 T13, migration 0144 ; code : `api/invitations_publiques.py`, `security/acceptation_invitation.py`, `infra/comptes.py`)

Deux routes publiques : `POST /api/v1/invitations/inspections` `{token}` et `/acceptances` `{token, email, password}`. Le
jeton voyage dans le **corps** (jamais dans l'adresse), son empreinte est le SHA-256 de la chaîne ASCII reçue
(comme à la création). Aucun jeton, empreinte, adresse, mot de passe ni IP dans un journal, une réponse ou la table
d'idempotence (pas d'`Idempotency-Key` : exemption écrite).

**Ordre de l'acceptation (B1), rien ne s'exécute avant l'étape qui précède** : (1) limite `invitation_ip` (30 par
15 min, /64 en IPv6) ; (2) lecture sans effet du lien : inconnu ou mal formé `404` (même corps), expiré / utilisé /
révoqué `410` : un jeton inconnu n'apprend rien sur les adresses et ne coûte ni liste de fuites ni appel à Auth ; (3)
limite `invitation_link` (10 par 15 min et par lien, clé = HMAC de l'empreinte) ; (4) adresse (`email_normalise`,
ASCII fermé, 254 au plus : `422`), règles du mot de passe, liste de fuites ; (5) l'adresse a-t-elle un compte :
`409 compte_existant`, lien **non consommé** ; (6) consommation atomique (`consomme_invitation` : un seul `update`) ;
(7) création du compte (Auth), profil dans le foyer du lien, session, événements. `429` + `Retry-After`. Les scopes
sont préfixés (`invitation_ip`, `invitation_link`) : ils ne partagent rien avec les 20 créneaux de connexion d'une IP.

- **Échecs après la consommation** : le lien est brûlé (l'hôte en recrée : 10 par jour), **sauf** la course d'adresse
  (B20) : si Auth rend `compte déjà existant`, `rend_invitation` rouvre le lien et la réponse est `409`. Un échec du
  profil supprime le compte créé ; si cette compensation échoue aussi, l'erreur `compte_orphelin_a_nettoyer`
  (identifiant de personne, jamais d'adresse) est journalisée et la réponse est `503`.
- **Reprise d'un compte (B10)** : seulement un compte **sans profil, sans foyer et sans hachage de mot de passe**
  (reste d'un ancien lien magique : rien à prendre), sans identité d'un autre fournisseur (Google...), non SSO, non banni, non supprimé ; l'état est relu après la consommation du lien, et rien n'est posé si le compte a changé entre-temps. Tout autre compte existant (profil ou
  hachage) : `409`, lien non consommé. L'adresse est **réservée 60 s** (`reprise_en_cours`, clé = HMAC de l'adresse)
  pour toute création ou reprise : deux liens visant la même adresse ne s'exécutent jamais ensemble, le perdant a `409`
  sans appeler Auth. Reprise : `updateUserById` (mot de passe, e-mail confirmé), profil, session, événement
  `compte_repris`. Si le profil échoue après le mot de passe, le compte (qui existait avant) n'est pas supprimé : il
  est signalé `compte_orphelin_a_nettoyer` (réparation : `docs/exploitation.md`). La réservation a un propriétaire :
  seul lui la libère. Si Auth crée un compte puis répond mal, le compte sans profil est retiré (adresse libérée).
  Risque accepté : une requête annulée (arrêt du processus) entre la création et le profil laisse un compte à
  nettoyer par la requête de `docs/exploitation.md`.
- **Liste de fuites hors service (B23)** : le mot de passe est accepté, l'événement `verification_fuites_indisponible`
  est écrit (aucune valeur).
- **Énumération d'adresses** : le `409` n'est rendu qu'à qui détient un lien valide, au plus 10 essais par lien et 30
  par IP en 15 min ; un jeton inconnu rend toujours `404`. Risque accepté (spec § 4 : refus si l'adresse a un compte).
- **Droits** : `consomme_invitation`, `rend_invitation`, `termine_invitation`, `compte_pour_email`, `reserve_reprise`,
  `libere_reprise` : `service_role` seul ; `etat_invitation` et `prend_un_creneau_invitation` : `popote_api` et
  `service_role`. `authenticated` et `anon` : rien. Le contexte service n'est ouvert que par
  `security/acceptation_invitation.py` (liste fermée de `base.service()`).

### 4.11 Effacer ses données et supprimer son compte (0.4 T14a, migration 0145 ; route T14b : `api/moi.py`)

- **`public.efface_mes_donnees()`** : le corps de l'ancienne `delete_my_account()` sans la suppression de
  `auth.users` (foyer verrouillé d'abord, charges propres retirées, saisies, comptes perso, profil, foyer du dernier
  membre, repartage pour l'autre), plus : mise à `null` de `account_key` et `ip_hash` de **tous** les événements de la
  personne (B7), suppression de ses lignes `login_session` (leur clé étrangère ne coule qu'avec `auth.users`, que la
  fonction ne supprime pas) et de ses `auth.sessions` / `auth.refresh_tokens` (B9, `private.ferme_les_sessions_auth`),
  puis l'événement `compte_supprime` dans la même transaction. Ses lignes `idempotency_key` partent en cascade avec son
  profil (B8). `invite_link.created_by` et `accepted_by` passent à `null` (`on delete set null`) : un lien accepté reste.
- **Journal** : `compte_supprime` ne porte aucune clé ; `person_id` passe à `null` quand `auth.users` est supprimé (clé
  étrangère). Les événements `connexion_ratee` et `connexion_bloquee` (clés de compte) se purgent à 90 jours, le reste à 1 an
  (0136).
- **Idempotente** : sans profil elle ne fait que refermer des sessions et n'écrit pas un second `compte_supprime`
  (nouvelle tentative après une panne d'Auth). `security definer`, `search_path = ''`, `execute` à `authenticated` seul
  (`anon`, `public`, `service_role` : rien) ; la personne vient de `auth.uid()`, sans identité : `insufficient_privilege`.
- **`delete_my_account()`** (appli en ligne) : même signature, mêmes droits, même effet ; appelle `efface_mes_donnees()` puis
  supprime `auth.users`. Risque accepté : `efface_mes_donnees` est appelable directement (PostgREST) par une personne
  connectée, sans réauthentification ; elle n'y gagne que ce qu'elle obtiendrait déjà par `delete_my_account`, et le compte
  Auth reste (elle peut se reconnecter). La garde de réauth est celle de la route (T14b).
- **Résidus connus** (hors de la fonction) : `auth.audit_log_entries` (journal de GoTrue : `actor_id`, adresse et IP ; ni la
  fonction ni la suppression d'`auth.users` n'y touchent, à traiter côté Auth) et `auth.flow_state.user_id` ; `login_throttle`
  (clés HMAC de compte, purgées à l'échéance, pas à la suppression) ; les identifiants d'une personne supprimée restent dans
  `depense_part`, `cloture_choix` et `versement_epargne` (uuid sans clé étrangère) tant que le foyer existe ; les événements
  écrits après l'effacement (reconnexion avant la suppression d'`auth.users`) gardent leurs clés. Les objets de Storage ne
  sont pas touchés ici.
- **`DELETE /api/v1/me`** (T14b) : session + réauthentification de moins de 5 minutes (`403 reauthentification_requise`
  sinon, rien n'est touché). Deux transactions, dans cet ordre : (1) `efface_mes_donnees()` sous la RLS de la personne, dans
  SA transaction, validée AVANT (2) `supprime_compte` (client d'administration d'Auth) ; `204` + cookie vidé (`Max-Age=0`,
  mêmes attributs que la pose). Pourquoi deux : Auth supprime `auth.users`, que le profil référence ; tant que l'effacement
  n'est pas validé, cette suppression l'attendrait, et lui attendrait Auth. Écart assumé à B4 (une transaction par
  requête quand c'est possible : ici ce ne l'est pas). Auth ne répond pas : `503 suppression_incomplete` AVEC le cookie vidé
  (la session n'existe plus) ; données et sessions sont parties, le compte Auth reste ; la personne se reconnecte et recommence
  (l'effacement se rejoue sans erreur et n'écrit pas un second `compte_supprime`). `deleteUser` sur `404 user_not_found` vaut
  succès ; un `404` d'une autre origine, non. L'événement `compte_supprime` est écrit par `efface_mes_donnees`, pas par la
  route ; sa `person_id` passe à null quand `auth.users` disparaît. Un journal ne reçoit jamais mot de passe ni jeton.
  Pas d'`Idempotency-Key` : `idempotency_key.person_id` référence le profil, que la route vient d'effacer (clé étrangère
  violée à l'enregistrement de la réponse) ; un second `DELETE` avec le même cookie rend `401`. Tests :
  `tests/integration/test_suppression_route.py` ; mutations rejouées : sans garde de réauth, sans effacement, sans appel à
  Auth, et effacement dans la transaction de session (le `503` annule alors l'effacement) font chacun échouer un test.

### 4.12 L'interface d'envoi des mails (0.4bis S3 ; code : `infra/mails.py`, `infra/mails_textes.py`)

- **La réinitialisation du mot de passe n'existe plus** (décision D3 du 13/11/2026 : plus aucun mot de passe ; le code par mail
  *est* la récupération). `POST /api/v1/password-resets` n'est plus ni dans le registre des routes ni dans `openapi.json` (un test le lit : sans session, toute route inconnue rend `401`, ce qui ne prouverait rien). Restent
  en base, retirés par S15 : la table `password_reset`, `cree_reinitialisation`, le créneau `reset` (`prend_un_creneau_reinit`)
  et, côté Python, `Empreintes.cle_reinitialisation` (et `_requise`, `ETIQUETTE_REINITIALISATION`), `prendre_un_creneau_de_reinitialisation` et les
  réglages `reinitialisation_essais` et `reinitialisation_fenetre_s`, que plus aucune route n'appelle.
- **`EnvoiMail`** (`Protocol`) : `envoie_le_code(MessageCode)` et `envoie_l_invitation(MessageInvitation)`. C'est ce que la demande
  de code (S5) et l'invitation (S12) appellent. Garanties : (1) l'envoi se fait **après** la réponse HTTP (`BackgroundTasks`) :
  un échec ne change jamais la réponse ; (2) un échec lève `MailIndisponible` et rien d'autre ; l'appelant le journalise par son
  type seul ; (3) un retour sans erreur veut dire « accepté par le fournisseur », pas « remis » ; (4) les textes viennent de
  `mails_textes.py`, et **une réalisation n'envoie que l'`Enveloppe`** (destinataire, objet, texte, heure d'expiration d'un code) qu'il rend :
  la base `EnvoiParEnveloppe` rend l'enveloppe et ne passe que celle-ci à `_transmet`, que la réalisation écrit ; seules
  `enveloppe_du_code` et `enveloppe_de_l_invitation` la fabriquent (cachet privé au module ; tests d'architecture : aucun autre appel,
  aucun autre fichier ne nomme le cachet, et un fichier `infra/mail_*.py` ne lit ni `.code`, ni `.lien`, ni un prénom, ni `MessageCode`), l'objet est vérifié contre
  les gabarits d'objet (`objet_admis`) et doit être un `str` exact. Les objets sont fixes, sauf un : celui de l'invitation, « {Hôte}
  t'a gardé une place en cuisine », où l'hôte est le **seul** prénom admis (jamais celui de l'invité), filtré par `prenom_valide`, 30 caractères
  au plus ; refusé, l'objet de repli « Une place t'attend en cuisine » s'applique. Jamais de code ni de lien dans un objet. `envoie_sans_remonter(envoyer,
  message, quoi)` est l'enveloppe de la tâche d'arrière-plan : `quoi` est un `TypeDeMail` (`code`, `invitation`, ou ces deux littéraux ; liste fermée,
  vérifiée à l'exécution, appariée au type exact du message : aucune adresse ni aucun code ne peut entrer dans le journal par là) ; elle
  journalise le type de l'erreur seul et borne l'envoi par son propre délai (20 s, sous les 25 s de la requête et au-dessus des 15 s de
  l'envoi réel). **Annulation, délai ou `MailIndisponible(issue_inconnue=True)` (requête partie, réponse perdue) : « issue inconnue »** (le
  fournisseur a pu accepter le mail : le journal ne dit jamais « non envoyé » alors) ; l'annulation repart même si la réalisation l'a
  traduite en erreur.
- **Les messages** : `MessageCode(destinataire, code, validite_min, expire_le)` (`expire_le` : l'échéance ABSOLUE du code, avec fuseau, fixée à la demande avant la base et jamais recalculée à l'envoi : S4 en fait `send_before` ; le code fait six chiffres ASCII ; le destinataire est **une seule adresse** de grammaire stricte :
  ASCII, partie locale de 64 caractères au plus, domaine à point, 254 au plus, ni virgule, ni espace, ni caractère de contrôle ou de
  direction, `infra.comptes.adresse_valide` et un point au domaine ; l'appelant la donne normalisée en minuscules) et `MessageInvitation(destinataire, prenom_invite, prenom_hote, lien, expire_le)` (`expire_le` avec décalage horaire, écrit à
  l'heure de Paris ; le lien est `<origine du front>/invitation#<jeton>` : `enveloppe_de_l_invitation(message, origines)` le refuse si ce n'est pas une origine
  de `Settings.origines`, s'il porte une partie utilisateur (`https://notre-popote.fr@evil.example/…`), un port non admis, un autre chemin,
  une requête (même vide), un blanc ou une tabulation, un jeton de plus de 128 caractères, ou s'il est en `http` ailleurs que vers l'hôte
  local ; un `POPOTE_PUBLIC_BASE_URL` hors de `Settings.origines` est signalé au démarrage hors local, car tous les liens seraient refusés). Leur `__repr__` masque tout : ni adresse, ni code, ni lien, ni prénom.
- **Les textes** : du texte clair, en français. L'objet du code est constant (`Ton code de connexion Popote`) et **ne porte jamais
  le code** : le fournisseur garde l'objet. Le seul prénom d'un objet est celui de l'hôte, dans l'invitation (voir plus haut). Dans le texte, un prénom passe par `prenom_affichable` :
  lettres Unicode (NFC d'abord, marques combinantes admises à trois de suite), espaces, tirets, apostrophes, 30 caractères au
  plus, une lettre visible au moins, sinon le repli « Quelqu'un » (« Bonjour, » pour l'invité). Sont refusés : les remplissages invisibles (U+3164, U+115F, U+1160, U+FFA0, U+2800), les caractères sans largeur (U+200B à U+200F, U+2060 à
  U+2064, U+FEFF) où qu'ils soient, les marques combinantes invisibles (U+034F, sélecteurs de variante, U+17B4, U+17B5, U+180B à
  U+180D, U+180F), tout prénom que NFKC change (pleine chasse, lettres mathématiques, ligatures) et tout mélange de deux écritures dans un
  même prénom (latin avec grec, cyrillique, arménien, cherokee ou coptique ; un titlo cyrillique sur une lettre latine). **Limites
  dites** : les homoglyphes d'une seule écriture passent (un prénom entièrement cyrillique qui ressemble à un prénom latin) ; un prénom
  qui mêle deux écritures légitimement (hiragana et kanji) reçoit le repli ; le ZWNJ des prénoms persans est refusé ; l'hôte choisit ses
  30 lettres (« Support Popote » passe) : le filtre réduit l'hameçonnage par prénom sans le supprimer (menace F6). Un prénom ne se garde jamais sans ce filtre : S12 l'applique aussi à la saisie.
- **Les réalisations** : `POPOTE_MAIL_PROVIDER` = `aucun` (défaut ; chaque envoi lève `MailIndisponible`, `MailAbsent`), `local`
  (`BoiteDeTest`, deux listes `codes` et `invitations`, **local seulement** : refusé ailleurs) ou `scaleway` (S4, ci-dessous).
  Hors local, `aucun` et l'absence de `POPOTE_PUBLIC_BASE_URL` sont signalés au démarrage ; le refus de démarrer sans fournisseur
  `scaleway` complet est armé en S7. Avec `scaleway`, la clé ou le projet manquant empêche de démarrer.
- **L'envoi réel, `infra/mail_scaleway.py` (S4)** : Scaleway Transactional Email, `POST` vers une adresse **écrite en dur** (région
  `fr-par`), clé dans `X-Auth-Token`. `EnvoiScaleway` hérite d'`EnvoiParEnveloppe` : il n'écrit que `_transmet(enveloppe)` et ne voit ni le
  code, ni le lien, ni un prénom (un test d'architecture le garde pour tout `infra/mail_*.py`) ; le sujet et le texte envoyés sont ceux de
  l'enveloppe. (1) **La clé n'est lue que par ce module** : test d'architecture (aucun autre fichier de `src/` ne nomme
  `scaleway_tem_secret_key`, hors réglages et fabrique, ni n'en appelle `get_secret_value` ; deux lectures dans le module, jamais passées à
  un autre code) ; `SecretStr`, `repr` des réglages et de l'envoi masqués, clé refusée à la construction si ce n'est pas un UUID (forme des
  clés Scaleway ; un blanc ou un caractère hors ASCII ferait recopier la clé par h11 dans son message) ; expéditeur (adresse et nom) limité au
  domaine vérifié `notre-popote.fr` et sans caractère d'en-tête ni mot encodé `=?`, projet de type `UUID` : tout est revalidé dans la fabrique,
  même si les réglages sont contournés (`model_construct`, `model_copy`). La clé n'est gardée que sous le nom `_cle_tem`, que le test d'architecture traite comme la clé. (2) **Aucune donnée dans les journaux ni les exceptions** : ni clé, ni
  adresse, ni objet, ni texte, ni corps de réponse ; seuls le type de l'erreur et la classe du statut (`4xx`, `5xx`). (3) Délais finis
  (3 s, 5 s, 15 s au total), aucune exception d'httpx chaînée (elle porte la requête entière : clé, adresse, texte ; on n'en garde que le
  type, dans une cause neuve sans pile) ; l'issue d'une tentative est un résultat (`_Issue`), pas une exception, et l'erreur finale est levée hors de tout
  `except`, donc sans contexte ; le `repr` d'une réponse masque son corps, redirections refusées, `trust_env=False`, réponse lue sur 64 Kio au plus, tout `Content-Encoding` refusé (`Accept-Encoding:
  identity` : sans décompression, la borne porte sur les octets reçus). (4) **Une** reprise sur coupure, délai ou `5xx` (pause de 0,5 s,
  `Retry-After` entier respecté jusqu'à 3 s) ; **aucune** sur `4xx`, ni sous un `2xx` même illisible ou dont le corps se coupe : un mail
  déjà accepté n'est jamais renvoyé par l'API ; au pire deux mails identiques (coupure après acceptation), jamais deux codes différents.
  (5) Succès = premier mail `new`, `sending` ou `sent` : **accepté, pas remis** ; l'identifiant du mail n'est pas gardé (un rebond dur ne
  se voit que dans la console TEM). (6) **Un code expiré n'est jamais livré** : `send_before` est `enveloppe.expire_le`, l'échéance
  ABSOLUE fixée une fois à la demande du code (`MessageCode.expire_le`), tronquée à la seconde, identique à la reprise et **jamais
  recalculée à l'envoi** ; un code déjà expiré n'est pas envoyé (les deux heures se comparent tronquées, comme TEM les verra). (7) L'annulation de la tâche n'est ni avalée ni reprise. (8) **Issue
  inconnue** : `MailIndisponible(issue_inconnue=True)` quand le mail a pu partir : coupure après l'envoi de la requête, délai (de requête ou
  total tombé pendant une requête en vol), tout `5xx` (TEM a pu enregistrer le mail avant d'échouer à répondre), `2xx` illisible ou à l'état
  `unknown`, exception étrangère du transport. Elle **cumule** les tentatives : une première tentative incertaine laisse l'issue
  inconnue quoi que dise la seconde. Elle est fausse pour un `4xx`, un état `failed` ou `canceled`, une **connexion impossible** (la requête
  n'est jamais partie : `ConnectError`, `ConnectTimeout`, `PoolTimeout`, reprise sans risque) et pour un délai total tombé pendant la pause
  après une telle tentative. Un statut reçu décide, même si le corps ou la fermeture casse ensuite. **La reprise recontrôle l'échéance du
  code** (sans toucher à `send_before`) : un code expiré pendant la pause n'est pas reposté. (9) **Règle globale : aucun outil ne capture les variables locales des cadres d'une pile.** La clé et l'adresse
  du destinataire sont des variables locales de `mail_scaleway.py` (`_transmet`, `_poste`) et des appelants (le message) pendant l'envoi,
  donc dans les cadres de toute pile qui traverse ces fonctions : aucun code ne peut les en retirer, on garantit donc qu'aucun outil ne les
  lit. Sentry (décidé le 13/11) arrivera avec `include_local_variables=False`, `send_default_pii=False` et `max_request_body_size="never"` ;
  un test d'architecture échoue si `sentry_sdk.init` apparaît sans ces trois réglages, ou si `show_locals`, `rich.traceback` ou
  `TracebackException(capture_locals=True)` apparaît dans `src/`. La clé reste un `SecretStr` jusqu'au dernier moment : la valeur brute
  n'existe que dans `_en_tetes_ou_rien` (nettoyage et contrôle de forme compris), le temps de construire les en-têtes ; la construction de l'envoi
  l'essaie une fois pour refuser une clé mal formée au démarrage, et l'erreur est levée hors de cette fonction. Le test d'architecture exige une seule
  lecture dans le module ; il refuse aussi `sentry_sdk.init` importé sous un alias, tout `capture_locals` autre que `False`, toute forme d'import
  de `rich.traceback`, et la constante `"_cle_tem"` hors du module. `ValidationError.errors()` ou `.json()` sur une erreur de réglages recopie la valeur de la clé (seuls `str` et `repr` la masquent) :
  ne jamais les appeler sur les réglages sans `include_input=False`. Sources, gestes de la
  clé, rotation et quota : `docs/exploitation.md`, « L'envoi réel ».
- Tests : `tests/unit/test_mails.py`, `tests/unit/test_mails_durcis.py`, `tests/unit/test_mail_scaleway.py` (faux transport
  `httpx.MockTransport` : aucun appel réel). `BoiteDeTest(en_panne=True)` simule un fournisseur qui ne répond plus. Mutations rejouées : le code dans l'objet, ne
  pas filtrer le prénom (hôte et invité), ne pas normaliser en NFC, marques et remplissages invisibles, avaler l'annulation,
  journaliser le message de l'erreur, `quoi` libre, objet non contrôlé ou portant le code, destinataire en `\S+`, origine du lien non vérifiée,
  invisible au milieu d'un prénom, écritures mêlées, NFKC, annulation dite « non envoyé » ou traduite en erreur, envoi sans délai propre.


### 4.13 Les clés d'accès : le socle (0.4bis S8a ; code : `infra/webauthn.py`, `config.py`)

Partie sans base : ni table, ni route. L'enregistrement (S8b), la connexion (S9) et la gestion (S10) s'appuient sur elle.

- **RP ID et origines** (`WEBAUTHN_PAR_ENV`, surchargeables par `POPOTE_WEBAUTHN_RP_ID` et `POPOTE_WEBAUTHN_ORIGINS`, liste séparée
  par des virgules) : prod `notre-popote.fr` et `https://notre-popote.fr` ; essai `essai.notre-popote.fr` et
  `https://essai.notre-popote.fr` ; local `localhost` et `http://localhost:5173` (jamais `127.0.0.1` : une adresse IP n'est pas un
  RP ID valide). **Aucun aperçu `*.workers.dev`** : son hôte n'a pas le RP ID de l'essai pour suffixe ; la route de défi y rendra
  `403 cle_origine_non_admise` (S8b), le code par mail reste possible. Le démarrage échoue si une origine n'est pas celle que le
  navigateur écrit (`schéma://hôte[:port]`, minuscules, sans chemin, barre finale ni port par défaut), si, hors local, elle n'est pas
  `https` sans port ou vise `localhost` ou une adresse IP, si, en local, `http` vise autre chose que `localhost`, ou si le RP ID n'est pas
  l'hôte (ou un domaine parent, à la frontière d'un point) de **chaque** origine, ou n'a pas de point (`com`). **Hors local, le RP ID est
  `notre-popote.fr` ou l'un de ses sous-domaines** : ni un suffixe public (`workers.dev`, `co.uk`) ni le domaine d'un autre ne démarrent.
- **Ce que la bibliothèque est tenue de faire** (lu dans `webauthn` 3.0.1) et ce que `infra/webauthn.py` y ajoute, W3C WebAuthn niveau 3
  (Recommandation du 25/08/2026) :
  - **options d'enregistrement** : clé découvrable (`residentKey: required`), `userVerification: required`, attestation `none`,
    défi de 32 octets (`secrets`), délai de 300 000 ms, `excludeCredentials` (transports connus seulement), identifiant d'utilisateur de
    1 à 64 octets (la bibliothèque remplace un identifiant vide par un tirage : refusé ici) ; **options de connexion** : aucune clé
    nommée, `userVerification: required` (la cérémonie ne part d'aucun nom : § 14.6.2) ;
  - **vérifications des deux cérémonies** : défi égal à celui des options (la base le tient à usage unique, S8b), origine dans la liste
    **exacte**, hachage du RP ID, UP, **UV exigé**, signature, BS jamais sans BE ; en plus, ici : **`crossOrigin` autre que `false`
    ou `topOrigin` présents refusés** (la bibliothèque lit « crossOrigin » avec `bool()` : la chaîne `"false"` vaudrait vrai et elle ne
    lit pas `topOrigin`), **attestation autre que `none` refusée** (Popote n'a aucune racine de confiance à offrir ; le CBOR est
    décodé ici avant la bibliothèque : `fmt` vaut `none`, `attStmt` est vide, `authData` est une chaîne d'octets : un `authData`
    entier lui ferait allouer `bytes(n)`), identifiant de clé de 16 à 1023 octets et **égal** à celui de l'attestation, **clé publique
    chargée et cohérente avec son algorithme** (la bibliothèque ne la charge pas : une P-256 annoncée EdDSA, un RSA de 1024 bits, un
    point hors courbe seraient écrits, puis refusés à toute connexion en comptant dans la limite des clés ; ici : -7 suppose
    EC2 P-256, -8 Ed25519, -257 RSA d'au moins 2048 bits et d'exposant 65537 au moins) ;
  - **connexion en plus** : l'identifiant de la réponse est celui de la clé lue en base ; **`userHandle` présent et égal** à celui de la
    personne (§ 7.2) ; éligibilité à la sauvegarde (BE) **inchangée** ; compteur : si l'un des deux n'est pas nul, il doit croître. Un
    compteur qui ne croît pas lève `CompteurDeCleRegresse`, **après** la vérification de la signature : sans signature valide, ce
    n'est qu'un refus ordinaire (S9 n'écrit `cle_suspecte` que sur cette erreur, un inconnu ne peut pas en provoquer) ;
  - **toute entrée illisible** (JSON, base64url, CBOR, clé COSE tronquée) donne `ReponseDeCleRefusee`, au message fixe : ni clé, ni
    identifiant, ni signature, ni défi n'y entrent. La cause reste chaînée pour le débogage, mais **son message recopie la réponse**
    (la bibliothèque écrit l'origine reçue, jusqu'à 1 Mio) : **un journal n'écrit que `erreur.type_de_la_cause`** (à tenir en S8b et S9).
    Les erreurs de la bibliothèque attrapées sont `WebAuthnException`, `ValueError`, `TypeError`, `KeyError`, `IndexError` (une clé COSE
    incomplète), `RecursionError` (un JSON imbriqué sur des milliers de niveaux, tenable dans 1 Mio) et `OverflowError` ; `MemoryError` n'est
    pas attrapée, le type de `authData` est contrôlé avant. Toute autre exception est un bogue et remonte ;
  - **une clé publique illisible en base** lève `CleStockeeIllisible` (hors de `ReponseDeCleRefusee`) : une donnée abîmée, pas une
    mauvaise réponse ; S9 alerte au lieu de répondre « clé refusée » ;
  - `defi_de_la_reponse` lit le défi annoncé dans la réponse, pour retrouver en base **le** défi (haché sur les octets décodés) ;
    `identifiant_de_la_cle` borne l'identifiant (16 à 1023 octets) avant que la route ne lise la base. Les dataclasses
    (`OptionsDeCeremonie`, `CleEnregistree`, `CleDeConnexion`, `CleExistante`) cachent défi, identifiants et clés dans leur `repr` ;
- **Limites dites.** (1) L'attestation `none` ne prouve pas que l'authentificateur détient la clé privée à l'enregistrement : W3C § 7.1
  note qu'un attaquant qui connaît un identifiant et une clé publique pourrait les enregistrer comme siens ; la parade est la base :
  **identifiant de clé unique pour tout le monde** (`409 cle_deja_enregistree`, S8b). (2) Le défi n'est vérifié qu'égal à celui qu'on
  donne : le rejeu d'un défi est refusé par la base, pas par ce module. (3) L'AAGUID est gardé, jamais interprété.
- **À tenir en S8b et S9.** (1) Seul `type_de_la_cause` va aux journaux, jamais le texte de la cause : il recopie la réponse du
  navigateur. (2) L'identifiant de clé est unique en base pour tout le monde (`409 cle_deja_enregistree`) : l'attestation `none` ne prouve
  pas la possession de la clé privée.
- **Authentificateur de test** : `tests/unit/_authentificateur.py` (ES256, EdDSA, RS256 ; UP, UV, BE, BS, compteur, `userHandle`,
  origine, RP ID, défi, signature, cadre, attestation réglables) ; il sert à tous les tests de S8b à S16.
- Tests : `tests/unit/test_webauthn.py` (refus d'origine, RP ID, défi, UV, UP, `userHandle`, BE, compteur, signature, cadre, attestation,
  identifiant ; réponses mal formées, JSON imbriqué, `authData` démesuré, clés publiques incohérentes, 750 réponses aux octets abîmés), `tests/unit/test_config_cles.py`. Mutations rejouées
  (`scripts` non versionnés, liste dans la demande de fusion) : UV non exigée (deux cérémonies, deux options), clé non découvrable,
  origine admise sans liste (deux cérémonies), attestation non filtrée, `crossOrigin`, `topOrigin`, `userHandle` (non exigé ou absent admis),
  clé de la réponse non comparée, BE libre, compteur (ignoré, égal admis, zéro des deux refusé, zéro après un compteur admis, contrôlé
  avant la signature), défi (taille, court admis, non comparé), bornes de l'identifiant de clé, identifiant d'attestation, identifiant
  d'utilisateur vide, RP ID des options, clés exclues, et dans la configuration : suffixe, frontière de point, `http`, `localhost`,
  RP ID sans point : chacune fait échouer un test.
- **Retour arrière** : retirer `infra/webauthn.py`, les réglages `webauthn_*` et la dépendance (`uv remove webauthn`).
