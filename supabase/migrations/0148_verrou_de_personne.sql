-- ═══════════════════════════════════════════════════════════════════════════
-- 0148 · LE VERROU DE PERSONNE ET LA FERMETURE DES SESSIONS (0.4bis S6 ; spec § 4 ; leçon 1, A2)
--
-- Une connexion en vol survit à la fermeture de toutes les sessions quand la preuve et la session qu'elle ouvre sont
-- deux instructions sans verrou commun (relevé de la revue de T15b ; même défaut dans le changement de mot de passe,
-- 0141). On pose le verrou UNE fois ; S7, S9, S10 et S14 s'en servent.
--
--  - `private.verrouille_la_personne` : le verrou de transaction de `cree_session` (0139), même clé
--    `hashtextextended(personne::text, 0)`, nommé ; `public.verrouille_la_personne` : le chemin Python des preuves
--    (`popote_api`, `service_role`).
--  - ORDRE DES VERROUS, partout : FOYER, puis PERSONNE, puis LIGNES (session, code, clé). Tout code qui ouvre une
--    session, en ferme plusieurs, révoque ou consomme un code, ajoute ou retire une clé ou supprime un compte prend
--    d'abord `verrouille_la_personne`. `cree_session`, `ferme_les_autres_sessions` (qui révoque aussi les codes en
--    attente), `ferme_les_autres_appareils` (idem), `fait_tourner_et_ferme_les_autres` et
--    `confirme_le_changement_de_mot_de_passe` la prennent EN PREMIER, avant toute ligne.
--  - L'ACTIVITÉ d'une session (A2). `private.session_valide` écrivait `last_seen_at` en tenant la ligne jusqu'à la fin
--    de la requête, donc AVANT que la route prenne la personne ou le foyer : deux onglets d'un même navigateur
--    s'interbloquent (`40P01`), et l'ordre foyer, personne serait inversé. Désormais l'API LIT la session sans écrire
--    ni verrouiller (`lit_la_session`, qui dit si l'activité a plus de 5 minutes), et l'écrit, quand il le faut, par
--    `note_l_activite_de_la_session` dans une transaction courte validée AVANT celle de la route : la personne,
--    puis la ligne, et rien n'est gardé. `session_valide` (que `session_courante` et `session_personne` appellent
--    encore) n'est pas touchée : l'API ne l'appelle plus, elle ne sert qu'au code déjà déployé.
--
-- DROITS : `popote_api` (et `service_role` pour les deux lectures et le verrou) ; jamais `authenticated`, jamais
-- `popote_internal`. Les variantes à horloge (`p_now`) vivent dans `private`, fermées à tous.
--
-- COMPATIBLE avec l'appli en ligne : cinq fonctions de 0.4 redéfinies à signature égale (rien de ce que la prod appelle),
-- six fonctions neuves ; `session_courante` et `session_personne` gardent leur sens. Le code déjà déployé tourne sur
-- cette migration jusqu'au déploiement : il lit encore par `session_courante`, inchangée.
--
-- RETOUR ARRIÈRE (sans perte : aucune donnée ne change de forme). Recréer les cinq fonctions comme les migrations 0139, 0140
-- et 0141 les définissent (leur `create or replace`, recopiés ci-dessous), PUIS retirer les six fonctions neuves :
--   create or replace function private.cree_session(
--     p_person uuid, p_hash bytea, p_browser text, p_os text, p_old_hash bytea, p_now timestamptz
--   ) returns uuid
--   language plpgsql
--   volatile
--   security definer
--   set search_path = ''
--   as $$
--   declare
--     v_id uuid;
--     v_ancienne public.login_session%rowtype;
--   begin
--     -- Sérialise les créations d'une même personne : sans cela deux connexions simultanées compteraient 9 sessions
--     -- chacune et en laisseraient 11.
--     perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(p_person::text, 0));
--
--     -- Pas de session pour une personne bannie ou supprimée : elle mourrait à la première lecture, autant refuser ici.
--     if exists (select 1 from auth.users u
--                 where u.id = p_person and (u.deleted_at is not null or u.banned_until > p_now)) then
--       raise exception 'Cette personne ne peut pas ouvrir de session.' using errcode = 'invalid_authorization_specification';
--     end if;
--
--     -- La session présentée (B22) : révoquée, journalisée ; une empreinte inconnue ou déjà morte est ignorée.
--     if p_old_hash is not null then
--       update public.login_session
--          set revoked_at = p_now
--        where token_hash = p_old_hash and revoked_at is null
--          and expires_at > p_now and absolute_expires_at > p_now
--       returning * into v_ancienne;
--       if found then
--         perform private.ecrit_evenement('session_fermee', v_ancienne.person_id, v_ancienne.id);
--       end if;
--     end if;
--
--     -- Au plus 10 sessions actives, la nouvelle comprise : on ferme les plus anciennes par dernière activité.
--     update public.login_session
--        set revoked_at = p_now
--      where id in (
--        select id from public.login_session
--         where person_id = p_person and revoked_at is null and expires_at > p_now and absolute_expires_at > p_now
--         order by last_seen_at desc, created_at desc, id desc
--         offset 9);
--
--     insert into public.login_session
--       (token_hash, person_id, browser, os, created_at, last_seen_at, expires_at, absolute_expires_at, reauth_at)
--     values
--       (p_hash, p_person, p_browser, p_os, p_now, p_now, p_now + interval '30 days', p_now + interval '90 days', p_now)
--     returning id into v_id;
--     return v_id;
--   end;
--   $$;
--
--   create or replace function private.ferme_les_autres_sessions(p_person uuid, p_keep uuid, p_now timestamptz)
--   returns void
--   language plpgsql
--   volatile
--   security definer
--   set search_path = ''
--   as $$
--   declare
--     v_fermees bigint;
--   begin
--     with fermees as (
--       update public.login_session s
--          set revoked_at = p_now
--        where s.person_id = p_person
--          and s.id <> p_keep
--          and s.revoked_at is null
--          and s.expires_at > p_now
--          and s.absolute_expires_at > p_now
--       returning s.id
--     )
--     select pg_catalog.count(private.ecrit_evenement('session_fermee', p_person, f.id)) into v_fermees
--       from fermees f;
--     perform private.ferme_les_sessions_auth(p_person);
--   end;
--   $$;
--
--   create or replace function private.fait_tourner_et_ferme_les_autres(p_old_hash bytea, p_new_hash bytea, p_now timestamptz)
--   returns uuid
--   language plpgsql
--   volatile
--   security definer
--   set search_path = ''
--   as $$
--   declare
--     v_session uuid;
--     v_person uuid;
--   begin
--     -- La rotation d'abord : c'est elle qui verrouille la ligne et départage deux changements simultanés.
--     update public.login_session s
--        set token_hash = p_new_hash
--       from auth.users u
--      where s.token_hash = p_old_hash
--        and u.id = s.person_id
--        and s.revoked_at is null and s.expires_at > p_now and s.absolute_expires_at > p_now
--        and (u.banned_until is null or u.banned_until <= p_now)
--        and u.deleted_at is null
--     returning s.id, s.person_id into v_session, v_person;
--     if v_session is null then
--       return null;
--     end if;
--
--     perform private.ferme_les_autres_sessions(v_person, v_session, p_now);
--     return v_session;
--   end;
--   $$;
--
--   create or replace function public.confirme_le_changement_de_mot_de_passe(
--     p_person uuid, p_session uuid, p_request_id text default null
--   )
--   returns void
--   language sql
--   volatile
--   security definer
--   set search_path = ''
--   as $$
--     update public.user_profile set password_set = true where id = p_person and password_set is not true;
--     select private.ecrit_evenement('mot_de_passe_change', p_person, null, null, null, null, p_request_id);
--     select private.ferme_les_autres_sessions(p_person, p_session, pg_catalog.now());
--   $$;
--
--   create or replace function public.ferme_les_autres_appareils(p_courante uuid)
--   returns integer
--   language plpgsql
--   volatile
--   security definer
--   set search_path = ''
--   as $$
--   declare
--     v_person uuid := auth.uid();
--     v_nombre integer;
--   begin
--     if v_person is null then
--       raise exception 'Aucune personne dans ce contexte.' using errcode = 'invalid_authorization_specification';
--     end if;
--     if p_courante is null then
--       raise exception 'La session à garder est obligatoire.' using errcode = 'invalid_parameter_value';
--     end if;
--     with fermees as (
--       update public.login_session s
--          set revoked_at = pg_catalog.now()
--        where s.person_id = v_person
--          and s.id <> p_courante
--          and s.revoked_at is null
--          and s.expires_at > pg_catalog.now()
--          and s.absolute_expires_at > pg_catalog.now()
--       returning s.id
--     ), evenements as (
--       select private.ecrit_evenement('session_fermee', v_person, f.id) from fermees f
--     )
--     select pg_catalog.count(*) into v_nombre from evenements;
--     return v_nombre;
--   end;
--   $$;
--
--   drop function public.verrouille_la_personne(uuid);
--   drop function public.lit_la_session(bytea);
--   drop function public.note_l_activite_de_la_session(bytea);
--   drop function private.note_l_activite_de_la_session(bytea, timestamptz);
--   drop function private.lit_la_session(bytea, timestamptz);
--   drop function private.verrouille_la_personne(uuid);
-- ═══════════════════════════════════════════════════════════════════════════
set local lock_timeout = '5s';
set local statement_timeout = '30s';

