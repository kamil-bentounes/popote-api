-- ═══════════════════════════════════════════════════════════════════════════
-- 0144 · LIRE ET ACCEPTER UNE INVITATION (T13 ; spec § 4, § 5.1 ; B1, B3, B10, B11, B19, B20, B24)
--
-- Objets neufs, sauf une contrainte : le CHECK de `login_throttle.scope` (0138, fusionnée, non modifiée : on la
-- remplace ici) accepte deux scopes de plus, `invitation_ip` et `invitation_link`. Ils sont distincts du scope
-- `ip` de la connexion : sinon 30 inspections d'une IP useraient aussi ses 20 créneaux de connexion (B11 nomme
-- les limites `ip` et `link` ; les noms de scope sont préfixés pour ne rien partager).
--
--  - `public.prend_un_creneau_invitation(scope, clé, limite, fenêtre)` : un créneau sur l'un des DEUX scopes
--    d'invitation (autre scope : refusé), sans escalade, 0 = passe sinon l'attente en secondes.
--  - `public.etat_invitation(p_hash)` : l'état d'un lien (`valide`, `expiree`, `utilisee`, `revoquee`, `inconnue`)
--    et le prénom de qui invite. Aucun effet. `popote_api` (inspection) et `service_role` (acceptation).
--  - `public.consomme_invitation(p_hash)` : UN SEUL `update` atomique (non accepté, non révoqué, non échu) qui rend
--    le foyer ; c'est le verrou. `service_role` seul.
--  - `public.rend_invitation(p_id)` : rouvre un lien consommé mais NON terminé (`accepted_by` nul) ; B20 : seul le
--    `409` de course d'adresse l'appelle. `service_role` seul.
--  - `public.termine_invitation(p_id, p_person)` : pose `accepted_by` sur un lien consommé (la table n'a aucun droit
--    pour `service_role` : tout passe par une fonction). `service_role` seul.
--  - `public.compte_pour_email(p_email)` : le compte de cette adresse (égalité sur la casse basse, paramétrée,
--    jamais un motif) : `id`, `orphelin` (B10 : sans profil, sans hachage de mot de passe, ni banni ni
--    supprimé). `service_role` seul.
--  - `public.reprise_en_cours` + `reserve_reprise` / `libere_reprise` : la réservation de 60 s qui sérialise deux
--    liens visant la même adresse (B10). `service_role` seul.
--
-- DROITS (B3) : le droit se vérifie sur le rôle COURANT ; le contexte service est `service_role`. `authenticated`
-- et `anon` n'ont aucune de ces fonctions, ni aucun droit sur la table. Aucune n'a de paramètre d'horloge (B19).
--
-- COMPATIBLE avec l'appli en ligne : fonctions et table neuves, aucun appelant dans l'appli actuelle ; la table
-- `invitation` et les fonctions Edge `invite` / `accept-invite` ne sont pas touchées (coexistence).
--
-- Retour arrière (sans perte : tout se reconstitue ; les liens déjà consommés restent consommés) :
--   drop function public.libere_reprise(bytea, uuid);
--   drop function public.reserve_reprise(bytea);
--   drop table public.reprise_en_cours;
--   drop function public.compte_pour_email(text);
--   drop function public.termine_invitation(uuid, uuid);
--   drop function public.rend_invitation(uuid);
--   drop function public.consomme_invitation(bytea);
--   drop function public.etat_invitation(bytea);
--   drop function public.prend_un_creneau_invitation(text, bytea, integer, integer);
--   alter table public.login_throttle drop constraint login_throttle_scope_check;
--   alter table public.login_throttle add constraint login_throttle_scope_check
--     check (scope in ('account', 'ip', 'reset'));   -- après avoir supprimé les lignes des scopes retirés
-- ═══════════════════════════════════════════════════════════════════════════
set local lock_timeout = '5s';
set local statement_timeout = '30s';

