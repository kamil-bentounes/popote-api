-- ═══════════════════════════════════════════════════════════════════════════
-- 0126 · LES RAPPELS PAR MAIL
--
-- Sept rappels (décongeler, une barquette qui périme, choisir les repas, noter les dépenses, confirmer les
-- charges, clôturer le mois, une facture annuelle). Trois règles tiennent tout le reste :
--
--  1. CHACUN RÈGLE LES SIENS. `rappel_reglage` ne se lit ni ne s'écrit qu'à son nom (`user_id = auth.uid()`) :
--     personne ne voit ce que l'autre a activé, personne ne le change à sa place.
--  2. COUPÉ PAR DÉFAUT. Pas de ligne, pas de mail. On n'envoie rien à qui ne l'a pas demandé : Léa ne reçoit
--     rien tant qu'elle n'a rien activé.
--  3. JAMAIS DEUX FOIS. `rappel_envoye` garde (membre, type, clé), unique. La fonction `rappels` réserve la ligne
--     AVANT d'envoyer : l'insertion unique fait office de verrou. Elle ne la rend que si l'échec est sûrement
--     arrivé AVANT l'envoi des données (connexion, authentification) ; après, ou dans le doute, le mail est peut-être
--     parti, et la réservation reste : un mail perdu vaut mieux qu'un doublon.
--
-- `rappels_a_envoyer(p_maintenant)` dit ce qui est DÛ à cet instant, à l'heure de Paris. Un rappel est dû à partir
-- de son heure et jusqu'à la fin du jour : un passage manqué se rattrape dans la journée. Elle est réservée au rôle
-- de service (une adresse mail se lit dans `auth.users`), comme `reserve_rappel` et `libere_rappel`.
--
-- Un mail par membre et par jour pour ce qui se regroupe (les barquettes qui périment, les factures annuelles) :
-- la clé est la date, et les barquettes ou les charges qu'il couvre sont réservées avec elle (`cles`).
--
-- Chaque heure, à la minute 5, `pg_cron` appelle (par `pg_net`) la fonction edge `rappels`. L'adresse de la fonction
-- et son secret se lisent dans Vault (`rappels_url`, `rappels_secret`), jamais ici : sans l'un ou l'autre, le job
-- ne fait rien. Ils se posent à la main, en production (voir la fin du fichier). Chaque appel laisse une ligne dans
-- `rappel_passe` (sans adresse ni contenu) : `select * from rappel_passe order by le desc` dit que ça tourne.
-- ═══════════════════════════════════════════════════════════════════════════

-- ── 1. Les réglages : un par membre et par type ─────────────────────────────
create table if not exists public.rappel_reglage (
  user_id    uuid not null references public.user_profile(id) on delete cascade,
  type       text not null check (type in (
    'sortir_du_congelateur', 'barquette_perime', 'choisir_les_repas', 'noter_les_depenses',
    'confirmer_les_charges', 'cloturer_le_mois', 'facture_annuelle')),
  actif      boolean not null default false,
  modifie_le timestamptz not null default now(),
  primary key (user_id, type)
);
comment on table public.rappel_reglage is
  'Un réglage par membre et par type de rappel. Pas de ligne = coupé : on n''envoie rien à qui ne l''a pas demandé.';

alter table public.rappel_reglage enable row level security;

drop policy if exists rappel_reglage_select on public.rappel_reglage;
create policy rappel_reglage_select on public.rappel_reglage for select to authenticated
  using (user_id = auth.uid());
drop policy if exists rappel_reglage_insert on public.rappel_reglage;
create policy rappel_reglage_insert on public.rappel_reglage for insert to authenticated
  with check (user_id = auth.uid());
drop policy if exists rappel_reglage_update on public.rappel_reglage;
create policy rappel_reglage_update on public.rappel_reglage for update to authenticated
  using (user_id = auth.uid()) with check (user_id = auth.uid());
drop policy if exists rappel_reglage_delete on public.rappel_reglage;
create policy rappel_reglage_delete on public.rappel_reglage for delete to authenticated
  using (user_id = auth.uid());

revoke all on public.rappel_reglage from anon;
/* `truncate` vide la table en ignorant la RLS ; `references` et `trigger` n'ont rien à faire entre les mains d'un
   membre. Il garde select, insert, update, delete : la RLS les borne à ses propres lignes. */
revoke truncate, references, trigger on public.rappel_reglage from anon, authenticated;

/* « Ça ne change pas » ne s'écrit pas en policy : une policy ne voit jamais l'ancienne et la nouvelle ligne
   ensemble. Le membre et le type d'une ligne ne se déplacent donc jamais (un `update … set user_id` qui passerait
   la ligne à l'autre membre serait de toute façon refusé par `with check`, mais le type, lui, est la clé). */
create or replace function public.tg_rappel_reglage_gele()
returns trigger language plpgsql set search_path = public, pg_temp as $$
begin
  if new.user_id is distinct from old.user_id or new.type is distinct from old.type then
    raise exception 'Le membre et le type d''un réglage ne changent pas.' using errcode = 'check_violation';
  end if;
  new.modifie_le := clock_timestamp();
  return new;
end $$;

