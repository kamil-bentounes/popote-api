-- La session de connexion (spec § 4) : la table `login_session` et sa lecture `session_personne`. Compatible avec
-- l'appli en ligne : rien ne la lit encore, et le front actuel s'authentifie par GoTrue. La CRÉATION d'une session
-- (connexion, rotation, révocation par appareil) est l'étape 0.4 : ici les tests la posent en direct. La colonne
-- d'appareil y arrivera aussi.
--
-- Pourquoi `login_session` : `session` désigne déjà la séance de cuisine (`session_task`, `session_convive`...) et
-- `auth.sessions` celle de GoTrue.
--
-- Le cookie ne porte que 32 octets tirés au hasard ; la base ne garde que leur SHA-256 (`token_hash`), jamais le
-- jeton : une fuite de la table ne donne aucune session. Aucun droit sur la table, à personne : seule la fonction
-- `security definer` ci-dessous la lit, et `popote_api` est le seul à pouvoir l'appeler. `popote_api` l'appelle en
-- son nom propre, AVANT d'emprunter `authenticated` (qui n'a pas le droit d'exécution) ; `popote_internal` n'en a
-- pas l'usage.
--
-- Retour arrière (sans perte : aucune session n'existe avant 0.4 hors essais ; elles se rouvrent par une
-- reconnexion) :
--   drop function public.session_personne(bytea);
--   drop table public.login_session;
set local lock_timeout = '5s';
set local statement_timeout = '30s';

create table public.login_session (
  id                  uuid primary key default gen_random_uuid(),
  -- SHA-256 du jeton de 256 bits : 32 octets exactement.
  token_hash          bytea not null unique check (length(token_hash) = 32),
  person_id           uuid not null references auth.users (id) on delete cascade,
  created_at          timestamptz not null default now(),
  last_seen_at        timestamptz not null default now(),
  -- Échéance glissante : 30 jours après la dernière activité, sans jamais passer l'échéance absolue.
  expires_at          timestamptz not null default now() + interval '30 days',
  absolute_expires_at timestamptz not null default now() + interval '90 days',
  revoked_at          timestamptz,
  check (expires_at <= absolute_expires_at)
);
-- La suppression d'une personne emporte ses sessions (cascade), et 0.4 les révoquera par personne.
create index login_session_person_id_idx on public.login_session (person_id);

-- RLS activée et aucune politique : même si un droit était rendu par erreur, la table resterait vide pour
-- `anon` et `authenticated`. Pas de `force` : la fonction ci-dessous s'exécute en propriétaire.
alter table public.login_session enable row level security;
revoke all on table public.login_session from public, anon, authenticated, service_role;

/* La personne d'une session valide, ou `null`. Valide : ni révoquée, ni échue (glissante), ni au bout de ses
   90 jours, et la personne n'est ni bannie (`banned_until` futur) ni supprimée (`deleted_at` posé).
   Un seul résultat pour tous les refus : l'appelant ne distingue pas inconnue, échue et révoquée.

   Côté écriture : `last_seen_at` et l'échéance glissante ne se repoussent qu'une fois toutes les 5 minutes, pour
   qu'un `GET` ne soit pas un `UPDATE` à chaque requête (verrou de ligne, WAL). Deux requêtes simultanées : la
   seconde attend le verrou, relit la ligne, ne la trouve plus assez ancienne et passe à la lecture. */
create or replace function public.session_personne(p_hash bytea)
returns uuid
language plpgsql
volatile
security definer
set search_path = ''
as $$
declare
  v_maintenant constant timestamptz := pg_catalog.now();
  v_personne uuid;
begin
  update public.login_session s
     set last_seen_at = v_maintenant,
         expires_at = least(v_maintenant + interval '30 days', s.absolute_expires_at)
    from auth.users u
   where s.token_hash = p_hash
     and u.id = s.person_id
     and s.revoked_at is null
     and s.expires_at > v_maintenant
     and s.absolute_expires_at > v_maintenant
     and s.last_seen_at <= v_maintenant - interval '5 minutes'
     and (u.banned_until is null or u.banned_until <= v_maintenant)
     and u.deleted_at is null
  returning s.person_id into v_personne;
  if found then
    return v_personne;
  end if;

  select s.person_id into v_personne
    from public.login_session s
    join auth.users u on u.id = s.person_id
   where s.token_hash = p_hash
     and s.revoked_at is null
     and s.expires_at > v_maintenant
     and s.absolute_expires_at > v_maintenant
     and (u.banned_until is null or u.banned_until <= v_maintenant)
     and u.deleted_at is null;
  return v_personne;
end;
$$;

comment on function public.session_personne(bytea) is
  'La personne de la session dont le jeton a cette empreinte SHA-256, ou null (inconnue, échue, révoquée, au bout '
  'des 90 jours, personne bannie ou supprimée). Repousse l''échéance glissante au plus une fois toutes les 5 minutes. '
  'Exécutable par popote_api seulement.';

-- Créée avec les droits par défaut de la pile locale (public, anon, authenticated, service_role) : on les retire
-- tous, un par un, comme le ferait un projet hébergé neuf ; seul `popote_api` reçoit l'exécution.
revoke all on function public.session_personne(bytea) from public, anon, authenticated, service_role;
grant execute on function public.session_personne(bytea) to popote_api;