-- ── 1. Deux scopes de plus ──────────────────────────────────────────────────
alter table public.login_throttle drop constraint login_throttle_scope_check;
alter table public.login_throttle add constraint login_throttle_scope_check
  check (scope in ('account', 'ip', 'reset', 'invitation_ip', 'invitation_link'));

create or replace function public.prend_un_creneau_invitation(
  p_scope text, p_key bytea, p_limit integer, p_window_s integer
) returns integer
language plpgsql
volatile
security definer
set search_path = ''
as $$
begin
  if p_scope is null or p_scope not in ('invitation_ip', 'invitation_link') then
    raise exception 'Scope de limite inconnu.' using errcode = 'invalid_parameter_value';
  end if;
  return (select t.attente_s
            from private.prend_un_creneau(p_scope, p_key, p_limit, p_window_s, p_window_s, false, pg_catalog.now()) t);
end;
$$;
comment on function public.prend_un_creneau_invitation(text, bytea, integer, integer) is
  'Prend un créneau sur la clé (IP ou empreinte de lien) : 0 (passe) ou l''attente en secondes. Sans escalade.';
revoke all on function public.prend_un_creneau_invitation(text, bytea, integer, integer)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.prend_un_creneau_invitation(text, bytea, integer, integer)
  to popote_api, service_role;

-- ── 2. Lire l'état d'un lien : aucun effet ──────────────────────────────────
create or replace function public.etat_invitation(p_hash bytea)
returns table (etat text, invited_by text, expires_at timestamptz)
language sql
stable
security definer
set search_path = ''
as $$
  select case
           when l.accepted_at is not null then 'utilisee'
           when l.revoked_at is not null then 'revoquee'
           when l.expires_at <= pg_catalog.now() then 'expiree'
           else 'valide'
         end,
         nullif(pg_catalog.btrim(p.display_name), ''),
         l.expires_at
    from public.invite_link l
    left join public.user_profile p on p.id = l.created_by
   where l.token_hash = p_hash
  union all
  select 'inconnue', null, null
   where not exists (select 1 from public.invite_link l2 where l2.token_hash = p_hash);
$$;
comment on function public.etat_invitation(bytea) is
  'État d''un lien par l''empreinte de son jeton, et le prénom de qui invite. Aucun effet.';
revoke all on function public.etat_invitation(bytea)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.etat_invitation(bytea) to popote_api, service_role;

-- ── 3. Consommer : un seul update atomique ──────────────────────────────────
create or replace function public.consomme_invitation(p_hash bytea)
returns table (id uuid, household_id uuid)
language sql
volatile
security definer
set search_path = ''
as $$
  -- La condition tient AU MOMENT de l'écriture : deux appels simultanés, un seul rend une ligne.
  update public.invite_link l
     set accepted_at = pg_catalog.now()
   where l.token_hash = p_hash
     and l.accepted_at is null
     and l.revoked_at is null
     and l.expires_at > pg_catalog.now()
  returning l.id, l.household_id;
$$;
comment on function public.consomme_invitation(bytea) is
  'Consomme un lien valide (un seul update atomique) et rend son foyer ; aucune ligne si le lien n''est pas valide.';
revoke all on function public.consomme_invitation(bytea)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.consomme_invitation(bytea) to service_role;

create or replace function public.rend_invitation(p_id uuid) returns boolean
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_lignes integer;
begin
  -- Seulement un lien consommé et NON terminé : jamais un lien dont quelqu'un est devenu membre.
  update public.invite_link set accepted_at = null
   where id = p_id and accepted_at is not null and accepted_by is null;
  get diagnostics v_lignes = row_count;
  return v_lignes = 1;
end;
$$;
comment on function public.rend_invitation(uuid) is
  'Rouvre un lien consommé dont personne n''est devenu membre (course d''adresse, B20). Rend vrai si rouvert.';
revoke all on function public.rend_invitation(uuid)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.rend_invitation(uuid) to service_role;

