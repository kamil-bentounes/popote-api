-- ═══════════════════════════════════════════════════════════════════════════
-- 0155 · LA GESTION DES CLÉS D'ACCÈS ET LES SESSIONS DE LA CLÉ (0.4bis S10 ; spec § 4 « Appareils » ; NIST § 4.2, FIDO)
--
-- La personne voit ses clés (une carte par clé), en renomme une, en supprime une. Supprimer une clé FERME les sessions qu'elle a
-- ouvertes : une clé compromise s'invalide aussitôt. Le numéro est 0155, pas 0152 : le plan est antérieur à S7c, S8b et S9.
--
--  - `public.mes_cles` : les clés de la personne (dix au plus), avec `id`, `name`, `created_at`, `last_used_at`, `device_type`
--    (`multi_device` si la clé peut être synchronisée, `single_device` sinon), `backed_up` et `transports`. JAMAIS la clé
--    publique, l'identifiant de clé ni l'AAGUID : rien qui permette de reconnaître ou de rejouer la clé.
--  - `public.renomme_ma_cle` : rend vrai si la clé est à la personne (faux sinon : une clé d'une autre personne est « inconnue »,
--    jamais révélée) ; refuse un nom vide, blanc, de plus de 40 caractères ou à caractère de contrôle (PostgREST l'expose : le
--    contrôle ne tient pas qu'à Python). Pas de session relue ni de `personne_peut_entrer` : renommer ne donne aucun accès. Pas de verrou de personne : renommer n'ajoute ni ne retire une clé ; une suppression qui précède fait
--    attendre la mise à jour sur la ligne, qui ne trouve alors plus rien.
--  - `public.supprime_ma_cle` : désigne la session par l'EMPREINTE de son cookie (comme 0153), prend le verrou de personne,
--    RELIT la session (non fermée, non échue) et sa preuve (300 s, horloge de la base), ferme les sessions de la clé
--    (`opened_with_credential` = la clé) puis supprime la clé, le tout dans UNE transaction sous le verrou, écrit `session_fermee` par session et `cle_supprimee`. Rend
--    `supprimee` (avec le nombre de sessions fermées et si la session courante en fait partie), `inconnue`, `session_perimee`
--    ou `preuve_perimee`. Un REFUS est un résultat rendu, jamais une exception. Supprimer la dernière clé est permis : le code
--    par mail reste. ORDRE DES VERROUS : (foyer, invitation,) PERSONNE, puis lignes de session, puis la clé.
--    Une connexion par cette clé en vol se croise avec elle sous le même verrou : si la suppression passe d'abord, la connexion
--    ne trouve plus la clé (refusée, aucune session) ; si la connexion passe d'abord, sa session est fermée avec la clé.
--  - `public.mes_appareils` : `mes_sessions` (0140) plus `opened_with` (`code`, `cle`, `invitation`, `autre`). NOM NOUVEAU : changer
--    les colonnes de sortie de `mes_sessions` ne se fait pas par `create or replace`, et le code déjà déployé l'appelle ; elle part
--    avec le reste en S15.
--  - `security_event.kind` accepte `cle_supprimee`.
--
-- DROITS : `authenticated` seul exécute les fonctions publiques ; `private` n'est ouvert à aucun rôle.
--
-- COMPATIBLE avec l'appli en ligne : des fonctions neuves, un CHECK élargi (aucune valeur retirée) ; `mes_sessions` ne bouge pas.
--
-- À FAIRE PAR S14 (suppression du compte) : `efface_mes_donnees` supprime les clés ; les sessions qu'elles ont ouvertes se ferment
-- aussi avec le compte (toutes les sessions de la personne partent). Fermer toutes les sessions ne RETIRE pas les clés : la liste
-- montre `last_used_at` de chacune, on y revoit celles qui servent encore.
--
-- RETOUR ARRIÈRE (sans perte, hors événements `cle_supprimee`). Retirer D'ABORD le code qui appelle `mes_cles` et `mes_appareils`
-- (`GET /me/passkeys`, `GET /me/sessions`). Le SQL entre les deux repères s'exécute tel quel, une fois les « -- » retirés, par un
-- rôle qui contourne la RLS (`postgres` : le `delete` des événements en dépend ; rejoué sur la base locale) :
-- >>> retour arrière
--   drop function public.supprime_ma_cle(bytea, uuid, text);
--   drop function private.supprime_ma_cle(uuid, uuid, uuid, text, timestamptz);
--   drop function public.renomme_ma_cle(uuid, text);
--   drop function public.mes_cles();
--   drop function public.mes_appareils(integer, timestamptz, uuid);
--   delete from public.security_event where kind = 'cle_supprimee';
--   alter table public.security_event drop constraint security_event_kind_check, add constraint
--     security_event_kind_check check (kind in (
--       'connexion_reussie', 'connexion_ratee', 'connexion_bloquee', 'deconnexion',
--       'reauthentification_reussie', 'reauthentification_ratee', 'session_fermee',
--       'mot_de_passe_change', 'reinitialisation_demandee', 'reinitialisation_utilisee',
--       'invitation_creee', 'invitation_acceptee', 'invitation_revoquee',
--       'compte_supprime', 'compte_repris', 'verification_fuites_indisponible',
--       'code_demande', 'connexion_par_code', 'cle_ajoutee', 'connexion_par_cle', 'cle_suspecte'));
-- <<< retour arrière
-- ═══════════════════════════════════════════════════════════════════════════
set local lock_timeout = '5s';
set local statement_timeout = '30s';

-- ── 1. Le journal : `cle_supprimee` ─────────────────────────────────────────
alter table public.security_event
  drop constraint security_event_kind_check,
  add constraint security_event_kind_check check (kind in (
    'connexion_reussie', 'connexion_ratee', 'connexion_bloquee', 'deconnexion',
    'reauthentification_reussie', 'reauthentification_ratee', 'session_fermee',
    'mot_de_passe_change', 'reinitialisation_demandee', 'reinitialisation_utilisee',
    'invitation_creee', 'invitation_acceptee', 'invitation_revoquee',
    'compte_supprime', 'compte_repris', 'verification_fuites_indisponible',
    'code_demande', 'connexion_par_code', 'cle_ajoutee', 'connexion_par_cle', 'cle_suspecte',
    'cle_supprimee')) not valid;
alter table public.security_event validate constraint security_event_kind_check;

-- ── 2. Les appareils : comment chaque session est née ───────────────────────
create or replace function public.mes_appareils(
  p_limit integer default 20, p_after_seen timestamptz default null, p_after_id uuid default null
) returns table (id uuid, browser text, os text, created_at timestamptz, last_seen_at timestamptz, opened_with text)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  v_person uuid := auth.uid();
begin
  if v_person is null then
    raise exception 'Aucune personne dans ce contexte.' using errcode = 'invalid_authorization_specification';
  end if;
  if p_limit is null or p_limit < 1 or p_limit > 101 then
    raise exception 'La taille de page doit valoir de 1 à 101.' using errcode = 'invalid_parameter_value';
  end if;
  return query
  select s.id, s.browser, s.os, s.created_at, s.last_seen_at, s.opened_with
    from public.login_session s
   where s.person_id = v_person
     and s.revoked_at is null
     and s.expires_at > pg_catalog.now()
     and s.absolute_expires_at > pg_catalog.now()
     and (p_after_seen is null or (s.last_seen_at, s.id) < (p_after_seen, p_after_id))
   order by s.last_seen_at desc, s.id desc
   limit p_limit;
end;
$$;
comment on function public.mes_appareils(integer, timestamptz, uuid) is
  'Les sessions actives de la personne du contexte, avec la preuve qui les a ouvertes (opened_with). Exécutable par authenticated seul.';
revoke all on function public.mes_appareils(integer, timestamptz, uuid)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.mes_appareils(integer, timestamptz, uuid) to authenticated;

-- ── 3. Lister et renommer ───────────────────────────────────────────────────
create or replace function public.mes_cles()
returns table (
  id uuid, name text, created_at timestamptz, last_used_at timestamptz,
  device_type text, backed_up boolean, transports text[]
)
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
    select k.id, k.name, k.created_at, k.last_used_at,
           case when k.backup_eligible then 'multi_device' else 'single_device' end,
           k.backup_state, k.transports
      from public.webauthn_credential k
     where k.person_id = auth.uid()
     order by k.created_at, k.id
     limit 10;
end;
$$;
comment on function public.mes_cles() is
  'Les clés de la personne du contexte (dix au plus) : jamais la clé publique, l''identifiant de clé ni l''AAGUID. authenticated seul.';
revoke all on function public.mes_cles()
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.mes_cles() to authenticated;

create or replace function public.renomme_ma_cle(p_id uuid, p_name text)
returns boolean
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_trouvee boolean;
begin
  if auth.uid() is null then
    raise exception 'Aucune personne dans ce contexte.' using errcode = 'invalid_authorization_specification';
  end if;
  if p_id is null or p_name is null or pg_catalog.char_length(p_name) not between 1 and 40
     or p_name !~ '\S' or p_name ~ '[[:cntrl:]]' then
    raise exception 'Paramètres invalides.' using errcode = 'invalid_parameter_value';
  end if;
  update public.webauthn_credential k set name = p_name where k.id = p_id and k.person_id = auth.uid();
  v_trouvee := found;
  return v_trouvee;
end;
$$;
comment on function public.renomme_ma_cle(uuid, text) is
  'Renomme une clé de la personne du contexte ; faux si la clé est inconnue ou à une autre personne. authenticated seul.';
revoke all on function public.renomme_ma_cle(uuid, text)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.renomme_ma_cle(uuid, text) to authenticated;

-- ── 4. Supprimer : les sessions de la clé d'abord, puis la clé ──────────────
create or replace function private.supprime_ma_cle(
  p_person uuid, p_session uuid, p_id uuid, p_request_id text, p_now timestamptz
) returns table (etat text, sessions_fermees integer, courante_fermee boolean)
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_reauth_at timestamptz;
  v_fermees uuid[];
begin
  if p_person is null or p_session is null or p_id is null or p_now is null
     or (p_request_id is not null and p_request_id !~ '^[0-9a-f]{32}$') then
    raise exception 'Paramètres invalides.' using errcode = 'invalid_parameter_value';
  end if;

  perform private.verrouille_la_personne(p_person);

  -- La session se RELIT sous le verrou : une fermeture de toutes les sessions qui précède l'a révoquée.
  select s.reauth_at into v_reauth_at
    from public.login_session s
   where s.id = p_session and s.person_id = p_person and s.revoked_at is null
     and s.expires_at > p_now and s.absolute_expires_at > p_now;
  if not found or not private.personne_peut_entrer(p_person) then
    return query select 'session_perimee'::text, 0, false;
    return;
  end if;
  if v_reauth_at < p_now - interval '300 seconds' then
    return query select 'preuve_perimee'::text, 0, false;
    return;
  end if;
  if not exists (select 1 from public.webauthn_credential k where k.id = p_id and k.person_id = p_person) then
    return query select 'inconnue'::text, 0, false;
    return;
  end if;

  -- Les sessions de la clé, puis la clé. `opened_with_credential` n'a pas de clé étrangère : le lien survit à la clé, mais seul le
  -- verrou et l'unique transaction garantissent qu'aucune session de la clé ne naît entre la fermeture et la suppression.
  with fermees as (
    update public.login_session s set revoked_at = p_now
     where s.person_id = p_person and s.opened_with_credential = p_id and s.revoked_at is null
       and s.expires_at > p_now and s.absolute_expires_at > p_now
    returning s.id)
  select coalesce(pg_catalog.array_agg(f.id), '{}') into v_fermees from fermees f;
  perform private.ecrit_evenement('session_fermee', p_person, f.id, null, null, null, p_request_id)
     from pg_catalog.unnest(v_fermees) as f(id);
  delete from public.webauthn_credential k where k.id = p_id and k.person_id = p_person;
  perform private.ecrit_evenement('cle_supprimee', p_person, p_session, null, null, null, p_request_id);
  return query select 'supprimee'::text, pg_catalog.cardinality(v_fermees), p_session = any (v_fermees);
end;
$$;
comment on function private.supprime_ma_cle(uuid, uuid, uuid, text, timestamptz) is
  'Variante à horloge de public.supprime_ma_cle. Interne (tests).';
revoke all on function private.supprime_ma_cle(uuid, uuid, uuid, text, timestamptz)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

create or replace function public.supprime_ma_cle(p_token_hash bytea, p_id uuid, p_request_id text default null)
returns table (etat text, sessions_fermees integer, courante_fermee boolean)
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_session uuid;
begin
  if auth.uid() is null then
    raise exception 'Aucune personne dans ce contexte.' using errcode = 'invalid_authorization_specification';
  end if;
  v_session := private.session_du_jeton(auth.uid(), p_token_hash);
  if v_session is null then
    return query select 'session_perimee'::text, 0, false;
    return;
  end if;
  return query select * from private.supprime_ma_cle(auth.uid(), v_session, p_id, p_request_id, pg_catalog.now());
end;
$$;
comment on function public.supprime_ma_cle(bytea, uuid, text) is
  'Supprime une clé de la personne du contexte, sous son verrou, la session de ce cookie et sa preuve (300 s) relues en base, et ferme les sessions que la clé a ouvertes ; rend supprimee, inconnue, session_perimee ou preuve_perimee. authenticated seul.';
revoke all on function public.supprime_ma_cle(bytea, uuid, text)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.supprime_ma_cle(bytea, uuid, text) to authenticated;
