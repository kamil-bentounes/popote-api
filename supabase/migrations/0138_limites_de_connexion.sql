-- ═══════════════════════════════════════════════════════════════════════════
-- 0138 · LES LIMITES DE CONNEXION, COMPTÉES EN BASE (spec § 3.6, § 7.1 ; B5, B6, B12, B19, B21, B24)
--
-- Une table de compteurs (`login_throttle`) et UNE fonction atomique qui les tient :
--
--  - `public.prend_les_creneaux(p_account, p_ip, …)` : l'IP d'abord ; le compte ne compte QUE si l'IP passe (B6).
--    Une IP bloquée ne peut donc pas épuiser les créneaux d'un compte. Les deux lignes se verrouillent toujours
--    dans cet ordre (IP puis compte) : deux connexions croisées (compte A / IP B, compte B / IP A) ne s'attendent
--    jamais en cercle (pas de `40P01`).
--  - 5 essais par compte et 20 par IP en 15 min (les valeurs viennent de `config.py` : ce sont les défauts). Au
--    créneau de trop : blocage de 15 min, puis 30, puis 60 (plafond, B5) ; chaque blocage consécutif double. Les
--    `strikes` retombent après 24 h sans blocage. Bloqué : la fonction rend l'attente SANS compter, donc un tiers
--    ne prolonge pas un blocage en insistant.
--  - le compteur de réinitialisation (`reset`, 3 par heure, sans escalade) se compte par (e-mail, IP) : l'API en
--    fait une seule clé (B5). Il ne touche pas le compteur de connexion.
--  - `public.libere_compte(p_key)` après un succès : remet le COMPTE à zéro, jamais l'IP (sinon un attaquant qui
--    connaît un mot de passe effacerait son propre compteur d'IP).
--  - une clé de compte inconnue se comporte comme une connue : la fonction ne regarde jamais `auth.users`.
--  - la clé est un HMAC de 32 octets calculé par l'API (`security/empreintes.py`) : aucune adresse ni IP ici.
--  - la fonction rend aussi, une seule fois par blocage, quelle clé vient d'être bloquée (`nouveau_blocage`) :
--    seul ce drapeau déclenche l'événement `connexion_bloquee` (B21), un par (clé, fenêtre de blocage).
--
-- DROITS (B3, B19) : `popote_api` (contexte connexion) et `service_role` (contexte service) exécutent les trois
-- fonctions publiques, aucune autre. Elles n'ont pas de paramètre d'horloge : les variantes à `p_now` vivent dans
-- `private`, que personne n'exécute hors tests.
--
-- RISQUE ACCEPTÉ (B5) : qui connaît l'adresse d'une personne peut ralentir SA connexion, au plus 60 min par
-- blocage ; « mot de passe oublié » reste ouvert. Écrit dans docs/securite.md.
--
-- COMPATIBLE avec l'appli en ligne : objets neufs, aucun appelant dans l'appli actuelle ; la tâche `pg_cron`
-- ne fait que du SQL.
--
-- Retour arrière (sans perte : les compteurs se reconstituent en 15 min) :
--   select cron.unschedule('limites-de-connexion-purge');   -- si pg_cron est là
--   drop function public.prend_les_creneaux(bytea, bytea, integer, integer, integer, integer);
--   drop function public.prend_un_creneau_reinit(bytea, integer, integer);
--   drop function private.prend_un_creneau_reinit(bytea, integer, integer, timestamptz);
--   drop function public.libere_compte(bytea);
--   drop function private.prend_les_creneaux(bytea, bytea, integer, integer, integer, integer, timestamptz);
--   drop function private.prend_un_creneau(text, bytea, integer, integer, integer, boolean, timestamptz);
--   drop function private.purge_login_throttle(timestamptz, integer);
--   drop table public.login_throttle;
-- ═══════════════════════════════════════════════════════════════════════════
set local lock_timeout = '5s';
set local statement_timeout = '30s';

-- ── 1. La table ─────────────────────────────────────────────────────────────
create table public.login_throttle (
  scope         text  not null check (scope in ('account', 'ip', 'reset')),
  key           bytea not null check (length(key) = 32),
  window_start  timestamptz not null,
  attempts      integer not null default 0 check (attempts >= 0),
  -- Blocages consécutifs : 0, 1, 2… L'attente double à chaque cran jusqu'au plafond.
  strikes       integer not null default 0 check (strikes >= 0),
  last_block_at timestamptz,
  blocked_until timestamptz,
  primary key (scope, key)
);
comment on table public.login_throttle is
  'Compteurs de limite : clés HMAC de 32 octets, jamais d''adresse ni d''IP. Purgés après 24 h sans activité.';
-- La purge parcourt par date.
create index login_throttle_window_start_idx on public.login_throttle (window_start);

alter table public.login_throttle enable row level security;
alter table public.login_throttle force row level security;
revoke all on table public.login_throttle from public, anon, authenticated, service_role, popote_api, popote_internal;

