-- ═══════════════════════════════════════════════════════════════════════════
-- 0149 · LA VÉRIFICATION DU CODE ET L'OUVERTURE DE LA SESSION (0.4bis S7a ; spec § 4 ; A1, leçons 1 et 3)
--
-- S5 (0147) écrit le code ; ici la base le VÉRIFIE et ouvre la session dans le même appel. La route et la rupture du
-- contrat sont S7b.
--
--  - `login_session.opened_with` (`code`, `cle`, `invitation`, `autre`) : par quelle preuve la session est née.
--  - `private/public.ouvre_la_session` : le corps de `cree_session` (0148) plus `opened_with`. NOM NOUVEAU : `cree_session`
--    garde sa signature et son corps, le code déjà déployé sur l'essai l'appelle pendant le déploiement ; elle part en S15
--    (le corps est alors écrit une seule fois).
--  - `private.personne_peut_entrer` (A1) : « a un profil, n'est ni bannie ni supprimée », écrit UNE fois. `demande_un_code`
--    (redéfinie à signature égale) et `ouvre_une_session_par_code` l'appellent ; S9, S14 et 0.4ter la redéfinissent.
--  - `public.ouvre_une_session_par_code` : un seul appel. La ligne se lit sans verrou pour connaître la personne, on prend
--    `verrouille_la_personne` (et celle de la session présentée), PUIS la preuve se relit `for update` SOUS le verrou : une
--    fermeture de toutes les sessions (qui révoque les codes, 0148) qui précède fait refuser ce code. Ordre des verrous :
--    foyer, invitation, personne, lignes ; `prend_les_creneaux` (limites) se prend avant, côté API. Une ligne FACTICE
--    (personne nulle) n'a pas de personne à verrouiller : le `for update` de sa ligne sérialise ses essais ; elle
--    compte l'essai comme une vraie et ne réussit jamais.
--    Un refus est un RÉSULTAT (la transaction se valide : l'essai reste) ; une erreur annule tout (le code reste valable).
--    La personne bannie, supprimée ou sans profil est refusée AVANT de consommer, essai compté, jamais par une exception.
--    Refus : demande inconnue, d'une autre adresse, révoquée, utilisée, échue, 5 essais faits, faux code, personne qui ne
--    peut pas entrer. Un code faux au 5e essai tue la ligne (`attempts` = 5). Le code juste au 5e essai passe.
--    Plafond d'essais : 6 codes par heure et par adresse (0147) × 5 essais, pas une limite de plus.
--    La comparaison des empreintes n'est pas à temps constant : c'est un HMAC à poivre, l'appelant n'en maîtrise pas
--    le début.
--  - `private.prend_un_creneau` : les crans retombent 24 h après la FIN du blocage. 0138 les remettait à zéro 24 h après
--    son DÉBUT : après un blocage de 24 h, l'escalade repartait à 15 minutes (environ 17 essais par jour au lieu de 5).
--  - `security_event.kind` accepte `connexion_par_code`.
--
-- DROITS : `popote_api` seul exécute les deux fonctions publiques nouvelles ; `service_role` n'a pas d'usage pour elles.
-- Les variantes à `p_now` vivent dans `private`, fermées à tous les rôles (B19).
--
-- COMPATIBLE avec l'appli en ligne : une colonne avec défaut (aucun code actuel ne lit `login_session`) ; des fonctions
-- neuves ; `cree_session` intacte ; `prend_un_creneau` et `demande_un_code` gardent leur signature, la première ne
-- change que des compteurs, la seconde rend ce qu'elle rendait ; un CHECK élargi, aucune valeur retirée.
--
-- RETOUR ARRIÈRE (il perd `opened_with` et les événements `connexion_par_code` du journal ; les sessions et les codes
-- se rouvrent). Le SQL entre les deux repères s'exécute tel quel, une fois les « -- » retirés (rejoué sur la base locale) :
-- >>> retour arrière
--   drop function public.ouvre_une_session_par_code(uuid, bytea, bytea, bytea, text, text, bytea, text);
--   drop function private.ouvre_une_session_par_code(uuid, bytea, bytea, bytea, text, text, bytea, timestamptz, text);
--   drop function public.ouvre_la_session(uuid, bytea, text, text, bytea, text);
--   drop function private.ouvre_la_session(uuid, bytea, text, text, bytea, text, timestamptz);
--   create or replace function public.demande_un_code(
--     p_email text,
--     p_account_key bytea,
--     p_code_request_id uuid,
--     p_code_hash bytea,
--     p_ip_hash bytea,
--     p_request_id text default null
--   ) returns table (personne uuid, demande uuid, nouveau boolean)
--   language plpgsql
--   volatile
--   security definer
--   set search_path = ''
--   as $$
--   declare
--     v_personne uuid;
--     v_actif public.login_code%rowtype;
--   begin
--     -- `p_request_id` se contrôle ici, pour les deux branches : sinon seul un compte réel (qui écrit l'événement) le
--     -- refuserait, et l'erreur de la base recopierait la ligne refusée.
--     if p_email is null or p_account_key is null or p_code_request_id is null or p_code_hash is null
--        or p_ip_hash is null or pg_catalog.octet_length(p_email) > 254
--        or pg_catalog.octet_length(p_account_key) <> 32 or pg_catalog.octet_length(p_code_hash) <> 32
--        or pg_catalog.octet_length(p_ip_hash) <> 32
--        or (p_request_id is not null and p_request_id !~ '^[0-9a-f]{32}$') then
--       raise exception 'Paramètres invalides.' using errcode = 'invalid_parameter_value';
--     end if;
--
--     -- Deux demandes de la même adresse se suivent, connue ou non : l'index unique ne verrait jamais une course.
--     perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtext('login_code'),
--                                              pg_catalog.hashtext(pg_catalog.encode(p_account_key, 'hex')));
--
--     /* Le compte se lit DEUX fois : une première sans verrou pour connaître la personne, puis, le verrou de la personne
--        pris, une seconde sous `for key share` (une suppression du compte attendrait, au lieu de casser l'insertion).
--        L'ordre clé de compte, personne, lignes reste ainsi celui de toutes les autres fonctions : un `key share` pris
--        avant le verrou de la personne ouvrirait un cycle avec qui tient la personne et attend `auth.users`.
--        `instance_id` : seul l'index `users_instance_id_email_idx (instance_id, lower(email))` sert la recherche. Sans
--        lui, un parcours complet de la table s'arrête à la première ligne trouvée : une adresse connue répondrait plus
--        vite qu'une inconnue (mesuré : 4 ms contre 12 ms sur 20 000 comptes). Supabase pose toujours cette valeur.
--        Un bannissement simultané n'attend pas le `key share` : la vérification (S7) relit l'état du compte. */
--     select u.id into v_personne
--       from auth.users u
--      where u.instance_id = '00000000-0000-0000-0000-000000000000'::uuid
--        and pg_catalog.lower(u.email) = p_email
--        and u.deleted_at is null
--        and (u.banned_until is null or u.banned_until <= pg_catalog.now())
--        and exists (select 1 from public.user_profile p where p.id = u.id)
--      order by u.id  -- deux comptes à la casse près (l'index unique d'Auth la distingue) : toujours le même
--      limit 1;
--
--     if v_personne is not null then
--       -- La même clé que `cree_session` (0139) : un code ne se révoque pas pendant qu'une session s'ouvre.
--       perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(v_personne::text, 0));
--       select u.id into v_personne
--         from auth.users u
--        where u.id = v_personne
--          and u.deleted_at is null
--          and (u.banned_until is null or u.banned_until <= pg_catalog.now())
--          and exists (select 1 from public.user_profile p where p.id = u.id)
--          for key share of u;
--     end if;
--
--     select * into v_actif
--       from public.login_code c
--      where c.account_key = p_account_key and c.used_at is null and c.revoked_at is null
--        for update;
--     -- Moins de 60 s : le code déjà parti reste le bon (un code mort, aux 5 essais faux, ne se rejoue pas).
--     if found and v_actif.created_at > pg_catalog.now() - interval '60 seconds' and v_actif.attempts < 5 then
--       return query select v_personne, v_actif.id, false;
--       return;
--     end if;
--
--     update public.login_code c
--        set revoked_at = pg_catalog.now()
--      where c.account_key = p_account_key and c.used_at is null and c.revoked_at is null;
--     insert into public.login_code (id, account_key, person_id, code_hash)
--     values (p_code_request_id, p_account_key, v_personne, p_code_hash);
--
--     -- Seulement pour un compte réel : une adresse inconnue n'écrit qu'une ligne purgée en un jour et un compteur
--     -- purgé en 24 h, jamais une ligne de journal gardée 90 jours (sinon une IP remplirait la base).
--     if v_personne is not null then
--       perform private.ecrit_evenement('code_demande', v_personne, null, null, p_account_key, p_ip_hash, p_request_id);
--     end if;
--     return query select v_personne, p_code_request_id, true;
--   end;
--   $$;
--   drop function private.personne_peut_entrer(uuid);
--   create or replace function private.prend_un_creneau(
--     p_scope text,
--     p_key bytea,
--     p_limit integer,
--     p_window_s integer,
--     p_max_block_s integer,
--     p_escalade boolean,
--     p_now timestamptz
--   ) returns table (attente_s integer, nouveau_blocage boolean)
--   language plpgsql
--   volatile
--   security invoker
--   set search_path = ''
--   as $$
--   declare
--     v_ligne public.login_throttle%rowtype;
--     v_fenetre constant interval := pg_catalog.make_interval(secs => p_window_s);
--     v_attempts integer;
--     v_strikes integer;
--     v_duree integer;
--   begin
--     if p_key is null or pg_catalog.length(p_key) <> 32 then
--       raise exception 'La clé de limite doit faire 32 octets.' using errcode = 'invalid_parameter_value';
--     end if;
--     -- Les bornes se vérifient ici, pour toutes les fonctions publiques : un appelant ne désactive pas la limite (limite
--     -- énorme), ne pose pas un blocage de plusieurs années, et un paramètre nul ne passe pas (`null < 1` n'est pas vrai).
--     if p_limit is null or p_window_s is null or p_max_block_s is null or p_escalade is null or p_now is null
--        or p_limit not between 1 and 10000
--        or p_window_s not between 1 and 86400
--        or p_max_block_s not between p_window_s and 86400 then
--       raise exception 'Limite, fenêtre ou plafond invalide.' using errcode = 'invalid_parameter_value';
--     end if;
--
--     -- Créer la ligne si elle manque ET la verrouiller en une seule instruction : la purge nocturne ne peut pas
--     -- l'effacer entre les deux (un `insert … do nothing` puis un `select … for update` laisserait cette fenêtre).
--     insert into public.login_throttle as t (scope, key, window_start) values (p_scope, p_key, p_now)
--     on conflict (scope, key) do update set window_start = t.window_start
--     returning t.* into v_ligne;
--
--     -- Bloqué : l'attente restante, sans compter.
--     if v_ligne.blocked_until is not null and v_ligne.blocked_until > p_now then
--       return query select pg_catalog.ceil(extract(epoch from v_ligne.blocked_until - p_now))::integer, false;
--       return;
--     end if;
--
--     v_attempts := v_ligne.attempts;
--     v_strikes := v_ligne.strikes;
--     -- Les crans retombent après 24 h sans blocage.
--     if v_ligne.last_block_at is not null and v_ligne.last_block_at <= p_now - interval '24 hours' then
--       v_strikes := 0;
--     end if;
--     -- Fenêtre échue : on repart de zéro.
--     if v_ligne.window_start <= p_now - v_fenetre then
--       v_attempts := 0;
--       v_ligne.window_start := p_now;
--     end if;
--
--     if v_attempts < p_limit then
--       update public.login_throttle
--          set attempts = v_attempts + 1, strikes = v_strikes, window_start = v_ligne.window_start
--        where scope = p_scope and key = p_key;
--       return query select 0, false;
--       return;
--     end if;
--
--     if not p_escalade then
--       -- Sans escalade : attendre la fin de la fenêtre, sans compter.
--       update public.login_throttle set strikes = v_strikes, window_start = v_ligne.window_start
--        where scope = p_scope and key = p_key;
--       return query select pg_catalog.ceil(extract(epoch from v_ligne.window_start + v_fenetre - p_now))::integer, false;
--       return;
--     end if;
--
--     v_strikes := v_strikes + 1;
--     -- 2^(strikes-1) : le 31e cran n'existe pas, le plafond tombe bien avant.
--     v_duree := least(p_max_block_s::bigint, p_window_s::bigint * (1::bigint << least(v_strikes - 1, 30)))::integer;
--     update public.login_throttle
--        set attempts = 0, strikes = v_strikes, window_start = p_now, last_block_at = p_now,
--            blocked_until = p_now + pg_catalog.make_interval(secs => v_duree)
--      where scope = p_scope and key = p_key;
--     return query select v_duree, true;
--   end;
--   $$;
--   alter table public.login_session drop column opened_with;
--   delete from public.security_event where kind = 'connexion_par_code';
--   alter table public.security_event drop constraint security_event_kind_check, add constraint
--     security_event_kind_check check (kind in (
--       'connexion_reussie', 'connexion_ratee', 'connexion_bloquee', 'deconnexion',
--       'reauthentification_reussie', 'reauthentification_ratee', 'session_fermee',
--       'mot_de_passe_change', 'reinitialisation_demandee', 'reinitialisation_utilisee',
--       'invitation_creee', 'invitation_acceptee', 'invitation_revoquee',
--       'compte_supprime', 'compte_repris', 'verification_fuites_indisponible', 'code_demande'));
-- <<< retour arrière
-- ═══════════════════════════════════════════════════════════════════════════
set local lock_timeout = '5s';
set local statement_timeout = '30s';

-- ── 1. Un CHECK élargi, une colonne ─────────────────────────────────────────
/* Même démarche que 0147 : la table est petite, le nouvel ensemble est un sur-ensemble de l'ancien. */
alter table public.security_event
  drop constraint security_event_kind_check,
  add constraint security_event_kind_check check (kind in (
    'connexion_reussie', 'connexion_ratee', 'connexion_bloquee', 'deconnexion',
    'reauthentification_reussie', 'reauthentification_ratee', 'session_fermee',
    'mot_de_passe_change', 'reinitialisation_demandee', 'reinitialisation_utilisee',
    'invitation_creee', 'invitation_acceptee', 'invitation_revoquee',
    'compte_supprime', 'compte_repris', 'verification_fuites_indisponible',
    'code_demande', 'connexion_par_code')) not valid;
alter table public.security_event validate constraint security_event_kind_check;

alter table public.login_session
  add column opened_with text not null default 'autre'
    check (opened_with in ('code', 'cle', 'invitation', 'autre'));

-- ── 2. Les crans retombent 24 h après la FIN du blocage ─────────────────────
/* Le corps de 0138 ; seule la condition de retombée change : `greatest(last_block_at, blocked_until)`. */
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
  if p_limit is null or p_window_s is null or p_max_block_s is null or p_escalade is null or p_now is null
     or p_limit not between 1 and 10000
     or p_window_s not between 1 and 86400
     or p_max_block_s not between p_window_s and 86400 then
    raise exception 'Limite, fenêtre ou plafond invalide.' using errcode = 'invalid_parameter_value';
  end if;

  insert into public.login_throttle as t (scope, key, window_start) values (p_scope, p_key, p_now)
  on conflict (scope, key) do update set window_start = t.window_start
  returning t.* into v_ligne;

  if v_ligne.blocked_until is not null and v_ligne.blocked_until > p_now then
    return query select pg_catalog.ceil(extract(epoch from v_ligne.blocked_until - p_now))::integer, false;
    return;
  end if;

  v_attempts := v_ligne.attempts;
  v_strikes := v_ligne.strikes;
  -- Les crans retombent 24 h après la FIN du dernier blocage (`blocked_until`), pas après son début : un blocage de
  -- 24 h se terminerait sinon à l'instant où les crans retombent, et l'escalade repartirait de 15 minutes.
  if v_ligne.last_block_at is not null
     and greatest(v_ligne.last_block_at, v_ligne.blocked_until) <= p_now - interval '24 hours' then
    v_strikes := 0;
  end if;
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
    update public.login_throttle set strikes = v_strikes, window_start = v_ligne.window_start
     where scope = p_scope and key = p_key;
    return query select pg_catalog.ceil(extract(epoch from v_ligne.window_start + v_fenetre - p_now))::integer, false;
    return;
  end if;

  v_strikes := v_strikes + 1;
  v_duree := least(p_max_block_s::bigint, p_window_s::bigint * (1::bigint << least(v_strikes - 1, 30)))::integer;
  update public.login_throttle
     set attempts = 0, strikes = v_strikes, window_start = p_now, last_block_at = p_now,
         blocked_until = p_now + pg_catalog.make_interval(secs => v_duree)
   where scope = p_scope and key = p_key;
  return query select v_duree, true;
end;
$$;

-- ── 3. « Peut entrer » : écrit une fois (A1) ────────────────────────────────
/* Un profil, ni banni ni supprimé. Le foyer n'est PAS exigé par cette fonction : `user_profile.household_id` est
   `not null`, et la personne qui a quitté son foyer n'a plus de profil (0.4ter, F3, la redéfinit). Le bannissement
   se compare à `now()` : la fonction n'a pas d'horloge à injecter, donc la variante à `p_now` y est infidèle hors
   production. Interne. */
create or replace function private.personne_peut_entrer(p_person uuid)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
      from auth.users u
      join public.user_profile p on p.id = u.id
     where u.id = p_person
       and u.deleted_at is null
       and (u.banned_until is null or u.banned_until <= pg_catalog.now()));
