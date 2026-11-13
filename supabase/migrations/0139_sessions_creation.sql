-- ═══════════════════════════════════════════════════════════════════════════
-- 0139 · LES SESSIONS CÔTÉ BASE : CRÉER, FAIRE TOURNER, FERMER, PURGER (spec § 4 ; B2, B3, B18, B19, B22)
--
-- 0133 ne fait que LIRE une session (`session_personne`). Ici l'API la crée à la connexion, la fait tourner
-- (le jeton change, la session reste) et la ferme, et une purge nocturne vide la table.
--
--  - Colonnes ajoutées, avec défaut : `browser` et `os` (familles courtes, bornées par CHECK : le RÉSUMÉ de l'agent
--    utilisateur, jamais le texte brut, ni adresse, ni localisation) et `reauth_at` (dernière preuve du mot de passe).
--  - `public.cree_session` : au plus 10 sessions actives par personne (la 11e ferme la plus ancienne par dernière
--    activité). Elle révoque aussi la session PRÉSENTÉE, s'il y en a une valide (B22) et écrit alors l'événement
--    `session_fermee` : un cookie périmé ne survit pas à une nouvelle connexion ; un cookie invalide est ignoré.
--  - `public.session_courante` : comme `session_personne` (la règle est UNE seule fonction privée, B2 : bannie,
--    supprimée, échue, révoquée, 90 jours, activité écrite au plus toutes les 5 minutes), mais rend aussi
--    l'identifiant de session et `reauth_at`. `session_personne` est redéfinie pour appeler cette règle : un
--    seul code, deux portes.
--  - `public.fait_tourner_session` : l'ancienne empreinte meurt aussitôt ; une session fermée, échue ou inconnue
--    ne tourne pas.
--  - `public.ferme_session` (par empreinte, idempotente) et `public.marque_reauth` (par session ET personne).
--  - purge (B18) : sessions échues ou révoquées depuis plus de 30 jours, par lots, `pg_cron` chaque nuit.
--
-- DROITS (B3, B19) : `popote_api` (contexte connexion) et `service_role` (contexte service) exécutent les fonctions
-- publiques ; jamais `authenticated` ni `popote_internal`. Pas de paramètre d'horloge dans les fonctions publiques :
-- les variantes à `p_now` vivent dans `private`.
--
-- COMPATIBLE avec l'appli en ligne : `login_session` n'est lue par aucun code actuel ; colonnes ajoutées avec défaut ;
-- `session_personne` garde sa signature et son résultat.
--
-- Retour arrière (sans perte : les sessions se rouvrent par une reconnexion). Dans CET ordre : `session_personne`
-- reprend d'abord son corps de 0133 (elle appelle `private.session_valide`, que la base ne suit pas) ;
--   select cron.unschedule('login-session-purge');   -- si pg_cron est là
--   create or replace function public.session_personne(p_hash bytea) ... -- corps de la migration 0133
--   drop function public.marque_reauth(uuid, uuid), public.ferme_session(bytea),
--     public.fait_tourner_session(bytea, bytea), public.session_courante(bytea),
--     public.cree_session(uuid, bytea, text, text, bytea);
--   drop function private.purge_login_session(timestamptz, integer), private.fait_tourner_session(bytea, bytea,
--     timestamptz), private.cree_session(uuid, bytea, text, text, bytea, timestamptz),
--     private.session_valide(bytea, timestamptz);
--   drop index public.login_session_expires_at_idx, public.login_session_revoked_at_idx;
--   alter table public.login_session drop column reauth_at, drop column os, drop column browser;
-- ═══════════════════════════════════════════════════════════════════════════
set local lock_timeout = '5s';
set local statement_timeout = '30s';

-- ── 1. Les colonnes ─────────────────────────────────────────────────────────
alter table public.login_session
  add column browser   text not null default 'autre'
    check (browser in ('chrome', 'firefox', 'safari', 'edge', 'autre')),
  add column os        text not null default 'autre'
    check (os in ('windows', 'macos', 'linux', 'android', 'ios', 'autre')),
  add column reauth_at timestamptz not null default now();
-- La purge parcourt par échéance et par révocation.
create index login_session_expires_at_idx on public.login_session (expires_at);
create index login_session_revoked_at_idx on public.login_session (revoked_at) where revoked_at is not null;

