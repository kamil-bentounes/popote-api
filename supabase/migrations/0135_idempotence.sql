-- ═══════════════════════════════════════════════════════════════════════════
-- 0135 · L'IDEMPOTENCE DES POST (spec § 3.5, étape 0.3)
--
-- Un `POST` qui crée quelque chose et que le client peut renvoyer (réseau coupé, double clic, reprise) porte un
-- en-tête `Idempotency-Key`. La première réponse est gardée ici, DANS LA MÊME TRANSACTION que l'effet : ou les
-- deux existent, ou aucun. Un renvoi de la même clé avec le même contenu rend la réponse gardée sans refaire
-- l'effet ; avec un autre contenu, c'est une erreur (422) ; pendant que le premier envoi tourne, c'est un conflit
-- (409). Brouillon : draft-ietf-httpapi-idempotency-key-header-08 (dernière version au 12/11/2026).
--
-- Compatible avec l'appli en ligne : une table et deux fonctions de plus, rien d'existant ne change, aucun appelant
-- avant la route qui s'en servira (étape 0.4).
--
-- Trois règles tiennent le reste :
--  1. CHACUN SA CLÉ. La clé primaire est (personne, clé) et la RLS borne la table à `auth.uid()` : la même clé chez
--     l'autre personne est une autre ligne, et personne ne lit ni ne rejoue la réponse de l'autre.
--  2. UN SEUL ENVOI À LA FOIS PAR CLÉ. `idempotence_verrouille` prend un verrou consultatif de transaction, à deux
--     entiers (comme `verrou_du_foyer`, 0095 : `hashtext('idempotence')` d'abord, la personne et la clé ensuite),
--     et ne l'attend pas : refusé = un autre envoi de la même clé est en cours. Le verrou meurt avec la
--     transaction, donc avec l'écriture de la ligne. Deux clés qui partageraient le même hachage de 32 bits se
--     refuseraient l'une l'autre pour un instant (un 409, qu'on retente) : jamais de mauvaise réponse rendue.
--  3. 24 HEURES. Une ligne échue ne compte plus (le code la remplace) ; `idempotence_purge` les efface, chaque
--     nuit par `pg_cron`.
--
-- Les `POST` sans session (connexion, acceptation d'une invitation) n'ont pas de personne : ils ne sont pas
-- concernés. Leur jeton à usage unique les protège du double envoi (spec § 3.5).
--
-- Ce que la table garde de la réponse : le statut (2xx), trois en-têtes au plus (`content-type`, `location`,
-- `etag`) et le corps, 64 Kio au plus. C'est un contenu de la personne (une recette, une dépense) : il reste 24 h,
-- lisible d'elle seule, et part avec son compte (`on delete cascade`).
--
-- Retour arrière (sans perte pour l'appli, qui n'a pas encore d'appelant) :
--   select cron.unschedule('idempotence-purge');   -- si pg_cron est là
--   drop function public.idempotence_purge();
--   drop function public.idempotence_verrouille(text);
--   drop table public.idempotency_key;
-- ═══════════════════════════════════════════════════════════════════════════
set local lock_timeout = '5s';
set local statement_timeout = '30s';

-- ── 1. La table ──────────────────────────────────────────────────────────────
create table if not exists public.idempotency_key (
  person_id   uuid not null references public.user_profile(id) on delete cascade,
  -- Chaîne de champ structuré (RFC 9651) : ASCII imprimable (espace compris), 1 à 255 signes, une fois les
  -- guillemets et les échappements retirés.
  key         text not null check (key ~ '^[ -~]{1,255}$'),
  method      text not null check (method in ('POST', 'PATCH')),
  path        text not null check (char_length(path) between 1 and 2048),
  -- SHA-256 en hexadécimal de la méthode, du chemin, de la requête et du corps (calculé par l'API).
  fingerprint text not null check (fingerprint ~ '^[0-9a-f]{64}$'),
  status      smallint not null check (status between 200 and 299),
  -- Liste fermée : rien d'autre ne se rejoue (ni `set-cookie`, ni un en-tête de trace).
  headers     jsonb not null default '{}'::jsonb check (
    jsonb_typeof(headers) = 'object'
    and (headers - array['content-type', 'location', 'etag']) = '{}'::jsonb),
  body        bytea not null check (octet_length(body) <= 65536),
  created_at  timestamptz not null default now(),
  expires_at  timestamptz not null default now() + interval '24 hours',
  primary key (person_id, key),
  check (expires_at > created_at)
);
comment on table public.idempotency_key is
  'La première réponse d''un POST à clé d''idempotence, gardée 24 h dans la transaction de son effet. Une personne ne voit que les siennes.';

/* Pas d'index sur `person_id` : la clé primaire le porte en tête. Celui-ci sert la purge. */
create index if not exists idempotency_key_expires_at on public.idempotency_key (expires_at);

-- ── 2. Les droits : la RLS borne tout à la personne ─────────────────────────
alter table public.idempotency_key enable row level security;
alter table public.idempotency_key force row level security;

drop policy if exists idempotency_key_select on public.idempotency_key;
create policy idempotency_key_select on public.idempotency_key for select to authenticated
  using (person_id = (select auth.uid()));
drop policy if exists idempotency_key_insert on public.idempotency_key;
create policy idempotency_key_insert on public.idempotency_key for insert to authenticated
  with check (person_id = (select auth.uid()));
/* Le code retire la ligne échue de SA clé avant d'écrire la nouvelle (la purge de la nuit n'est pas passée). */
drop policy if exists idempotency_key_delete on public.idempotency_key;
create policy idempotency_key_delete on public.idempotency_key for delete to authenticated
  using (person_id = (select auth.uid()));

/* Pas d'`update` : une ligne gardée ne change jamais, elle expire. Les privilèges par défaut de Supabase donnent
   tout à `anon`, `authenticated` et `service_role` sur une table neuve : on les retire d'abord, puis on pose
   exactement ce qui sert. Le rôle de service n'y touche pas (la purge est une fonction du propriétaire). */
revoke all on public.idempotency_key from public, anon, authenticated, service_role;
grant select, insert, delete on public.idempotency_key to authenticated;

-- ── 3. Le verrou de la clé ──────────────────────────────────────────────────
/* `security invoker` : la personne est `auth.uid()` de l'appelant, jamais un paramètre. Sans personne (rôle de
   service, anonyme), elle refuse : `hashtext(null)` rendrait NULL et `pg_try_advisory_xact_lock(…, NULL)` aussi,
   un « verrou » qui ne verrouille rien. La personne fait 36 signes : concaténée à la clé, elle ne s'y confond
   pas. */
create or replace function public.idempotence_verrouille(p_cle text)
returns boolean language plpgsql volatile security invoker set search_path = '' as $$
declare
  v_personne uuid := auth.uid();
begin
  if v_personne is null or p_cle is null then
    raise exception 'Une clé d''idempotence appartient à une personne connectée.'
      using errcode = 'insufficient_privilege';
  end if;
  return pg_try_advisory_xact_lock(hashtext('idempotence'), hashtext(v_personne::text || p_cle));
end $$;
comment on function public.idempotence_verrouille(text) is
  'Vrai si le verrou (personne, clé) est pris pour la transaction ; faux si un autre envoi de la même clé le tient.';
revoke all on function public.idempotence_verrouille(text) from public, anon, authenticated, service_role;
grant execute on function public.idempotence_verrouille(text) to authenticated;

-- ── 4. La purge des lignes échues ───────────────────────────────────────────
/* Par lots de 1000 : chaque `delete` reste borné (mémoire, journal) si la table a grossi ; la fonction reste UNE
   transaction, donc les verrous de ligne tiennent jusqu'à sa fin. Rend le nombre de lignes effacées (jamais leur
   contenu). `security definer` : le propriétaire de la table passe la RLS,
   alors que personne d'autre ne doit pouvoir effacer la ligne d'un autre ; `search_path` vide. */
create or replace function public.idempotence_purge()
returns integer language plpgsql volatile security definer set search_path = '' as $$
declare
  v_taille_du_lot constant integer := 1000;
  v_effacees integer := 0;
  v_lot integer;
begin
  loop
    delete from public.idempotency_key
    where ctid = any (array(
      select ctid from public.idempotency_key where expires_at <= now() limit v_taille_du_lot));
    get diagnostics v_lot = row_count;
    v_effacees := v_effacees + v_lot;
    exit when v_lot < v_taille_du_lot;
  end loop;
  return v_effacees;
end $$;
comment on function public.idempotence_purge() is
  'Efface les lignes d''idempotence échues, par lots de 1000 ; rend leur nombre. Lancée chaque nuit par pg_cron.';
revoke all on function public.idempotence_purge() from public, anon, authenticated, service_role;
grant execute on function public.idempotence_purge() to service_role;

/* La planification, gardée comme celle des rappels (0126) : sans `pg_cron` (une base locale qui ne l'a pas), la
   migration passe quand même, et un avertissement le dit. Pourquoi `pg_cron` et non une route interne (T10) : la
   purge n'a besoin d'aucun secret ni d'aucune sortie réseau, le réveil vit dans la base qu'il nettoie, et rien ne
   dépend de la disponibilité de l'API. À 03 h 17 UTC, hors des heures rondes où tout le monde planifie. */
do $$
begin
  if exists (select 1 from pg_extension where extname = 'pg_cron') then
    begin
      execute $q$select cron.schedule('idempotence-purge', '17 3 * * *', 'select public.idempotence_purge()')$q$;
    exception when others then
      raise warning 'LA PURGE DE L''IDEMPOTENCE N''EST PAS PLANIFIÉE : % (job « idempotence-purge »).', sqlerrm;
    end;
  else
    raise warning 'LA PURGE DE L''IDEMPOTENCE N''EST PAS PLANIFIÉE : pg_cron est absent. Active-le (Database > '
      'Extensions), puis : select cron.schedule(''idempotence-purge'', ''17 3 * * *'', ''select public.idempotence_purge()'').';
  end if;
end $$;
