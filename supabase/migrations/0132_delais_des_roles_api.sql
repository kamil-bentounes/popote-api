-- Les délais des rôles de connexion de l'API (spec § 5.1, § 8.2). Compatible avec l'appli en ligne : `popote_api` et
-- `popote_internal` n'y servent à rien (ses requêtes passent par PostgREST, donc par `authenticator`), et `alter role
-- … set` ne s'applique qu'aux NOUVELLES connexions de ces deux rôles.
--
-- Pourquoi sur le rôle : le contexte « personne » emprunte `authenticated` par `set local role`, et `set role` n'applique
-- pas les réglages du rôle emprunté (seulement ceux du rôle de connexion). Sans ces `alter role`, une requête de
-- l'API n'aurait aucune borne côté base : l'annulation côté client ne la coupe pas sous Supavisor (la requête continue
-- sur le serveur). Le code pose les mêmes valeurs par `set local` à chaque transaction (`infra/db.py`, un test compare).
--
-- Valeurs :
--   popote_api       statement_timeout 8 s   : même borne qu'`authenticator` et `authenticated` (la voie actuelle) ;
--                                              une requête qui y passe passe ici. Au-delà, c'est un travail asynchrone.
--                    lock_timeout 5 s        : un verrou de foyer (budget) se libère en quelques centaines de ms ;
--                                              attendre plus, c'est un interblocage ou un travail resté ouvert.
--                    idle_in_transaction 15 s: aucune attente réseau dans une transaction (règle d'écriture) ; une
--                                              transaction oubliée ouverte garderait ses verrous et sa connexion.
--   popote_internal  statement_timeout 30 s  : purges et rappels par lots, « délai serveur » de normes-api.md § 3.6.
--                    lock_timeout 10 s       : les lots attendent un peu plus qu'une requête de personne.
--                    idle_in_transaction 15 s: comme ci-dessus.
--
-- Droits : aucun `grant` à poser ici, ceux d'emprunt sont ceux de 0130. Le `revoke` du bas écrit que ces rôles n'ont
-- pas le droit de créer d'objets dans `public` (ils n'exécutent jamais de DDL) : sans effet aujourd'hui, la création y
-- est déjà fermée, et il ne retire pas ce qu'un rôle tiendrait de PUBLIC. Rien à défaire.
--
-- Retour arrière (sans perte : aucune donnée touchée) :
--   alter role popote_api reset statement_timeout;
--   alter role popote_api reset lock_timeout;
--   alter role popote_api reset idle_in_transaction_session_timeout;
--   alter role popote_internal reset statement_timeout;
--   alter role popote_internal reset lock_timeout;
--   alter role popote_internal reset idle_in_transaction_session_timeout;
set local lock_timeout = '5s';
set local statement_timeout = '30s';

alter role popote_api set statement_timeout = '8s';
alter role popote_api set lock_timeout = '5s';
alter role popote_api set idle_in_transaction_session_timeout = '15s';

alter role popote_internal set statement_timeout = '30s';
alter role popote_internal set lock_timeout = '10s';
alter role popote_internal set idle_in_transaction_session_timeout = '15s';

revoke create on schema public from popote_api, popote_internal;
