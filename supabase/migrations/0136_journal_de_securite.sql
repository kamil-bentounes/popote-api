-- ═══════════════════════════════════════════════════════════════════════════
-- 0136 · LE JOURNAL DE SÉCURITÉ (spec § 4, § 7.7)
--
-- Une ligne par événement de sécurité (connexion, déconnexion, mot de passe, invitation, suppression du compte).
-- C'est la preuve et la détection, pas un historique d'activité : la table ne garde QUE ce qui sert à relier des
-- événements entre eux, jamais ce qui désigne une personne en clair :
--
--  - ni e-mail, ni adresse IP, ni agent utilisateur, ni champ libre ;
--  - `account_key` et `ip_hash` sont des HMAC-SHA256 de 32 octets que l'API calcule avec un poivre qu'elle seule
--    connaît (`security/empreintes.py`). Sans le poivre, une fuite de la table ne donne ni adresse ni IP, et ne
--    permet pas d'en tester une. Une IPv6 est regroupée par /64 avant le HMAC (B12) ;
--  - `person_id` est effacé à la suppression du compte (`on delete set null`) : l'événement reste, sans personne.
--  - `session_id` et `invitation_id` n'ont pas de clé étrangère : la session ou le lien peut être purgé avant
--    l'événement, qui doit survivre.
--
-- CONSERVATION (B7) : les échecs de connexion et les blocages (`connexion_ratee`, `connexion_bloquee`) sont liés à
-- une clé de compte, pas à une personne : 90 jours. Tout le reste : 1 an. La purge est par lots, idempotente, et ne
-- rend que des comptes ; `pg_cron` la lance chaque nuit.
--
-- DROITS (B3, B17, B19) :
--  - le schéma `private` naît fermé : aucun rôle n'y a `usage`, aucun objet n'y est exécutable hors propriétaire.
--    Les aides internes et les variantes à horloge (`p_now`) y vivent ; une migration qui a besoin d'y appeler
--    quelque chose depuis `popote_api` y ajoute `usage` pour ce rôle seul. Une fonction publique (`authenticated`)
--    n'a jamais de paramètre d'horloge : une personne choisirait sa date.
--  - `public.journalise` est exécutable par `popote_api` (contexte connexion) ET par `service_role` (contexte
--    service, où le rôle COURANT est `service_role`, pas `popote_internal`) ; jamais par `authenticated` : une
--    personne ne forge pas d'événement. Le droit se lit sur le rôle courant, pas sur le rôle de connexion.
--
-- COMPATIBLE avec l'appli en ligne : objets neufs, aucun appelant dans l'appli actuelle ; la tâche `pg_cron` ne
-- fait que du SQL.
--
-- Retour arrière (sans perte pour l'appli : personne n'écrit encore ici hors essais) :
--   select cron.unschedule('journal-securite-purge');   -- si pg_cron est là
--   drop function public.journalise(text, uuid, uuid, uuid, bytea, bytea, text);
--   drop function private.ecrit_evenement(text, uuid, uuid, uuid, bytea, bytea, text);
--   drop function private.purge_journal_securite(timestamptz, integer);
--   drop table public.security_event;
--   drop schema private;
-- ═══════════════════════════════════════════════════════════════════════════
set local lock_timeout = '5s';
set local statement_timeout = '30s';

-- ── 1. Le schéma privé, fermé ───────────────────────────────────────────────
create schema if not exists private;
comment on schema private is
  'Aides internes et variantes à horloge. Aucun rôle applicatif n''y a usage tant qu''une migration ne le donne pas.';
revoke all on schema private from public, anon, authenticated, service_role, popote_api, popote_internal;

-- ── 2. La table ─────────────────────────────────────────────────────────────
create table public.security_event (
  id            bigint generated always as identity primary key,
  occurred_at   timestamptz not null default now(),
  -- Liste fermée (B10, B23 y ajoutent `compte_repris` et `verification_fuites_indisponible`). Le test de dérive
  -- compare cette liste à `Evenement` (src/popote_api/security/journal_securite.py).
  kind          text not null check (kind in (
    'connexion_reussie', 'connexion_ratee', 'connexion_bloquee', 'deconnexion',
    'reauthentification_reussie', 'reauthentification_ratee', 'session_fermee',
    'mot_de_passe_change', 'reinitialisation_demandee', 'reinitialisation_utilisee',
    'invitation_creee', 'invitation_acceptee', 'invitation_revoquee',
    'compte_supprime', 'compte_repris', 'verification_fuites_indisponible')),
  person_id     uuid references auth.users (id) on delete set null,
  session_id    uuid,
  invitation_id uuid,
  -- HMAC-SHA256 : 32 octets exactement. Null quand l'événement n'a pas de clé (ou que le poivre manque).
  account_key   bytea check (length(account_key) = 32),
  ip_hash       bytea check (length(ip_hash) = 32),
  -- L'identifiant de la requête, que l'API génère (`identifiant.py` : un UUID en 32 caractères hexadécimaux),
  -- jamais une valeur du client. Cette forme-là seulement : pas de champ libre où loger une adresse.
  request_id    text check (request_id ~ '^[0-9a-f]{32}$')
);
comment on table public.security_event is
  'Événements de sécurité. Aucun e-mail, aucune IP, aucun agent : des HMAC et des identifiants. Échecs 90 jours, le reste 1 an.';