$$;
comment on function private.personne_peut_entrer(uuid) is
  'Vrai si la personne a un profil et n''est ni bannie ni supprimée : la seule définition de « peut entrer » (demande et vérification d''un code, clés). Interne.';
revoke all on function private.personne_peut_entrer(uuid)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

/* `demande_un_code` (0147), à signature égale : les deux `exists (… user_profile …)` deviennent l'appel. Même corps pour le
   reste, mot pour mot. */
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
     or p_ip_hash is null or pg_catalog.octet_length(p_email) > 254
     or pg_catalog.octet_length(p_account_key) <> 32 or pg_catalog.octet_length(p_code_hash) <> 32
     or pg_catalog.octet_length(p_ip_hash) <> 32
     or (p_request_id is not null and p_request_id !~ '^[0-9a-f]{32}$') then
    raise exception 'Paramètres invalides.' using errcode = 'invalid_parameter_value';
  end if;

  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtext('login_code'),
                                           pg_catalog.hashtext(pg_catalog.encode(p_account_key, 'hex')));

  /* Le compte se lit DEUX fois (voir 0147) : sans verrou pour connaître la personne, puis, son verrou pris, sous
     `for key share`. L'ordre clé de compte, personne, lignes reste celui de toutes les fonctions. `instance_id` : seul
     l'index `users_instance_id_email_idx` sert la recherche (même durée pour une adresse connue et inconnue). */
  select u.id into v_personne
    from auth.users u
   where u.instance_id = '00000000-0000-0000-0000-000000000000'::uuid
     and pg_catalog.lower(u.email) = p_email
     and private.personne_peut_entrer(u.id)
   order by u.id
   limit 1;

  if v_personne is not null then
    perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(v_personne::text, 0));
    select u.id into v_personne
      from auth.users u
     where u.id = v_personne
       and private.personne_peut_entrer(u.id)
       for key share of u;
  end if;

  select * into v_actif
    from public.login_code c
   where c.account_key = p_account_key and c.used_at is null and c.revoked_at is null
     for update;
  if found and v_actif.created_at > pg_catalog.now() - interval '60 seconds' and v_actif.attempts < 5 then
    return query select v_personne, v_actif.id, false;
    return;
  end if;

  update public.login_code c
     set revoked_at = pg_catalog.now()
   where c.account_key = p_account_key and c.used_at is null and c.revoked_at is null;
  insert into public.login_code (id, account_key, person_id, code_hash)
  values (p_code_request_id, p_account_key, v_personne, p_code_hash);

  if v_personne is not null then
    perform private.ecrit_evenement('code_demande', v_personne, null, null, p_account_key, p_ip_hash, p_request_id);
  end if;
  return query select v_personne, p_code_request_id, true;