-- ── 2. La règle de lecture : une seule fonction (B2) ────────────────────────
create or replace function private.session_valide(p_hash bytea, p_now timestamptz)
returns table (person_id uuid, session_id uuid, reauth_at timestamptz)
language plpgsql
volatile
security definer
set search_path = ''
as $$
begin
  return query
  with candidate as (
    select s.id
      from public.login_session s
      join auth.users u on u.id = s.person_id
     where s.token_hash = p_hash
       and s.revoked_at is null
       and s.expires_at > p_now
       and s.absolute_expires_at > p_now
       and s.last_seen_at <= p_now - interval '5 minutes'
       and (u.banned_until is null or u.banned_until <= p_now)
       and u.deleted_at is null
       for update of s skip locked
  )
  update public.login_session s
     set last_seen_at = p_now,
         expires_at = least(p_now + interval '30 days', s.absolute_expires_at)
    from candidate
   where s.id = candidate.id
  returning s.person_id, s.id, s.reauth_at;
  if found then
    return;
  end if;

  return query
  select s.person_id, s.id, s.reauth_at
    from public.login_session s
    join auth.users u on u.id = s.person_id
   where s.token_hash = p_hash
     and s.revoked_at is null
     and s.expires_at > p_now
     and s.absolute_expires_at > p_now
     and (u.banned_until is null or u.banned_until <= p_now)
     and u.deleted_at is null;
end;
$$;
comment on function private.session_valide(bytea, timestamptz) is
  'La règle unique de lecture d''une session (B2). Interne : session_personne et session_courante l''appellent.';
revoke all on function private.session_valide(bytea, timestamptz)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

create or replace function public.session_personne(p_hash bytea)
returns uuid
language sql
volatile
security definer
set search_path = ''
as $$
  select v.person_id from private.session_valide(p_hash, pg_catalog.now()) v;
$$;

create or replace function public.session_courante(p_hash bytea)
returns table (person_id uuid, session_id uuid, reauth_at timestamptz)
language sql
volatile
security definer
set search_path = ''
as $$
  select * from private.session_valide(p_hash, pg_catalog.now());
$$;
comment on function public.session_courante(bytea) is
  'La personne, l''identifiant et reauth_at de la session de ce jeton, ou aucune ligne. Même règle que session_personne. '
  'Exécutable par popote_api et service_role seulement.';
revoke all on function public.session_courante(bytea) from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.session_courante(bytea) to popote_api, service_role;

-- ── 3. Créer ────────────────────────────────────────────────────────────────
create or replace function private.cree_session(
  p_person uuid, p_hash bytea, p_browser text, p_os text, p_old_hash bytea, p_now timestamptz
) returns uuid
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_id uuid;
  v_ancienne public.login_session%rowtype;
begin
  -- Sérialise les créations d'une même personne : sans cela deux connexions simultanées compteraient 9 sessions
  -- chacune et en laisseraient 11.
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(p_person::text, 0));

  -- Pas de session pour une personne bannie ou supprimée : elle mourrait à la première lecture, autant refuser ici.
  if exists (select 1 from auth.users u
              where u.id = p_person and (u.deleted_at is not null or u.banned_until > p_now)) then
    raise exception 'Cette personne ne peut pas ouvrir de session.' using errcode = 'invalid_authorization_specification';
  end if;

  -- La session présentée (B22) : révoquée, journalisée ; une empreinte inconnue ou déjà morte est ignorée.
  if p_old_hash is not null then
    update public.login_session
       set revoked_at = p_now
     where token_hash = p_old_hash and revoked_at is null
       and expires_at > p_now and absolute_expires_at > p_now
    returning * into v_ancienne;
    if found then
      perform private.ecrit_evenement('session_fermee', v_ancienne.person_id, v_ancienne.id);
    end if;
  end if;

  -- Au plus 10 sessions actives, la nouvelle comprise : on ferme les plus anciennes par dernière activité.
  update public.login_session
     set revoked_at = p_now
   where id in (
     select id from public.login_session
      where person_id = p_person and revoked_at is null and expires_at > p_now and absolute_expires_at > p_now
      order by last_seen_at desc, created_at desc, id desc
      offset 9);

  insert into public.login_session
    (token_hash, person_id, browser, os, created_at, last_seen_at, expires_at, absolute_expires_at, reauth_at)
  values
    (p_hash, p_person, p_browser, p_os, p_now, p_now, p_now + interval '30 days', p_now + interval '90 days', p_now)
  returning id into v_id;
  return v_id;
end;
$$;
comment on function private.cree_session(uuid, bytea, text, text, bytea, timestamptz) is
  'Variante à horloge de public.cree_session. Interne (tests).';
revoke all on function private.cree_session(uuid, bytea, text, text, bytea, timestamptz)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

create or replace function public.cree_session(
  p_person uuid, p_hash bytea, p_browser text default 'autre', p_os text default 'autre', p_old_hash bytea default null
) returns uuid
language sql
volatile
security definer
set search_path = ''
as $$
  select private.cree_session(p_person, p_hash, p_browser, p_os, p_old_hash, pg_catalog.now());
$$;
comment on function public.cree_session(uuid, bytea, text, text, bytea) is
  'Crée la session d''une personne (au plus 10 actives : la plus ancienne se ferme) et révoque la session présentée, '
  's''il y en a une valide. Exécutable par popote_api et service_role seulement.';
