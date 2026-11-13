-- ═══════════════════════════════════════════════════════════════════════════
-- 0140 · LES APPAREILS : LISTER, FERMER UN, FERMER TOUS LES AUTRES (spec § 4, « Appareils » ; B3, B19, B26)
--
-- Contexte « personne » : la requête tourne sous `authenticated`, `auth.uid()` vaut la personne de la session. Les trois
-- fonctions lisent CETTE personne et nulle autre : une session d'une autre personne est « inconnue », jamais révélée.
--
--  - `public.mes_sessions(p_limit, p_after_seen, p_after_id)` : les sessions ACTIVES de la personne (ni révoquées, ni
--    échues), de la dernière activité la plus récente à la plus ancienne, puis par identifiant ; la page reprend
--    strictement après le couple (p_after_seen, p_after_id). Rien d'autre que l'identifiant, l'appareil (familles
--    courtes) et les dates : jamais d'empreinte, d'adresse ni de texte d'agent.
--  - `public.ferme_un_appareil(p_id, p_courante)` : rend `fermee`, `deja_fermee` (la session est à la personne mais
--    n'était plus active) ou `inconnue` (autre personne, ou rien). Un événement par session fermée, dans la même
--    transaction : `deconnexion` si c'est la session courante, `session_fermee` sinon.
--  - `public.ferme_les_autres_appareils(p_courante)` : ferme toutes les AUTRES sessions actives de la personne ;
--    rend leur nombre. Un événement `session_fermee` par session.
-- Les noms ne reprennent pas `ferme_session` : celle de 0139 (par empreinte) sert la connexion.
--
-- DROITS (B3) : `authenticated` seul. `anon`, `popote_api`, `popote_internal`, `service_role`, `public` : aucun.
-- Pas de paramètre d'horloge (B19) : les fonctions lisent `now()`.
--
-- COMPATIBLE avec l'appli en ligne : trois fonctions neuves, aucune table, colonne ni fonction existante modifiée.
--
-- Retour arrière (sans perte) :
--   drop function public.ferme_les_autres_appareils(uuid), public.ferme_un_appareil(uuid, uuid),
--     public.mes_sessions(integer, timestamptz, uuid);
--   drop index public.login_session_person_seen_idx;
-- ═══════════════════════════════════════════════════════════════════════════
set local lock_timeout = '5s';
set local statement_timeout = '30s';

-- Index de la liste : les sessions d'une personne, par dernière activité.
create index if not exists login_session_person_seen_idx on public.login_session (person_id, last_seen_at desc, id desc);

create or replace function public.mes_sessions(
  p_limit integer default 20, p_after_seen timestamptz default null, p_after_id uuid default null
) returns table (id uuid, browser text, os text, created_at timestamptz, last_seen_at timestamptz)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  v_person uuid := auth.uid();
begin
  if v_person is null then
    raise exception 'Aucune personne dans ce contexte.' using errcode = 'invalid_authorization_specification';
  end if;
  if p_limit is null or p_limit < 1 or p_limit > 101 then
    raise exception 'La taille de page doit valoir de 1 à 101.' using errcode = 'invalid_parameter_value';
  end if;
  return query
  select s.id, s.browser, s.os, s.created_at, s.last_seen_at
    from public.login_session s
   where s.person_id = v_person
     and s.revoked_at is null
     and s.expires_at > pg_catalog.now()
     and s.absolute_expires_at > pg_catalog.now()
     and (p_after_seen is null or (s.last_seen_at, s.id) < (p_after_seen, p_after_id))
   order by s.last_seen_at desc, s.id desc
   limit p_limit;
end;
$$;
comment on function public.mes_sessions(integer, timestamptz, uuid) is
  'Les sessions actives de la personne du contexte (auth.uid()), de la plus récente à la plus ancienne. Exécutable par authenticated seul.';
revoke all on function public.mes_sessions(integer, timestamptz, uuid)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.mes_sessions(integer, timestamptz, uuid) to authenticated;

create or replace function public.ferme_un_appareil(p_id uuid, p_courante uuid default null)
returns text
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_person uuid := auth.uid();
  v_id uuid;
begin
  if v_person is null then
    raise exception 'Aucune personne dans ce contexte.' using errcode = 'invalid_authorization_specification';
  end if;
  update public.login_session s
     set revoked_at = pg_catalog.now()
   where s.id = p_id
     and s.person_id = v_person
     and s.revoked_at is null
     and s.expires_at > pg_catalog.now()
     and s.absolute_expires_at > pg_catalog.now()
  returning s.id into v_id;
  if found then
    perform private.ecrit_evenement(
      case when p_id is not distinct from p_courante then 'deconnexion' else 'session_fermee' end, v_person, v_id);
    return 'fermee';
  end if;
  if exists (select 1 from public.login_session s where s.id = p_id and s.person_id = v_person) then
    return 'deja_fermee';
  end if;
  return 'inconnue';
end;
$$;
comment on function public.ferme_un_appareil(uuid, uuid) is
  'Ferme une session de la personne du contexte : fermee, deja_fermee ou inconnue (autre personne comprise). Un événement par session fermée. Exécutable par authenticated seul.';
revoke all on function public.ferme_un_appareil(uuid, uuid)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.ferme_un_appareil(uuid, uuid) to authenticated;

create or replace function public.ferme_les_autres_appareils(p_courante uuid)
returns integer
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_person uuid := auth.uid();
  v_nombre integer;
begin
  if v_person is null then
    raise exception 'Aucune personne dans ce contexte.' using errcode = 'invalid_authorization_specification';
  end if;
  if p_courante is null then
    raise exception 'La session à garder est obligatoire.' using errcode = 'invalid_parameter_value';
  end if;
  with fermees as (
    update public.login_session s
       set revoked_at = pg_catalog.now()
     where s.person_id = v_person
       and s.id <> p_courante
       and s.revoked_at is null
       and s.expires_at > pg_catalog.now()
       and s.absolute_expires_at > pg_catalog.now()
    returning s.id
  ), evenements as (
    select private.ecrit_evenement('session_fermee', v_person, f.id) from fermees f
  )
  select pg_catalog.count(*) into v_nombre from evenements;
  return v_nombre;
end;
$$;
comment on function public.ferme_les_autres_appareils(uuid) is
  'Ferme toutes les autres sessions actives de la personne du contexte ; rend leur nombre. Exécutable par authenticated seul.';
revoke all on function public.ferme_les_autres_appareils(uuid)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.ferme_les_autres_appareils(uuid) to authenticated;