end;
$$;

-- ── 4. Ouvrir la session : `cree_session` plus la façon de naître ───────────
/* Le corps de `private.cree_session` (0148), l'insertion porte `opened_with`. Le verrou de personne (et celui de la
   session présentée) se prend en premier : celui qui a déjà prouvé sous ce verrou le garde (verrou réentrant). */
create or replace function private.ouvre_la_session(
  p_person uuid, p_hash bytea, p_browser text, p_os text, p_old_hash bytea, p_opened_with text, p_now timestamptz
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
  perform private.verrouille_la_personne(p_person, p_old_hash, p_now);

  if exists (select 1 from auth.users u
              where u.id = p_person and (u.deleted_at is not null or u.banned_until > p_now)) then
    raise exception 'Cette personne ne peut pas ouvrir de session.' using errcode = 'invalid_authorization_specification';
  end if;

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

  update public.login_session
     set revoked_at = p_now
   where id in (
     select id from public.login_session
      where person_id = p_person and revoked_at is null and expires_at > p_now and absolute_expires_at > p_now
      order by last_seen_at desc, created_at desc, id desc
      offset 9);

  insert into public.login_session
    (token_hash, person_id, browser, os, created_at, last_seen_at, expires_at, absolute_expires_at, reauth_at,
     opened_with)
  values
    (p_hash, p_person, p_browser, p_os, p_now, p_now, p_now + interval '30 days', p_now + interval '90 days', p_now,
     p_opened_with)
  returning id into v_id;
  return v_id;
end;
$$;
comment on function private.ouvre_la_session(uuid, bytea, text, text, bytea, text, timestamptz) is
  'Ouvre la session d''une personne (cree_session et opened_with) ; variante à horloge de public.ouvre_la_session. Interne.';
revoke all on function private.ouvre_la_session(uuid, bytea, text, text, bytea, text, timestamptz)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

create or replace function public.ouvre_la_session(
  p_person uuid, p_hash bytea, p_browser text default 'autre', p_os text default 'autre',
  p_old_hash bytea default null, p_opened_with text default 'autre'
) returns uuid
language sql
volatile
security definer
set search_path = ''
as $$
  select private.ouvre_la_session(p_person, p_hash, p_browser, p_os, p_old_hash, p_opened_with, pg_catalog.now());
$$;
comment on function public.ouvre_la_session(uuid, bytea, text, text, bytea, text) is
  'Ouvre la session d''une personne, née par `code`, `cle`, `invitation` ou `autre`, et révoque la session présentée. À appeler sous le verrou de la personne, sa preuve faite. popote_api seul.';
revoke all on function public.ouvre_la_session(uuid, bytea, text, text, bytea, text)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.ouvre_la_session(uuid, bytea, text, text, bytea, text) to popote_api;

-- ── 5. Vérifier le code et ouvrir la session : un seul appel ────────────────
create or replace function private.ouvre_une_session_par_code(
  p_code_request_id uuid,
  p_account_key bytea,
  p_code_hash bytea,
  p_hash bytea,
  p_browser text,
  p_os text,
  p_old_hash bytea,
  p_now timestamptz,
  p_request_id text default null
) returns table (ouverte boolean, session uuid, personne uuid)
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_titulaire uuid;
  v_ligne public.login_code%rowtype;
  v_peut_entrer boolean;
  v_session uuid;
begin
  if p_code_request_id is null or p_account_key is null or p_code_hash is null or p_hash is null or p_now is null
     or pg_catalog.octet_length(p_account_key) <> 32 or pg_catalog.octet_length(p_code_hash) <> 32
     or pg_catalog.octet_length(p_hash) <> 32
     or (p_request_id is not null and p_request_id !~ '^[0-9a-f]{32}$') then
    raise exception 'Paramètres invalides.' using errcode = 'invalid_parameter_value';
  end if;

  -- La personne de la ligne, sans verrou : elle ne change jamais. Demande inconnue ou d'une autre adresse : refus.
  select c.person_id into v_titulaire
    from public.login_code c
   where c.id = p_code_request_id and c.account_key = p_account_key;
  if not found then
    return query select false, null::uuid, null::uuid;
    return;
  end if;

  if v_titulaire is not null then
    perform private.verrouille_la_personne(v_titulaire, p_old_hash, p_now);
    -- Ordre : la session présentée, puis la ligne d'`auth.users`, puis celle du code.
    -- (1) `delete_my_account` (0145) supprime les sessions PUIS le compte : prendre le compte avant la session
    --     présentée ferait un cycle avec elle (`40P01`). La session ne se verrouille que si elle est encore valable.
    -- (2) La suppression d'un compte par Auth tient le compte puis supprime le code en cascade : le code ne se prend
    --     qu'après le compte (comme `demande_un_code`), jamais avant.
    if p_old_hash is not null then
      perform 1 from public.login_session s
       where s.token_hash = p_old_hash and s.revoked_at is null
         and s.expires_at > p_now and s.absolute_expires_at > p_now
         for update;
    end if;
    perform 1 from auth.users u where u.id = v_titulaire for key share;
  end if;

  -- La preuve se relit SOUS le verrou : une fermeture des sessions ou une demande plus récente a pu la révoquer.
  select * into v_ligne
    from public.login_code c
   where c.id = p_code_request_id and c.account_key = p_account_key
     and c.used_at is null and c.revoked_at is null and c.expires_at > p_now and c.attempts < 5
     for update;
  if not found then
    return query select false, null::uuid, null::uuid;
    return;
  end if;

  v_peut_entrer := private.personne_peut_entrer(v_ligne.person_id);
  if v_ligne.person_id is null or not v_peut_entrer or v_ligne.code_hash <> p_code_hash then
    update public.login_code c set attempts = c.attempts + 1 where c.id = v_ligne.id;
    return query select false, null::uuid, null::uuid;
    return;
  end if;

  update public.login_code c set used_at = p_now where c.id = v_ligne.id;
  v_session := private.ouvre_la_session(v_ligne.person_id, p_hash, p_browser, p_os, p_old_hash, 'code', p_now);
  perform private.ecrit_evenement('connexion_par_code', v_ligne.person_id, v_session, null, p_account_key, null,
                                  p_request_id);
  return query select true, v_session, v_ligne.person_id;
end;
$$;
comment on function private.ouvre_une_session_par_code(uuid, bytea, bytea, bytea, text, text, bytea, timestamptz, text) is
  'Variante à horloge de public.ouvre_une_session_par_code. Interne (tests).';
revoke all on function private.ouvre_une_session_par_code(uuid, bytea, bytea, bytea, text, text, bytea, timestamptz, text)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

create or replace function public.ouvre_une_session_par_code(
  p_code_request_id uuid,
  p_account_key bytea,
  p_code_hash bytea,
  p_hash bytea,
  p_browser text,
  p_os text,
  p_old_hash bytea default null,
  p_request_id text default null
) returns table (ouverte boolean, session uuid, personne uuid)
language sql
volatile
security definer
set search_path = ''
as $$
  select * from private.ouvre_une_session_par_code(
    p_code_request_id, p_account_key, p_code_hash, p_hash, p_browser, p_os, p_old_hash, pg_catalog.now(),
    p_request_id);
$$;
comment on function public.ouvre_une_session_par_code(uuid, bytea, bytea, bytea, text, text, bytea, text) is
  'Vérifie le code et ouvre la session en un appel ; un refus (faux code, code échu, utilisé, révoqué, personne qui ne peut pas entrer) est un résultat `ouverte = faux`, jamais une exception. popote_api seul.';
revoke all on function public.ouvre_une_session_par_code(uuid, bytea, bytea, bytea, text, text, bytea, text)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.ouvre_une_session_par_code(uuid, bytea, bytea, bytea, text, text, bytea, text)
  to popote_api;