-- ── 1. Le verrou de personne ────────────────────────────────────────────────
/* La clé est celle que `cree_session` posait en ligne (0139) : le même verrou consultatif de transaction, donc
   une seule file par personne pour tout ce qui ouvre ou ferme ses sessions. Une personne nulle ne verrouillerait
   RIEN (`hashtextextended(null)` est nul) : refusée. */
create or replace function private.verrouille_la_personne(p_person uuid)
returns void
language plpgsql
volatile
security invoker
set search_path = ''
as $$
begin
  if p_person is null then
    raise exception 'Une personne est obligatoire pour la verrouiller.' using errcode = 'invalid_parameter_value';
  end if;
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(p_person::text, 0));
end;
$$;
comment on function private.verrouille_la_personne(uuid) is
  'Le verrou de transaction d''une personne : ouvrir une session, en fermer plusieurs, révoquer ou consommer un code, ajouter ou retirer une clé, supprimer le compte. Ordre des verrous : foyer, puis personne, puis lignes. Interne.';
revoke all on function private.verrouille_la_personne(uuid)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

create or replace function public.verrouille_la_personne(p_person uuid)
returns void
language sql
volatile
security definer
set search_path = ''
as $$
  select private.verrouille_la_personne(p_person);
$$;
comment on function public.verrouille_la_personne(uuid) is
  'Prend le verrou de transaction d''une personne (le chemin Python des preuves). popote_api et service_role seulement.';