-- La clé étrangère est indexée (la suppression d'un compte la parcourt) ; l'index sur la date sert la purge.
create index security_event_person_id_idx on public.security_event (person_id) where person_id is not null;
create index security_event_occurred_at_idx on public.security_event (occurred_at);

-- RLS activée ET forcée, aucune politique, aucun droit : même rendu par erreur, un droit ne montrerait rien.
alter table public.security_event enable row level security;
alter table public.security_event force row level security;
revoke all on table public.security_event from public, anon, authenticated, service_role, popote_api, popote_internal;

-- ── 3. L'écriture : une aide interne et la fonction du code ─────────────────
/* L'aide interne, appelée par les fonctions `security definer` des tâches suivantes dans leur transaction (rien
   d'autre ne l'exécute : elle s'exécute avec les droits de l'appelant, donc en propriétaire depuis une de ces
   fonctions, et échoue pour tout autre). Le type est contrôlé par la table. */
create or replace function private.ecrit_evenement(
  p_kind text,
  p_person uuid default null,
  p_session uuid default null,
  p_invitation uuid default null,
  p_account_key bytea default null,
  p_ip_hash bytea default null,
  p_request_id text default null
) returns void
language sql
volatile
security invoker
set search_path = ''
as $$
  insert into public.security_event (kind, person_id, session_id, invitation_id, account_key, ip_hash, request_id)
  values (p_kind, p_person, p_session, p_invitation, p_account_key, p_ip_hash, p_request_id);
$$;
comment on function private.ecrit_evenement(text, uuid, uuid, uuid, bytea, bytea, text) is
  'Écrit un événement de sécurité dans la transaction de l''appelant. Interne : aucun rôle applicatif ne l''exécute.';
revoke all on function private.ecrit_evenement(text, uuid, uuid, uuid, bytea, bytea, text)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

/* La fonction du code Python. `popote_api` (contexte connexion) et `service_role` (contexte service) seulement.
   Pas d'horloge : l'événement porte `now()`. */
create or replace function public.journalise(
  p_kind text,
  p_person uuid default null,
  p_session uuid default null,
  p_invitation uuid default null,
  p_account_key bytea default null,
  p_ip_hash bytea default null,
  p_request_id text default null
) returns void
language plpgsql
volatile
security definer
set search_path = ''
as $$
begin
  perform private.ecrit_evenement(p_kind, p_person, p_session, p_invitation, p_account_key, p_ip_hash, p_request_id);
end;
$$;
comment on function public.journalise(text, uuid, uuid, uuid, bytea, bytea, text) is
  'Écrit un événement de sécurité. Exécutable par popote_api (contexte connexion) et service_role (contexte service) seulement.';
revoke all on function public.journalise(text, uuid, uuid, uuid, bytea, bytea, text)
  from public, anon, authenticated, service_role, popote_api, popote_internal;
grant execute on function public.journalise(text, uuid, uuid, uuid, bytea, bytea, text)
  to popote_api, service_role;

-- ── 4. La purge ─────────────────────────────────────────────────────────────
/* Par lots (5 000 par défaut ; les tests en prennent 2) : chaque `delete` reste de taille bornée (la fonction
   n'est tout de même qu'une transaction : les verrous de ligne tiennent jusqu'à sa fin). `skip locked` : deux purges simultanées ne s'attendent pas. Idempotente : un
   deuxième passage ne trouve rien. Rend le nombre de lignes effacées, jamais une valeur ; le message de notice
   non plus. Variante à horloge (`p_now`) : dans `private`, jamais exécutable par une personne. */
create or replace function private.purge_journal_securite(
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
    delete from public.security_event
     where id in (
       select id from public.security_event
        where occurred_at < p_now - case
                when kind in ('connexion_ratee', 'connexion_bloquee') then interval '90 days'
                else interval '365 days' end
        order by id
        limit p_lot
          for update skip locked);
    get diagnostics v_lot = row_count;
    v_total := v_total + v_lot;
    exit when v_lot < p_lot;
  end loop;
  raise notice 'purge du journal de securite : % ligne(s) effacee(s)', v_total;
  return v_total;
end;
$$;
comment on function private.purge_journal_securite(timestamptz, integer) is
  'Efface les événements de sécurité échus (échecs de connexion 90 jours, le reste 1 an), par lots ; rend leur nombre. Lancée chaque nuit par pg_cron.';
revoke all on function private.purge_journal_securite(timestamptz, integer)
  from public, anon, authenticated, service_role, popote_api, popote_internal;

/* La planification, gardée comme celle des rappels (0126) : sans `pg_cron` (une base locale qui ne l'a pas), la
   migration passe quand même, et un avertissement le dit. `pg_cron` et non une route interne : la purge n'a besoin
   d'aucun secret ni d'aucune sortie réseau, et rien ne dépend de la disponibilité de l'API. 03 h 41 UTC. */
do $$
begin
  if exists (select 1 from pg_extension where extname = 'pg_cron') then
    begin
      execute $q$select cron.schedule('journal-securite-purge', '41 3 * * *', 'select private.purge_journal_securite()')$q$;
    exception when others then
      raise warning 'LA PURGE DU JOURNAL DE SÉCURITÉ N''EST PAS PLANIFIÉE : % (job « journal-securite-purge »).', sqlerrm;
    end;
  else
    raise warning 'LA PURGE DU JOURNAL DE SÉCURITÉ N''EST PAS PLANIFIÉE : pg_cron est absent. Active-le (Database > '
      'Extensions), puis : select cron.schedule(''journal-securite-purge'', ''41 3 * * *'', ''select private.purge_journal_securite()'').';
  end if;
end $$;
