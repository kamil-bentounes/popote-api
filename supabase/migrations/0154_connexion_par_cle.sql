-- ═══════════════════════════════════════════════════════════════════════════
-- 0154 · LA CONNEXION PAR CLÉ D'ACCÈS (0.4bis S9a ; spec § 4 ; D3, W3C § 7.2, § 14.6.2 ; leçons 1 et 3)
--
-- S8b (0153) a posé les clés et leur enregistrement ; ici la base accueille la CONNEXION : un défi SANS personne, la clé lue
-- par son identifiant sous le verrou de personne, la session ouverte dans le même appel. La route et la vérification de la
-- signature (Python, `infra/webauthn.py`) sont S9b. Le numéro est 0154, pas 0151 : le plan est antérieur à S7c.
--
--  - `login_session.opened_with_credential` : la clé qui a ouvert la session. Un simple identifiant, SANS clé étrangère : un
--    `on delete set null` perdrait le lien et laisserait vivre les sessions d'une clé supprimée (S10 les ferme AVANT de
--    supprimer la clé).
--  - `webauthn_challenge` accepte le but `authentication` : sans personne ni session (la cérémonie part sans nom
--    d'utilisateur, W3C § 14.6.2). Un CHECK lie but, personne et session : jamais un défi d'enregistrement sans les deux, ni un
--    défi de connexion avec l'un des deux. `cree_un_defi_anonyme` borne les défis anonymes VIVANTS (plafond souple : deux
--    demandes qui se croisent peuvent le dépasser d'au plus le nombre de connexions du pool) ; `consomme_un_defi_anonyme` les
--    consomme (`delete … returning`) ; `purge_defis_anonymes` efface les échus chaque heure (la table ne gonfle pas, même avec
--    des /64 IPv6 qui tournent).
--  - `login_throttle.scope` accepte `cle_ip` (les vérifications de signature d'une IP : 20 par 15 min, attente jusqu'à 1 h) et
--    `cle_defi_ip` (les défis qu'une IP demande : sans escalade, une page de connexion en demande un à chaque chargement).
--    `prend_un_creneau_de_cle` les prend.
--  - `cle_pour_connexion` : la clé par son identifiant ; PREND le verrou de personne puis relit la ligne `for update` (la
--    clé lue est celle que la vérification utilisera), et ne rend rien si la clé est inconnue ou la personne ne peut pas entrer
--    (`personne_peut_entrer`, A1) : un refus, jamais une exception.
--  - `ouvre_une_session_par_cle` : sous le même verrou (réentrant), RELIT la clé (compteur inchangé depuis la lecture, compteur
--    qui croît, ou deux zéros), met à jour compteur, `backup_state`, `uv_initialized`, `last_used_at`, ouvre la session
--    `opened_with = 'cle'` (qui révoque la session présentée, B22) et écrit `connexion_par_cle`. Ne rend rien si l'un des
--    contrôles échoue : le compteur reste, aucune session ne naît.
--    ORDRE DES VERROUS : (limites,) personne, la session présentée, puis auth.users en `key share`, puis la clé. Un
--    refus est un résultat ; une erreur annule tout (le défi, consommé dans la même transaction, redevient valable).
--  - `security_event.kind` accepte `connexion_par_cle` et `cle_suspecte`.
--
-- DROITS : `popote_api` seul exécute les fonctions publiques ; `private` n'est ouvert à aucun rôle.
--
-- COMPATIBLE avec l'appli en ligne : une colonne nulle, des fonctions neuves, trois CHECK élargis (aucune valeur retirée) ; la
-- contrainte de but de `webauthn_challenge` ne touche que des tables de 0.4bis.
--
-- RETOUR ARRIÈRE (perd les sessions ouvertes par clé et les défis de connexion en vol : la personne se reconnecte par code).
-- Le SQL entre les deux repères s'exécute tel quel, une fois les « -- » retirés (rejoué sur la base locale) :
-- >>> retour arrière
--   select cron.unschedule(jobid) from cron.job where jobname = 'webauthn-defis-anonymes-purge';   -- si pg_cron est là
--   drop function public.ouvre_une_session_par_cle(uuid, bigint, bigint, boolean, boolean, bytea, text, text, bytea, text);
--   drop function private.ouvre_une_session_par_cle(uuid, bigint, bigint, boolean, boolean, bytea, text, text, bytea,
--     timestamptz, text);
--   drop function public.cle_pour_connexion(bytea, bytea);
--   drop function private.cle_pour_connexion(bytea, bytea, timestamptz);
--   drop function public.prend_un_creneau_de_cle(text, bytea, integer, integer, integer);
--   drop function public.consomme_un_defi_anonyme(bytea);
--   drop function private.consomme_un_defi_anonyme(bytea, timestamptz);
--   drop function public.cree_un_defi_anonyme(bytea, integer);
--   drop function private.cree_un_defi_anonyme(bytea, integer, timestamptz);
--   drop function private.purge_defis_anonymes(timestamptz, integer);
--   update public.login_session set revoked_at = coalesce(revoked_at, now()) where opened_with = 'cle';
--   alter table public.login_session drop column opened_with_credential;
--   delete from public.webauthn_challenge where purpose = 'authentication';
--   drop index public.webauthn_challenge_anonyme_idx;
--   alter table public.webauthn_challenge drop constraint webauthn_challenge_but_check;
--   alter table public.webauthn_challenge alter column person_id set not null, alter column session_id set not null,
--     add constraint webauthn_challenge_purpose_check check (purpose in ('registration'));
--   delete from public.login_throttle where scope in ('cle_ip', 'cle_defi_ip');
--   alter table public.login_throttle drop constraint login_throttle_scope_check, add constraint
--     login_throttle_scope_check check (scope in (
--       'account', 'ip', 'reset', 'invitation_ip', 'invitation_link',
--       'code_ip', 'code_paire', 'code_compte', 'mail_global', 'couple', 'compte_entier'));
--   delete from public.security_event where kind in ('connexion_par_cle', 'cle_suspecte');
--   alter table public.security_event drop constraint security_event_kind_check, add constraint
--     security_event_kind_check check (kind in (
--       'connexion_reussie', 'connexion_ratee', 'connexion_bloquee', 'deconnexion',
--       'reauthentification_reussie', 'reauthentification_ratee', 'session_fermee',
--       'mot_de_passe_change', 'reinitialisation_demandee', 'reinitialisation_utilisee',
--       'invitation_creee', 'invitation_acceptee', 'invitation_revoquee',
--       'compte_supprime', 'compte_repris', 'verification_fuites_indisponible',
--       'code_demande', 'connexion_par_code', 'cle_ajoutee'));
-- <<< retour arrière
-- ═══════════════════════════════════════════════════════════════════════════
set local lock_timeout = '5s';
set local statement_timeout = '30s';

-- ── 1. Trois CHECK élargis, une colonne ─────────────────────────────────────
alter table public.security_event
  drop constraint security_event_kind_check,
  add constraint security_event_kind_check check (kind in (
    'connexion_reussie', 'connexion_ratee', 'connexion_bloquee', 'deconnexion',
    'reauthentification_reussie', 'reauthentification_ratee', 'session_fermee',
    'mot_de_passe_change', 'reinitialisation_demandee', 'reinitialisation_utilisee',
    'invitation_creee', 'invitation_acceptee', 'invitation_revoquee',
    'compte_supprime', 'compte_repris', 'verification_fuites_indisponible',
    'code_demande', 'connexion_par_code', 'cle_ajoutee', 'connexion_par_cle', 'cle_suspecte')) not valid;
alter table public.security_event validate constraint security_event_kind_check;

alter table public.login_throttle
  drop constraint login_throttle_scope_check,
  add constraint login_throttle_scope_check check (scope in (
    'account', 'ip', 'reset', 'invitation_ip', 'invitation_link',
    'code_ip', 'code_paire', 'code_compte', 'mail_global',
    'couple', 'compte_entier', 'cle_ip', 'cle_defi_ip')) not valid;
alter table public.login_throttle validate constraint login_throttle_scope_check;

-- Sans clé étrangère, volontairement : voir l'en-tête.
alter table public.login_session add column opened_with_credential uuid;
comment on column public.login_session.opened_with_credential is
  'La clé d''accès (webauthn_credential.id) qui a ouvert la session, sinon nul. Sans clé étrangère : supprimer la clé ferme ses sessions (S10).';
create index login_session_opened_with_credential_idx on public.login_session (opened_with_credential)
  where opened_with_credential is not null;

-- ── 2. Le défi de connexion : sans personne ni session ──────────────────────
alter table public.webauthn_challenge
  drop constraint webauthn_challenge_purpose_check,
  alter column person_id drop not null,
  alter column session_id drop not null,
  add constraint webauthn_challenge_but_check check (
    (purpose = 'registration' and person_id is not null and session_id is not null)
    or (purpose = 'authentication' and person_id is null and session_id is null));
create index webauthn_challenge_anonyme_idx on public.webauthn_challenge (expires_at)
  where purpose = 'authentication';

/* Le défi d'une cérémonie de connexion. `p_plafond` : le nombre de défis anonymes vivants au-delà duquel on refuse (rend
   `trop_de_defis`) ; un dépassement de quelques unités par des demandes simultanées est accepté. Rend `creee`. */
create or replace function private.cree_un_defi_anonyme(p_defi bytea, p_plafond integer, p_now timestamptz)
returns text
language plpgsql
volatile
security definer
set search_path = ''
as $$
begin
  if p_defi is null or pg_catalog.octet_length(p_defi) <> 32 or p_now is null
     or p_plafond is null or p_plafond not between 1 and 1000000 then
    raise exception 'Paramètres invalides.' using errcode = 'invalid_parameter_value';
  end if;
  if (select pg_catalog.count(*) from public.webauthn_challenge c
       where c.purpose = 'authentication' and c.expires_at > p_now) >= p_plafond then
    return 'trop_de_defis';
  end if;
  insert into public.webauthn_challenge (challenge, purpose, person_id, session_id, created_at, expires_at)
  values (p_defi, 'authentication', null, null, p_now, p_now + interval '10 minutes');
  return 'creee';
end;
$$;
comment on function private.cree_un_defi_anonyme(bytea, integer, timestamptz) is
  'Variante à horloge de public.cree_un_defi_anonyme. Interne (tests).';
revoke all on function private.cree_un_defi_anonyme(bytea, integer, timestamptz)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

create or replace function public.cree_un_defi_anonyme(p_defi bytea, p_plafond integer)
returns text
language sql
volatile
security definer
set search_path = ''
as $$
  select private.cree_un_defi_anonyme(p_defi, p_plafond, pg_catalog.now());
$$;
comment on function public.cree_un_defi_anonyme(bytea, integer) is
  'Garde le défi d''une connexion par clé (sans personne, 10 minutes) ; rend creee ou trop_de_defis (plafond de défis vivants). popote_api seul.';
revoke all on function public.cree_un_defi_anonyme(bytea, integer)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.cree_un_defi_anonyme(bytea, integer) to popote_api;

/* `delete … returning` : un défi ne sert qu'une fois, même pour deux requêtes parallèles (la seconde attend la ligne puis ne la
   trouve plus). Un défi d'enregistrement, échu ou inconnu n'est NI rendu NI brûlé. Une taille autre que 32 octets rend nul, sans
   lever : le défi vient du corps d'une requête anonyme. */
create or replace function private.consomme_un_defi_anonyme(p_defi bytea, p_now timestamptz)
returns bytea
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_defi bytea;
begin
  if p_now is null then
    raise exception 'Paramètres invalides.' using errcode = 'invalid_parameter_value';
  end if;
  if p_defi is null or pg_catalog.octet_length(p_defi) <> 32 then
    return null;
  end if;
  delete from public.webauthn_challenge c
   where c.challenge = p_defi and c.purpose = 'authentication' and c.expires_at > p_now
  returning c.challenge into v_defi;
  return v_defi;
end;
$$;
comment on function private.consomme_un_defi_anonyme(bytea, timestamptz) is
  'Variante à horloge de public.consomme_un_defi_anonyme. Interne (tests).';
revoke all on function private.consomme_un_defi_anonyme(bytea, timestamptz)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

create or replace function public.consomme_un_defi_anonyme(p_defi bytea)
returns bytea
language sql
volatile
security definer
set search_path = ''
as $$
  select private.consomme_un_defi_anonyme(p_defi, pg_catalog.now());
$$;
comment on function public.consomme_un_defi_anonyme(bytea) is
  'Consomme le défi d''une connexion par clé (à usage unique, 10 minutes) et le rend ; nul sinon. popote_api seul.';
revoke all on function public.consomme_un_defi_anonyme(bytea)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.consomme_un_defi_anonyme(bytea) to popote_api;

-- ── 3. Les créneaux d'une IP ────────────────────────────────────────────────
/* `cle_ip` escalade (jusqu'au plafond donné) ; `cle_defi_ip` ne fait qu'attendre la fin de la fenêtre. La clé est l'empreinte
   HMAC de l'IP (`Empreintes.cle_ip_requise`), jamais l'IP. */
create or replace function public.prend_un_creneau_de_cle(
  p_scope text, p_key bytea, p_limit integer, p_window_s integer, p_max_block_s integer
) returns table (attente_s integer, nouveau_blocage boolean)
language plpgsql
volatile
security definer
set search_path = ''
as $$
begin
  if p_scope is null or p_scope not in ('cle_ip', 'cle_defi_ip') then
    raise exception 'Limite inconnue.' using errcode = 'invalid_parameter_value';
  end if;
  return query select * from private.prend_un_creneau(
    p_scope, p_key, p_limit, p_window_s, p_max_block_s, p_scope = 'cle_ip', pg_catalog.now());
end;
$$;
comment on function public.prend_un_creneau_de_cle(text, bytea, integer, integer, integer) is
  'Prend un créneau de connexion par clé pour une IP (cle_ip : vérifications, avec escalade ; cle_defi_ip : défis, sans). popote_api seul.';
revoke all on function public.prend_un_creneau_de_cle(text, bytea, integer, integer, integer)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.prend_un_creneau_de_cle(text, bytea, integer, integer, integer) to popote_api;

-- ── 4. La clé de la connexion : lue sous le verrou de personne ──────────────
/* La personne se lit sans verrou (une clé ne change jamais de personne), on prend son verrou (et celui de la session présentée),
   puis la ligne `for update` : une suppression de la clé ou une fermeture des sessions qui précède se voit. L'ordre de
   `ouvre_une_session_par_code` : session présentée, puis `auth.users` en `key share` (une suppression de compte tient le compte
   puis efface ses lignes en cascade), puis les lignes. Rien n'est rendu pour une clé inconnue, une personne qui ne peut pas entrer
   ou une personne sans identifiant d'utilisateur : le même résultat vide. */
create or replace function private.cle_pour_connexion(p_credential_id bytea, p_old_hash bytea, p_now timestamptz)
returns table (
  personne uuid, cle uuid, compteur bigint, cle_publique bytea, peut_etre_sauvegardee boolean,
  identifiant_utilisateur bytea
)
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_personne uuid;
begin
  if p_credential_id is null or pg_catalog.octet_length(p_credential_id) not between 16 and 1023 or p_now is null
     or (p_old_hash is not null and pg_catalog.octet_length(p_old_hash) <> 32) then
    raise exception 'Paramètres invalides.' using errcode = 'invalid_parameter_value';
  end if;

  select k.person_id into v_personne from public.webauthn_credential k where k.credential_id = p_credential_id;
  if not found then
    return;
  end if;

  perform private.verrouille_la_personne(v_personne, p_old_hash, p_now);
  if p_old_hash is not null then
    perform 1 from public.login_session s
     where s.token_hash = p_old_hash and s.revoked_at is null
       and s.expires_at > p_now and s.absolute_expires_at > p_now
       for update;
  end if;
  perform 1 from auth.users u where u.id = v_personne for key share;

  if not private.personne_peut_entrer(v_personne) then
    return;
  end if;
  return query
    select k.person_id, k.id, k.sign_count, k.public_key, k.backup_eligible, h.user_handle
      from public.webauthn_credential k
      join public.webauthn_user h on h.person_id = k.person_id
     where k.credential_id = p_credential_id and k.person_id = v_personne
       for update of k;
end;
$$;
comment on function private.cle_pour_connexion(bytea, bytea, timestamptz) is
  'Variante à horloge de public.cle_pour_connexion. Interne (tests).';
revoke all on function private.cle_pour_connexion(bytea, bytea, timestamptz)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

create or replace function public.cle_pour_connexion(p_credential_id bytea, p_old_hash bytea default null)
returns table (
  personne uuid, cle uuid, compteur bigint, cle_publique bytea, peut_etre_sauvegardee boolean,
  identifiant_utilisateur bytea
)
language sql
volatile
security definer
set search_path = ''
as $$
  select * from private.cle_pour_connexion(p_credential_id, p_old_hash, pg_catalog.now());
$$;
comment on function public.cle_pour_connexion(bytea, bytea) is
  'La clé de cet identifiant, pour vérifier une assertion : prend le verrou de la personne (et celui de la session présentée) puis relit la clé `for update` ; rien si la clé est inconnue ou la personne ne peut pas entrer. popote_api seul.';
revoke all on function public.cle_pour_connexion(bytea, bytea)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.cle_pour_connexion(bytea, bytea) to popote_api;

-- ── 5. Ouvrir la session de la clé ──────────────────────────────────────────
/* Appelée APRÈS `cle_pour_connexion` et la vérification de la signature, dans la même transaction : le verrou de la personne est
   tenu, la ligne de la clé aussi. Ne rend rien (la transaction se valide, rien n'est écrit) si : la clé a disparu, son compteur
   n'est plus `p_compteur_ancien`, le nouveau compteur ne croît pas (deux zéros admis), l'état de sauvegarde dépasse l'éligibilité,
   ou la personne ne peut plus entrer. */
create or replace function private.ouvre_une_session_par_cle(
  p_cle uuid,
  p_compteur_ancien bigint,
  p_compteur bigint,
  p_backup_state boolean,
  p_uv boolean,
  p_hash bytea,
  p_browser text,
  p_os text,
  p_old_hash bytea,
  p_now timestamptz,
  p_request_id text default null
) returns table (session uuid, personne uuid)
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_personne uuid;
  v_ligne public.webauthn_credential%rowtype;
  v_session uuid;
begin
  if p_cle is null or p_compteur_ancien is null or p_compteur is null or p_backup_state is null or p_uv is null
     or p_hash is null or p_now is null or pg_catalog.octet_length(p_hash) <> 32
     or p_compteur not between 0 and 4294967295
     or (p_request_id is not null and p_request_id !~ '^[0-9a-f]{32}$') then
    raise exception 'Paramètres invalides.' using errcode = 'invalid_parameter_value';
  end if;

  select k.person_id into v_personne from public.webauthn_credential k where k.id = p_cle;
  if not found then
    return;
  end if;
  perform private.verrouille_la_personne(v_personne, p_old_hash, p_now);
  -- Même ordre que `cle_pour_connexion` et 0149 : la session présentée AVANT `auth.users` (réentrant, sans coût quand
  -- `cle_pour_connexion` l'a déjà prise) ; un appel isolé ne ferait sinon pas le même ordre que `delete_my_account`.
  if p_old_hash is not null then
    perform 1 from public.login_session s
     where s.token_hash = p_old_hash and s.revoked_at is null
       and s.expires_at > p_now and s.absolute_expires_at > p_now
       for update;
  end if;
  perform 1 from auth.users u where u.id = v_personne for key share;

  select * into v_ligne from public.webauthn_credential k where k.id = p_cle and k.person_id = v_personne for update;
  if not found or v_ligne.sign_count <> p_compteur_ancien
     or not ((p_compteur > 0 or v_ligne.sign_count > 0) and p_compteur > v_ligne.sign_count
             or (p_compteur = 0 and v_ligne.sign_count = 0))
     or (p_backup_state and not v_ligne.backup_eligible)
     or not private.personne_peut_entrer(v_personne) then
    return;
  end if;

  update public.webauthn_credential k
     set sign_count = p_compteur, backup_state = p_backup_state, uv_initialized = k.uv_initialized or p_uv,
         last_used_at = p_now
   where k.id = p_cle;
  v_session := private.ouvre_la_session(v_personne, p_hash, p_browser, p_os, p_old_hash, 'cle', p_now);
  update public.login_session s set opened_with_credential = p_cle where s.id = v_session;
  perform private.ecrit_evenement('connexion_par_cle', v_personne, v_session, null, null, null, p_request_id);
  return query select v_session, v_personne;
end;
$$;
comment on function private.ouvre_une_session_par_cle(
  uuid, bigint, bigint, boolean, boolean, bytea, text, text, bytea, timestamptz, text) is
  'Variante à horloge de public.ouvre_une_session_par_cle. Interne (tests).';
revoke all on function private.ouvre_une_session_par_cle(
  uuid, bigint, bigint, boolean, boolean, bytea, text, text, bytea, timestamptz, text)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

create or replace function public.ouvre_une_session_par_cle(
  p_cle uuid,
  p_compteur_ancien bigint,
  p_compteur bigint,
  p_backup_state boolean,
  p_uv boolean,
  p_hash bytea,
  p_browser text default 'autre',
  p_os text default 'autre',
  p_old_hash bytea default null,
  p_request_id text default null
) returns table (session uuid, personne uuid)
language sql
volatile
security definer
set search_path = ''
as $$
  select * from private.ouvre_une_session_par_cle(
    p_cle, p_compteur_ancien, p_compteur, p_backup_state, p_uv, p_hash, p_browser, p_os, p_old_hash,
    pg_catalog.now(), p_request_id);
$$;
comment on function public.ouvre_une_session_par_cle(uuid, bigint, bigint, boolean, boolean, bytea, text, text, bytea, text) is
  'Met à jour la clé (compteur, sauvegarde, dernier usage), ouvre la session née par clé et écrit connexion_par_cle ; à appeler après cle_pour_connexion et la vérification de la signature, dans la même transaction. Rien si un contrôle échoue. popote_api seul.';
revoke all on function public.ouvre_une_session_par_cle(uuid, bigint, bigint, boolean, boolean, bytea, text, text, bytea, text)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.ouvre_une_session_par_cle(uuid, bigint, bigint, boolean, boolean, bytea, text, text, bytea, text)
  to popote_api;

-- ── 6. La purge des défis anonymes échus : chaque heure ─────────────────────
/* Un défi échu ne sert plus (la consommation refuse l'échéance passée) et ne compte plus au plafond : on l'efface vite, par
   lots. La purge de 0153 (échéance + 1 jour) reste, pour les défis d'enregistrement. */
create or replace function private.purge_defis_anonymes(
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
        where c.purpose = 'authentication' and c.expires_at < p_now
        order by c.challenge
        limit p_lot
          for update skip locked);
    get diagnostics v_lot = row_count;
    v_total := v_total + v_lot;
    exit when v_lot < p_lot;
  end loop;
  raise notice 'purge des défis de connexion : % ligne(s) effacee(s)', v_total;
  return v_total;
end;
$$;
comment on function private.purge_defis_anonymes(timestamptz, integer) is
  'Efface les défis de connexion par clé échus, par lots ; rend leur nombre. Lancée chaque heure par pg_cron.';
revoke all on function private.purge_defis_anonymes(timestamptz, integer)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

/* Planification gardée comme 0147 et 0153 : sans `pg_cron`, la migration passe et un avertissement le dit. */
do $$
begin
  if exists (select 1 from pg_extension where extname = 'pg_cron') then
    begin
      execute $q$select cron.schedule('webauthn-defis-anonymes-purge', '17 * * * *', 'select private.purge_defis_anonymes()')$q$;
    exception when others then
      raise warning 'LA PURGE DES DÉFIS DE CONNEXION N''EST PAS PLANIFIÉE : % (job « webauthn-defis-anonymes-purge »).', sqlerrm;
    end;
  else
    raise warning 'LA PURGE DES DÉFIS DE CONNEXION N''EST PAS PLANIFIÉE : pg_cron est absent. Active-le (Database > '
      'Extensions), puis : select cron.schedule(''webauthn-defis-anonymes-purge'', ''17 * * * *'', ''select private.purge_defis_anonymes()'').';
  end if;
end $$;