revoke all on function public.cree_session(uuid, bytea, text, text, bytea)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.cree_session(uuid, bytea, text, text, bytea) to popote_api, service_role;

-- ── 4. Faire tourner, fermer, marquer ───────────────────────────────────────
create or replace function private.fait_tourner_session(p_old_hash bytea, p_new_hash bytea, p_now timestamptz)
returns uuid
language sql
volatile
security definer
set search_path = ''
as $$
  update public.login_session s
     set token_hash = p_new_hash
    from auth.users u
   where s.token_hash = p_old_hash
     and u.id = s.person_id
     and s.revoked_at is null and s.expires_at > p_now and s.absolute_expires_at > p_now
     and (u.banned_until is null or u.banned_until <= p_now)
     and u.deleted_at is null
  returning s.id;
$$;
revoke all on function private.fait_tourner_session(bytea, bytea, timestamptz)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

create or replace function public.fait_tourner_session(p_old_hash bytea, p_new_hash bytea)
returns uuid
language sql
volatile
security definer
set search_path = ''
as $$
  select private.fait_tourner_session(p_old_hash, p_new_hash, pg_catalog.now());
$$;
comment on function public.fait_tourner_session(bytea, bytea) is
  'Change l''empreinte d''une session valide (l''ancienne meurt aussitôt) ; rend son identifiant, ou null.';
revoke all on function public.fait_tourner_session(bytea, bytea) from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.fait_tourner_session(bytea, bytea) to popote_api, service_role;

create or replace function public.ferme_session(p_hash bytea)
returns uuid
language sql
volatile
security definer
set search_path = ''
as $$
  update public.login_session set revoked_at = pg_catalog.now()
   where token_hash = p_hash and revoked_at is null
  returning id;
$$;
comment on function public.ferme_session(bytea) is
  'Ferme la session de ce jeton (idempotent) ; rend son identifiant, ou null si elle était inconnue ou déjà fermée.';
revoke all on function public.ferme_session(bytea) from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.ferme_session(bytea) to popote_api, service_role;

create or replace function public.marque_reauth(p_session uuid, p_person uuid)
returns boolean
language sql
volatile
security definer
set search_path = ''
as $$
  with m as (
    update public.login_session set reauth_at = pg_catalog.now()
     where id = p_session and person_id = p_person and revoked_at is null
       and expires_at > pg_catalog.now() and absolute_expires_at > pg_catalog.now()
    returning 1)
  select exists (select 1 from m);
$$;
comment on function public.marque_reauth(uuid, uuid) is
  'Marque la session réauthentifiée à l''instant ; sans effet (faux) si elle n''est pas à cette personne ou est fermée.';
revoke all on function public.marque_reauth(uuid, uuid) from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.marque_reauth(uuid, uuid) to popote_api, service_role;

-- ── 5. La purge (B18) ───────────────────────────────────────────────────────
create or replace function private.purge_login_session(p_now timestamptz default now(), p_lot integer default 5000)
returns integer
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_total integer := 0;
  v_lot integer;
begin
  if p_lot is null or p_lot < 1 then
    raise exception 'La taille du lot doit être positive.' using errcode = 'invalid_parameter_value';
  end if;
  loop
    delete from public.login_session
     where id in (
       select id from public.login_session
        where revoked_at < p_now - interval '30 days' or expires_at < p_now - interval '30 days'
        order by id
        limit p_lot
          for update skip locked);
    get diagnostics v_lot = row_count;
    v_total := v_total + v_lot;
    exit when v_lot < p_lot;
  end loop;
  raise notice 'purge des sessions de connexion : % ligne(s) effacee(s)', v_total;
  return v_total;
end;
$$;
comment on function private.purge_login_session(timestamptz, integer) is
  'Efface les sessions échues ou révoquées depuis plus de 30 jours, par lots ; rend leur nombre. Lancée chaque nuit par pg_cron.';
revoke all on function private.purge_login_session(timestamptz, integer)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

do $$
begin
  if exists (select 1 from pg_extension where extname = 'pg_cron') then
    begin
      execute $q$select cron.schedule('login-session-purge', '53 3 * * *', 'select private.purge_login_session()')$q$;
    exception when others then
      raise warning 'LA PURGE DES SESSIONS DE CONNEXION N''EST PAS PLANIFIÉE : % (job « login-session-purge »).', sqlerrm;
    end;
  else
    raise warning 'LA PURGE DES SESSIONS DE CONNEXION N''EST PAS PLANIFIÉE : pg_cron est absent. Active-le (Database > '
      'Extensions), puis : select cron.schedule(''login-session-purge'', ''53 3 * * *'', ''select private.purge_login_session()'').';
  end if;
end $$;
