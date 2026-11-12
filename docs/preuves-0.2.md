# Preuves de l'étape 0.2

Chaque section dit ce qui est prouvé, comment le rejouer (sans aucun secret) et ce qui reste à surveiller.

## Preuve 3 : Supavisor

Date : 12/11/2026. Migration : `supabase/migrations/0130_roles_api.sql`. Tests : `tests/integration/test_roles.py`.

### Ce qui est prouvé

Les deux rôles de connexion de l'API (spec § 5.1) se comportent de la même façon en direct sur Postgres et
à travers le pooler Supavisor du projet d'essai, en mode transaction, port 6543, TLS exigé :

- `popote_api` emprunte `authenticated` par `set local role` le temps d'une transaction, puis redevient
  `popote_api` ; il ne peut pas emprunter `service_role` ;
- `popote_internal` emprunte `service_role` le temps d'une transaction, puis redevient `popote_internal` ;
  il ne peut pas emprunter `authenticated` ;
- sans emprunt, `popote_api` n'a aucun droit sur les tables (`public.household` : `InsufficientPrivilege`) ;
- l'identifiant de connexion est bien `<rôle>.<ref du projet>` ; la connexion cliente est chiffrée
  (`sslmode=require`, `ssl_in_use` vrai) ;
- les rôles sont créés `login noinherit nosuperuser nocreatedb nocreaterole noreplication`, les droits
  d'emprunt par `grant … with inherit false, set true` (Postgres 17.6 en local comme sur l'essai).

L'essai accepte `grant service_role to popote_internal` pour `postgres` : la spec § 5.1 n'a pas à changer.

### Commandes

```bash
# 1. Migration (projet d'essai lié ; en CLI 3.x, db push vise la base locale sans --remote)
SUPABASE_ACCESS_TOKEN="$SUPABASE_ESSAI_TOKEN" npx supabase link --project-ref "$ESSAI_REF"
SUPABASE_ACCESS_TOKEN="$SUPABASE_ESSAI_TOKEN" SUPABASE_DB_PASSWORD="$ESSAI_DB_PASSWORD" \
  npx supabase db push --remote --dry-run     # ne doit lister que 0130
SUPABASE_ACCESS_TOKEN="$SUPABASE_ESSAI_TOKEN" SUPABASE_DB_PASSWORD="$ESSAI_DB_PASSWORD" \
  npx supabase db push --remote --yes

# 2. Mots de passe (32 caractères alphanumériques tirés au hasard, écrits dans secrets.env)
#    posés par POST /v1/projects/$ESSAI_REF/database/query : alter role popote_api|popote_internal password …

# 3. Hôte du pooler : GET /v1/projects/$ESSAI_REF/config/database/pooler
#    -> aws-1-eu-west-1.pooler.supabase.com:6543, pool_mode = transaction

# 4. Les tests, rejoués contre le pooler
export POPOTE_TEST_DSN_API="postgresql://popote_api.$ESSAI_REF:$ESSAI_PW_API@$HOTE_POOLER:6543/postgres?sslmode=require"
export POPOTE_TEST_DSN_INTERNAL="postgresql://popote_internal.$ESSAI_REF:$ESSAI_PW_INTERNAL@$HOTE_POOLER:6543/postgres?sslmode=require"
uv run pytest tests/integration/test_roles.py -m integration -v -rxX
```

Sans ces deux variables, le même fichier vise la base locale (`127.0.0.1:54322`) et pose lui-même le mot de
passe `essai-local` sur les deux rôles. Avec une seule des deux, le test échoue.

### Résultats

| Test | Locale (Postgres 17.6) | Pooler, mode transaction |
|---|---|---|
| `popote_api` emprunte `authenticated` le temps de la transaction | réussi | réussi |
| `popote_api` ne peut pas emprunter `service_role` | réussi | réussi |
| `popote_internal` emprunte `service_role` le temps de la transaction | réussi | réussi |
| `popote_internal` ne peut pas emprunter `authenticated` | réussi | réussi |
| aucun droit sur les tables sans emprunt | réussi | réussi |
| aucun `execute` sur les fonctions `security definer` sans emprunt | échec attendu (xfail strict) | échec attendu (xfail strict) |

Locale, pooler : 5 réussis et 1 échec attendu chacun.

La ligne « locale » a été jouée sur une copie jetable de l'image `supabase/postgres:17.6.1.166` (migrations
0001 à 0130 rejouées, `storage` et `auth.users` réduits au strict nécessaire), et non sur la pile locale
partagée : celle-ci n'a pas pu recevoir 0130 (voir « À surveiller »).

### `execute` hérité de PUBLIC (à fermer à l'étape 0.7)

21 des 93 fonctions `security definer` de `public` portent `=X/postgres` : le droit `execute` est donné à
`PUBLIC`, donc `popote_api` l'a sans rien emprunter. Ce sont toutes des fonctions de déclencheur (`tg_*`,
retour `trigger`), qu'on ne peut pas appeler directement : l'exposition réelle est nulle aujourd'hui, mais
le droit existe. Les 72 autres sont fermées à `PUBLIC`. Le test est en `xfail(strict=True)` : il passera
(et fera échouer la suite, à retirer alors) le jour où la migration de fermeture retire ce droit.
Même constat sur la base locale et sur la copie jetable.

### À surveiller

- **`SET ROLE` de session : il fuit entre clients du pooler.** Constaté sur l'essai : un client qui lance
  `set role authenticated` (hors transaction) laisse le serveur sous ce rôle, et quinze connexions neuves
  ouvertes ensuite sont toutes devenues `authenticated`. Seul `set local role` (dans une transaction)
  est sûr ; après `set local`, les connexions suivantes voient bien `popote_api`. Règle pour l'API :
  jamais de `set role` de session, jamais de `set` sans `local`, toujours `set_config(…, true)`. Un
  contrôle statique (recherche de `set role` sans `local` dans `src/`) ou un test de non-fuite sur les
  requêtes de l'API serait utile. Le serveur de l'essai a été remis à zéro par `reset role`.
- **Instructions préparées.** Le test les désactive (`prepare_threshold=None`) : le mode transaction
  n'assure pas le même serveur d'un appel à l'autre. Une exécution répétée avec le seuil par défaut de
  psycopg est passée sans erreur sur l'essai (Supavisor les gère), mais l'API doit garder le réglage
  explicite plutôt que de s'y fier.
- **Pile locale partagée en retard.** Elle n'a enregistré que 0001 à 0121 alors que 0122 à 0129 existent
  dans `supabase_admin` (fonctions appartenant à `supabase_admin`) : `npx supabase migration up` échoue à
  0122 (`must be owner of function mange_une_part`). La migration 0130 n'y est donc pas appliquée ; à
  réparer par Kamil (`migration repair` ou remise à zéro) avant que la CI ou un autre poste ne s'y fie.
- **Mots de passe.** `ESSAI_PW_API` et `ESSAI_PW_INTERNAL` sont dans `secrets.env` (droits 600) ; ceux de la
  prod seront tirés à part, dans le gestionnaire de secrets, au déploiement.
- **Région.** L'hôte du pooler de l'essai est en `eu-west-1`, et non `eu-west-3` comme dans le plan.
