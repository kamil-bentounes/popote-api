-- ═══════════════════════════════════════════════════════════════════════════
-- LES CHARGES ET LES DÉPENSES
--
-- Il n'y a qu'UNE liste de charges par foyer. Pas « les communes » d'un côté et
-- « les perso » de l'autre qu'il faudrait synchroniser : chaque ligne dit qui
-- participe, et « perso » n'est que le cas où il n'y a qu'une personne dedans.
-- C'est ce qui évite deux listes qui divergent au premier mois.
--
-- Une CHARGE est un modèle. Une DÉPENSE est une ligne de mois, engendrée ou
-- saisie, qui porte son partage FIGÉ en centimes (D60). Une fois posée, elle ne
-- dépend plus de rien : ni du revenu de l'époque, ni de la règle du foyer, ni
-- même de l'existence de la charge qui l'a produite.
-- ═══════════════════════════════════════════════════════════════════════════

-- ── La charge : le modèle ──────────────────────────────────────────────────
create table public.charge (
  id            uuid primary key default gen_random_uuid(),
  household_id  uuid not null references public.household(id) on delete cascade,
  /* La ligne du catalogue dont elle vient, quand elle en vient. NULL pour une
     charge inventée : le catalogue propose, il n'enferme pas. */
  catalogue_id  uuid references public.catalogue_charge(id) on delete set null,
  libelle       text not null check (length(btrim(libelle)) between 1 and 80),
  /* Le montant POUR SA PÉRIODE : 1450 € pour un foncier annuel, 300 € pour une
     copro trimestrielle. La provision mensuelle s'en déduit. */
  montant_cents integer not null check (montant_cents >= 0),
  periodicite   text not null check (periodicite in ('mensuel', 'trimestriel', 'annuel')),
  /* Variable : le montant n'est qu'une provision, et l'app demandera le réel en
     fin de mois. L'énergie à la consommation, typiquement. */
  variable      boolean not null default false,
  /* NULL = la règle du foyer. Sinon la charge impose la sienne — c'est ainsi
     que « les courses au prorata mais Netflix à 50/50 » se dit. */
  cle           text check (cle in ('prorata', 'moitie')),
  /* Le compte débité. C'est l'écart entre qui doit et qui paie qui fait le
     solde ; sans lui, l'app ne pourrait annoncer qu'un montant, pas un virement. */
  compte_id     uuid references public.compte(id) on delete set null,
  debut         date not null,
  fin           date,
  created_at    timestamptz not null default now(),
  constraint charge_fin_apres_debut check (fin is null or fin >= debut),
  constraint charge_debut_borne
    check (debut between '2000-01-01'::date and (current_date + interval '5 years')::date)
);

-- ── Qui participe ──────────────────────────────────────────────────────────
-- Une charge sans participant ne concerne personne : le trigger plus bas refuse
-- d'ouvrir un mois sur une charge vide plutôt que d'engendrer une dépense que
-- nul ne paie.
create table public.charge_participant (
  charge_id       uuid not null references public.charge(id) on delete cascade,
  user_profile_id uuid not null references public.user_profile(id) on delete cascade,
  household_id    uuid not null references public.household(id) on delete cascade,
  primary key (charge_id, user_profile_id)
);

-- ── La dépense : la ligne d'un mois ────────────────────────────────────────
create table public.depense (
  id            uuid primary key default gen_random_uuid(),
  household_id  uuid not null references public.household(id) on delete cascade,
  /* La charge qui l'a produite. `on delete set null` et non `cascade` : on
     supprime une charge quand elle cesse d'exister, pas pour effacer ce qu'elle
     a coûté. L'historique du budget survit à son modèle. */
  charge_id     uuid references public.charge(id) on delete set null,
  /* Le PREMIER jour du mois concerné. C'est la maille de tout le budget. */
  mois          date not null,
  libelle       text not null check (length(btrim(libelle)) between 1 and 80),
  montant_cents integer not null check (montant_cents >= 0),
  /* `provision` : le montant attendu, pas encore confronté au réel.
     `reelle` : le montant constaté. La régularisation transforme l'une en
     l'autre et émet l'écart. */
  nature        text not null default 'provision' check (nature in ('provision', 'reelle')),
  /* D67 : d'où vient la ligne. `reference_externe` permettra à l'agrégateur
     bancaire de RAPPROCHER au lieu de dupliquer. Deux colonnes aujourd'hui,
     aucun dédoublonnage plus tard. */
  source            text not null default 'modele'
                    check (source in ('modele', 'manuel', 'banque', 'courses')),
  reference_externe text,
  compte_id     uuid references public.compte(id) on delete set null,
  /* Qui a réellement avancé l'argent. NULL tant que ce n'est pas réglé. */
  paye_par      uuid references public.user_profile(id) on delete set null,
  regle_le      date,
  created_at    timestamptz not null default now(),
  /* L'idempotence du générateur tient dans cette contrainte : rouvrir novembre
     dix fois ne crée pas dix lignes. Sans elle, un générateur paresseux
     appelé à chaque ouverture de l'app produirait un doublon par visite. */
  unique (charge_id, mois),
  constraint depense_mois_premier_du_mois check (mois = date_trunc('month', mois)::date),
  constraint depense_reference_unique_par_foyer unique (household_id, reference_externe)
);