drop trigger if exists tg_rappel_reglage_gele on public.rappel_reglage;
create trigger tg_rappel_reglage_gele before update on public.rappel_reglage
  for each row execute function public.tg_rappel_reglage_gele();

-- ── 2. Ce qui est parti : le verrou contre le double envoi ──────────────────
create table if not exists public.rappel_envoye (
  user_id   uuid not null references public.user_profile(id) on delete cascade,
  type      text not null,
  cle       text not null,
  envoye_le timestamptz not null default now(),
  primary key (user_id, type, cle)
);
comment on table public.rappel_envoye is
  'Un rappel parti (ou en train de partir) : membre, type, clé. Unique : jamais deux fois. Écrit par la fonction `rappels` seule.';

/* Aucune policy : ni lecture ni écriture côté client. Le rôle de service contourne la RLS. */
alter table public.rappel_envoye enable row level security;
revoke all on public.rappel_envoye from anon, authenticated;
revoke truncate, references, trigger on public.rappel_envoye from anon, authenticated;

-- ── 2 bis. Le journal des passages : ça tourne, ou ça ne tourne pas ───────────
-- Une ligne par appel du réveil horaire (`origine = 'cron'` : appelée, ou pas de secret, ou erreur) et une par
-- résultat de la fonction (`origine = 'fonction'` : combien dus, envoyés, en échec). Aucune adresse, aucun contenu.
create table if not exists public.rappel_passe (
  id       bigint generated always as identity primary key,
  le       timestamptz not null default now(),
  origine  text not null check (origine in ('cron', 'fonction')),
  statut   text not null,
  dus      integer,
  envoyes  integer,
  echecs   integer
);
comment on table public.rappel_passe is
  'Le journal des passages des rappels : moment, statut, nombre dus, envoyés, échecs. Ni adresse ni contenu. Service seul.';
create index if not exists rappel_passe_le on public.rappel_passe (le desc);
alter table public.rappel_passe enable row level security;
revoke all on public.rappel_passe from anon, authenticated;
revoke truncate, references, trigger on public.rappel_passe from anon, authenticated;

-- ── 3. Les prénoms, et les membres qui ont activé un type ────────────────────
/* Un prénom, normalisé PARTOUT de la même façon (le destinataire, « pour qui », « qui doit poser son revenu ») :
   les blancs de bout retirés, le premier mot seulement (comme `prenom_de`, que la clôture emploie), 40 signes au
   plus, et un repli sûr quand il est vide : « toi » pour le destinataire, « Quelqu’un » pour un autre. */
create or replace function public.rappel_prenom(p_nom text, p_repli text)
returns text language sql immutable set search_path = public, pg_temp as $$
  select coalesce(nullif(left(split_part(btrim(coalesce(p_nom, '')), ' ', 1), 40), ''), p_repli)
$$;

-- Un membre sans adresse, banni, supprimé, ou dont l'adresse n'est pas confirmée n'est pas joignable : rien à lui envoyer.
create or replace function public.rappel_actifs(p_type text)
returns table (uid uuid, foyer uuid, prenom text, email text)
language sql stable security definer set search_path = public, pg_temp as $$
  select p.id, p.household_id,
         public.rappel_prenom(p.display_name, 'toi'),
         u.email::text
  from public.rappel_reglage r
  join public.user_profile p on p.id = r.user_id
  join auth.users u on u.id = p.id
  where r.type = p_type and r.actif
    and u.email is not null and btrim(u.email) <> ''
    and u.email_confirmed_at is not null
    and u.deleted_at is null
    and (u.banned_until is null or u.banned_until <= now())
$$;

/* Le point d'un repas dans la semaine : `congelateur`, `frigo`, `autre` (sauté, ou autre chose qu'une barquette),
   `vide`. C'est la lecture de `contenuDe` (src/lib/choix.ts), côté base : une case « prévue » sans barquette ni
   extra est VIDE (on ne sait pas), « sauté » est une réponse. */
create or replace function public.rappel_point(p_uid uuid, p_jour date, p_repas text)
returns text language sql stable security definer set search_path = public, pg_temp as $$
  select coalesce((
    select case
      when s.state = 'saute' then 'autre'
      when po.id is not null then case when po.location = 'congelateur' then 'congelateur' else 'frigo' end
      when exists (select 1 from public.meal_extra e where e.meal_slot_id = s.id) then 'autre'
      else 'vide'
    end
    from public.meal_slot s
    left join public.portion po on po.id = s.portion_id
    where s.user_profile_id = p_uid and s.day = p_jour and s.meal = p_repas
  ), 'vide')
$$;

