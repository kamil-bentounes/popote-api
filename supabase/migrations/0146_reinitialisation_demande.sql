-- ═══════════════════════════════════════════════════════════════════════════
-- 0146 · LA DEMANDE DE RÉINITIALISATION DU MOT DE PASSE (T15a ; spec § 4, § 3.6 ; B3, B5, B9, B10, B24)
--
-- Objets neufs, aucune table ni fonction existante modifiée.
--
--  - `public.password_reset` : l'empreinte SHA-256 du jeton (jamais le jeton), 30 minutes AU PLUS (CHECK), usage
--    unique (`used_at`), révocable. Au plus UN lien actif par personne (index unique partiel) : une nouvelle demande
--    révoque la précédente. RLS activée ET forcée, aucune politique, aucun droit.
--  - `public.cree_reinitialisation(p_email, p_hash)` : l'adresse DÉJÀ normalisée (`email_normalise`, B24), comparée
--    en minuscules, paramétrée. Pour un compte ni banni ni supprimé, AVEC profil et foyer (B10 : un compte sans
--    profil ne reçoit pas de lien, il repasse par une invitation), révoque les liens actifs de la personne, écrit
--    le nouveau et rend l'identifiant de la personne ; sinon rend null, sans rien écrire. Sérialisée par personne
--    (verrou consultatif de la transaction). `popote_api` et `service_role` (B3).
--  - `private.purge_password_reset` : efface par lots les liens dont la fin de vie date de plus de 7 jours ;
--    planifiée chaque nuit par pg_cron si l'extension est là.
--
-- L'USAGE du lien (`consomme_reinitialisation`, `apres_reinitialisation`) est la tâche T15b.
--
-- COMPATIBLE avec l'appli en ligne : table et fonctions neuves, aucun appelant dans l'appli actuelle ; Supabase
-- Auth, `delete_my_account` et la table `invitation` ne sont pas touchés. La table suit `auth.users` : supprimer
-- un compte (dont `efface_mes_donnees` puis Auth) emporte ses liens (`on delete cascade`).
--
-- RETOUR ARRIÈRE (sans perte : un lien se redemande) :
--   select cron.unschedule('password-reset-purge');   -- si pg_cron est là
--   drop function private.purge_password_reset(timestamptz, integer);
--   drop function public.cree_reinitialisation(text, bytea);
--   drop table public.password_reset;
-- ═══════════════════════════════════════════════════════════════════════════
set local lock_timeout = '5s';
set local statement_timeout = '30s';

-- ── 1. La table ─────────────────────────────────────────────────────────────
create table public.password_reset (
  id         uuid primary key default gen_random_uuid(),
  person_id  uuid not null references auth.users (id) on delete cascade,
  -- SHA-256 du jeton : 32 octets exactement. Le jeton lui-même n'est jamais écrit.
  token_hash bytea not null unique check (octet_length(token_hash) = 32),
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default now() + interval '30 minutes',
  used_at    timestamptz,
  revoked_at timestamptz,
  check (expires_at > created_at and expires_at <= created_at + interval '30 minutes')
);
comment on table public.password_reset is
  'Lien de réinitialisation du mot de passe : l''empreinte SHA-256 du jeton, jamais le jeton. 30 minutes, usage unique, révocable.';

-- La clé étrangère est indexée ; l'index partiel garantit un seul lien actif par personne et sert la révocation.
create unique index password_reset_actif_idx on public.password_reset (person_id)
  where used_at is null and revoked_at is null;
-- La purge parcourt par date.
create index password_reset_expires_idx on public.password_reset (expires_at);

alter table public.password_reset enable row level security;
alter table public.password_reset force row level security;
revoke all on table public.password_reset from public, anon, authenticated, service_role, popote_api, popote_internal;

-- ── 2. La demande ───────────────────────────────────────────────────────────
create or replace function public.cree_reinitialisation(p_email text, p_hash bytea)
returns uuid
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_person uuid;
begin
  if p_email is null or p_hash is null or pg_catalog.octet_length(p_hash) <> 32 then
    raise exception 'Paramètres invalides.' using errcode = 'invalid_parameter_value';
  end if;
  select u.id into v_person
    from auth.users u
   where pg_catalog.lower(u.email) = p_email
     and u.deleted_at is null
     and (u.banned_until is null or u.banned_until <= pg_catalog.now())
     and exists (select 1 from public.user_profile p
                  where p.id = u.id and p.household_id is not null)
     for key share of u;  -- une suppression du compte entre ici et l'insertion attendrait, au lieu de casser l'insertion
  if v_person is null then
    return null;
  end if;
  -- Deux demandes simultanées de la même personne se suivent : l'index unique ne verrait jamais une course.
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtext('password_reset'),
                                           pg_catalog.hashtext(v_person::text));
  update public.password_reset r
     set revoked_at = pg_catalog.now()
   where r.person_id = v_person and r.used_at is null and r.revoked_at is null;
  insert into public.password_reset (person_id, token_hash) values (v_person, p_hash);
  return v_person;
end;
$$;
comment on function public.cree_reinitialisation(text, bytea) is
  'Crée un lien de réinitialisation pour l''adresse normalisée (révoque les précédents) ; rend la personne, ou null (inconnu, banni, supprimé, sans profil ou sans foyer).';
revoke all on function public.cree_reinitialisation(text, bytea)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.cree_reinitialisation(text, bytea) to popote_api, service_role;

-- ── 3. La purge : fin de vie + 7 jours ──────────────────────────────────────
create or replace function private.purge_password_reset(p_now timestamptz default now(), p_lot integer default 5000)
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
    delete from public.password_reset
     where password_reset.id in (
       select r.id from public.password_reset r
        where least(r.expires_at, coalesce(r.revoked_at, 'infinity'), coalesce(r.used_at, 'infinity'))
              < p_now - interval '7 days'
        order by r.id
        limit p_lot
          for update skip locked);
    get diagnostics v_lot = row_count;
    v_total := v_total + v_lot;
    exit when v_lot < p_lot;
  end loop;
  raise notice 'purge des liens de réinitialisation : % ligne(s) effacee(s)', v_total;
  return v_total;
end;
$$;
comment on function private.purge_password_reset(timestamptz, integer) is
  'Efface les liens de réinitialisation dont la fin de vie date de plus de 7 jours, par lots ; rend leur nombre. Lancée chaque nuit par pg_cron.';
revoke all on function private.purge_password_reset(timestamptz, integer)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

/* Planification gardée comme 0142 : sans `pg_cron`, la migration passe et un avertissement le dit. 03 h 37 UTC. */
do $$
begin
  if exists (select 1 from pg_extension where extname = 'pg_cron') then
    begin
      execute $q$select cron.schedule('password-reset-purge', '37 3 * * *', 'select private.purge_password_reset()')$q$;
    exception when others then
      raise warning 'LA PURGE DES LIENS DE RÉINITIALISATION N''EST PAS PLANIFIÉE : % (job « password-reset-purge »).', sqlerrm;
    end;
  else
    raise warning 'LA PURGE DES LIENS DE RÉINITIALISATION N''EST PAS PLANIFIÉE : pg_cron est absent. Active-le (Database > '
      'Extensions), puis : select cron.schedule(''password-reset-purge'', ''37 3 * * *'', ''select private.purge_password_reset()'').';
  end if;
end $$;