revoke all on function public.verrouille_la_personne(uuid)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.verrouille_la_personne(uuid) to popote_api, service_role;

-- ── 2. L'activité d'une session : lue sans écrire, écrite en sa propre transaction ──────────────
/* Pourquoi deux fonctions. Lire une session ne doit tenir AUCUN verrou de ligne : `session_valide` (0139) met
   `last_seen_at` à jour quand il a plus de 5 minutes, et la ligne reste verrouillée jusqu'à la fin de la requête,
   donc avant que la route prenne le verrou de la personne ou du foyer (ordre inversé : deux onglets d'un même
   navigateur s'interbloquent, `40P01`). `lit_la_session` ne fait que lire et dit si l'activité est périmée ;
   l'API l'écrit alors par `note_l_activite_de_la_session`, dans une transaction courte validée AVANT celle de la
   route : elle prend la personne, puis la ligne, et ne garde rien. */
create or replace function private.lit_la_session(p_hash bytea, p_now timestamptz)
returns table (person_id uuid, session_id uuid, reauth_at timestamptz, activite_perimee boolean)
language sql
stable
security definer
set search_path = ''
as $$
  select s.person_id, s.id, s.reauth_at, s.last_seen_at <= p_now - interval '5 minutes'
    from public.login_session s
    join auth.users u on u.id = s.person_id
   where s.token_hash = p_hash
     and s.revoked_at is null
     and s.expires_at > p_now
     and s.absolute_expires_at > p_now
     and (u.banned_until is null or u.banned_until <= p_now)
     and u.deleted_at is null;
