-- L'adresse de la personne connectée, pour `GET /api/v1/me` (spec § 3.10, plan 0.3 amendement A17). Compatible avec
-- l'appli en ligne : une fonction de plus, que rien n'appelle encore.
--
-- Pourquoi une fonction : `user_profile` n'a pas d'e-mail (il est dans `auth.users`), et `authenticated` n'a aucun
-- droit sur `auth.users`. La fonction `security definer` ne rend que la ligne de `auth.uid()` : une personne ne peut
-- pas demander l'adresse d'une autre, aucun paramètre ne le permet. `anon`, `service_role` et `popote_api` n'ont pas
-- le droit de l'exécuter : le contexte « personne » l'appelle après `set local role authenticated`.
--
-- Retour arrière (sans perte) :
--   drop function public.mon_email();
set local lock_timeout = '5s';
set local statement_timeout = '30s';

create or replace function public.mon_email()
returns text
language sql
stable
security definer
set search_path = ''
as $$
  select u.email::text from auth.users u where u.id = auth.uid() and u.deleted_at is null
$$;

comment on function public.mon_email() is
  'L''adresse de connexion de la personne de la session (auth.uid()), ou null. Exécutable par authenticated seulement.';

revoke all on function public.mon_email() from public, anon, authenticated, service_role;
grant execute on function public.mon_email() to authenticated;
