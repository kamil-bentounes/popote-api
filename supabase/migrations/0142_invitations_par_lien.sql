-- ═══════════════════════════════════════════════════════════════════════════
-- 0142 · LES INVITATIONS PAR LIEN, CÔTÉ HÔTE : LA CRÉATION (spec § 4, § 3.5, § 3.6 ; étape 0.4, T12a)
--
-- Un lien d'invitation n'a pas d'e-mail : un jeton de 256 bits tiré par l'API, dont SEUL le SHA-256 (32 octets)
-- vit ici ; sept jours au plus, à usage unique, révocable. Cette migration pose la table et la création ; la
-- liste et la révocation (T12b) et l'acceptation (T13) viennent plus tard.
--
-- Compatible avec l'appli en ligne : une table NEUVE et des fonctions neuves, aucun appelant avant la route
-- `POST /api/v1/me/invitations`. La table `invitation` actuelle et les fonctions Edge `invite` / `accept-invite`
-- ne sont pas touchées : les deux mécanismes coexistent jusqu'à la contraction.
--
-- Règles qui tiennent le reste :
--  1. DIX PAR 24 H GLISSANTES, RÉVOQUÉES COMPRISES. Le quota compte toutes les lignes du foyer créées depuis 24 h :
--     révoquer ne rend pas le créneau (sinon créer-révoquer en boucle contourne la limite).
--  2. UN VERROU PAR FOYER. Le comptage et l'insertion se font sous un verrou consultatif de transaction du foyer,
--     attendu : quinze créations parallèles en laissent passer exactement dix.
--  3. PAS D'HORLOGE POUR UNE PERSONNE (B19). `public.cree_invitation(p_hash)` n'a pas de `p_now` : elle appelle
--     `private.cree_invitation(personne, empreinte, p_now)`, que seuls l'administrateur et les tests exécutent.
--  4. LA PERSONNE QUI SUPPRIME SON COMPTE (B8). `created_by` et `accepted_by` passent à `null` (`on delete set
--     null`), le lien reste : il vit son délai et sa purge. Les deux clés étrangères sont indexées.
--
-- Retour arrière (sans perte pour l'appli, qui n'a pas d'appelant) :
--   select cron.unschedule('invite-link-purge');   -- si pg_cron est là
--   drop function public.cree_invitation(bytea);
--   drop function private.cree_invitation(uuid, bytea, timestamptz);
--   drop function private.purge_invite_link(timestamptz, integer);
--   drop table public.invite_link;
-- ═══════════════════════════════════════════════════════════════════════════
set local lock_timeout = '5s';
set local statement_timeout = '30s';

-- ── 1. La table ──────────────────────────────────────────────────────────────
create table public.invite_link (
  id           uuid primary key default gen_random_uuid(),
  household_id uuid not null references public.household (id) on delete cascade,
  created_by   uuid references public.user_profile (id) on delete set null,
  -- SHA-256 du jeton : 32 octets exactement. Le jeton lui-même n'est jamais écrit.
  token_hash   bytea not null unique check (octet_length(token_hash) = 32),
  created_at   timestamptz not null default now(),
  expires_at   timestamptz not null default now() + interval '7 days',
  revoked_at   timestamptz,
  accepted_at  timestamptz,
  accepted_by  uuid references public.user_profile (id) on delete set null,
  check (expires_at > created_at and expires_at <= created_at + interval '7 days')
);
comment on table public.invite_link is
  'Lien d''invitation d''un foyer : l''empreinte SHA-256 du jeton, jamais le jeton. 7 jours, usage unique, révocable.';

-- Clés étrangères indexées (la suppression d'un foyer ou d'un compte les parcourt) ; le premier sert aussi le
-- quota (foyer + date) ; le dernier, la liste des liens en attente.
create index invite_link_household_created_idx on public.invite_link (household_id, created_at desc);
create index invite_link_created_by_idx on public.invite_link (created_by) where created_by is not null;
create index invite_link_accepted_by_idx on public.invite_link (accepted_by) where accepted_by is not null;
create index invite_link_pending_idx on public.invite_link (household_id, created_at desc, id desc)
  where revoked_at is null and accepted_at is null;

-- RLS activée ET forcée, aucune politique, aucun droit : on n'y accède que par les fonctions ci-dessous.
alter table public.invite_link enable row level security;
alter table public.invite_link force row level security;
revoke all on table public.invite_link from public, anon, authenticated, service_role, popote_api, popote_internal;

-- ── 2. La création, variante à horloge (B19) ────────────────────────────────
create or replace function private.cree_invitation(p_person uuid, p_hash bytea, p_now timestamptz)
returns table (etat text, id uuid, created_at timestamptz, expires_at timestamptz, attente integer)
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  c_quota constant integer := 10;
  v_foyer uuid;
  v_nombre integer;
  v_libere timestamptz;
  v_id uuid;
begin
  if p_person is null or p_now is null or p_hash is null or pg_catalog.octet_length(p_hash) <> 32 then
    raise exception 'Personne, empreinte de 32 octets et instant sont obligatoires.'
      using errcode = 'invalid_parameter_value';
  end if;
  select p.household_id into v_foyer from public.user_profile p where p.id = p_person;
  if v_foyer is null then
    return query select 'aucun_foyer'::text, null::uuid, null::timestamptz, null::timestamptz, null::integer;
    return;
  end if;

  -- Le verrou du foyer, ATTENDU : le comptage et l'insertion qui suivent ne se croisent pas avec un autre envoi.
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtext('invitation'), pg_catalog.hashtext(v_foyer::text));

  select pg_catalog.count(*) into v_nombre
    from public.invite_link l
   where l.household_id = v_foyer and l.created_at > p_now - interval '24 hours';
  if v_nombre >= c_quota then
    -- Le créneau se libère quand la dixième plus récente sort de la fenêtre.
    select l.created_at + interval '24 hours' into v_libere
      from public.invite_link l
     where l.household_id = v_foyer and l.created_at > p_now - interval '24 hours'
     order by l.created_at desc
    offset c_quota - 1 limit 1;
    return query select 'quota'::text, null::uuid, null::timestamptz, null::timestamptz,
      greatest(1, pg_catalog.ceil(extract(epoch from v_libere - p_now))::integer);
    return;
  end if;

  insert into public.invite_link as l (household_id, created_by, token_hash, created_at, expires_at)
  values (v_foyer, p_person, p_hash, p_now, p_now + interval '7 days')
  returning l.id into v_id;
  perform private.ecrit_evenement('invitation_creee', p_person, null, v_id);
  return query select 'creee'::text, v_id, p_now, p_now + interval '7 days', null::integer;