$$;
comment on function private.lit_la_session(bytea, timestamptz) is
  'La règle de lecture d''une session SANS écriture ni verrou de ligne (même règle que session_valide) ; dit si l''activité a plus de 5 minutes. Interne.';
revoke all on function private.lit_la_session(bytea, timestamptz)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

create or replace function public.lit_la_session(p_hash bytea)
returns table (person_id uuid, session_id uuid, reauth_at timestamptz, activite_perimee boolean)
language sql
stable
security definer
set search_path = ''
as $$
  select * from private.lit_la_session(p_hash, pg_catalog.now());
$$;
comment on function public.lit_la_session(bytea) is
  'La personne, la session, reauth_at et « activité périmée » de ce jeton, ou aucune ligne ; n''écrit rien et ne verrouille rien. popote_api et service_role seulement.';
revoke all on function public.lit_la_session(bytea)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.lit_la_session(bytea) to popote_api, service_role;

create or replace function private.note_l_activite_de_la_session(p_hash bytea, p_now timestamptz)
returns boolean
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_person uuid;
  v_notee boolean;
begin
  -- Sans verrou : on ne sait pas encore s'il y a quelque chose à écrire, ni pour qui.
  select s.person_id into v_person
    from public.login_session s
    join auth.users u on u.id = s.person_id
   where s.token_hash = p_hash
     and s.revoked_at is null and s.expires_at > p_now and s.absolute_expires_at > p_now
     and s.last_seen_at <= p_now - interval '5 minutes'
     and (u.banned_until is null or u.banned_until <= p_now) and u.deleted_at is null;
  if v_person is null then
    return false;
  end if;
  -- La personne d'abord, la ligne ensuite : l'ordre de `cree_session`.
  perform private.verrouille_la_personne(v_person);
  -- Les conditions se relisent sous le verrou : une session fermée entre-temps n'est pas rouverte.
  with notee as (
    update public.login_session s
       set last_seen_at = p_now,
           expires_at = least(p_now + interval '30 days', s.absolute_expires_at)
      from auth.users u
     where s.token_hash = p_hash and u.id = s.person_id
       and s.revoked_at is null and s.expires_at > p_now and s.absolute_expires_at > p_now
       and s.last_seen_at <= p_now - interval '5 minutes'
       and (u.banned_until is null or u.banned_until <= p_now) and u.deleted_at is null
    returning 1)
  select exists (select 1 from notee) into v_notee;
  return v_notee;
end;
$$;
comment on function private.note_l_activite_de_la_session(bytea, timestamptz) is
  'Repousse l''activité d''une session vue depuis plus de 5 minutes, sous le verrou de sa personne. Variante à horloge. Interne.';
revoke all on function private.note_l_activite_de_la_session(bytea, timestamptz)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

create or replace function public.note_l_activite_de_la_session(p_hash bytea)
returns boolean
language sql
volatile
security definer
set search_path = ''
as $$
  select private.note_l_activite_de_la_session(p_hash, pg_catalog.now());
$$;
comment on function public.note_l_activite_de_la_session(bytea) is
  'Écrit l''activité d''une session vue depuis plus de 5 minutes (vrai), sinon ne fait rien (faux). À valider seule, avant la transaction de la route. popote_api seul.';
revoke all on function public.note_l_activite_de_la_session(bytea)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.note_l_activite_de_la_session(bytea) to popote_api;