-- ── 4. Ce qui est dû à cet instant ──────────────────────────────────────────
-- Rend, pour chaque rappel dû : le membre, son adresse, son prénom, le type, la clé (ce qui identifie CE rappel :
-- un jour, une semaine, un mois, une barquette…), toutes les clés que ce mail couvre (`cles`, qui sert à
-- `reserve_rappel` : un mail pour trois lasagnes réserve les trois barquettes) et les données du gabarit.
-- Rien n'est dû si le rappel est coupé, si la clé est déjà dans `rappel_envoye`, ou si l'heure n'est pas venue.
-- L'heure est celle de Paris : « 19 h » veut dire 19 h à Paris, été comme hiver.
create or replace function public.rappels_a_envoyer(p_maintenant timestamptz)
returns table (user_id uuid, email text, prenom text, type text, cle text, cles text[], donnees jsonb)
language plpgsql stable security definer set search_path = public, pg_temp
as $$
declare
  v_aujourdhui date := (p_maintenant at time zone 'Europe/Paris')::date;
  v_heure     time := (p_maintenant at time zone 'Europe/Paris')::time;
  v_demain    date := ((p_maintenant at time zone 'Europe/Paris')::date + 1);
  v_mois      date := date_trunc('month', (p_maintenant at time zone 'Europe/Paris'))::date;
  v_mois_prec date := (date_trunc('month', (p_maintenant at time zone 'Europe/Paris')) - interval '1 month')::date;
  v_dernier_jour date := (date_trunc('month', (p_maintenant at time zone 'Europe/Paris')) + interval '1 month - 1 day')::date;
  v_semaine   text := to_char((p_maintenant at time zone 'Europe/Paris')::date, 'IYYY"-W"IW');
  v_debut_apres_demain timestamptz := (((p_maintenant at time zone 'Europe/Paris')::date + 2))::timestamp at time zone 'Europe/Paris';