-- ── La part de chacun, FIGÉE, en centimes ──────────────────────────────────
--
-- Le cœur de D60. On stocke des CENTIMES, pas des pourcentages : 10,25 € en
-- 50/50 donne deux parts de 5,13 qui font 10,26, et la somme des parts ne
-- recompose plus le total. Le pourcentage n'est que la provenance ; ce qui
-- s'additionne, ce sont des entiers.
create table public.depense_part (
  depense_id      uuid not null references public.depense(id) on delete cascade,
  user_profile_id uuid not null references public.user_profile(id) on delete cascade,
  household_id    uuid not null references public.household(id) on delete cascade,
  part_cents      integer not null check (part_cents >= 0),
  /* Pour la trace : la clé qui a produit cette part, telle qu'elle était. */
  part_bps        integer not null check (part_bps between 0 and 10000),
  primary key (depense_id, user_profile_id)
);

comment on table public.depense_part is
  'La part de chacun sur une dépense, figée en centimes au moment où la dépense '
  'naît (D60). Ne dépend plus ensuite du revenu, de la règle, ni de la charge.';

-- ═══ La provision mensuelle d'une charge ═══════════════════════════════════
-- Une charge annuelle de 1450 € n'est pas « une dépense en octobre » : c'est
-- 120,83 € tous les mois (D61). Le reliquat de l'arrondi n'est pas rattrapé
-- ici : c'est la régularisation (D62) qui le solde quand le vrai montant arrive.
create or replace function public.provision_mensuelle(montant_cents integer, periodicite text)
returns integer language sql immutable as $$
  select case periodicite
           when 'mensuel'     then montant_cents
           when 'trimestriel' then round(montant_cents / 3.0)::integer
           when 'annuel'      then round(montant_cents / 12.0)::integer
         end
$$;

-- ═══ Ouvrir un mois ════════════════════════════════════════════════════════
--
-- Engendre une dépense par charge active ce mois-là, et fige les parts.
-- Idempotente : `on conflict do nothing` sur (charge_id, mois).
--
-- ⚠️ Elle doit tourner pour le rôle de service ET pour un authentifié. Le
--    premier l'appellera depuis une tâche planifiée, le second en ouvrant
--    l'app le 1er — il n'y a pas de `pg_cron` ici, donc l'ouverture est
--    paresseuse, et c'est justement pour ça qu'elle doit être idempotente :
--    la clé se fige au PREMIER appel, quel qu'il soit, et les suivants ne
--    touchent plus rien.
create or replace function public.ouvre_le_mois(le_mois date, le_foyer uuid default null)
returns integer
language plpgsql security definer set search_path = public as $$
declare
  foyer uuid := case when public.is_service_role() and le_foyer is not null
                     then le_foyer else public.current_household() end;
  debut_mois date := date_trunc('month', le_mois)::date;
  fin_mois   date := (date_trunc('month', le_mois) + interval '1 month - 1 day')::date;
  nees  integer := 0;
