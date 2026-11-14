-- ═══════════════════════════════════════════════════════════════════════════
-- 0151 · LE BLOCAGE VISE LE COUPLE (COMPTE, IP), PAS LE COMPTE SEUL (0.4bis S7c ; B5, B6, B21)
--
-- Avant : cinq refus bloquaient le compte entier (toutes IP, 24 h) : docs/securite.md § 4.3.
--
--  - `public.prend_les_creneaux_de_connexion` : l'IP (inchangée), puis le COMPTE ENTIER lu (bloqué : son attente, sans
--    rien compter), puis le COUPLE (5 par 15 min, blocage qui double jusqu'à 24 h), puis le compte entier compté
--    (20 refus en 24 h, puis 60 min fixes ; un couple déjà bloqué n'y compte plus : une IP seule en pèse au plus 5).
--    Un créneau refusé n'use jamais les suivants.
--  - `public.libere_le_couple` après un succès : couple à zéro, un refus de moins sur le compte entier, jamais l'IP.
--  - `login_throttle.scope` accepte `couple` et `compte_entier`.
--
-- EXPANSION : `prend_les_creneaux` et `libere_compte` (0138) restent pour l'appli encore en ligne ; retirées en S15.
--
-- Retour arrière (sans perte : les compteurs se reconstituent) :
--   drop function public.libere_le_couple(bytea, bytea);
--   drop function public.prend_les_creneaux_de_connexion(bytea, bytea, bytea, integer, integer, integer, integer, integer, integer, integer);
--   drop function private.prend_les_creneaux_de_connexion(bytea, bytea, bytea, integer, integer, integer, integer, integer, integer, integer, timestamptz);
--   drop function private.prend_un_creneau_fixe(text, bytea, integer, integer, integer, timestamptz);
--   delete from public.login_throttle where scope in ('couple', 'compte_entier');
--   alter table public.login_throttle drop constraint login_throttle_scope_check, add constraint login_throttle_scope_check
--     check (scope in ('account', 'ip', 'reset', 'invitation_ip', 'invitation_link',
--                      'code_ip', 'code_paire', 'code_compte', 'mail_global'));
-- ═══════════════════════════════════════════════════════════════════════════
set local lock_timeout = '5s';
set local statement_timeout = '30s';

alter table public.login_throttle
  drop constraint login_throttle_scope_check,
  add constraint login_throttle_scope_check check (scope in (
    'account', 'ip', 'reset', 'invitation_ip', 'invitation_link',
    'code_ip', 'code_paire', 'code_compte', 'mail_global',
    'couple', 'compte_entier')) not valid;
alter table public.login_throttle validate constraint login_throttle_scope_check;

/* `p_limit` essais par fenêtre ; le suivant pose un blocage de `p_block_s` et repart de zéro. Bloqué : l'attente, sans compter. */
create or replace function private.prend_un_creneau_fixe(
  p_scope text, p_key bytea, p_limit integer, p_window_s integer, p_block_s integer, p_now timestamptz
) returns table (attente_s integer, nouveau_blocage boolean)
language plpgsql
volatile
security invoker
set search_path = ''
as $$
declare
  v_ligne public.login_throttle%rowtype;
  v_attempts integer;
begin
  if p_key is null or pg_catalog.length(p_key) <> 32 then
    raise exception 'La clé de limite doit faire 32 octets.' using errcode = 'invalid_parameter_value';
  end if;
  if p_limit is null or p_window_s is null or p_block_s is null or p_now is null
     or p_limit not between 1 and 10000
     or p_window_s not between 1 and 86400
     or p_block_s not between 1 and 86400 then
    raise exception 'Limite, fenêtre ou blocage invalide.' using errcode = 'invalid_parameter_value';
  end if;

  insert into public.login_throttle as t (scope, key, window_start) values (p_scope, p_key, p_now)
  on conflict (scope, key) do update set window_start = t.window_start
  returning t.* into v_ligne;

  if v_ligne.blocked_until is not null and v_ligne.blocked_until > p_now then
    return query select pg_catalog.ceil(extract(epoch from v_ligne.blocked_until - p_now))::integer, false;
    return;
  end if;

  v_attempts := v_ligne.attempts;
  if v_ligne.window_start <= p_now - pg_catalog.make_interval(secs => p_window_s) then
    v_attempts := 0;
    v_ligne.window_start := p_now;
  end if;

  if v_attempts < p_limit then
    update public.login_throttle set attempts = v_attempts + 1, window_start = v_ligne.window_start
     where scope = p_scope and key = p_key;
    return query select 0, false;
    return;
  end if;

  update public.login_throttle
     set attempts = 0, window_start = p_now, last_block_at = p_now,
         blocked_until = p_now + pg_catalog.make_interval(secs => p_block_s)
   where scope = p_scope and key = p_key;
  return query select p_block_s, true;
end;
$$;
revoke all on function private.prend_un_creneau_fixe(text, bytea, integer, integer, integer, timestamptz)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

/* Ordre des verrous : IP, puis couple, puis compte entier, toujours (aucun cercle d'attente). `nouveau_blocage` : `ip`, `couple`
   ou `account` (le compte entier), une seule fois par blocage (B21). */
create or replace function private.prend_les_creneaux_de_connexion(
  p_couple bytea, p_account bytea, p_ip bytea,
  p_limit_couple integer, p_limit_account integer, p_limit_ip integer,
  p_window_s integer, p_max_block_s integer, p_account_window_s integer, p_account_block_s integer,
  p_now timestamptz
) returns table (attente_s integer, nouveau_blocage text)
language plpgsql
volatile
security invoker
set search_path = ''
as $$
declare
  v_attente integer;
  v_nouveau boolean;
begin
  if p_account is null or pg_catalog.length(p_account) <> 32 or p_couple is null or pg_catalog.length(p_couple) <> 32 then
    raise exception 'La clé de limite doit faire 32 octets.' using errcode = 'invalid_parameter_value';
  end if;
  select t.attente_s, t.nouveau_blocage into v_attente, v_nouveau
    from private.prend_un_creneau('ip', p_ip, p_limit_ip, p_window_s, p_max_block_s, true, p_now) t;
  if v_attente > 0 then
    return query select v_attente, case when v_nouveau then 'ip' end;
    return;
  end if;
  -- Le compte entier est déjà bloqué : on le dit, sans user le créneau du couple (le même refus pour toute IP).
  select pg_catalog.ceil(extract(epoch from t.blocked_until - p_now))::integer into v_attente
    from public.login_throttle t
   where t.scope = 'compte_entier' and t.key = p_account and t.blocked_until > p_now;
  if v_attente > 0 then
    return query select v_attente, null::text;
    return;
  end if;
  select t.attente_s, t.nouveau_blocage into v_attente, v_nouveau
    from private.prend_un_creneau('couple', p_couple, p_limit_couple, p_window_s, p_max_block_s, true, p_now) t;
  if v_attente > 0 then
    return query select v_attente, case when v_nouveau then 'couple' end;
    return;
  end if;
  -- Un couple déjà passé en blocage ne compte plus sur le compte entier : une IP seule en pèse au plus `p_limit_couple`.
  if exists (select 1 from public.login_throttle t where t.scope = 'couple' and t.key = p_couple and t.strikes > 0) then
    return query select 0, null::text;
    return;
  end if;
  select t.attente_s, t.nouveau_blocage into v_attente, v_nouveau
    from private.prend_un_creneau_fixe(
      'compte_entier', p_account, p_limit_account, p_account_window_s, p_account_block_s, p_now) t;
  return query select v_attente, case when v_nouveau then 'account' end;
end;
$$;
revoke all on function private.prend_les_creneaux_de_connexion(bytea, bytea, bytea, integer, integer, integer, integer, integer, integer, integer, timestamptz)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

create or replace function public.prend_les_creneaux_de_connexion(
  p_couple bytea, p_account bytea, p_ip bytea,
  p_limit_couple integer default 5,
  p_limit_account integer default 20,
  p_limit_ip integer default 20,
  p_window_s integer default 900,
  p_max_block_s integer default 86400,
  p_account_window_s integer default 86400,
  p_account_block_s integer default 3600
) returns table (attente_s integer, nouveau_blocage text)
language sql
volatile
security definer
set search_path = ''
as $$
  select * from private.prend_les_creneaux_de_connexion(
    p_couple, p_account, p_ip, p_limit_couple, p_limit_account, p_limit_ip,
    p_window_s, p_max_block_s, p_account_window_s, p_account_block_s, pg_catalog.now());
$$;
revoke all on function public.prend_les_creneaux_de_connexion(bytea, bytea, bytea, integer, integer, integer, integer, integer, integer, integer)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.prend_les_creneaux_de_connexion(bytea, bytea, bytea, integer, integer, integer, integer, integer, integer, integer)
  to popote_api, service_role;

create or replace function public.libere_le_couple(p_couple bytea, p_account bytea) returns void
language sql
volatile
security definer
set search_path = ''
as $$
  -- Le refus n'est rendu que si l'essai a compté : un couple déjà passé en blocage n'a rien compté sur le compte entier.
  update public.login_throttle set attempts = case when attempts > 0 then attempts - 1 else 0 end
   where scope = 'compte_entier' and key = p_account
     and exists (select 1 from public.login_throttle c where c.scope = 'couple' and c.key = p_couple and c.strikes = 0);
  update public.login_throttle
     set attempts = 0, strikes = 0, last_block_at = null, blocked_until = null
   where scope = 'couple' and key = p_couple;
$$;
revoke all on function public.libere_le_couple(bytea, bytea)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.libere_le_couple(bytea, bytea) to popote_api, service_role;
