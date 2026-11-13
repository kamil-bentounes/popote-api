-- ═══════════════════════════════════════════════════════════════════════════
-- 0143 · LES INVITATIONS PAR LIEN, CÔTÉ HÔTE : LA LISTE ET LA RÉVOCATION (spec § 4 ; étape 0.4, T12b)
--
-- Contexte « personne » : la requête tourne sous `authenticated`, `auth.uid()` vaut la personne de la session, et
-- le foyer vient de SON profil. Aucun paramètre ne désigne une personne ou un foyer : un lien d'un autre foyer est
-- « inconnu », jamais révélé, jamais touché.
--
--  - `public.mes_invitations(p_limit, p_after_created, p_after_id)` : les liens EN ATTENTE du foyer (ni expirés, ni
--    utilisés, ni révoqués), du plus récent au plus ancien, puis par identifiant ; la page reprend strictement après
--    le couple (p_after_created, p_after_id). Rien d'autre que l'identifiant et les deux dates : ni jeton, ni
--    empreinte, ni nom de la personne qui l'a créé.
--  - `public.revoque_invitation(p_id)` : rend `revoquee`, `deja` (déjà révoqué, ou échu : il ne sert plus),
--    `utilisee` (déjà accepté : on ne le révoque pas) ou `inconnue` (autre foyer, ou rien). Un événement
--    `invitation_revoquee` dans la même transaction, seulement quand un lien passe réellement à révoqué.
--
-- DROITS (B3) : `authenticated` seul. `anon`, `popote_api`, `popote_internal`, `service_role`, `public` : aucun.
-- Pas de paramètre d'horloge (B19) : les fonctions lisent `now()`.
--
-- COMPATIBLE avec l'appli en ligne : deux fonctions neuves ; la table `invite_link` (0142), la table `invitation`
-- actuelle et les fonctions Edge `invite` / `accept-invite` ne bougent pas.
--
-- Retour arrière (sans perte) :
--   drop function public.revoque_invitation(uuid), public.mes_invitations(integer, timestamptz, uuid);
-- ═══════════════════════════════════════════════════════════════════════════
set local lock_timeout = '5s';
set local statement_timeout = '30s';

create or replace function public.mes_invitations(
  p_limit integer default 20, p_after_created timestamptz default null, p_after_id uuid default null
) returns table (id uuid, created_at timestamptz, expires_at timestamptz)
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
  v_person uuid := auth.uid();
  v_foyer uuid;
begin
  if v_person is null then
    raise exception 'Aucune personne dans ce contexte.' using errcode = 'invalid_authorization_specification';
  end if;
  if p_limit is null or p_limit < 1 or p_limit > 101 then
    raise exception 'La taille de page doit valoir de 1 à 101.' using errcode = 'invalid_parameter_value';
  end if;
  select p.household_id into v_foyer from public.user_profile p where p.id = v_person;
  if v_foyer is null then
    return;
  end if;
  return query
  select l.id, l.created_at, l.expires_at
    from public.invite_link l
   where l.household_id = v_foyer
     and l.revoked_at is null
     and l.accepted_at is null
     and l.expires_at > pg_catalog.now()
     and (p_after_created is null or (l.created_at, l.id) < (p_after_created, p_after_id))
   order by l.created_at desc, l.id desc
   limit p_limit;
end;
$$;
comment on function public.mes_invitations(integer, timestamptz, uuid) is
  'Les liens d''invitation en attente du foyer de la personne du contexte (auth.uid()), du plus récent au plus ancien. Exécutable par authenticated seul.';
revoke all on function public.mes_invitations(integer, timestamptz, uuid)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.mes_invitations(integer, timestamptz, uuid) to authenticated;

create or replace function public.revoque_invitation(p_id uuid)
returns text
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_person uuid := auth.uid();
  v_foyer uuid;
  v_id uuid;
  v_etat text;
begin
  if v_person is null then
    raise exception 'Aucune personne dans ce contexte.' using errcode = 'invalid_authorization_specification';
  end if;
  select p.household_id into v_foyer from public.user_profile p where p.id = v_person;
  if v_foyer is null then
    return 'inconnue';
  end if;
  update public.invite_link l
     set revoked_at = pg_catalog.now()
   where l.id = p_id
     and l.household_id = v_foyer
     and l.revoked_at is null
     and l.accepted_at is null
     and l.expires_at > pg_catalog.now()
  returning l.id into v_id;
  if found then
    perform private.ecrit_evenement('invitation_revoquee', v_person, null, v_id);
    return 'revoquee';
  end if;
  -- Pas révoqué par cet appel : le lien est-il du foyer, et pourquoi n'a-t-il pas bougé ?
  select case when l.accepted_at is not null then 'utilisee' else 'deja' end into v_etat
    from public.invite_link l
   where l.id = p_id and l.household_id = v_foyer;
  return coalesce(v_etat, 'inconnue');
end;
$$;
comment on function public.revoque_invitation(uuid) is
  'Révoque un lien du foyer de la personne du contexte : revoquee, deja, utilisee ou inconnue (autre foyer compris). Un événement par lien révoqué. Exécutable par authenticated seul.';
revoke all on function public.revoque_invitation(uuid)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.revoque_invitation(uuid) to authenticated;
