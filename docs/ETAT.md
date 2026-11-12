# État de l'API à la fin de l'étape 0.3 (13/11/2026)

## Ce que fait l'API

- **Socle HTTP** : erreurs `problem+json` (RFC 9457), journal JSON et trace W3C, limites de taille, de type et
  de délai, débit par adresse puis par personne, garde du relais et de l'origine, `Idempotency-Key` sur les
  `POST`, `ETag` et requêtes conditionnelles, pagination par curseur, formats communs, contrat `openapi.json`
  gardé en CI. Règles : [`normes-api.md`](normes-api.md).
- **Base** : deux pools (`popote_api`, `popote_internal`), contextes personne et service par `set local role`,
  erreurs de la base traduites, nouvelle porte du service (migration 0131). Règles : [`securite.md`](securite.md) § 5.1.
- **Session** : lecture de la session de connexion, `/api/v1` fermé sans session ; seule route métier :
  `GET /api/v1/me`, avec l'amorce de la matrice d'autorisation (`tests/authz/`).
- **Routes internes** : `/internal/*` signées par HMAC (`X-Popote-Signature`) ; aucune route réelle encore.
- **Essai** : migrations appliquées par la CI (`migre-essai`), image déployée ; `GET /api/v1/me` sans cookie
  rend `401` en `problem+json` avec `WWW-Authenticate`, à travers le relais.
- **Preuve sur le pooler de l'essai** : [`preuves-0.2.md`](preuves-0.2.md), preuve 3.

## Ce qui reste à Kamil

1. Poser les secrets du conteneur d'essai : `~/PERSO/sauvegardes-popote/outils-prod/pose_env_conteneur_essai.py`
   (`POPOTE_DATABASE_URL_INTERNAL`, `POPOTE_INTERNAL_SECRET`) ; sans eux le conteneur d'essai ne démarre pas à jour.
2. Décider D4 (suivi des erreurs : `suivi.signale` est une prise sans effet) et D6 (fournisseur de mails).
3. Rejeu complet des suites de contextes sur le pooler : demande une adresse d'administration de l'essai pour
   semer les données fictives (voir la preuve 3) ; non fournie, donc non faite.

## Ce qui part en 0.4

Connexion : contexte « connexion » de la base (#83), journal de sécurité et clés HMAC (#84), vérification du mot
de passe en base (#85), invitation, réinitialisation, appareils, suppression.
Plus tard : fermer `execute` de `PUBLIC` sur 21 fonctions de déclencheur (#37, 0.7), rôle de lecture pour la
sauvegarde (#35, 0.7).
