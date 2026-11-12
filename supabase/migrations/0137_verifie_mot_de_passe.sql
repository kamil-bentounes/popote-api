-- ═══════════════════════════════════════════════════════════════════════════
-- 0137 · VÉRIFIER UN MOT DE PASSE EN BASE (spec § 4, B15, B24)
--
-- L'API ne détient jamais un mot de passe : elle le passe à la base, qui le compare au hachage bcrypt que GoTrue a
-- écrit dans `auth.users.encrypted_password` (`crypt()` de pgcrypto), puis l'oublie. Personne ne change son mot de
-- passe à la bascule : les hachages actuels restent valables.
--
--  - `public.verifie_mot_de_passe(p_email, p_password) returns uuid` : la personne, ou `null`. Jamais la raison.
--  - `public.verifie_mot_de_passe_de(p_person, p_password) returns boolean` : même contrôle pour une personne
--    connue (la réauthentification, T10).
--  - `private.mot_de_passe_correspond(p_password, p_hash)` : le coeur commun, interne.
--
-- Tout refus rend `null` / `false` SANS exception et sans le dire : adresse inconnue, deux comptes pour la même
-- adresse (casse), compte SSO ou anonyme, banni (`banned_until` futur), supprimé (`deleted_at`), hachage vide, nul
-- ou mal formé, hachage qui ne commence pas par `$2a$`, mot de passe vide, nul ou de plus de 72 octets, adresse
-- non confirmée (`email_confirmed_at` nul : GoTrue refuse aussi cette connexion ; sans cela, quelqu'un qui s'inscrirait
-- avec l'adresse d'un tiers entrerait ici). Un compte supprimé ne compte pas dans le doublon d'adresse.
--
--  - SEUL `$2a$` EST ACCEPTÉ (B15) : pgcrypto ne reconnaît pas `$2b$` ni `$2y$` ; devant un préfixe inconnu, il
--    retombe sur l'ancien `crypt` DES et rend une chaîne sans rapport, sans erreur. Un compte à un autre préfixe
--    passe par « mot de passe oublié ». Les préfixes de la prod sont comptés à la répétition de la bascule.
--  - EXACTEMENT UN `crypt()` DANS TOUTES LES BRANCHES : le vrai hachage, ou un hachage factice de même coût que ceux
--    de la base (`$2a$10$`), tiré une fois et écrit ici. Un compte inconnu, banni ou sans hachage coûte le même
--    bcrypt qu'un mauvais mot de passe : le temps ne dit rien. Le test le mesure.
--  - 72 OCTETS : bcrypt ne lit pas au-delà. L'API écarte déjà les candidats plus longs (`candidats_de_connexion`),
--    jamais tronqués ; ici, défense en profondeur : plus de 72 octets est un refus, même avec le bon préfixe (une
--    troncature accepterait un mot de passe qui n'est pas le bon).
--  - L'ADRESSE arrive sous la forme de l'API (`email_normalise` : NFKC, minuscules, espaces de bord retirés, la même
--    que la clé de limite, B24) ; la base y ajoute `lower(btrim())`, idempotent sur cette forme, et compare à celle
--    de `auth.users`. Une adresse n'est jamais un motif (égalité, pas `ilike`).
--
-- Droits : `popote_api` SEUL (contexte « connexion », `Base.connexion()`) ; ni `authenticated`, ni `anon`, ni
-- `service_role`, ni `popote_internal`. Un `crypt()` par appel est un coût (de l'ordre de 50 à 100 ms) : le pool `popote_api` et
-- la limite de connexion (T6) l'encadrent ; aucun appel ne se fait sans avoir pris un créneau.
--
-- COMPATIBLE avec l'appli en ligne : fonctions neuves, lecture seule de `auth.users`, aucun appelant actuel.
--
-- Retour arrière (sans perte) :
--   drop function public.verifie_mot_de_passe_de(uuid, text);
--   drop function public.verifie_mot_de_passe(text, text);
--   drop function private.mot_de_passe_correspond(text, text);
-- ═══════════════════════════════════════════════════════════════════════════
set local lock_timeout = '5s';
set local statement_timeout = '30s';

-- ── 1. Le coeur : un seul crypt(), toujours ─────────────────────────────────
create or replace function private.mot_de_passe_correspond(p_password text, p_hash text)
returns boolean
language plpgsql
volatile
security invoker
set search_path = ''
as $$
declare
  -- Hachage bcrypt factice de coût 10, d'un mot de passe tiré au hasard puis jeté : il ne correspond à personne.
  c_factice constant text := '$2a$10$TomZERTB2nLik39KZPllf.Hj5WyG1pEvK9axxrIM7a3IdbHay1/Q2';
  v_mot_de_passe constant text := coalesce(p_password, '');
  v_utilisable boolean := p_hash is not null
    and pg_catalog.left(p_hash, 4) = '$2a$'
    and pg_catalog.length(p_hash) = 60
    and v_mot_de_passe <> ''
    and pg_catalog.octet_length(v_mot_de_passe) <= 72;
  v_calcule text;
begin
  begin
    v_calcule := extensions.crypt(v_mot_de_passe, case when v_utilisable then p_hash else c_factice end);
  exception when invalid_parameter_value then
    -- Hachage mal formé : refus, et le même coût qu'ailleurs (un temps court dirait que le compte existe).
    v_utilisable := false;
    v_calcule := extensions.crypt(v_mot_de_passe, c_factice);
  end;
  return v_utilisable and v_calcule = p_hash;
end;
$$;
comment on function private.mot_de_passe_correspond(text, text) is
  'Vrai si le mot de passe (72 octets au plus, non vide) correspond au hachage $2a$ ; un seul crypt() dans toutes les branches. Interne.';
revoke all on function private.mot_de_passe_correspond(text, text)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

-- ── 2. Par adresse : la connexion ───────────────────────────────────────────
create or replace function public.verifie_mot_de_passe(p_email text, p_password text)
returns uuid
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_email constant text := pg_catalog.lower(pg_catalog.btrim(coalesce(p_email, '')));
  v_maintenant constant timestamptz := pg_catalog.now();
  v_comptes integer;
  v_personne uuid;
  v_hash text;
begin
  -- Un hachage n'est rendu que pour un compte actif et confirmé ; deux comptes non supprimés (ou aucun) pour
  -- l'adresse : aucun hachage.
  select pg_catalog.count(*),
         (pg_catalog.array_agg(u.id))[1],
         (pg_catalog.array_agg(case
            when (u.banned_until is null or u.banned_until <= v_maintenant) and u.email_confirmed_at is not null
            then u.encrypted_password end))[1]
    into v_comptes, v_personne, v_hash
    from auth.users u
   where v_email <> ''
     and pg_catalog.lower(pg_catalog.btrim(u.email)) = v_email
     and u.deleted_at is null
     and not u.is_sso_user
     and not u.is_anonymous;
  if v_comptes is distinct from 1 then
    v_hash := null;
  end if;
  if private.mot_de_passe_correspond(p_password, v_hash) then
    return v_personne;
  end if;
  return null;
end;
$$;
comment on function public.verifie_mot_de_passe(text, text) is
  'La personne dont le mot de passe est le bon, ou null (jamais la raison du refus). Seul $2a$ est accepté ; un crypt() par appel. Exécutable par popote_api seulement.';
revoke all on function public.verifie_mot_de_passe(text, text)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.verifie_mot_de_passe(text, text) to popote_api;

-- ── 3. Par personne : la réauthentification ─────────────────────────────────
create or replace function public.verifie_mot_de_passe_de(p_person uuid, p_password text)
returns boolean
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_maintenant constant timestamptz := pg_catalog.now();
  v_hash text;
begin
  select u.encrypted_password
    into v_hash
    from auth.users u
   where u.id = p_person
     and (u.banned_until is null or u.banned_until <= v_maintenant)
     and u.deleted_at is null
     and u.email_confirmed_at is not null
     and not u.is_sso_user
     and not u.is_anonymous;
  return private.mot_de_passe_correspond(p_password, v_hash);
end;
$$;
comment on function public.verifie_mot_de_passe_de(uuid, text) is
  'Vrai si le mot de passe est celui de cette personne (compte actif, hachage $2a$) ; un crypt() par appel. Exécutable par popote_api seulement.';
revoke all on function public.verifie_mot_de_passe_de(uuid, text)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.verifie_mot_de_passe_de(uuid, text) to popote_api;
