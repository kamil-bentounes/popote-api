-- La nouvelle porte du service (spec § 5.1) : `is_service_role()` ne se fie plus à une revendication seule.
-- Compatible avec l'appli en ligne : ses fonctions Edge passent par PostgREST, donc `session_user = 'authenticator'`,
-- avec la revendication `role = service_role` que PostgREST pose après avoir vérifié la signature du JWT.
--
-- Retour arrière (sans perte : aucune donnée touchée) : remettre la définition de 0006,
--   create or replace function public.is_service_role() returns boolean language sql stable as $f$
--     select current_user = 'service_role'
--         or coalesce(nullif(current_setting('request.jwt.claims', true), '')::jsonb ->> 'role', '') = 'service_role'
--   $f$;
--   comment on function public.is_service_role() is null;
-- Les `revoke` / `grant` du bas rejouent 0126 : rien à défaire.
set local lock_timeout = '5s';
set local statement_timeout = '30s';

/* Pourquoi `session_user` : c'est le rôle de CONNEXION, que ni `set role`, ni une fonction `security definer`, ni
   un paramètre de session ne changent. `current_user` devient le propriétaire dans une fonction `security definer`
   (c'était la raison du recours à la revendication), et la revendication n'est qu'un paramètre : un `set_config`
   dans le pool « personne » l'écrivait lui-même. Un `case` plutôt qu'un `or` : elle n'est convertie en json que
   pour `authenticator` ; pour tout autre rôle, une valeur illisible est ignorée sans erreur. */
create or replace function public.is_service_role()
returns boolean language sql stable set search_path = '' as $$
  select case session_user
    when 'popote_internal' then true
    when 'authenticator' then
      coalesce(nullif(pg_catalog.current_setting('request.jwt.claims', true), '')::jsonb ->> 'role', '') = 'service_role'
    else false
  end
$$;

comment on function public.is_service_role() is
  'Vrai pour la connexion de l''API interne (popote_internal), ou pour PostgREST (authenticator) quand il a vérifié '
  'un JWT de rôle service_role. La branche authenticator part au J+2 de la bascule (spec § 5.1, § 11) : il ne restera '
  'que popote_internal. Ni current_user ni une revendication seule ne suffisent.';

/* Les fonctions réservées au service : exécutables par `service_role` seulement. Le rôle de connexion
   `popote_internal` les atteint en empruntant `service_role` (`set local role`), il n'a donc pas besoin de droit
   propre. `appelle_les_rappels()` n'a pas d'appelant de service (`pg_cron` la lance en `postgres`, son propriétaire),
   n'a pas de porte elle-même, et `service_role` en garde le droit comme avant. `is_service_role()` reste, elle,
   exécutable par tous : les déclencheurs la lisent sous le rôle de l'appelant. */
revoke all on function public.rappel_prenom(text, text) from public, anon, authenticated;
revoke all on function public.rappel_actifs(text) from public, anon, authenticated;
revoke all on function public.rappel_point(uuid, date, text) from public, anon, authenticated;
revoke all on function public.rappels_a_envoyer(timestamptz) from public, anon, authenticated;
revoke all on function public.prepare_les_rappels(timestamptz) from public, anon, authenticated;
revoke all on function public.note_la_passe(text, integer, integer, integer) from public, anon, authenticated;
revoke all on function public.reserve_rappel(uuid, text, text[]) from public, anon, authenticated;
revoke all on function public.libere_rappel(uuid, text, text[]) from public, anon, authenticated;
revoke all on function public.appelle_les_rappels() from public, anon, authenticated;
grant execute on function public.rappel_prenom(text, text) to service_role;
grant execute on function public.rappel_actifs(text) to service_role;
grant execute on function public.rappel_point(uuid, date, text) to service_role;
grant execute on function public.rappels_a_envoyer(timestamptz) to service_role;
grant execute on function public.prepare_les_rappels(timestamptz) to service_role;
grant execute on function public.note_la_passe(text, integer, integer, integer) to service_role;
grant execute on function public.reserve_rappel(uuid, text, text[]) to service_role;
grant execute on function public.libere_rappel(uuid, text, text[]) to service_role;
grant execute on function public.appelle_les_rappels() to service_role;