begin
  if foyer is null then return 0; end if;

  with parts as (
    select p.user_profile_id as uid, p.part_bps
    from public.parts_du_foyer(debut_mois, foyer) p
  ),
  -- Une charge active ce mois-là, et qui concerne au moins quelqu'un de présent.
  actives as (
    select c.*,
           public.provision_mensuelle(c.montant_cents, c.periodicite) as du_mois
    from public.charge c
    where c.household_id = foyer
      and c.debut <= fin_mois
      and (c.fin is null or c.fin >= debut_mois)
      and exists (
        select 1 from public.charge_participant cp
        join parts on parts.uid = cp.user_profile_id
        where cp.charge_id = c.id)
  ),
  creees as (
    insert into public.depense
      (household_id, charge_id, mois, libelle, montant_cents, nature, source, compte_id)
    select foyer, a.id, debut_mois, a.libelle, a.du_mois,
           case when a.variable then 'provision' else 'provision' end,
           'modele', a.compte_id
    from actives a
    on conflict (charge_id, mois) do nothing
    returning id, charge_id, montant_cents
  ),
  -- Les participants de chaque dépense neuve, avec leur poids du mois.
  pesee as (
    select c.id as depense_id, c.montant_cents, cp.user_profile_id as uid,
           parts.part_bps,
           sum(parts.part_bps) over (partition by c.id) as bps_total
    from creees c
    join public.charge_participant cp on cp.charge_id = c.charge_id
    join parts on parts.uid = cp.user_profile_id
  ),
  /* Les participants d'une charge ne sont pas toujours tout le foyer : leurs
     parts ne font donc pas 10000 à elles seules. On les renormalise sur leur
     propre total — sans quoi une charge à un seul participant ne lui
     attribuerait que 60 % de ce qu'il paie seul. */
  brut as (
    select depense_id, uid, part_bps, montant_cents,
           (montant_cents::bigint * part_bps / bps_total)::integer as cents,
           row_number() over (partition by depense_id order by part_bps desc, uid) as rang
    from pesee where bps_total > 0
  ),
  /* Le centime résiduel de la division va au plus gros contributeur : la somme
     des parts DOIT recomposer le total, sinon le budget ment dès la
     première ligne. */
  reste as (
    select depense_id, montant_cents - sum(cents) as r
    from brut group by depense_id, montant_cents
  )
  insert into public.depense_part
    (depense_id, user_profile_id, household_id, part_cents, part_bps)
  select b.depense_id, b.uid, foyer,
         b.cents + case when b.rang = 1 then coalesce(r.r, 0) else 0 end,
         b.part_bps
  from brut b left join reste r on r.depense_id = b.depense_id;

  get diagnostics nees = row_count;
  return nees;
end $$;

comment on function public.ouvre_le_mois(date, uuid) is
  'Engendre les dépenses du mois à partir des charges actives et fige les parts '
  'en centimes. Idempotente : la clé se fige au premier appel, les suivants ne '
  'touchent rien. `le_foyer` n''est honoré que pour le rôle de service.';

revoke execute on function public.ouvre_le_mois(date, uuid) from public, anon;
grant   execute on function public.ouvre_le_mois(date, uuid) to authenticated, service_role;