begin
  if not public.is_service_role() then
    raise exception 'Réservé au rôle de service.' using errcode = 'insufficient_privilege';
  end if;

  -- ── sortir_du_congelateur : la veille à 19 h, pour un repas de demain qui porte une barquette congelée ──
  if v_heure >= time '19:00' then
    return query
    with a as (select * from public.rappel_actifs('sortir_du_congelateur')),
    sl as (
      select s.household_id as foyer, s.meal, s.portion_id, po.label, po.recipe_id, pr.display_name as qui,
             s.user_profile_id as qid
      from public.meal_slot s
      join public.portion po on po.id = s.portion_id
      join public.user_profile pr on pr.id = s.user_profile_id
      where s.day = v_demain and s.state = 'prevu'
        and po.location = 'congelateur' and po.state = 'au_frais'
        and s.household_id in (select foyer from a)
    )
    select a.uid, a.email, a.prenom, 'sortir_du_congelateur'::text, v_demain::text, array[v_demain::text],
           jsonb_build_object('jour', v_demain, 'plats', p.plats)
    from a
    cross join lateral (
      select jsonb_agg(g.obj order by g.ordre, g.nom) as plats
      from (
        select min(array_position(array['petit_dejeuner', 'dejeuner', 'collation', 'diner'], x.meal)) as ordre,
               x.label as nom,
               jsonb_build_object(
                 'label', x.label,
                 'recipe_id', x.recipe_id,
                 'image_url', max(r.image_url),
                 'n', count(distinct x.portion_id),
                 'portion_ids', jsonb_agg(distinct x.portion_id),
                 'restant', (select count(*) from public.portion q
                             where q.household_id = a.foyer and q.location = 'congelateur' and q.state = 'au_frais'
                               and q.label = x.label and q.recipe_id is not distinct from x.recipe_id
                               and q.id not in (select portion_id from sl where foyer = a.foyer)),
                 'repas', (select jsonb_agg(jsonb_build_object('meal', y.meal, 'pour', y.pour)
                                            order by array_position(array['petit_dejeuner', 'dejeuner', 'collation', 'diner'], y.meal))
                           /* « pour qui », vu du destinataire : lui-même sous le prénom que le mail lui donne (`a.prenom`),
                                       les autres sous leur prénom normalisé. */
                           from (select sl2.meal,
                                        jsonb_agg(distinct case when sl2.qid = a.uid then a.prenom
                                                                else public.rappel_prenom(sl2.qui, 'Quelqu’un') end) as pour
                                 from sl sl2
                                 where sl2.foyer = a.foyer and sl2.label = x.label
                                   and sl2.recipe_id is not distinct from x.recipe_id
                                 group by sl2.meal) y)
               ) as obj
        from sl x
        left join public.recipe r on r.id = x.recipe_id
        where x.foyer = a.foyer
        group by x.label, x.recipe_id
      ) g
    ) p
    where p.plats is not null
      and not exists (select 1 from public.rappel_envoye e
                      where e.user_id = a.uid and e.type = 'sortir_du_congelateur' and e.cle = v_demain::text);
  end if;

  -- ── barquette_perime : à 8 h, UN mail par membre et par jour pour ce qui périme avant demain soir ──
  -- Dans la fenêtre : une barquette du frigo qui périme avant la fin de demain, ou qui a péri il y a moins de 24 h
  -- (le mail dit alors « périmée : à jeter »). « Prévue nulle part » : aucun repas à venir ne la réclame À TEMPS ;
  -- une barquette prévue pour un repas APRÈS sa péremption compte comme non prévue, et le mail le dit
  -- (`tardives` : le jour du repas de chacune de ces barquettes). Une réclamation d'un jour PASSÉ est un repas que personne n'a noté, pas
  -- une vraie réservation (comme 0122).
  -- La clé du mail est la DATE : un seul par jour et par membre. Chaque barquette qu'il couvre est réservée avec
  -- (`cles`), donc une barquette déjà annoncée ne l'est jamais deux fois, et une barquette qui arrive après le
  -- passage de 8 h attend le lendemain (un mail perdu vaut mieux qu'un doublon).
  if v_heure >= time '08:00' then
    return query
    with a as (
      select x.* from public.rappel_actifs('barquette_perime') x
      where not exists (select 1 from public.rappel_envoye e
                        where e.user_id = x.uid and e.type = 'barquette_perime' and e.cle = v_aujourdhui::text)
    ),
    pe as (
      select a.uid, a.foyer, po.id as pid, po.label, po.recipe_id, po.expires_at,
             (select min(s.day) from public.meal_slot s
              where s.portion_id = po.id and s.state = 'prevu' and s.day >= v_aujourdhui
                and s.day > (po.expires_at at time zone 'Europe/Paris')::date) as tardive
      from a
      join public.portion po on po.household_id = a.foyer
      where po.location = 'frigo' and po.state in ('au_frais', 'decongelee')
        and po.expires_at >= p_maintenant - interval '24 hours' and po.expires_at < v_debut_apres_demain
        and not exists (select 1 from public.meal_slot s
                        where s.portion_id = po.id and s.state = 'prevu' and s.day >= v_aujourdhui
                          and s.day <= (po.expires_at at time zone 'Europe/Paris')::date)
        and not exists (select 1 from public.rappel_envoye e
                        where e.user_id = a.uid and e.type = 'barquette_perime' and e.cle = po.id::text)
    ),
    pl as (
      select pe.uid, pe.label, pe.recipe_id, count(*) as n, min(pe.expires_at) as expire,
             jsonb_agg(pe.pid order by pe.pid) as ids,
             coalesce(jsonb_agg(pe.tardive order by pe.tardive) filter (where pe.tardive is not null), '[]'::jsonb) as tardives,
             max(r.image_url) as image_url
      from pe
      left join public.recipe r on r.id = pe.recipe_id
      group by pe.uid, pe.label, pe.recipe_id
    )
    select a.uid, a.email, a.prenom, 'barquette_perime'::text, v_aujourdhui::text,
           array[v_aujourdhui::text] || (select array_agg(pe.pid::text order by pe.pid::text) from pe where pe.uid = a.uid),
           jsonb_build_object(
             'n', (select count(*) from pe where pe.uid = a.uid),
             'plats', (select jsonb_agg(jsonb_build_object(
                                 'label', pl.label, 'recipe_id', pl.recipe_id, 'image_url', pl.image_url,
                                 'n', pl.n, 'portion_ids', pl.ids, 'expire', pl.expire, 'tardives', pl.tardives)
                               order by pl.expire, pl.label)
                       from pl where pl.uid = a.uid))
    from a
    where exists (select 1 from pe where pe.uid = a.uid);
  end if;

  -- ── choisir_les_repas : le dimanche à 18 h, s'il reste des dîners vides dans les 7 jours suivants ──
  if extract(isodow from v_aujourdhui) = 7 and v_heure >= time '18:00' then
    return query
    select a.uid, a.email, a.prenom, 'choisir_les_repas'::text, v_semaine, array[v_semaine],
           jsonb_build_object(
             'semaine', v_semaine, 'vides', j.vides, 'jours', j.jours,
             'congelateur', (select count(*) from public.portion q
                             where q.household_id = a.foyer and q.location = 'congelateur' and q.state = 'au_frais'),
             'frigo', (select count(*) from public.portion q
                       where q.household_id = a.foyer and q.location = 'frigo' and q.state in ('au_frais', 'decongelee')))
    from public.rappel_actifs('choisir_les_repas') a
    cross join lateral (
      select jsonb_agg(jsonb_build_object('jour', d.jour, 'midi', d.midi, 'soir', d.soir) order by d.jour) as jours,
             count(*) filter (where d.soir = 'vide') as vides
      from (select (v_aujourdhui + g)::date as jour,
                   public.rappel_point(a.uid, (v_aujourdhui + g)::date, 'dejeuner') as midi,
                   public.rappel_point(a.uid, (v_aujourdhui + g)::date, 'diner') as soir
            from generate_series(1, 7) g) d
    ) j
    where j.vides > 0
      and not exists (select 1 from public.rappel_envoye e
                      where e.user_id = a.uid and e.type = 'choisir_les_repas' and e.cle = v_semaine);
  end if;

  -- ── noter_les_depenses : le dimanche à 20 h, si rien n'a été noté depuis 7 jours ──
  -- Les dépenses du mois vivent dans `saisie` (une par dépense déclarée sur une ligne « au fil du mois »). Il n'y
  -- a quelque chose à noter que si le mois a une telle ligne dont le membre porte une part.
  if extract(isodow from v_aujourdhui) = 7 and v_heure >= time '20:00' then
    return query
    select a.uid, a.email, a.prenom, 'noter_les_depenses'::text, v_semaine, array[v_semaine],
           jsonb_build_object(
             'mois', v_mois, 'semaine', v_semaine,
             'depuis_jours', (select v_aujourdhui - max(s.fait_le) from public.saisie s where s.household_id = a.foyer),
             'lignes', (select count(*) from public.depense d
                        join public.depense_part dp on dp.depense_id = d.id and dp.user_profile_id = a.uid
                        where d.household_id = a.foyer and d.mois = v_mois and d.facon = 'au_fil'))
    from public.rappel_actifs('noter_les_depenses') a
    where exists (select 1 from public.depense d
                  join public.depense_part dp on dp.depense_id = d.id and dp.user_profile_id = a.uid
                  where d.household_id = a.foyer and d.mois = v_mois and d.facon = 'au_fil')
      and not exists (select 1 from public.saisie s
                      where s.household_id = a.foyer
                        and (s.fait_le > v_aujourdhui - 7 or s.created_at > p_maintenant - interval '7 days'))
      and not exists (select 1 from public.rappel_envoye e
                      where e.user_id = a.uid and e.type = 'noter_les_depenses' and e.cle = v_semaine);
  end if;

  -- ── confirmer_les_charges : le 1er à 9 h, s'il y a des lignes du MOIS FINI à confirmer ──
  -- Les lignes à confirmer sont celles de la clôture, première étape : les factures du mois qui vient de finir
  -- (`facon = 'facture'`, `confirme_le` vide), tant que le mois n'est pas clôturé.
  if extract(day from v_aujourdhui) = 1 and v_heure >= time '09:00' then
    return query
    select a.uid, a.email, a.prenom, 'confirmer_les_charges'::text, to_char(v_mois_prec, 'YYYY-MM'),
           array[to_char(v_mois_prec, 'YYYY-MM')],
           jsonb_build_object('mois', v_mois_prec, 'n', l.n, 'lignes', l.lignes)
    from public.rappel_actifs('confirmer_les_charges') a
    cross join lateral (
      select count(*) as n,
             coalesce(jsonb_agg(jsonb_build_object('libelle', x.libelle, 'montant_cents', x.montant_cents)
                                order by x.libelle) filter (where x.rang <= 6), '[]'::jsonb) as lignes
      from (select d.libelle, d.montant_cents,
                   row_number() over (order by d.libelle) as rang
            from public.depense d
            join public.depense_part dp on dp.depense_id = d.id and dp.user_profile_id = a.uid
            where d.household_id = a.foyer and d.mois = v_mois_prec and d.facon = 'facture' and d.confirme_le is null
              and not exists (select 1 from public.cloture c where c.household_id = a.foyer and c.mois = v_mois_prec)) x
    ) l
    where l.n > 0
      and not exists (select 1 from public.rappel_envoye e
                      where e.user_id = a.uid and e.type = 'confirmer_les_charges' and e.cle = to_char(v_mois_prec, 'YYYY-MM'));
  end if;

  -- ── cloturer_le_mois : le dernier jour du mois à 19 h, si le mois n'est pas clos ──
  -- Un mois se clôture à partir du 1er du suivant, et seulement pour qui y avait un revenu et était dans le foyer
  -- (`budget-cloture-quand`) : on prévient donc ce soir-là, la veille. Un mois sans aucune ligne à son nom n'a
  -- rien à clore.
  if v_aujourdhui = v_dernier_jour and v_heure >= time '19:00' then
    return query
    select a.uid, a.email, a.prenom, 'cloturer_le_mois'::text, to_char(v_mois, 'YYYY-MM'), array[to_char(v_mois, 'YYYY-MM')],
           jsonb_build_object(
             'mois', v_mois,
             'lignes', (select count(*) from public.depense d
                        join public.depense_part dp on dp.depense_id = d.id and dp.user_profile_id = a.uid
                        where d.household_id = a.foyer and d.mois = v_mois),
             'a_confirmer', (select count(*) from public.depense d
                             join public.depense_part dp on dp.depense_id = d.id and dp.user_profile_id = a.uid
                             where d.household_id = a.foyer and d.mois = v_mois
                               and d.facon = 'facture' and d.confirme_le is null),
             /* Les gardes de `cloture_le_mois` (0108) : chaque AUTRE membre présent ce mois-là doit avoir posé son
                revenu, sinon le partage basculerait à moitié-moitié et la clôture le figerait. Le mail le dit
                au lieu de promettre une clôture qui sera refusée. */
             'absent', (select public.rappel_prenom(o.display_name, 'Quelqu’un')
                        from public.user_profile o
                        where o.household_id = a.foyer and o.id <> a.uid and o.entre_le <= v_dernier_jour
                          and not exists (select 1 from public.revenu v
                                          where v.user_profile_id = o.id and v.household_id = a.foyer
                                            and v.valid_from <= v_dernier_jour)
                        order by o.created_at limit 1))
    from public.rappel_actifs('cloturer_le_mois') a
    join public.user_profile up on up.id = a.uid
    where up.entre_le <= v_dernier_jour
      and exists (select 1 from public.revenu rv
                  where rv.user_profile_id = a.uid and rv.household_id = a.foyer and rv.valid_from <= v_dernier_jour)
      and exists (select 1 from public.depense d
                  join public.depense_part dp on dp.depense_id = d.id and dp.user_profile_id = a.uid
                  where d.household_id = a.foyer and d.mois = v_mois)
      and not exists (select 1 from public.cloture c where c.household_id = a.foyer and c.mois = v_mois)
      and not exists (select 1 from public.rappel_envoye e
                      where e.user_id = a.uid and e.type = 'cloturer_le_mois' and e.cle = to_char(v_mois, 'YYYY-MM'));
  end if;

  -- ── facture_annuelle : 15 jours avant le mois où une charge annuelle se paie, UN mail par membre et par jour ──
  -- Une charge annuelle (« mise de côté ») ne porte pas de date d'échéance : la seule trace du mois où elle se
  -- paie est la dernière facture saisie (`facture.paye_le`). Sans facture passée, rien à annoncer. Le jour du
  -- rappel : le 1er de ce mois-là, moins 15 jours, cette année ou la prochaine (un mois de janvier se prévient
  -- en décembre). Pas de rappel si la facture de l'année est déjà saisie. Deux charges le même jour : un seul
  -- mail, qui les liste. La clé est la date ; chaque charge (« charge:année ») est réservée avec.
  if v_heure >= time '09:00' then
    return query
    with due as (
      select a.uid, a.email, a.prenom, c.id as charge_id, c.libelle, y.annee, f.paye_le, f.montant_cents,
             make_date(y.annee, extract(month from f.paye_le)::int, 1) as mois
      from public.rappel_actifs('facture_annuelle') a
      join public.charge_participant cp on cp.user_profile_id = a.uid
      join public.charge c on c.id = cp.charge_id
      cross join lateral (
        select fa.paye_le, fa.montant_cents from public.facture fa
        where fa.charge_id = c.id and fa.origine = 'saisie'
        order by fa.paye_le desc limit 1) f
      cross join lateral (
        select yy as annee from unnest(array[extract(year from v_aujourdhui)::int,
                                             extract(year from v_aujourdhui)::int + 1]) yy) y
      where c.periodicite = 'annuel' and c.archive_le is null and (c.fin is null or c.fin >= v_aujourdhui)
        and make_date(y.annee, extract(month from f.paye_le)::int, 1) - 15 = v_aujourdhui
        and not exists (select 1 from public.facture fa
                        where fa.charge_id = c.id and fa.origine = 'saisie' and fa.annee = y.annee)
        and not exists (select 1 from public.rappel_envoye e
                        where e.user_id = a.uid and e.type = 'facture_annuelle'
                          and e.cle in (v_aujourdhui::text, c.id::text || ':' || y.annee::text))
    )
    select d.uid, d.email, d.prenom, 'facture_annuelle'::text, v_aujourdhui::text,
           array[v_aujourdhui::text] || array_agg(d.charge_id::text || ':' || d.annee::text order by d.libelle, d.charge_id),
           jsonb_build_object(
             'n', count(*),
             'charges', jsonb_agg(jsonb_build_object(
                          'charge_id', d.charge_id, 'libelle', d.libelle, 'annee', d.annee, 'mois', d.mois,
                          'derniere_paye_le', d.paye_le, 'derniere_montant_cents', d.montant_cents)
                        order by d.libelle, d.charge_id))
    from due d
    group by d.uid, d.email, d.prenom;
  end if;
end $$;

-- ── 5. Réserver, libérer : le verrou de l'envoi ─────────────────────────────
-- `reserve_rappel` pose TOUTES les clés d'un mail d'un coup, ou aucune : vrai si c'est fait, faux si l'une était
-- déjà prise (un autre passage l'a eue). Elle rend faux plutôt que de lever une erreur : « déjà parti » est une
-- réponse normale. `libere_rappel` rend les clés quand l'envoi a échoué, pour que l'heure suivante réessaie.
create or replace function public.reserve_rappel(p_user uuid, p_type text, p_cles text[])
returns boolean language plpgsql security definer set search_path = public, pg_temp as $$
begin
  if not public.is_service_role() then
    raise exception 'Réservé au rôle de service.' using errcode = 'insufficient_privilege';
  end if;
  if p_cles is null or cardinality(p_cles) = 0 then return false; end if;
  /* Coupé entre la lecture et l'envoi : on ne réserve plus, donc rien ne part. Un exemple (`essai:…`) n'est pas un
     rappel et se demande coupé. */
  if exists (select 1 from unnest(p_cles) c where c not like 'essai:%')
     and not exists (select 1 from public.rappel_reglage r where r.user_id = p_user and r.type = p_type and r.actif) then
    return false;
  end if;
  if exists (select 1 from public.rappel_envoye e
             where e.user_id = p_user and e.type = p_type and e.cle = any (p_cles)) then
    return false;
  end if;
  insert into public.rappel_envoye (user_id, type, cle)
  select p_user, p_type, c from (select distinct unnest(p_cles) as c) x;
  return true;
exception when unique_violation then
  /* Deux passages en même temps : celui qui perd rend faux, et ses insertions partielles sont défaites avec le
     bloc. */
  return false;
end $$;

create or replace function public.libere_rappel(p_user uuid, p_type text, p_cles text[])
returns void language plpgsql security definer set search_path = public, pg_temp as $$
begin
  if not public.is_service_role() then
    raise exception 'Réservé au rôle de service.' using errcode = 'insufficient_privilege';
  end if;
  delete from public.rappel_envoye where user_id = p_user and type = p_type and cle = any (p_cles);
end $$;

-- ── 5 bis. Préparer la passe : ouvrir les mois, purger ──────────────────────
-- L'ouverture d'un mois du budget est PARESSEUSE : c'est la première lecture de l'écran qui crée ses lignes
-- (`ouvre_le_mois`). Un mois que personne n'a ouvert n'a donc ni facture à confirmer, ni ligne « au fil » : les
-- rappels du budget ne le verraient pas. Avant de lire quoi que ce soit, la fonction edge appelle donc celle-ci :
-- pour chaque foyer où un membre a activé un rappel du budget, elle ouvre le mois fini et le mois en cours
-- (idempotent, comme l'écran ; un mois clôturé ne gagne aucune ligne). Elle ne rattrape que ces deux mois : ce
-- sont les seuls que les rappels lisent.
-- Elle purge aussi : les lignes de `rappel_envoye` et de `rappel_passe` de plus de 120 jours.
-- `ouvre_le_mois` ne laisse passer un foyer explicite que pour le rôle de service, et le lit dans les revendications
-- de la requête (`is_service_role`) : sous `security definer`, `current_user` n'est plus le rôle appelant. Elles sont
-- donc posées pour la durée de la transaction, puis rendues.
create or replace function public.prepare_les_rappels(p_maintenant timestamptz)
returns jsonb language plpgsql security definer set search_path = public, pg_temp as $$
declare
  v_mois      date := date_trunc('month', (p_maintenant at time zone 'Europe/Paris'))::date;
  v_mois_prec date := (date_trunc('month', (p_maintenant at time zone 'Europe/Paris')) - interval '1 month')::date;
  v_avant     text := current_setting('request.jwt.claims', true);
  v_purges    integer := 0;
  v_lignes    integer := 0;
  v_erreurs   integer := 0;
  v_foyers    integer := 0;
  v_foyer     uuid;
  v_m         date;
begin
  if not public.is_service_role() then
    raise exception 'Réservé au rôle de service.' using errcode = 'insufficient_privilege';
  end if;

  delete from public.rappel_envoye where envoye_le < p_maintenant - interval '120 days';
  get diagnostics v_purges = row_count;
  delete from public.rappel_passe where le < p_maintenant - interval '120 days';

  perform set_config('request.jwt.claims', '{"role":"service_role"}', true);
  for v_foyer in
    select distinct x.foyer from (
      select foyer from public.rappel_actifs('noter_les_depenses')
      union all select foyer from public.rappel_actifs('confirmer_les_charges')
      union all select foyer from public.rappel_actifs('cloturer_le_mois')) x
  loop
    v_foyers := v_foyers + 1;
    foreach v_m in array array[v_mois_prec, v_mois] loop
      begin
        v_lignes := v_lignes + coalesce(public.ouvre_le_mois(v_m, v_foyer), 0);
      exception when others then
        /* Un foyer qui échoue ne bloque ni les autres ni les rappels de la cuisine. */
        v_erreurs := v_erreurs + 1;
        raise warning 'rappels : le mois % d''un foyer n''a pas pu être ouvert (%)', v_m, sqlerrm;
      end;
    end loop;
  end loop;
  perform set_config('request.jwt.claims', coalesce(v_avant, ''), true);

  return jsonb_build_object('purges', v_purges, 'foyers', v_foyers, 'lignes_nees', v_lignes, 'erreurs', v_erreurs);
end $$;

-- Le résultat d'une passe, écrit par la fonction edge : combien dus, envoyés, en échec. Aucune adresse.
create or replace function public.note_la_passe(p_statut text, p_dus integer, p_envoyes integer, p_echecs integer)
returns void language plpgsql security definer set search_path = public, pg_temp as $$
begin
  if not public.is_service_role() then
    raise exception 'Réservé au rôle de service.' using errcode = 'insufficient_privilege';
  end if;
  if p_statut not in ('ok', 'echecs', 'erreur') then
    raise exception 'Statut de passe inconnu.' using errcode = 'check_violation';
  end if;
  insert into public.rappel_passe (origine, statut, dus, envoyes, echecs)
  values ('fonction', p_statut, p_dus, p_envoyes, p_echecs);
end $$;

-- ── 6. Le réveil horaire : pg_cron appelle la fonction edge, par pg_net ─────
-- L'adresse et le secret viennent de Vault ; l'un des deux manque, on ne fait rien (c'est l'état d'une base
-- locale, et celui d'une production où personne n'a encore posé les secrets) — mais on le DIT, dans
-- `rappel_passe` : une panne se voit. Statuts : `sans_extension` (pg_net ou Vault absent), `sans_secret`,
-- `appelee`, `erreur`. `pg_net` répond de façon asynchrone : le résultat de la passe est écrit par la fonction
-- (`note_la_passe`). Son délai est de 60 s : une passe qui envoie plusieurs mails dépasse les 25 s d'avant.
create or replace function public.appelle_les_rappels()
returns void language plpgsql security definer set search_path = public, pg_temp as $$
declare
  v_url text;
  v_secret text;
begin
  delete from public.rappel_passe where le < now() - interval '120 days';
  if to_regclass('vault.decrypted_secrets') is null or to_regnamespace('net') is null then
    insert into public.rappel_passe (origine, statut) values ('cron', 'sans_extension');
    return;
  end if;
  execute $q$select decrypted_secret from vault.decrypted_secrets where name = 'rappels_url' limit 1$q$ into v_url;
  execute $q$select decrypted_secret from vault.decrypted_secrets where name = 'rappels_secret' limit 1$q$ into v_secret;
  if coalesce(btrim(v_url), '') = '' or coalesce(btrim(v_secret), '') = '' then
    insert into public.rappel_passe (origine, statut) values ('cron', 'sans_secret');
    return;
  end if;
  begin
    perform net.http_post(
      url := v_url,
      headers := jsonb_build_object('Content-Type', 'application/json', 'x-rappels-secret', v_secret),
      body := '{}'::jsonb,
      timeout_milliseconds := 60000);
    insert into public.rappel_passe (origine, statut) values ('cron', 'appelee');
  exception when others then
    insert into public.rappel_passe (origine, statut) values ('cron', 'erreur');
  end;
end $$;

/* Rien de tout ceci n'est appelable du dehors. `rappel_actifs` et `rappel_point` lisent `auth.users` ou le
   repas de n'importe qui : elles ne servent qu'à `rappels_a_envoyer`. */
revoke all on function public.rappel_prenom(text, text) from public, anon, authenticated;
revoke all on function public.rappel_actifs(text) from public, anon, authenticated;
revoke all on function public.rappel_point(uuid, date, text) from public, anon, authenticated;
revoke all on function public.rappels_a_envoyer(timestamptz) from public, anon, authenticated;
revoke all on function public.prepare_les_rappels(timestamptz) from public, anon, authenticated;
revoke all on function public.note_la_passe(text, integer, integer, integer) from public, anon, authenticated;
revoke all on function public.reserve_rappel(uuid, text, text[]) from public, anon, authenticated;
revoke all on function public.libere_rappel(uuid, text, text[]) from public, anon, authenticated;
revoke all on function public.appelle_les_rappels() from public, anon, authenticated;
grant execute on function public.rappel_prenom(text, text) to service_role;
grant execute on function public.rappel_actifs(text) to service_role;
grant execute on function public.rappel_point(uuid, date, text) to service_role;
grant execute on function public.rappels_a_envoyer(timestamptz) to service_role;
grant execute on function public.prepare_les_rappels(timestamptz) to service_role;
grant execute on function public.note_la_passe(text, integer, integer, integer) to service_role;
grant execute on function public.reserve_rappel(uuid, text, text[]) to service_role;
grant execute on function public.libere_rappel(uuid, text, text[]) to service_role;

/* Les extensions et la planification, tolérantes : une base locale sans `pg_cron` ou sans `pg_net` ne doit pas
   empêcher la migration. Sans elles, les rappels ne partent simplement pas (le réglage et l'écran existent quand
   même). EN PRODUCTION, en revanche, un job absent est une panne : le contrôle de la fin la dit. */
do $$
begin
  begin
    create extension if not exists pg_net with schema extensions;
  exception when others then
    raise notice 'pg_net indisponible (%) : le job des rappels ne pourra pas appeler la fonction.', sqlerrm;
  end;
  begin
    create extension if not exists pg_cron;
  exception when others then
    raise notice 'pg_cron indisponible (%) : les rappels ne seront pas planifiés.', sqlerrm;
  end;
  if exists (select 1 from pg_extension where extname = 'pg_cron') then
    begin
      execute $q$select cron.schedule('rappels-par-mail', '5 * * * *', 'select public.appelle_les_rappels()')$q$;
    exception when others then
      raise notice 'Planification des rappels impossible (%).', sqlerrm;
    end;
  end if;
end $$;

/* Le contrôle de la fin : le job existe-t-il vraiment ? Sinon, un AVERTISSEMENT explicite (pas une erreur : la
   migration doit passer en local, où les extensions peuvent manquer), que la sortie de `supabase db push` montre. */
do $$
declare
  v_present boolean := false;
begin
  if to_regclass('cron.job') is not null then
    execute $q$select exists (select 1 from cron.job where jobname = 'rappels-par-mail')$q$ into v_present;
  end if;
  if not v_present then
    raise warning 'LES RAPPELS NE SONT PAS PLANIFIÉS : le job « rappels-par-mail » n''existe pas dans cron.job. '
      'Active les extensions pg_cron et pg_net (Database > Extensions), puis rejoue la planification '
      '(select cron.schedule(''rappels-par-mail'', ''5 * * * *'', ''select public.appelle_les_rappels()'')). '
      'Sans elle, aucun mail ne part, et rien d''autre ne le dit.';
  end if;
end $$;

-- ── À POSER EN PRODUCTION, à la main, une fois (rien de secret n'est écrit ici) ─────────────────────────────
--   select vault.create_secret('https://<projet>.supabase.co/functions/v1/rappels', 'rappels_url');
--   select vault.create_secret('<le même secret que RAPPELS_SECRET de la fonction>', 'rappels_secret');
-- Et, côté fonction : GMAIL_USER, GMAIL_APP_PASSWORD, APP_BASE_URL, RAPPELS_SECRET.