-- ── 2. Une ligne : prendre un créneau ───────────────────────────────────────
/* Verrouille la ligne (`for update`, après un `insert … on conflict do nothing` qui la crée) puis décide. Rend
   l'attente en secondes (0 = passe) et `true` si CET appel vient de poser un blocage. Bloqué : rend l'attente
   restante sans rien écrire. Au créneau de trop : le blocage dure `p_window_s` × 2^(strikes-1), plafonné à
   `p_max_block_s`, et le compteur repart à zéro (la fenêtre suivante commence au déblocage). `p_escalade` faux
   (`reset`) : pas de blocage, le créneau de trop attend la fin de la fenêtre et ne compte pas. */
create or replace function private.prend_un_creneau(
  p_scope text,
  p_key bytea,
  p_limit integer,
  p_window_s integer,
  p_max_block_s integer,
  p_escalade boolean,
  p_now timestamptz
) returns table (attente_s integer, nouveau_blocage boolean)
language plpgsql
volatile
security invoker
set search_path = ''
as $$
declare
  v_ligne public.login_throttle%rowtype;
  v_fenetre constant interval := pg_catalog.make_interval(secs => p_window_s);
  v_attempts integer;
  v_strikes integer;
  v_duree integer;
begin
  if p_key is null or pg_catalog.length(p_key) <> 32 then
    raise exception 'La clé de limite doit faire 32 octets.' using errcode = 'invalid_parameter_value';
  end if;
  -- Les bornes se vérifient ici, pour toutes les fonctions publiques : un appelant ne désactive pas la limite (limite
  -- énorme), ne pose pas un blocage de plusieurs années, et un paramètre nul ne passe pas (`null < 1` n'est pas vrai).
  if p_limit is null or p_window_s is null or p_max_block_s is null or p_escalade is null or p_now is null
     or p_limit not between 1 and 10000
     or p_window_s not between 1 and 86400
     or p_max_block_s not between p_window_s and 86400 then
    raise exception 'Limite, fenêtre ou plafond invalide.' using errcode = 'invalid_parameter_value';
  end if;

  -- Créer la ligne si elle manque ET la verrouiller en une seule instruction : la purge nocturne ne peut pas
  -- l'effacer entre les deux (un `insert … do nothing` puis un `select … for update` laisserait cette fenêtre).
  insert into public.login_throttle as t (scope, key, window_start) values (p_scope, p_key, p_now)
  on conflict (scope, key) do update set window_start = t.window_start
  returning t.* into v_ligne;

  -- Bloqué : l'attente restante, sans compter.
  if v_ligne.blocked_until is not null and v_ligne.blocked_until > p_now then
    return query select pg_catalog.ceil(extract(epoch from v_ligne.blocked_until - p_now))::integer, false;
    return;
  end if;

  v_attempts := v_ligne.attempts;
  v_strikes := v_ligne.strikes;
  -- Les crans retombent après 24 h sans blocage.
  if v_ligne.last_block_at is not null and v_ligne.last_block_at <= p_now - interval '24 hours' then
    v_strikes := 0;
  end if;
  -- Fenêtre échue : on repart de zéro.
  if v_ligne.window_start <= p_now - v_fenetre then
    v_attempts := 0;
    v_ligne.window_start := p_now;
  end if;

  if v_attempts < p_limit then
    update public.login_throttle
       set attempts = v_attempts + 1, strikes = v_strikes, window_start = v_ligne.window_start
     where scope = p_scope and key = p_key;
    return query select 0, false;
    return;
  end if;

  if not p_escalade then
    -- Sans escalade : attendre la fin de la fenêtre, sans compter.
    update public.login_throttle set strikes = v_strikes, window_start = v_ligne.window_start
     where scope = p_scope and key = p_key;
    return query select pg_catalog.ceil(extract(epoch from v_ligne.window_start + v_fenetre - p_now))::integer, false;
    return;
  end if;

  v_strikes := v_strikes + 1;
  -- 2^(strikes-1) : le 31e cran n'existe pas, le plafond tombe bien avant.
  v_duree := least(p_max_block_s::bigint, p_window_s::bigint * (1::bigint << least(v_strikes - 1, 30)))::integer;
  update public.login_throttle
     set attempts = 0, strikes = v_strikes, window_start = p_now, last_block_at = p_now,
         blocked_until = p_now + pg_catalog.make_interval(secs => v_duree)
   where scope = p_scope and key = p_key;
  return query select v_duree, true;
end;
$$;
comment on function private.prend_un_creneau(text, bytea, integer, integer, integer, boolean, timestamptz) is
  'Prend un créneau sur une clé : 0 (passe) ou l''attente en secondes, et si ce créneau pose un nouveau blocage. Interne.';
revoke all on function private.prend_un_creneau(text, bytea, integer, integer, integer, boolean, timestamptz)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

-- ── 3. La connexion : l'IP d'abord, le compte seulement si l'IP passe ───────
create or replace function private.prend_les_creneaux(
  p_account bytea,
  p_ip bytea,
  p_limit_account integer,
  p_limit_ip integer,
  p_window_s integer,
  p_max_block_s integer,
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
  select t.attente_s, t.nouveau_blocage into v_attente, v_nouveau
    from private.prend_un_creneau('ip', p_ip, p_limit_ip, p_window_s, p_max_block_s, true, p_now) t;
  if v_attente > 0 then
    return query select v_attente, case when v_nouveau then 'ip' end;
    return;
  end if;
  select t.attente_s, t.nouveau_blocage into v_attente, v_nouveau
    from private.prend_un_creneau('account', p_account, p_limit_account, p_window_s, p_max_block_s, true, p_now) t;
  return query select v_attente, case when v_nouveau then 'account' end;
end;
$$;
comment on function private.prend_les_creneaux(bytea, bytea, integer, integer, integer, integer, timestamptz) is
  'Variante à horloge de public.prend_les_creneaux. Interne (tests).';
revoke all on function private.prend_les_creneaux(bytea, bytea, integer, integer, integer, integer, timestamptz)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

create or replace function public.prend_les_creneaux(
  p_account bytea,
  p_ip bytea,
  p_limit_account integer default 5,
  p_limit_ip integer default 20,
  p_window_s integer default 900,
  p_max_block_s integer default 3600
) returns table (attente_s integer, nouveau_blocage text)
language sql
volatile
security definer
set search_path = ''
as $$
  select * from private.prend_les_creneaux(
    p_account, p_ip, p_limit_account, p_limit_ip, p_window_s, p_max_block_s, pg_catalog.now());
$$;
comment on function public.prend_les_creneaux(bytea, bytea, integer, integer, integer, integer) is
  'Prend un créneau sur l''IP, puis sur le compte si l''IP passe : (attente en secondes, 0 = passe ; clé nouvellement '
  'bloquée « ip » ou « account », sinon null). Exécutable par popote_api et service_role seulement.';
revoke all on function public.prend_les_creneaux(bytea, bytea, integer, integer, integer, integer)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.prend_les_creneaux(bytea, bytea, integer, integer, integer, integer)
  to popote_api, service_role;

-- ── 4. La réinitialisation par mail : 3 par heure et par (e-mail, IP), sans escalade ───────────
create or replace function private.prend_un_creneau_reinit(
  p_key bytea, p_limit integer, p_window_s integer, p_now timestamptz
) returns integer
language sql
volatile
security invoker
set search_path = ''
as $$
  select t.attente_s from private.prend_un_creneau('reset', p_key, p_limit, p_window_s, p_window_s, false, p_now) t;
$$;
revoke all on function private.prend_un_creneau_reinit(bytea, integer, integer, timestamptz)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

create or replace function public.prend_un_creneau_reinit(
  p_key bytea, p_limit integer default 3, p_window_s integer default 3600
) returns integer
language sql
volatile
security definer
set search_path = ''
as $$
  select private.prend_un_creneau_reinit(p_key, p_limit, p_window_s, pg_catalog.now());
$$;
comment on function public.prend_un_creneau_reinit(bytea, integer, integer) is
  'Prend un créneau de réinitialisation sur la clé (e-mail, IP) : 0 (passe) ou l''attente en secondes.';
revoke all on function public.prend_un_creneau_reinit(bytea, integer, integer)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.prend_un_creneau_reinit(bytea, integer, integer) to popote_api, service_role;

-- ── 5. Le succès : le compte à zéro, jamais l'IP ────────────────────────────
create or replace function public.libere_compte(p_key bytea) returns void
language sql
volatile
security definer
set search_path = ''
as $$
  update public.login_throttle
     set attempts = 0, strikes = 0, last_block_at = null, blocked_until = null
   where scope = 'account' and key = p_key;
$$;
comment on function public.libere_compte(bytea) is
  'Remet à zéro le compteur de COMPTE après une connexion réussie ; jamais celui de l''IP.';
revoke all on function public.libere_compte(bytea) from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.libere_compte(bytea) to popote_api, service_role;

-- ── 6. La purge ─────────────────────────────────────────────────────────────
/* Par lots, idempotente, rend le nombre de lignes effacées (jamais une valeur). Une ligne sans activité depuis 24 h
   ne retient plus rien : ses crans seraient retombés de toute façon. */
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
comment on function private.purge_login_throttle(timestamptz, integer) is
  'Efface les compteurs de limite sans activité depuis 24 h, par lots ; rend leur nombre. Lancée chaque nuit par pg_cron.';
revoke all on function private.purge_login_throttle(timestamptz, integer)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

do $$
begin
  if exists (select 1 from pg_extension where extname = 'pg_cron') then
    begin
      execute $q$select cron.schedule('limites-de-connexion-purge', '47 3 * * *', 'select private.purge_login_throttle()')$q$;
    exception when others then
      raise warning 'LA PURGE DES LIMITES DE CONNEXION N''EST PAS PLANIFIÉE : % (job « limites-de-connexion-purge »).', sqlerrm;
    end;
  else
    raise warning 'LA PURGE DES LIMITES DE CONNEXION N''EST PAS PLANIFIÉE : pg_cron est absent. Active-le (Database > '
      'Extensions), puis : select cron.schedule(''limites-de-connexion-purge'', ''47 3 * * *'', ''select private.purge_login_throttle()'').';
  end if;
end $$;