end;
$$;
comment on function private.cree_invitation(uuid, bytea, timestamptz) is
  'Variante à horloge de public.cree_invitation, pour les tests et l''administrateur : aucun rôle applicatif ne l''exécute.';
revoke all on function private.cree_invitation(uuid, bytea, timestamptz)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

-- ── 3. La création, version de la personne ──────────────────────────────────
/* Pas d'horloge : `now()`. Rend `creee` (avec la ligne), `quota` (avec l'attente en secondes) ou `aucun_foyer`. */
create or replace function public.cree_invitation(p_hash bytea)
returns table (etat text, id uuid, created_at timestamptz, expires_at timestamptz, attente integer)
language plpgsql
volatile
security definer
set search_path = ''
as $$
begin
  if auth.uid() is null then
    raise exception 'Aucune personne dans ce contexte.' using errcode = 'invalid_authorization_specification';
  end if;
  return query select * from private.cree_invitation(auth.uid(), p_hash, pg_catalog.now());
end;
$$;
comment on function public.cree_invitation(bytea) is
  'Crée un lien d''invitation pour le foyer de la personne du contexte (10 par 24 h glissantes, révoquées comprises). Exécutable par authenticated seul.';
revoke all on function public.cree_invitation(bytea)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.cree_invitation(bytea) to authenticated;

-- ── 4. La purge : fin de vie + 30 jours ─────────────────────────────────────
/* La fin de vie d'un lien : la première de l'échéance, de la révocation et de l'acceptation. Par lots ; variante
   à horloge dans `private`, jamais exécutable par une personne. Rend le nombre de lignes, jamais une valeur. */
create or replace function private.purge_invite_link(p_now timestamptz default now(), p_lot integer default 5000)
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
    delete from public.invite_link
     where invite_link.id in (
       select l.id from public.invite_link l
        where least(l.expires_at, coalesce(l.revoked_at, 'infinity'), coalesce(l.accepted_at, 'infinity'))
              < p_now - interval '30 days'
        order by l.id
        limit p_lot
          for update skip locked);
    get diagnostics v_lot = row_count;
    v_total := v_total + v_lot;
    exit when v_lot < p_lot;
  end loop;
  raise notice 'purge des liens d''invitation : % ligne(s) effacee(s)', v_total;
  return v_total;
end;
$$;
comment on function private.purge_invite_link(timestamptz, integer) is
  'Efface les liens d''invitation dont la fin de vie date de plus de 30 jours, par lots ; rend leur nombre. Lancée chaque nuit par pg_cron.';
revoke all on function private.purge_invite_link(timestamptz, integer)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

/* Planification gardée comme 0126 : sans `pg_cron`, la migration passe et un avertissement le dit. 03 h 29 UTC. */
do $$
begin
  if exists (select 1 from pg_extension where extname = 'pg_cron') then
    begin
      execute $q$select cron.schedule('invite-link-purge', '29 3 * * *', 'select private.purge_invite_link()')$q$;
    exception when others then
      raise warning 'LA PURGE DES LIENS D''INVITATION N''EST PAS PLANIFIÉE : % (job « invite-link-purge »).', sqlerrm;
    end;
  else
    raise warning 'LA PURGE DES LIENS D''INVITATION N''EST PAS PLANIFIÉE : pg_cron est absent. Active-le (Database > '
      'Extensions), puis : select cron.schedule(''invite-link-purge'', ''29 3 * * *'', ''select private.purge_invite_link()'').';
  end if;
end $$;
