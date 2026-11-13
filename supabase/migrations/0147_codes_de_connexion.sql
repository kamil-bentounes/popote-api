-- ═══════════════════════════════════════════════════════════════════════════
-- 0147 · LES CODES DE CONNEXION : LA DEMANDE (0.4bis S5 ; spec § 3.6, § 4, § 7.1 ; D3, B6)
--
-- Une personne demande un code à six chiffres reçu par mail. Cette migration pose la base de la DEMANDE ; la
-- vérification et la session sont S7.
--
--  - `public.login_code` : le HMAC du code (jamais le code), 10 minutes AU PLUS (CHECK), 5 essais, usage unique
--    (`used_at`), révocable. Au plus UN code actif par clé de compte (index unique partiel) : une nouvelle demande
--    révoque le précédent. `id` est l'identifiant de demande (`code_request_id`) que l'API tire : ce n'est pas un
--    secret, le code est protégé par le poivre. `person_id` est NUL pour une ligne FACTICE, écrite pour une adresse
--    inconnue : même insertion, même durée, aucun mail, et rien qui distingue la réponse. RLS activée ET forcée,
--    aucun droit.
--  - `public.prend_les_creneaux_de_demande` : un seul ordre, IP puis (adresse, IP) puis adresse ; un refus n'use
--    pas les suivants (B6). Sans escalade : le créneau de trop attend la fin de la fenêtre et ne compte pas. Il n'y
--    a PAS de créneau global à la demande : dix adresses bidon depuis une IP l'auraient épuisé pour tout le monde.
--  - `public.prend_un_envoi` : le coupe-circuit GLOBAL de mails (60 par heure), pris par la tâche d'envoi après la
--    réponse, pour un compte réel seulement : il protège le quota du fournisseur sans qu'un anonyme puisse
--    l'épuiser.
--  - `public.demande_un_code` : le MÊME travail pour une adresse connue et inconnue. Verrou sur la clé du compte
--    (deux demandes simultanées se suivent) puis, pour un compte réel, sur la personne (la même clé que
--    `cree_session`, 0139 : la règle d'ordre de S6 nomme ce verrou). Un code actif de moins de 60 secondes n'est
--    pas remplacé : même identifiant rendu, pas de nouveau code, donc pas de mail (un double clic ne tue pas le
--    code déjà parti). `code_demande` ne s'écrit que pour un compte réel : une IP ne remplit pas le journal.
--  - `private.purge_login_code` : échéance + 1 jour, chaque nuit par pg_cron. `private.purge_journal_securite`
--    est redéfinie : `code_demande` part à 90 jours, comme les échecs de connexion (liés à une clé, pas à une
--    personne) ; le reste du journal garde 1 an.
--  - `login_throttle.scope` accepte `code_ip`, `code_paire`, `code_compte`, `mail_global` ;
--    `security_event.kind` accepte `code_demande`.
--
-- DROITS : `popote_api` seul exécute les trois fonctions publiques (contexte connexion). Pas d'horloge dans une
-- fonction publique : les variantes à `p_now` vivent dans `private`, fermées à tous les rôles (B19).
--
-- COMPATIBLE avec l'appli en ligne : table et fonctions neuves ; deux CHECK de tables de 0.4 ÉLARGIS (aucune valeur
-- retirée : ce que le code déjà déployé écrit passe encore) ; `purge_journal_securite` garde sa signature.
--
-- RETOUR ARRIÈRE (sans perte pour l'appli : un code se redemande). Dans CET ordre, et les CHECK d'avant ne passent
-- que si les lignes aux valeurs neuves sont parties :
--   select cron.unschedule('login-code-purge');   -- si pg_cron est là
--   drop function public.demande_un_code(text, bytea, uuid, bytea, bytea, text);
--   drop function public.prend_un_envoi(integer, integer);
--   drop function private.prend_un_envoi(integer, integer, timestamptz);
--   drop function public.prend_les_creneaux_de_demande(bytea, bytea, bytea, integer, integer, integer, integer, integer);
--   drop function private.prend_les_creneaux_de_demande(bytea, bytea, bytea, integer, integer, integer, integer,
--     integer, timestamptz);
--   drop function private.purge_login_code(timestamptz, integer);
--   drop table public.login_code;
--   delete from public.login_throttle where scope in ('code_ip', 'code_paire', 'code_compte', 'mail_global');
--   delete from public.security_event where kind = 'code_demande';
--   alter table public.login_throttle drop constraint login_throttle_scope_check, add constraint
--     login_throttle_scope_check check (scope in ('account', 'ip', 'reset', 'invitation_ip', 'invitation_link'));
--   alter table public.security_event drop constraint security_event_kind_check, add constraint
--     security_event_kind_check check (kind in (<la liste de 0136, sans 'code_demande'>));
--   create or replace function private.purge_journal_securite(...)  -- corps de la migration 0136
-- ═══════════════════════════════════════════════════════════════════════════
set local lock_timeout = '5s';
set local statement_timeout = '30s';

-- ── 1. Deux CHECK élargis (rien n'est retiré) ───────────────────────────────
alter table public.login_throttle
  drop constraint login_throttle_scope_check,
  add constraint login_throttle_scope_check check (scope in (
    'account', 'ip', 'reset', 'invitation_ip', 'invitation_link',
    'code_ip', 'code_paire', 'code_compte', 'mail_global')) not valid;
alter table public.login_throttle validate constraint login_throttle_scope_check;

alter table public.security_event
  drop constraint security_event_kind_check,
  add constraint security_event_kind_check check (kind in (
    'connexion_reussie', 'connexion_ratee', 'connexion_bloquee', 'deconnexion',
    'reauthentification_reussie', 'reauthentification_ratee', 'session_fermee',
    'mot_de_passe_change', 'reinitialisation_demandee', 'reinitialisation_utilisee',
    'invitation_creee', 'invitation_acceptee', 'invitation_revoquee',
    'compte_supprime', 'compte_repris', 'verification_fuites_indisponible',
    'code_demande')) not valid;
alter table public.security_event validate constraint security_event_kind_check;

-- ── 2. La table ─────────────────────────────────────────────────────────────
create table public.login_code (
  -- L'identifiant de demande : tiré par l'API, PAS un secret (sans le code il ne sert à rien).
  id          uuid primary key default gen_random_uuid(),
  -- HMAC de 32 octets de l'adresse (le même que celui du journal) : jamais l'adresse.
  account_key bytea not null check (octet_length(account_key) = 32),
  -- Nul pour une ligne factice (adresse inconnue, bannie, supprimée ou sans profil).
  person_id   uuid references auth.users (id) on delete cascade,
  -- HMAC-SHA256 de (identifiant de demande, clé du compte, code) : jamais le code.
  code_hash   bytea not null check (octet_length(code_hash) = 32),
  attempts    smallint not null default 0 check (attempts between 0 and 5),
  created_at  timestamptz not null default now(),
  expires_at  timestamptz not null default now() + interval '10 minutes',
  used_at     timestamptz,
  revoked_at  timestamptz,
  check (expires_at > created_at and expires_at <= created_at + interval '10 minutes')
);
comment on table public.login_code is
  'Code de connexion par mail : le HMAC du code, jamais le code. 10 minutes, 5 essais, usage unique ; une ligne sans personne est factice.';

-- Un seul code actif par clé de compte ; l'index sert aussi la révocation.
create unique index login_code_actif_idx on public.login_code (account_key)
  where used_at is null and revoked_at is null;
-- La clé étrangère est indexée (la suppression d'un compte la parcourt) ; les lignes factices n'en ont pas.
create index login_code_person_id_idx on public.login_code (person_id) where person_id is not null;
-- La purge parcourt par échéance.
create index login_code_expires_at_idx on public.login_code (expires_at);

alter table public.login_code enable row level security;
alter table public.login_code force row level security;
revoke all on table public.login_code from public, anon, authenticated, service_role, popote_api, popote_internal;

-- ── 3. Les créneaux de la demande : IP, puis (adresse, IP), puis adresse ────
create or replace function private.prend_les_creneaux_de_demande(
  p_ip bytea,
  p_paire bytea,
  p_compte bytea,
  p_limit_ip integer,
  p_limit_paire integer,
  p_limit_compte integer,
  p_window_s integer,
  p_window_compte_s integer,
  p_now timestamptz
) returns integer
language plpgsql
volatile
security invoker
set search_path = ''
as $$
declare
  v_attente integer;
begin
  -- Toujours dans cet ordre : deux demandes croisées ne s'attendent jamais en cercle (pas de `40P01`), et un
  -- refus rend l'attente SANS toucher aux suivants (B6) : une IP bloquée n'use ni la paire ni le compte.
  select t.attente_s into v_attente
    from private.prend_un_creneau('code_ip', p_ip, p_limit_ip, p_window_s, p_window_s, false, p_now) t;
  if v_attente > 0 then
    return v_attente;
  end if;
  select t.attente_s into v_attente
    from private.prend_un_creneau('code_paire', p_paire, p_limit_paire, p_window_s, p_window_s, false, p_now) t;
  if v_attente > 0 then
    return v_attente;
  end if;
  select t.attente_s into v_attente
    from private.prend_un_creneau('code_compte', p_compte, p_limit_compte, p_window_compte_s, p_window_compte_s,
                                  false, p_now) t;
  return v_attente;
end;
$$;
comment on function private.prend_les_creneaux_de_demande(bytea, bytea, bytea, integer, integer, integer, integer, integer, timestamptz) is
  'Variante à horloge de public.prend_les_creneaux_de_demande. Interne (tests).';
revoke all on function private.prend_les_creneaux_de_demande(bytea, bytea, bytea, integer, integer, integer, integer, integer, timestamptz)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

create or replace function public.prend_les_creneaux_de_demande(
  p_ip bytea,
  p_paire bytea,
  p_compte bytea,
  p_limit_ip integer default 10,
  p_limit_paire integer default 3,
  p_limit_compte integer default 6,
  p_window_s integer default 900,
  p_window_compte_s integer default 3600
) returns integer
language sql
volatile
security definer
set search_path = ''
as $$
  select private.prend_les_creneaux_de_demande(
    p_ip, p_paire, p_compte, p_limit_ip, p_limit_paire, p_limit_compte, p_window_s, p_window_compte_s,
    pg_catalog.now());
$$;
comment on function public.prend_les_creneaux_de_demande(bytea, bytea, bytea, integer, integer, integer, integer, integer) is
  'Prend un créneau de demande de code sur l''IP, puis sur (adresse, IP), puis sur l''adresse : 0 (passe) ou l''attente en secondes. Un refus n''use pas les suivants. popote_api seul.';
revoke all on function public.prend_les_creneaux_de_demande(bytea, bytea, bytea, integer, integer, integer, integer, integer)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.prend_les_creneaux_de_demande(bytea, bytea, bytea, integer, integer, integer, integer, integer)
  to popote_api;

-- ── 4. Le coupe-circuit global : 60 mails par heure, compté à l'envoi réel ──
create or replace function private.prend_un_envoi(p_limit integer, p_window_s integer, p_now timestamptz)
returns integer
language sql
volatile
security invoker
set search_path = ''
as $$
  select t.attente_s
    from private.prend_un_creneau('mail_global', pg_catalog.decode(pg_catalog.repeat('00', 32), 'hex'),
                                  p_limit, p_window_s, p_window_s, false, p_now) t;
$$;
revoke all on function private.prend_un_envoi(integer, integer, timestamptz)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

create or replace function public.prend_un_envoi(p_limit integer default 60, p_window_s integer default 3600)
returns integer
language sql
volatile
security definer
set search_path = ''
as $$
  select private.prend_un_envoi(p_limit, p_window_s, pg_catalog.now());
$$;
comment on function public.prend_un_envoi(integer, integer) is
  'Coupe-circuit global des mails : 0 (le mail peut partir) ou l''attente en secondes. Pris par la tâche d''envoi, pour un compte réel seulement. popote_api seul.';
revoke all on function public.prend_un_envoi(integer, integer)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.prend_un_envoi(integer, integer) to popote_api;

-- ── 5. La demande : le même travail pour une adresse connue et inconnue ─────
/* `p_email` est l'adresse DÉJÀ normalisée (`email_normalise`), comparée en minuscules, paramétrée. Rend la personne
   (nulle : adresse inconnue, bannie, supprimée ou sans profil ; le foyer n'est pas exigé : une personne sortie d'un
   foyer doit pouvoir se connecter pour en rejoindre un), l'identifiant de demande EFFECTIF et si un code neuf vient
   d'être écrit (faux : un code de moins de 60 s est déjà là, personne n'envoie rien). */
create or replace function public.demande_un_code(
  p_email text,
  p_account_key bytea,
  p_code_request_id uuid,
  p_code_hash bytea,
  p_ip_hash bytea,
  p_request_id text default null
) returns table (personne uuid, demande uuid, nouveau boolean)
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_personne uuid;
  v_actif public.login_code%rowtype;
begin
  if p_email is null or p_account_key is null or p_code_request_id is null or p_code_hash is null
     or p_ip_hash is null
     or pg_catalog.octet_length(p_account_key) <> 32 or pg_catalog.octet_length(p_code_hash) <> 32
     or pg_catalog.octet_length(p_ip_hash) <> 32 then
    raise exception 'Paramètres invalides.' using errcode = 'invalid_parameter_value';
  end if;

  -- Deux demandes de la même adresse se suivent, connue ou non : l'index unique ne verrait jamais une course.
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtext('login_code'),
                                           pg_catalog.hashtext(pg_catalog.encode(p_account_key, 'hex')));

  select u.id into v_personne
    from auth.users u
   where pg_catalog.lower(u.email) = p_email
     and u.deleted_at is null
     and (u.banned_until is null or u.banned_until <= pg_catalog.now())
     and exists (select 1 from public.user_profile p where p.id = u.id)
     for key share of u;  -- une suppression du compte attendrait, au lieu de casser l'insertion

  if v_personne is not null then
    -- La même clé que `cree_session` (0139) : un code ne se révoque pas pendant qu'une session s'ouvre.
    perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(v_personne::text, 0));
  end if;

  select * into v_actif
    from public.login_code c
   where c.account_key = p_account_key and c.used_at is null and c.revoked_at is null
     for update;
  -- Moins de 60 s : le code déjà parti reste le bon (un code mort, aux 5 essais faux, ne se rejoue pas).
  if found and v_actif.created_at > pg_catalog.now() - interval '60 seconds' and v_actif.attempts < 5 then
    return query select v_personne, v_actif.id, false;
    return;
  end if;

  update public.login_code c
     set revoked_at = pg_catalog.now()
   where c.account_key = p_account_key and c.used_at is null and c.revoked_at is null;
  insert into public.login_code (id, account_key, person_id, code_hash)
  values (p_code_request_id, p_account_key, v_personne, p_code_hash);

  -- Seulement pour un compte réel : une adresse inconnue n'écrit qu'une ligne purgée en un jour et un compteur
  -- purgé en 24 h, jamais une ligne de journal gardée 90 jours (sinon une IP remplirait la base).
  if v_personne is not null then
    perform private.ecrit_evenement('code_demande', v_personne, null, null, p_account_key, p_ip_hash, p_request_id);
  end if;
  return query select v_personne, p_code_request_id, true;
end;
$$;
comment on function public.demande_un_code(text, bytea, uuid, bytea, bytea, text) is
  'Écrit un code pour l''adresse normalisée (ligne factice si elle n''a pas de compte) et révoque le précédent, sauf s''il a moins de 60 s ; rend (personne ou null, identifiant de demande, code neuf). popote_api seul.';
revoke all on function public.demande_un_code(text, bytea, uuid, bytea, bytea, text)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.demande_un_code(text, bytea, uuid, bytea, bytea, text) to popote_api;

-- ── 6. La purge : échéance + 1 jour ─────────────────────────────────────────
create or replace function private.purge_login_code(p_now timestamptz default now(), p_lot integer default 5000)
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
    delete from public.login_code
     where login_code.id in (
       select c.id from public.login_code c
        where c.expires_at < p_now - interval '1 day'
        order by c.id
        limit p_lot
          for update skip locked);
    get diagnostics v_lot = row_count;
    v_total := v_total + v_lot;
    exit when v_lot < p_lot;
  end loop;
  raise notice 'purge des codes de connexion : % ligne(s) effacee(s)', v_total;
  return v_total;
end;
$$;
comment on function private.purge_login_code(timestamptz, integer) is
  'Efface les codes de connexion dont l''échéance date de plus d''un jour, par lots ; rend leur nombre. Lancée chaque nuit par pg_cron.';
revoke all on function private.purge_login_code(timestamptz, integer)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

/* Planification gardée comme 0142 : sans `pg_cron`, la migration passe et un avertissement le dit. 03 h 43 UTC. */
do $$
begin
  if exists (select 1 from pg_extension where extname = 'pg_cron') then
    begin
      execute $q$select cron.schedule('login-code-purge', '43 3 * * *', 'select private.purge_login_code()')$q$;
    exception when others then
      raise warning 'LA PURGE DES CODES DE CONNEXION N''EST PAS PLANIFIÉE : % (job « login-code-purge »).', sqlerrm;
    end;
  else
    raise warning 'LA PURGE DES CODES DE CONNEXION N''EST PAS PLANIFIÉE : pg_cron est absent. Active-le (Database > '
      'Extensions), puis : select cron.schedule(''login-code-purge'', ''43 3 * * *'', ''select private.purge_login_code()'').';
  end if;
end $$;

-- ── 7. Le journal : `code_demande` part à 90 jours, comme les échecs de connexion ───────────────
/* Même corps que 0136, une valeur de plus dans la liste courte : ces événements tiennent à une clé de compte, pas
   à une personne (6 lignes par heure et par compte réel au plus). */
create or replace function private.purge_journal_securite(
  p_now timestamptz default now(),
  p_lot integer default 5000
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
    delete from public.security_event
     where id in (
       select id from public.security_event
        where occurred_at < p_now - case
                when kind in ('connexion_ratee', 'connexion_bloquee', 'code_demande') then interval '90 days'
                else interval '365 days' end
        order by id
        limit p_lot
          for update skip locked);
    get diagnostics v_lot = row_count;
    v_total := v_total + v_lot;
    exit when v_lot < p_lot;
  end loop;
  raise notice 'purge du journal de securite : % ligne(s) effacee(s)', v_total;
  return v_total;
end;
$$;
