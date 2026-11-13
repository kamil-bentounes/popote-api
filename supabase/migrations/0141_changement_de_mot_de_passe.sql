-- ═══════════════════════════════════════════════════════════════════════════
-- 0141 · CHANGER SON MOT DE PASSE : LA ROTATION ET LA FERMETURE DES AUTRES SESSIONS (spec § 4 ; B3, B4, B9, B19)
--
-- `PUT /api/v1/me/password` fait en une transaction, AVANT d'écrire le mot de passe dans Auth :
--  - `public.fait_tourner_et_ferme_les_autres(p_old_hash, p_new_hash)` : change l'empreinte de la session courante
--    (l'ancienne meurt aussitôt : la rotation sert de verrou, un second changement simultané avec l'ancien cookie
--    ne trouve plus de session et rend null), ferme TOUTES les autres sessions de la personne (un événement
--    `session_fermee` chacune) et supprime ses sessions et jetons de renouvellement Supabase Auth (B9).
--    Rend l'identifiant de la session, ou null si l'ancienne empreinte ne désigne aucune session valide.
--  - `private.ferme_les_sessions_auth(p_person)` : la suppression des lignes `auth.sessions` et
--    `auth.refresh_tokens` de la personne (B9) ; la réinitialisation et la suppression de compte (T14, T15) la
--    réutiliseront.
--  - `public.confirme_le_changement_de_mot_de_passe(p_person, p_request_id)` : après le succès d'Auth, `password_set`
--    à vrai (l'ancienne appli en dépend pendant la fenêtre de retour) et l'événement `mot_de_passe_change`.
--
-- DROITS (B3, B19) : seul `popote_api` (contexte connexion) exécute les deux fonctions publiques ; ni `authenticated`,
-- ni `service_role`, ni `popote_internal`. Aucun paramètre d'horloge exécutable : la variante à `p_now` vit dans
-- `private`, fermée à tous.
--
-- COMPATIBLE avec l'appli en ligne : aucune table ni colonne changée ; fonctions nouvelles que l'appli actuelle
-- n'appelle pas ; `password_set` est seulement remis à vrai (valeur qu'elle lit déjà). Les lignes `auth.sessions`
-- ne sont supprimées que par ces fonctions, appelées par la nouvelle API.
--
-- Retour arrière (sans perte) :
--   drop function public.confirme_le_changement_de_mot_de_passe(uuid, text),
--     public.fait_tourner_et_ferme_les_autres(bytea, bytea);
--   drop function private.fait_tourner_et_ferme_les_autres(bytea, bytea, timestamptz),
--     private.ferme_les_sessions_auth(uuid);
-- ═══════════════════════════════════════════════════════════════════════════
set local lock_timeout = '5s';
set local statement_timeout = '30s';

create or replace function private.ferme_les_sessions_auth(p_person uuid)
returns void
language sql
volatile
security definer
set search_path = ''
as $$
  delete from auth.refresh_tokens where user_id = p_person::text;
  delete from auth.sessions where user_id = p_person;
$$;
comment on function private.ferme_les_sessions_auth(uuid) is
  'Supprime les sessions et les jetons de renouvellement Supabase Auth de la personne (B9). Interne : aucun rôle ne l''exécute.';
revoke all on function private.ferme_les_sessions_auth(uuid)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

create or replace function private.fait_tourner_et_ferme_les_autres(p_old_hash bytea, p_new_hash bytea, p_now timestamptz)
returns uuid
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_session uuid;
  v_person uuid;
  v_fermees bigint;
begin
  -- La rotation d'abord : c'est elle qui verrouille la ligne et départage deux changements simultanés.
  update public.login_session s
     set token_hash = p_new_hash
    from auth.users u
   where s.token_hash = p_old_hash
     and u.id = s.person_id
     and s.revoked_at is null and s.expires_at > p_now and s.absolute_expires_at > p_now
     and (u.banned_until is null or u.banned_until <= p_now)
     and u.deleted_at is null
  returning s.id, s.person_id into v_session, v_person;
  if v_session is null then
    return null;
  end if;

  with fermees as (
    update public.login_session s
       set revoked_at = p_now
     where s.person_id = v_person
       and s.id <> v_session
       and s.revoked_at is null
       and s.expires_at > p_now
       and s.absolute_expires_at > p_now
    returning s.id
  )
  select pg_catalog.count(private.ecrit_evenement('session_fermee', v_person, f.id)) into v_fermees
    from fermees f;
  perform private.ferme_les_sessions_auth(v_person);
  return v_session;
end;
$$;
revoke all on function private.fait_tourner_et_ferme_les_autres(bytea, bytea, timestamptz)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

create or replace function public.fait_tourner_et_ferme_les_autres(p_old_hash bytea, p_new_hash bytea)
returns uuid
language sql
volatile
security definer
set search_path = ''
as $$
  select private.fait_tourner_et_ferme_les_autres(p_old_hash, p_new_hash, pg_catalog.now());
$$;
comment on function public.fait_tourner_et_ferme_les_autres(bytea, bytea) is
  'Change l''empreinte de la session courante, ferme les autres sessions de la personne et ses sessions Supabase Auth ; rend l''identifiant de la session, ou null. Exécutable par popote_api seul.';
revoke all on function public.fait_tourner_et_ferme_les_autres(bytea, bytea)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.fait_tourner_et_ferme_les_autres(bytea, bytea) to popote_api;

create or replace function public.confirme_le_changement_de_mot_de_passe(p_person uuid, p_request_id text default null)
returns void
language sql
volatile
security definer
set search_path = ''
as $$
  update public.user_profile set password_set = true where id = p_person and password_set is not true;
  select private.ecrit_evenement('mot_de_passe_change', p_person, null, null, null, null, p_request_id);
$$;
comment on function public.confirme_le_changement_de_mot_de_passe(uuid, text) is
  'Après le succès d''Auth : password_set à vrai et événement mot_de_passe_change. Exécutable par popote_api seul.';
revoke all on function public.confirme_le_changement_de_mot_de_passe(uuid, text)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.confirme_le_changement_de_mot_de_passe(uuid, text) to popote_api;