create or replace function public.termine_invitation(p_id uuid, p_person uuid) returns boolean
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_lignes integer;
begin
  update public.invite_link set accepted_by = p_person
   where id = p_id and accepted_at is not null and accepted_by is null;
  get diagnostics v_lignes = row_count;
  return v_lignes = 1;
end;
$$;
comment on function public.termine_invitation(uuid, uuid) is
  'Pose accepted_by sur un lien consommé : la personne est devenue membre. Rend vrai si posé.';
revoke all on function public.termine_invitation(uuid, uuid)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.termine_invitation(uuid, uuid) to service_role;

-- ── 4. Le compte d'une adresse ──────────────────────────────────────────────
create or replace function public.compte_pour_email(p_email text)
returns table (id uuid, orphelin boolean, a_un_profil boolean)
language sql
stable
security definer
set search_path = ''
as $$
  -- Un orphelin n'a RIEN à prendre : ni profil, ni hachage, ni identité d'un autre fournisseur (Google...), ni
  -- compte SSO ; il n'est ni banni ni supprimé. Plusieurs comptes pour une adresse : le non-orphelin d'abord, donc
  -- l'adresse reste « connue » et le résultat est déterministe.
  select t.id, t.orphelin, t.a_un_profil
    from (
      select u.id,
             exists (select 1 from public.user_profile p where p.id = u.id) as a_un_profil,
             (    u.deleted_at is null
              and (u.banned_until is null or u.banned_until <= pg_catalog.now())
              and coalesce(u.encrypted_password, '') = ''
              and not coalesce(u.is_sso_user, false)
              and not exists (select 1 from auth.identities i where i.user_id = u.id and i.provider <> 'email')
              and not exists (select 1 from public.user_profile p where p.id = u.id)) as orphelin
        from auth.users u
       where pg_catalog.lower(u.email) = p_email
    ) t
   order by t.orphelin, t.id
   limit 1;
$$;
comment on function public.compte_pour_email(text) is
  'Le compte de l''adresse (déjà normalisée) : son identifiant, et s''il est un orphelin repris sans rien prendre.';
revoke all on function public.compte_pour_email(text)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.compte_pour_email(text) to service_role;

-- ── 5. La réservation d'une reprise ─────────────────────────────────────────
create table public.reprise_en_cours (
  key        bytea primary key check (octet_length(key) = 32),
  owner      uuid not null,
  expires_at timestamptz not null
);
comment on table public.reprise_en_cours is
  'Réservation de 60 s d''une reprise de compte, par clé HMAC d''adresse : sérialise deux liens visant la même adresse.';
alter table public.reprise_en_cours enable row level security;
alter table public.reprise_en_cours force row level security;
revoke all on table public.reprise_en_cours from public, anon, authenticated, service_role, popote_api, popote_internal;

create or replace function public.reserve_reprise(p_key bytea) returns uuid
language sql
volatile
security definer
set search_path = ''
as $$
  -- Rend le propriétaire (un uuid aléatoire) si la clé est libre ou si sa réservation est échue ; `null` si un
  -- autre lien la tient. Seul le propriétaire libère : une réservation échue puis reprise n'est pas défaite par
  -- l'ancien porteur.
  insert into public.reprise_en_cours as r (key, owner, expires_at)
  values (p_key, gen_random_uuid(), pg_catalog.now() + interval '60 seconds')
  on conflict (key) do update set owner = excluded.owner, expires_at = excluded.expires_at
    where r.expires_at <= pg_catalog.now()
  returning owner;
$$;
create or replace function public.libere_reprise(p_key bytea, p_owner uuid) returns void
language sql
volatile
security definer
set search_path = ''
as $$
  delete from public.reprise_en_cours where key = p_key and owner = p_owner;
$$;
revoke all on function public.reserve_reprise(bytea)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
revoke all on function public.libere_reprise(bytea, uuid)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.reserve_reprise(bytea) to service_role;
grant execute on function public.libere_reprise(bytea, uuid) to service_role;