-- `private.session_valide` (0139, que `session_courante` et `session_personne` appellent encore) n'est pas changée :
-- elle écrit l'activité en tenant la ligne jusqu'à la fin de la requête, ce que l'API ne fait plus (elle lit par
-- `lit_la_session`). Elle ne sert qu'au code déjà déployé, pendant la fenêtre de déploiement. Lui faire prendre la
-- personne avant d'écrire ferait attendre toute requête de la même personne pendant toute la requête d'une autre
-- (le `skip locked` de 0139 existe pour l'éviter) : l'écriture de l'activité se fait donc en dehors.

-- ── 3. Tout ce qui ferme des sessions prend la personne en premier ──────────────────────────────
/* `cree_session` : le corps de 0139, la clé posée en ligne devient l'appel nommé. */
create or replace function private.cree_session(
  p_person uuid, p_hash bytea, p_browser text, p_os text, p_old_hash bytea, p_now timestamptz
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
  perform private.verrouille_la_personne(p_person);

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
    (token_hash, person_id, browser, os, created_at, last_seen_at, expires_at, absolute_expires_at, reauth_at)
  values
    (p_hash, p_person, p_browser, p_os, p_now, p_now, p_now + interval '30 days', p_now + interval '90 days', p_now)
  returning id into v_id;
  return v_id;
end;
$$;

/* `ferme_les_autres_sessions` (0141) : le verrou en premier, et les codes en attente de la personne meurent
   avec ses autres sessions (un code demandé avant la fermeture ne ré-ouvre rien après). */
create or replace function private.ferme_les_autres_sessions(p_person uuid, p_keep uuid, p_now timestamptz)
returns void
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_fermees bigint;
begin
  perform private.verrouille_la_personne(p_person);
  with fermees as (
    update public.login_session s
       set revoked_at = p_now
     where s.person_id = p_person
       and s.id <> p_keep
       and s.revoked_at is null
       and s.expires_at > p_now
       and s.absolute_expires_at > p_now
    returning s.id
  )
  select pg_catalog.count(private.ecrit_evenement('session_fermee', p_person, f.id)) into v_fermees
    from fermees f;
  update public.login_code c
     set revoked_at = p_now
   where c.person_id = p_person and c.used_at is null and c.revoked_at is null;
  perform private.ferme_les_sessions_auth(p_person);
end;
$$;

/* `fait_tourner_et_ferme_les_autres` (0141, retirée en S15) : la personne avant la rotation de la ligne. */
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
begin
  select s.person_id into v_person from public.login_session s where s.token_hash = p_old_hash;
  if v_person is null then
    return null;
  end if;
  perform private.verrouille_la_personne(v_person);
  -- La rotation ensuite : c'est elle qui verrouille la ligne et départage deux changements simultanés.
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

  perform private.ferme_les_autres_sessions(v_person, v_session, p_now);
  return v_session;
end;
$$;

/* `confirme_le_changement_de_mot_de_passe` (0141) : la personne avant l'écriture du profil. */
create or replace function public.confirme_le_changement_de_mot_de_passe(
  p_person uuid, p_session uuid, p_request_id text default null
)
returns void
language sql
volatile
security definer
set search_path = ''
as $$
  select private.verrouille_la_personne(p_person);
  update public.user_profile set password_set = true where id = p_person and password_set is not true;
  select private.ecrit_evenement('mot_de_passe_change', p_person, null, null, null, null, p_request_id);
  select private.ferme_les_autres_sessions(p_person, p_session, pg_catalog.now());
$$;

/* `ferme_les_autres_appareils` (0140) : le verrou en premier, les codes en attente révoqués. */
create or replace function public.ferme_les_autres_appareils(p_courante uuid)
returns integer
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_person uuid := auth.uid();
  v_nombre integer;
begin
  if v_person is null then
    raise exception 'Aucune personne dans ce contexte.' using errcode = 'invalid_authorization_specification';
  end if;
  if p_courante is null then
    raise exception 'La session à garder est obligatoire.' using errcode = 'invalid_parameter_value';
  end if;
  perform private.verrouille_la_personne(v_person);
  with fermees as (
    update public.login_session s
       set revoked_at = pg_catalog.now()
     where s.person_id = v_person
       and s.id <> p_courante
       and s.revoked_at is null
       and s.expires_at > pg_catalog.now()
       and s.absolute_expires_at > pg_catalog.now()
    returning s.id
  ), evenements as (
    select private.ecrit_evenement('session_fermee', v_person, f.id) from fermees f
  )
  select pg_catalog.count(*) into v_nombre from evenements;
  update public.login_code c
     set revoked_at = pg_catalog.now()
   where c.person_id = v_person and c.used_at is null and c.revoked_at is null;
  return v_nombre;
end;
$$;