-- ═══ Les droits ════════════════════════════════════════════════════════════
--
-- Classe C sur les quatre tables : le foyer voit et écrit ce qui le concerne.
-- Les charges perso y comprises — « chacun les siennes » est une convention
-- d'usage, pas un verrou : les deux les voient et peuvent les corriger, ce qui
-- est cohérent avec un foyer qui partage tout. Le revenu, lui, reste écrit par
-- son seul titulaire : un salaire n'est pas une dépense.
do $$
declare t text;
begin
  foreach t in array array['charge', 'charge_participant', 'depense', 'depense_part'] loop
    execute format('alter table public.%I enable row level security', t);
    execute format(
      'create policy %I on public.%I for select to authenticated
         using (household_id = public.current_household())', t || '_select', t);
    execute format(
      'create policy %I on public.%I for insert to authenticated
         with check (household_id = public.current_household())', t || '_insert', t);
    execute format(
      'create policy %I on public.%I for update to authenticated
         using (household_id = public.current_household())
         with check (household_id = public.current_household())', t || '_update', t);
    execute format(
      'create policy %I on public.%I for delete to authenticated
         using (household_id = public.current_household())', t || '_delete', t);
  end loop;
end $$;

-- ── Ce qu'une ligne désigne appartient au même foyer qu'elle ───────────────
create trigger z_compte_id_meme_foyer before insert or update on public.charge
  for each row execute function public.tg_meme_foyer('compte_id', 'compte');
create trigger z_charge_id_meme_foyer before insert or update on public.charge_participant
  for each row execute function public.tg_meme_foyer('charge_id', 'charge');
create trigger z_user_profile_id_meme_foyer before insert or update on public.charge_participant
  for each row execute function public.tg_meme_foyer('user_profile_id', 'user_profile');
create trigger z_charge_id_meme_foyer before insert or update on public.depense
  for each row execute function public.tg_meme_foyer('charge_id', 'charge');
create trigger z_compte_id_meme_foyer before insert or update on public.depense
  for each row execute function public.tg_meme_foyer('compte_id', 'compte');
create trigger z_paye_par_meme_foyer before insert or update on public.depense
  for each row execute function public.tg_meme_foyer('paye_par', 'user_profile');
create trigger z_depense_id_meme_foyer before insert or update on public.depense_part
  for each row execute function public.tg_meme_foyer('depense_id', 'depense');
create trigger z_user_profile_id_meme_foyer before insert or update on public.depense_part
  for each row execute function public.tg_meme_foyer('user_profile_id', 'user_profile');

-- ── Ce qui ne change pas ───────────────────────────────────────────────────
--
-- Une dépense ne change pas de mois : la déplacer réécrirait deux mois d'un
-- coup, celui qu'elle quitte et celui où elle arrive — et les parts figées
-- qu'elle porte ne vaudraient plus pour ni l'un ni l'autre. Et elle ne change
-- pas de charge, sans quoi l'unicité qui porte l'idempotence ne dirait rien.
create or replace function public.tg_depense_ancree()
returns trigger language plpgsql as $$
begin
  if public.is_service_role() then return new; end if;
  if new.mois is distinct from old.mois then
    raise exception 'Une dépense ne change pas de mois.' using errcode = 'check_violation';
  end if;
  if new.charge_id is distinct from old.charge_id then
    raise exception 'Une dépense ne change pas de charge.' using errcode = 'check_violation';
  end if;
  return new;
end $$;

create trigger tg_depense_ancree before update on public.depense
  for each row execute function public.tg_depense_ancree();

-- Une part figée est figée : corriger le montant d'une dépense se fait en
-- reposant ses parts, pas en les retouchant une par une jusqu'à ce que la
-- somme tombe juste par hasard.
create or replace function public.tg_part_figee()
returns trigger language plpgsql as $$
begin
  if public.is_service_role() then return new; end if;
  raise exception 'Une part ne se retouche pas : supprime-la et repose-la.'
    using errcode = 'check_violation';
end $$;

create trigger tg_depense_part_figee before update on public.depense_part
  for each row execute function public.tg_part_figee();

-- ── Les index des prédicats ────────────────────────────────────────────────
create index charge_household_idx        on public.charge (household_id);
create index charge_compte_idx           on public.charge (compte_id);
create index charge_participant_hh_idx   on public.charge_participant (household_id);
create index charge_participant_uid_idx  on public.charge_participant (user_profile_id);
create index depense_household_mois_idx  on public.depense (household_id, mois);
create index depense_charge_idx          on public.depense (charge_id);
create index depense_part_household_idx  on public.depense_part (household_id);
create index depense_part_uid_idx        on public.depense_part (user_profile_id);

-- ── L'export suit le schéma, dans la MÊME migration ────────────────────────
-- `tables_de_foyer()` énumère par introspection : `tests/rgpd.test.ts` devient
-- rouge à l'instant où une table portant `household_id` manque ici.
create or replace function public.export_my_data()
returns jsonb language sql stable security definer set search_path = public as $$
  with hh as (select public.current_household() as id)
  select public.export_my_data_base() || jsonb_build_object(
    'weighing',            (select coalesce(jsonb_agg(to_jsonb(w)), '[]'::jsonb)
                            from public.weighing w, hh where w.household_id = hh.id),
    'household_unit_weight', (select coalesce(jsonb_agg(to_jsonb(u)), '[]'::jsonb)
                            from public.household_unit_weight u, hh where u.household_id = hh.id),
    'household_ingredient_resolution', (select coalesce(jsonb_agg(to_jsonb(r)), '[]'::jsonb)
                            from public.household_ingredient_resolution r, hh
                            where r.household_id = hh.id),
    'foyer_ami',           (select coalesce(jsonb_agg(to_jsonb(a)), '[]'::jsonb)
                            from public.foyer_ami a, hh
                            where a.invite_par = hh.id or a.accepte_par = hh.id),
    'recipes',             (select coalesce(jsonb_agg(to_jsonb(r)), '[]'::jsonb)
                            from public.recipe r, hh where r.owner_household_id = hh.id),
    'session_convives',    (select coalesce(jsonb_agg(to_jsonb(s)), '[]'::jsonb)
                            from public.session_convive s, hh
                            where s.hote_id = hh.id or s.invite_id = hh.id),
    -- Budget, lot 1
    'comptes',             (select coalesce(jsonb_agg(to_jsonb(c)), '[]'::jsonb)
                            from public.compte c, hh where c.household_id = hh.id),
    'revenus',             (select coalesce(jsonb_agg(to_jsonb(v)), '[]'::jsonb)
                            from public.revenu v, hh where v.household_id = hh.id),
    'regles_partage',      (select coalesce(jsonb_agg(to_jsonb(g)), '[]'::jsonb)
                            from public.regle_partage g, hh where g.household_id = hh.id),
    -- Budget, lot 2
    'charges',             (select coalesce(jsonb_agg(to_jsonb(c)), '[]'::jsonb)
                            from public.charge c, hh where c.household_id = hh.id),
    'charge_participants', (select coalesce(jsonb_agg(to_jsonb(p)), '[]'::jsonb)
                            from public.charge_participant p, hh where p.household_id = hh.id),
    'depenses',            (select coalesce(jsonb_agg(to_jsonb(d)), '[]'::jsonb)
                            from public.depense d, hh where d.household_id = hh.id),
    'depense_parts',       (select coalesce(jsonb_agg(to_jsonb(x)), '[]'::jsonb)
                            from public.depense_part x, hh where x.household_id = hh.id)
  )
$$;
revoke execute on function public.export_my_data() from public, anon;
grant   execute on function public.export_my_data() to authenticated;
