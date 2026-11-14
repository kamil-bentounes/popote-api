-- ═══════════════════════════════════════════════════════════════════════════
-- 0153 · LES CLÉS D'ACCÈS : LES TABLES ET L'ENREGISTREMENT (0.4bis S8b ; spec § 4 ; D3, W3C § 7.1, § 13.4.3, § 14.6.1)
--
-- Une personne enregistre une clé d'accès (WebAuthn) : un défi à usage unique, la réponse du navigateur vérifiée en Python
-- (S8a, `infra/webauthn.py`), puis la clé écrite. La connexion par clé est S9, la gestion S10.
--
--  - `public.webauthn_user` : l'identifiant d'utilisateur WebAuthn (« user handle »), 64 octets tirés au hasard par l'API,
--    UN par personne, SANS donnée personnelle (W3C § 14.6.1) : ni e-mail, ni identifiant de compte.
--  - `public.webauthn_credential` : la clé (identifiant UNIQUE pour tout le monde : l'attestation `none` ne prouve pas la
--    possession de la clé privée, la parade est l'unicité), sa clé publique COSE, son compteur, ses indicateurs BE / BS / UV,
--    l'AAGUID (gardé, jamais traduit), un nom de 1 à 40 caractères.
--  - `public.webauthn_challenge` : le défi (32 octets), son but, la personne ET la session qui l'ont demandé, 10 minutes.
--    Le défi est gardé tel quel (pas un secret : il sort dans les options). Les trois tables : RLS activée ET forcée, aucun droit.
--  - Fonctions de la PERSONNE (`authenticated`, `auth.uid()`, sans horloge ; variantes à `p_now` dans `private`, B19) :
--      `mon_identifiant_webauthn` : crée l'identifiant d'utilisateur (`insert … on conflict do nothing` puis `select`) SOUS le
--        verrou de personne, avant que l'API bâtisse les options : deux onglets pour la première clé repartent avec le même ;
--      `mes_identifiants_de_cle` : les clés à exclure (`excludeCredentials`) ;
--      `cree_un_defi` : le défi ; refuse une session périmée, et la 11e clé (`trop_de_cles`) ;
--      `consomme_un_defi` : `delete … returning`, lié à la personne, à la session et au but, valable 10 minutes ; rend le défi ;
--      `enregistre_une_cle` : sous le verrou de personne, RELIT la session `p_session` (non fermée, non échue) et sa preuve
--        (moins de 300 s, horloge de la base), refuse la 11e clé, l'identifiant déjà pris, et écrit `cle_ajoutee`. Sans cette
--        relecture, une session volée qui lance l'enregistrement, puis une fermeture de toutes les sessions, laisserait la clé de
--        l'attaquant (leçon 1 de T15b, appliquée à la persistance). Fermer toutes les sessions ne RETIRE pas les clés (S10).
--    ORDRE DES VERROUS : foyer, invitation, PERSONNE (`verrouille_la_personne`), puis lignes ; chaque fonction qui touche une
--    clé ou un défi prend la personne en premier (réentrant). Un REFUS est un résultat rendu (`etat`), jamais une exception.
--  - `private.purge_webauthn_challenge` : échéance + 1 jour, chaque nuit par pg_cron.
--  - `security_event.kind` accepte `cle_ajoutee`.
--
-- DROITS : `authenticated` seul exécute les cinq fonctions publiques ; `private` n'est ouvert à aucun rôle.
--
-- COMPATIBLE avec l'appli en ligne : trois tables et des fonctions neuves, un CHECK élargi (aucune valeur retirée).
-- Aucun appelant avant les routes `/api/v1/me/passkey-challenges` et `/api/v1/me/passkeys`.
--
-- À FAIRE PAR S14 (suppression du compte) : effacer `webauthn_challenge`, `webauthn_credential`, `webauthn_user` de la personne
-- sous les trois verrous ; d'ici là elles tombent avec `auth.users` (clés étrangères en cascade).
--
-- RETOUR ARRIÈRE (perd les clés enregistrées : la personne se reconnecte par code et les recrée). Le SQL entre les deux repères
-- s'exécute tel quel, une fois les « -- » retirés (rejoué sur la base locale) :
-- >>> retour arrière
--   select cron.unschedule('webauthn-challenge-purge');   -- si pg_cron est là
--   drop function public.enregistre_une_cle(uuid, bytea, bytea, bigint, text[], boolean, boolean, boolean, uuid, text, text);
--   drop function private.enregistre_une_cle(uuid, uuid, bytea, bytea, bigint, text[], boolean, boolean, boolean, uuid, text,
--     text, timestamptz);
--   drop function public.consomme_un_defi(uuid, text, bytea);
--   drop function private.consomme_un_defi(uuid, uuid, text, bytea, timestamptz);
--   drop function public.cree_un_defi(uuid, text, bytea);
--   drop function private.cree_un_defi(uuid, uuid, text, bytea, timestamptz);
--   drop function public.mes_identifiants_de_cle();
--   drop function public.mon_identifiant_webauthn(bytea);
--   drop function private.purge_webauthn_challenge(timestamptz, integer);
--   drop table public.webauthn_challenge;
--   drop table public.webauthn_credential;
--   drop table public.webauthn_user;
--   delete from public.security_event where kind = 'cle_ajoutee';
--   alter table public.security_event drop constraint security_event_kind_check, add constraint
--     security_event_kind_check check (kind in (
--       'connexion_reussie', 'connexion_ratee', 'connexion_bloquee', 'deconnexion',
--       'reauthentification_reussie', 'reauthentification_ratee', 'session_fermee',
--       'mot_de_passe_change', 'reinitialisation_demandee', 'reinitialisation_utilisee',
--       'invitation_creee', 'invitation_acceptee', 'invitation_revoquee',
--       'compte_supprime', 'compte_repris', 'verification_fuites_indisponible',
--       'code_demande', 'connexion_par_code'));
-- <<< retour arrière
-- ═══════════════════════════════════════════════════════════════════════════
set local lock_timeout = '5s';
set local statement_timeout = '30s';

-- ── 1. Le journal : `cle_ajoutee` ───────────────────────────────────────────
alter table public.security_event
  drop constraint security_event_kind_check,
  add constraint security_event_kind_check check (kind in (
    'connexion_reussie', 'connexion_ratee', 'connexion_bloquee', 'deconnexion',
    'reauthentification_reussie', 'reauthentification_ratee', 'session_fermee',
    'mot_de_passe_change', 'reinitialisation_demandee', 'reinitialisation_utilisee',
    'invitation_creee', 'invitation_acceptee', 'invitation_revoquee',
    'compte_supprime', 'compte_repris', 'verification_fuites_indisponible',
    'code_demande', 'connexion_par_code', 'cle_ajoutee')) not valid;
alter table public.security_event validate constraint security_event_kind_check;

-- ── 2. Les tables ───────────────────────────────────────────────────────────
create table public.webauthn_user (
  person_id  uuid primary key references auth.users (id) on delete cascade,
  -- Opaque, 64 octets aléatoires (W3C § 14.6.1) : jamais un e-mail ni un identifiant dérivé du compte.
  user_handle bytea not null unique check (octet_length(user_handle) = 64),
  created_at timestamptz not null default now()
);
comment on table public.webauthn_user is
  'Identifiant d''utilisateur WebAuthn (64 octets aléatoires, sans donnée personnelle), un par personne.';

create table public.webauthn_credential (
  id            uuid primary key default gen_random_uuid(),
  person_id     uuid not null references public.webauthn_user (person_id) on delete cascade,
  -- Unique pour TOUTES les personnes : une attestation `none` ne prouve pas la possession de la clé privée (W3C § 7.1).
  credential_id bytea not null unique check (octet_length(credential_id) between 16 and 1023),
  -- La clé publique au format COSE, telle que l'authentificateur l'a écrite (cohérence vérifiée par l'API).
  public_key    bytea not null check (octet_length(public_key) between 1 and 1024),
  -- Un entier non signé de 32 bits (W3C § 6.1) ; zéro tant qu'une clé synchronisée ne compte pas.
  sign_count    bigint not null default 0 check (sign_count between 0 and 4294967295),
  transports    text[] not null default '{}'
                check (transports <@ array['usb', 'nfc', 'ble', 'smart-card', 'internal', 'cable', 'hybrid']),
  backup_eligible boolean not null,
  backup_state  boolean not null check (backup_eligible or not backup_state),
  uv_initialized boolean not null,
  -- Gardé, jamais traduit en nom d'appareil (aucune liste externe).
  aaguid        uuid not null,
  name          text not null check (char_length(name) between 1 and 40),
  created_at    timestamptz not null default now(),
  last_used_at  timestamptz
);
comment on table public.webauthn_credential is
  'Une clé d''accès : identifiant unique pour tout le monde, clé publique COSE, compteur, indicateurs BE / BS / UV. 10 au plus par personne.';
create index webauthn_credential_person_id_idx on public.webauthn_credential (person_id, created_at, id);

create table public.webauthn_challenge (
  -- Le défi lui-même (32 octets) : il sort dans les options, ce n'est pas un secret ; à usage unique, 10 minutes.
  challenge  bytea primary key check (octet_length(challenge) = 32),
  purpose    text not null check (purpose in ('registration')),
  person_id  uuid not null references public.webauthn_user (person_id) on delete cascade,
  session_id uuid not null references public.login_session (id) on delete cascade,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default now() + interval '10 minutes',
  check (expires_at > created_at and expires_at <= created_at + interval '10 minutes')
);
comment on table public.webauthn_challenge is
  'Défi WebAuthn à usage unique, lié à la personne et à la session qui l''ont demandé : 10 minutes au plus.';
create index webauthn_challenge_person_id_idx on public.webauthn_challenge (person_id);
create index webauthn_challenge_session_id_idx on public.webauthn_challenge (session_id);
create index webauthn_challenge_expires_at_idx on public.webauthn_challenge (expires_at);

alter table public.webauthn_user enable row level security;
alter table public.webauthn_user force row level security;
revoke all on table public.webauthn_user from public, anon, authenticated, service_role, popote_api, popote_internal;
alter table public.webauthn_credential enable row level security;
alter table public.webauthn_credential force row level security;
revoke all on table public.webauthn_credential
  from public, anon, authenticated, service_role, popote_api, popote_internal;
alter table public.webauthn_challenge enable row level security;
alter table public.webauthn_challenge force row level security;
revoke all on table public.webauthn_challenge
  from public, anon, authenticated, service_role, popote_api, popote_internal;

-- ── 3. L'identifiant d'utilisateur : créé sous le verrou, avant les options ──
/* Le candidat vient de l'API (CSPRNG). Deux premières demandes en parallèle : la seconde attend le verrou, trouve la ligne
   de la première et rend LE MÊME identifiant (sinon la clé serait ensuite refusée sur `userHandle`). Pas d'horloge. */
create or replace function public.mon_identifiant_webauthn(p_candidat bytea)
returns bytea
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_personne uuid := auth.uid();
  v_identifiant bytea;
begin
  if v_personne is null then
    raise exception 'Aucune personne dans ce contexte.' using errcode = 'invalid_authorization_specification';
  end if;
  if p_candidat is null or pg_catalog.octet_length(p_candidat) <> 64 then
    raise exception 'Paramètres invalides.' using errcode = 'invalid_parameter_value';
  end if;
  perform private.verrouille_la_personne(v_personne);
  insert into public.webauthn_user (person_id, user_handle) values (v_personne, p_candidat)
  on conflict (person_id) do nothing;
  select u.user_handle into v_identifiant from public.webauthn_user u where u.person_id = v_personne;
  return v_identifiant;
end;
$$;
comment on function public.mon_identifiant_webauthn(bytea) is
  'Crée (ou relit) l''identifiant d''utilisateur WebAuthn de la personne du contexte, sous son verrou. authenticated seul.';
revoke all on function public.mon_identifiant_webauthn(bytea)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.mon_identifiant_webauthn(bytea) to authenticated;

/* Les clés déjà enregistrées, pour `excludeCredentials` : le navigateur n'en crée pas une seconde sur le même appareil.
   Dix lignes au plus (la borne est celle de `enregistre_une_cle`). */
create or replace function public.mes_identifiants_de_cle()
returns table (identifiant bytea, transports text[])
language plpgsql
stable
security definer
set search_path = ''
as $$
begin
  if auth.uid() is null then
    raise exception 'Aucune personne dans ce contexte.' using errcode = 'invalid_authorization_specification';
  end if;
  return query
    select k.credential_id, k.transports
      from public.webauthn_credential k
     where k.person_id = auth.uid()
     order by k.created_at, k.id
     limit 10;
end;
$$;
comment on function public.mes_identifiants_de_cle() is
  'Les identifiants des clés de la personne du contexte (dix au plus), pour `excludeCredentials`. authenticated seul.';
revoke all on function public.mes_identifiants_de_cle()
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.mes_identifiants_de_cle() to authenticated;

-- ── 4. Le défi : créé, puis consommé ────────────────────────────────────────
/* Rend `creee`, `session_perimee` (la session n'est plus ouverte, ou la personne ne peut plus entrer) ou `trop_de_cles`
   (dix clés déjà : pas de cérémonie pour rien). Le verrou de personne d'abord : le défi se lie à une session qu'une fermeture
   de toutes les sessions peut révoquer. */
create or replace function private.cree_un_defi(
  p_person uuid, p_session uuid, p_purpose text, p_defi bytea, p_now timestamptz
) returns text
language plpgsql
volatile
security definer
set search_path = ''
as $$
begin
  if p_person is null or p_session is null or p_defi is null or p_now is null
     or p_purpose is distinct from 'registration' or pg_catalog.octet_length(p_defi) <> 32 then
    raise exception 'Paramètres invalides.' using errcode = 'invalid_parameter_value';
  end if;
  perform private.verrouille_la_personne(p_person);
  if not private.personne_peut_entrer(p_person) or not exists (
       select 1 from public.login_session s
        where s.id = p_session and s.person_id = p_person and s.revoked_at is null
          and s.expires_at > p_now and s.absolute_expires_at > p_now) then
    return 'session_perimee';
  end if;
  if (select pg_catalog.count(*) from public.webauthn_credential k where k.person_id = p_person) >= 10 then
    return 'trop_de_cles';
  end if;
  insert into public.webauthn_challenge (challenge, purpose, person_id, session_id, created_at, expires_at)
  values (p_defi, p_purpose, p_person, p_session, p_now, p_now + interval '10 minutes');
  return 'creee';
end;
$$;
comment on function private.cree_un_defi(uuid, uuid, text, bytea, timestamptz) is
  'Variante à horloge de public.cree_un_defi. Interne (tests).';
revoke all on function private.cree_un_defi(uuid, uuid, text, bytea, timestamptz)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

create or replace function public.cree_un_defi(p_session uuid, p_purpose text, p_defi bytea)
returns text
language plpgsql
volatile
security definer
set search_path = ''
as $$
begin
  if auth.uid() is null then
    raise exception 'Aucune personne dans ce contexte.' using errcode = 'invalid_authorization_specification';
  end if;
  return private.cree_un_defi(auth.uid(), p_session, p_purpose, p_defi, pg_catalog.now());
end;
$$;
comment on function public.cree_un_defi(uuid, text, bytea) is
  'Garde le défi d''une cérémonie pour la personne et la session du contexte (10 minutes) ; rend creee, session_perimee ou trop_de_cles. authenticated seul.';
revoke all on function public.cree_un_defi(uuid, text, bytea)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.cree_un_defi(uuid, text, bytea) to authenticated;

/* `delete … returning` : un défi ne sert qu'une fois, même pour deux requêtes parallèles (la seconde attend la ligne puis ne
   la trouve plus). Le défi d'une autre personne, d'une autre session, d'un autre but ou échu n'est NI rendu NI brûlé. Le
   verrou de personne d'abord : la ligne ne se prend qu'après (ordre des verrous). Rend le défi, ou null. */
create or replace function private.consomme_un_defi(
  p_person uuid, p_session uuid, p_purpose text, p_defi bytea, p_now timestamptz
) returns bytea
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_defi bytea;
begin
  if p_person is null or p_session is null or p_purpose is null or p_defi is null or p_now is null then
    raise exception 'Paramètres invalides.' using errcode = 'invalid_parameter_value';
  end if;
  perform private.verrouille_la_personne(p_person);
  delete from public.webauthn_challenge c
   where c.challenge = p_defi and c.purpose = p_purpose and c.person_id = p_person and c.session_id = p_session
     and c.expires_at > p_now
  returning c.challenge into v_defi;
  return v_defi;
end;
$$;
comment on function private.consomme_un_defi(uuid, uuid, text, bytea, timestamptz) is
  'Variante à horloge de public.consomme_un_defi. Interne (tests).';
revoke all on function private.consomme_un_defi(uuid, uuid, text, bytea, timestamptz)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

create or replace function public.consomme_un_defi(p_session uuid, p_purpose text, p_defi bytea)
returns bytea
language plpgsql
volatile
security definer
set search_path = ''
as $$
begin
  if auth.uid() is null then
    raise exception 'Aucune personne dans ce contexte.' using errcode = 'invalid_authorization_specification';
  end if;
  return private.consomme_un_defi(auth.uid(), p_session, p_purpose, p_defi, pg_catalog.now());
end;
$$;
comment on function public.consomme_un_defi(uuid, text, bytea) is
  'Consomme le défi de la personne et de la session du contexte (à usage unique, 10 minutes) et le rend ; null sinon. authenticated seul.';
revoke all on function public.consomme_un_defi(uuid, text, bytea)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.consomme_un_defi(uuid, text, bytea) to authenticated;

-- ── 5. L'enregistrement de la clé ───────────────────────────────────────────
/* Dans l'ordre, sous le verrou de personne : la session présentée (non fermée, non échue, personne qui peut entrer), sa preuve
   (300 s, passe à exactement 300 : comme `exige_reauth`), la borne de dix clés, puis l'insertion (`on conflict do nothing` :
   l'identifiant de clé est unique pour tout le monde, y compris contre une autre personne en parallèle), puis l'événement.
   Rend `creee` (avec la ligne), `session_perimee`, `preuve_perimee`, `trop_de_cles` ou `cle_deja_enregistree`. */
create or replace function private.enregistre_une_cle(
  p_person uuid,
  p_session uuid,
  p_credential bytea,
  p_public_key bytea,
  p_sign_count bigint,
  p_transports text[],
  p_backup_eligible boolean,
  p_backup_state boolean,
  p_uv boolean,
  p_aaguid uuid,
  p_name text,
  p_request_id text,
  p_now timestamptz
) returns table (etat text, id uuid, created_at timestamptz)
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_reauth_at timestamptz;
  v_id uuid;
  v_cree timestamptz;
begin
  if p_person is null or p_session is null or p_credential is null or p_public_key is null or p_sign_count is null
     or p_backup_eligible is null or p_backup_state is null or p_uv is null or p_aaguid is null or p_name is null
     or p_now is null or (p_request_id is not null and p_request_id !~ '^[0-9a-f]{32}$') then
    raise exception 'Paramètres invalides.' using errcode = 'invalid_parameter_value';
  end if;

  perform private.verrouille_la_personne(p_person);

  -- La session se RELIT sous le verrou : une fermeture de toutes les sessions qui précède l'a révoquée.
  select s.reauth_at into v_reauth_at
    from public.login_session s
   where s.id = p_session and s.person_id = p_person and s.revoked_at is null
     and s.expires_at > p_now and s.absolute_expires_at > p_now;
  if not found or not private.personne_peut_entrer(p_person) then
    return query select 'session_perimee'::text, null::uuid, null::timestamptz;
    return;
  end if;
  if v_reauth_at < p_now - interval '300 seconds' then
    return query select 'preuve_perimee'::text, null::uuid, null::timestamptz;
    return;
  end if;
  if (select pg_catalog.count(*) from public.webauthn_credential k where k.person_id = p_person) >= 10 then
    return query select 'trop_de_cles'::text, null::uuid, null::timestamptz;
    return;
  end if;

  insert into public.webauthn_credential as k
    (person_id, credential_id, public_key, sign_count, transports, backup_eligible, backup_state, uv_initialized,
     aaguid, name, created_at)
  values
    (p_person, p_credential, p_public_key, p_sign_count, coalesce(p_transports, '{}'), p_backup_eligible,
     p_backup_state, p_uv, p_aaguid, p_name, p_now)
  on conflict (credential_id) do nothing
  returning k.id, k.created_at into v_id, v_cree;
  if v_id is null then
    return query select 'cle_deja_enregistree'::text, null::uuid, null::timestamptz;
    return;
  end if;

  perform private.ecrit_evenement('cle_ajoutee', p_person, p_session, null, null, null, p_request_id);
  return query select 'creee'::text, v_id, v_cree;
end;
$$;
comment on function private.enregistre_une_cle(
  uuid, uuid, bytea, bytea, bigint, text[], boolean, boolean, boolean, uuid, text, text, timestamptz) is
  'Variante à horloge de public.enregistre_une_cle. Interne (tests).';
revoke all on function private.enregistre_une_cle(
  uuid, uuid, bytea, bytea, bigint, text[], boolean, boolean, boolean, uuid, text, text, timestamptz)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

create or replace function public.enregistre_une_cle(
  p_session uuid,
  p_credential bytea,
  p_public_key bytea,
  p_sign_count bigint,
  p_transports text[],
  p_backup_eligible boolean,
  p_backup_state boolean,
  p_uv boolean,
  p_aaguid uuid,
  p_name text,
  p_request_id text default null
) returns table (etat text, id uuid, created_at timestamptz)
language plpgsql
volatile
security definer
set search_path = ''
as $$
begin
  if auth.uid() is null then
    raise exception 'Aucune personne dans ce contexte.' using errcode = 'invalid_authorization_specification';
  end if;
  return query select * from private.enregistre_une_cle(
    auth.uid(), p_session, p_credential, p_public_key, p_sign_count, p_transports, p_backup_eligible,
    p_backup_state, p_uv, p_aaguid, p_name, p_request_id, pg_catalog.now());
end;
$$;
comment on function public.enregistre_une_cle(
  uuid, bytea, bytea, bigint, text[], boolean, boolean, boolean, uuid, text, text) is
  'Enregistre la clé d''accès de la personne du contexte, sous son verrou, la session et sa preuve (300 s) relues en base ; rend creee, session_perimee, preuve_perimee, trop_de_cles ou cle_deja_enregistree. authenticated seul.';
revoke all on function public.enregistre_une_cle(
  uuid, bytea, bytea, bigint, text[], boolean, boolean, boolean, uuid, text, text)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.enregistre_une_cle(
  uuid, bytea, bytea, bigint, text[], boolean, boolean, boolean, uuid, text, text) to authenticated;

-- ── 6. La purge : échéance + 1 jour ─────────────────────────────────────────
create or replace function private.purge_webauthn_challenge(
  p_now timestamptz default now(), p_lot integer default 5000
) returns integer
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
    delete from public.webauthn_challenge
     where webauthn_challenge.challenge in (
       select c.challenge from public.webauthn_challenge c
        where c.expires_at < p_now - interval '1 day'
        order by c.challenge
        limit p_lot
          for update skip locked);
    get diagnostics v_lot = row_count;
    v_total := v_total + v_lot;
    exit when v_lot < p_lot;
  end loop;
  raise notice 'purge des défis WebAuthn : % ligne(s) effacee(s)', v_total;
  return v_total;
end;
$$;
comment on function private.purge_webauthn_challenge(timestamptz, integer) is
  'Efface les défis WebAuthn dont l''échéance date de plus d''un jour, par lots ; rend leur nombre. Lancée chaque nuit par pg_cron.';
revoke all on function private.purge_webauthn_challenge(timestamptz, integer)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

/* Planification gardée comme 0147 : sans `pg_cron`, la migration passe et un avertissement le dit. 03 h 51 UTC. */
do $$
begin
  if exists (select 1 from pg_extension where extname = 'pg_cron') then
    begin
      execute $q$select cron.schedule('webauthn-challenge-purge', '51 3 * * *', 'select private.purge_webauthn_challenge()')$q$;
    exception when others then
      raise warning 'LA PURGE DES DÉFIS WEBAUTHN N''EST PAS PLANIFIÉE : % (job « webauthn-challenge-purge »).', sqlerrm;
    end;
  else
    raise warning 'LA PURGE DES DÉFIS WEBAUTHN N''EST PAS PLANIFIÉE : pg_cron est absent. Active-le (Database > '
      'Extensions), puis : select cron.schedule(''webauthn-challenge-purge'', ''51 3 * * *'', ''select private.purge_webauthn_challenge()'').';
  end if;
end $$;
