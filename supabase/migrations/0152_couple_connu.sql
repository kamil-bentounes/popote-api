-- ═══════════════════════════════════════════════════════════════════════════
-- 0152 · LE COUPLE CONNU : LE COMPTE ENTIER BLOQUÉ N'ARRÊTE PAS L'APPAREIL HABITUEL (0.4bis S7c ; B5)
--
-- Sans cela, un tiers qui connaît l'adresse bloquait la personne 60 min partout avec 5 refus depuis 4 IP neuves (peu coûteuses :
-- quatre /64 IPv6), et recommençait avec 4 autres. Un couple (compte, IP) qui a réussi une connexion il y a moins de 30 jours est
-- « connu » : le blocage du compte entier ne l'arrête pas et ses essais ne comptent plus dessus ; sa propre limite (5) et celle de
-- l'IP restent. Une IP neuve de la personne est bloquée, son appareil habituel non.
--
--  - `login_throttle.last_success_at` : date du dernier succès du couple (colonne facultative, expansion).
--  - `prend_les_creneaux_de_connexion` (même signature) : un couple connu saute la lecture et le compte du compte entier.
--  - `libere_le_couple` (même signature) pose la date ; il ne rend un essai au compte entier que si l'essai du succès avait compté
--    (couple ni en cran, ni déjà connu).
--  - `purge_login_throttle` garde la ligne d'un couple connu 30 jours (une clé HMAC et une date, jamais l'adresse ni l'IP).
--
-- Retour arrière (sans perte : les couples redeviennent inconnus) : rejouer `private.prend_les_creneaux_de_connexion` et
-- `public.libere_le_couple` de 0151 et `private.purge_login_throttle` de 0138, puis
-- `alter table public.login_throttle drop column last_success_at;`.
-- ═══════════════════════════════════════════════════════════════════════════
set local lock_timeout = '5s';
set local statement_timeout = '30s';

alter table public.login_throttle add column last_success_at timestamptz;

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
  v_connu constant boolean := exists (
    select 1 from public.login_throttle t
     where t.scope = 'couple' and t.key = p_couple and t.last_success_at > p_now - interval '30 days');
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
  -- Le compte entier est déjà bloqué : on le dit, sans user le créneau du couple, sauf pour un couple connu.
  if not v_connu then
    select pg_catalog.ceil(extract(epoch from t.blocked_until - p_now))::integer into v_attente
      from public.login_throttle t
     where t.scope = 'compte_entier' and t.key = p_account and t.blocked_until > p_now;
    if v_attente > 0 then
      return query select v_attente, null::text;
      return;
    end if;
  end if;
  select t.attente_s, t.nouveau_blocage into v_attente, v_nouveau
    from private.prend_un_creneau('couple', p_couple, p_limit_couple, p_window_s, p_max_block_s, true, p_now) t;
  if v_attente > 0 then
    return query select v_attente, case when v_nouveau then 'couple' end;
    return;
  end if;
  -- Ne comptent sur le compte entier ni un couple connu, ni un couple déjà passé en blocage (une IP seule en pèse au plus 5).
  if v_connu or exists (
       select 1 from public.login_throttle t where t.scope = 'couple' and t.key = p_couple and t.strikes > 0) then
    return query select 0, null::text;
    return;
  end if;
  select t.attente_s, t.nouveau_blocage into v_attente, v_nouveau
    from private.prend_un_creneau_fixe(
      'compte_entier', p_account, p_limit_account, p_account_window_s, p_account_block_s, p_now) t;
  return query select v_attente, case when v_nouveau then 'account' end;
end;
$$;

create or replace function public.libere_le_couple(p_couple bytea, p_account bytea) returns void
language sql
volatile
security definer
set search_path = ''
as $$
  -- L'essai de ce succès n'a compté sur le compte entier que si le couple n'était ni en cran, ni déjà connu.
  update public.login_throttle set attempts = case when attempts > 0 then attempts - 1 else 0 end
   where scope = 'compte_entier' and key = p_account
     and exists (select 1 from public.login_throttle c where c.scope = 'couple' and c.key = p_couple and c.strikes = 0
                   and (c.last_success_at is null or c.last_success_at <= pg_catalog.now() - interval '30 days'));
  update public.login_throttle
     set attempts = 0, strikes = 0, last_block_at = null, blocked_until = null, last_success_at = pg_catalog.now()
   where scope = 'couple' and key = p_couple;
$$;

create or replace function private.purge_login_throttle(
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
    delete from public.login_throttle t
     using (
       select scope, key from public.login_throttle
        where greatest(window_start, coalesce(last_block_at, window_start), coalesce(blocked_until, window_start))
              < p_now - interval '24 hours'
          and (last_success_at is null or last_success_at <= p_now - interval '30 days')
        order by window_start
        limit p_lot
          for update skip locked) v
     where t.scope = v.scope and t.key = v.key;
    get diagnostics v_lot = row_count;
    v_total := v_total + v_lot;
    exit when v_lot < p_lot;
  end loop;
  raise notice 'purge des limites de connexion : % ligne(s) effacee(s)', v_total;
  return v_total;
end;
$$;
revoke all on function private.purge_login_throttle(timestamptz, integer)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
comment on function private.purge_login_throttle(timestamptz, integer) is
  'Efface les compteurs sans activité depuis 24 h (un couple connu : 30 jours après son dernier succès), par lots ; rend leur nombre.';
revoke all on function private.prend_les_creneaux_de_connexion(bytea, bytea, bytea, integer, integer, integer, integer, integer, integer, integer, timestamptz)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
revoke all on function public.libere_le_couple(bytea, bytea)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.libere_le_couple(bytea, bytea) to popote_api, service_role;
comment on column public.login_throttle.last_success_at is
  'Dernier succès du couple (compte, IP) : le rend « connu » 30 jours. Purgé avec la ligne.';
