-- ═══════════════════════════════════════════════════════════════════════════
-- QUE PERSONNE NE SOIT DÉSAVANTAGÉ
--
-- Un audit arithmétique a simulé douze mois avec des revenus d'exemple —
-- 3 000 € et 2 000 €, quinze charges, 181 dépenses, 32 000 € — et mesuré ce
-- qu'on redoutait : le centime de l'arrondi tombe TOUJOURS du même côté.
-- 104,52 centimes sur l'année, sur 157 lignes partagées, sans une seule
-- exception. Plus deux défauts durs. Cette migration règle les quatre.
-- ═══════════════════════════════════════════════════════════════════════════

-- ── 1 · La répartition aux PLUS FORTS RESTES ──────────────────────────────
--
-- Partout, le reliquat de la division entière allait « au plus gros
-- contributeur » (`order by poids desc`). C'est commode et c'est biaisé : le
-- même paie l'arrondi chaque mois, sur chaque ligne. Et sur une charge
-- moitié-moitié, l'égalité était départagée par l'identifiant — un uuid tiré
-- une fois, figé à vie : Netflix à 15,99 € donnait 8,00 / 7,99 à la même
-- personne pendant des années.
--
-- La méthode des plus forts restes (Hamilton) donne le centime à celui dont la
-- part exacte a la plus grande partie fractionnaire. C'est la répartition
-- proportionnelle la plus juste connue, et surtout : elle ne penche pas.
-- L'ordre du reste de la division EST cette partie fractionnaire, à l'échelle
-- près — on l'a donc gratuitement.
--
-- Le signe est traité à part : on répartit la valeur absolue puis on le
-- rétablit. La division entière tronque vers zéro, et sur un remboursement
-- c'était le gros contributeur qui en profitait.

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
  if debut_mois < '2000-01-01'::date
     or debut_mois > (current_date + interval '5 years')::date then
    raise exception 'Mois hors des bornes raisonnables : %', debut_mois
      using errcode = 'check_violation';
  end if;

  create temp table if not exists depenses_nees
    (id uuid, charge_id uuid, montant_cents integer) on commit drop;
  delete from depenses_nees where true;

  with actives as (
    select c.id, c.libelle, c.cle, c.compte_id, c.variable, c.periodicite, c.enveloppe_id,
           public.provision_mensuelle(c.montant_cents, c.periodicite) as du_mois
    from public.charge c
    where c.household_id = foyer
      and c.archive_le is null
      and c.debut <= fin_mois
      and (c.fin is null or c.fin >= debut_mois)
      and exists (
        select 1 from public.charge_participant cp
        join public.user_profile p on p.id = cp.user_profile_id
        where cp.charge_id = c.id and p.entre_le <= fin_mois)
  )
  insert into public.depense
    (household_id, charge_id, mois, libelle, montant_cents, montant_prevu_cents,
     nature, source, compte_id, enveloppe_id)
  select foyer, a.id, debut_mois, a.libelle, a.du_mois, a.du_mois,
         case when a.variable or a.periodicite <> 'mensuel' or a.enveloppe_id is not null
              then 'estimee' else 'connue' end,
         'modele', a.compte_id, a.enveloppe_id
  from actives a
  on conflict do nothing;

  get diagnostics nees = row_count;

  insert into depenses_nees (id, charge_id, montant_cents)
  select d.id, d.charge_id, d.montant_cents
  from public.depense d
  where d.household_id = foyer and d.mois = debut_mois and d.source = 'modele'
    and not exists (select 1 from public.depense_part p where p.depense_id = d.id);

  perform public.repartit_les_lignes(foyer, debut_mois);
  return nees;
end $$;

-- ── Le cœur : une seule fonction qui répartit, et bien ────────────────────
--
-- Elle était recopiée dans quatre endroits, chacun avec sa variante du même
-- biais. Une seule maintenant : ce qui est juste l'est partout, et ce qui
-- serait faux se corrige une fois.
create or replace function public.repartit_les_lignes(foyer uuid, le_mois date)
returns void
language sql security definer set search_path = public as $$
  with a_refaire as (
    select d.id, d.charge_id, d.montant_cents
    from public.depense d
    where d.household_id = foyer and d.mois = le_mois and d.source = 'modele'
      and d.charge_id is not null
      and not exists (select 1 from public.depense_part p where p.depense_id = d.id)
  ),
  pesee as (
    select n.id as depense_id, n.montant_cents, cp.user_profile_id as uid,
           case when sum(p.part_bps) over (partition by n.id) = 0
                then 1 else p.part_bps end as poids
    from a_refaire n
    join public.charge c on c.id = n.charge_id
    join public.charge_participant cp on cp.charge_id = c.id
    join lateral public.parts_du_foyer(le_mois, foyer, c.cle) p
      on p.user_profile_id = cp.user_profile_id
  ),
  total as (
    select depense_id, montant_cents, uid, poids,
           sum(poids) over (partition by depense_id) as poids_total
    from pesee
  ),
  /* On répartit la VALEUR ABSOLUE, puis on rétablit le signe : la division
     entière tronque vers zéro, et sur un remboursement c'était le plus gros
     contributeur qui en profitait. */
  brut as (
    select depense_id, uid, poids, poids_total,
           case when montant_cents < 0 then -1 else 1 end as signe,
           abs(montant_cents)::bigint * poids / poids_total as base,
           /* Le reste de la division EST la partie fractionnaire à l'échelle
              près : les plus forts restes se lisent directement dedans. */
           row_number() over (
             partition by depense_id
             order by (abs(montant_cents)::bigint * poids) % poids_total desc, uid
           ) as rang,
           abs(montant_cents)::bigint as absolu,
           (poids::bigint * 10000) / poids_total as bps_base,
           row_number() over (
             partition by depense_id
             order by (poids::bigint * 10000) % poids_total desc, uid
           ) as rang_bps
    from total where poids_total > 0
  ),
  manque as (
    select depense_id, max(absolu) - sum(base) as cents,
           10000 - sum(bps_base) as bps
    from brut group by depense_id
  )
  insert into public.depense_part
    (depense_id, user_profile_id, household_id, part_cents, part_bps)
  select b.depense_id, b.uid, foyer,
         (b.base + case when b.rang <= m.cents then 1 else 0 end)::integer * b.signe,
         (b.bps_base + case when b.rang_bps <= m.bps then 1 else 0 end)::integer
  from brut b join manque m on m.depense_id = b.depense_id
$$;
revoke execute on function public.repartit_les_lignes(uuid, date) from public, anon, authenticated;

comment on function public.repartit_les_lignes(uuid, date) is
  'Pose les parts des dépenses du mois qui n''en ont pas encore, aux PLUS FORTS '
  'RESTES : le centime de l''arrondi va à celui dont la part exacte a la plus '
  'grande partie fractionnaire, jamais au même par construction.';

-- ── 2 · `refige_pour` : même répartition, et verrou À LA LIGNE ────────────
--
-- Le verrou portait sur le MOIS : une seule ligne confirmée gelait tout le
-- reste. Conséquence mesurée : quelqu'un facturé 915 € pour un mois qu'il
-- n'habite pas, qui corrige sa date d'entrée, et dont l'`update` réussit en
-- silence sans rien changer — parce qu'une autre ligne du mois avait été
-- confirmée entre-temps. Une ligne réglée se défend ; elle n'a pas à défendre
-- ses voisines.
create or replace function public.refige_pour(foyer uuid, le_mois date)
returns void
language plpgsql security definer set search_path = public as $$
declare debut_mois date := date_trunc('month', le_mois)::date;
begin
  if foyer is null then return; end if;

  /* On ne retire QUE les parts des lignes qu'on saura repeupler, et qui ne
     sont ni réglées ni confirmées. Le reste garde ce qu'il a. */
  delete from public.depense_part p
  where p.depense_id in (
    select d.id from public.depense d
    where d.household_id = foyer and d.mois = debut_mois and d.source = 'modele'
      and d.charge_id is not null
      and d.regle_le is null and d.confirme_le is null
      and exists (
        select 1 from public.charge_participant cp
        join public.user_profile up on up.id = cp.user_profile_id
        where cp.charge_id = d.charge_id and up.entre_le <= debut_mois));

  perform public.repartit_les_lignes(foyer, debut_mois);
end $$;
revoke execute on function public.refige_pour(uuid, date) from public, anon, authenticated;

-- ── 3 · L'excédent : il DÉBORDAIT, et il ne conservait pas ───────────────
--
-- `sum(ecart * part_cents / …)` multipliait deux `integer` : un loyer de
-- 1 250 € confirmé à 1 550 € donnait 2,27 milliards, au-delà de la capacité
-- d'un entier. Vérifié : `integer out of range`, et tout l'écran du mois meurt.
-- Le seuil était de 283 € d'écart sur leur loyer.
--
-- Et la division tronquée par ligne perdait des centimes que personne ne
-- recevait : six sur l'année, et parfois en inventait. Ici aussi, plus forts
-- restes.
create or replace function public.excedent_du_mois(le_mois date)
returns table (user_profile_id uuid, excedent_cents bigint)
language sql stable security definer set search_path = public as $$
  with lignes as (
    select d.id, d.montant_cents, coalesce(d.montant_prevu_cents, d.montant_cents) as prevu
    from public.depense d
    where d.household_id = public.current_household()
      and d.mois = date_trunc('month', le_mois)::date
      and d.source = 'modele'
      and d.nature = 'connue'
  ),
  parts as (
    select p.user_profile_id as uid, l.id,
           l.prevu - l.montant_cents as ecart,
           p.part_cents,
           sum(p.part_cents) over (partition by l.id) as total_ligne
    from lignes l join public.depense_part p on p.depense_id = l.id
    where l.prevu <> l.montant_cents
  ),
  /* `::bigint` AVANT la multiplication, et la valeur absolue pour que la
     troncature ne dépende pas du signe. */
  brut as (
    select uid, id,
           case when ecart < 0 then -1 else 1 end as signe,
           abs(ecart)::bigint * part_cents / nullif(total_ligne, 0) as base,
           abs(ecart)::bigint as absolu,
           row_number() over (
             partition by id
             order by (abs(ecart)::bigint * part_cents) % nullif(total_ligne, 0) desc, uid
           ) as rang
    from parts where total_ligne <> 0
  ),
  manque as (select id, max(absolu) - sum(base) as combien from brut group by id)
  select b.uid,
         sum((b.base + case when b.rang <= m.combien then 1 else 0 end) * b.signe)::bigint
  from brut b join manque m on m.id = b.id
  group by b.uid
$$;
revoke execute on function public.excedent_du_mois(date) from public, anon;
grant   execute on function public.excedent_du_mois(date) to authenticated, service_role;

-- ── 4 · Confirmer reproportionnait sur les CENTIMES, pas sur la clé ──────
--
-- La nouvelle répartition se faisait sur les parts déjà arrondies, et non sur
-- les points de base. Mesuré : Netflix à 15,99 € en moitié-moitié donne
-- 8,00/7,99 ; confirmé à 16,00 € il donne 8,01/7,99 au lieu de 8,00/8,00, et
-- chaque aller-retour creuse l'écart — sans borne, toujours dans le même sens,
-- pendant que les points de base affichent toujours 5000/5000. L'écriture
-- contredisait la clé.
create or replace function public.confirme_la_depense(la_depense uuid, reel_cents integer)
returns void
language plpgsql security definer set search_path = public as $$
declare foyer uuid := public.current_household();
        ancien integer;
        nb_parts integer;   -- surtout pas `combien` : c'est aussi une colonne du CTE
begin
  select d.montant_cents into ancien from public.depense d
  where d.id = la_depense and d.household_id = foyer;
  if ancien is null then raise exception 'Dépense inconnue.'; end if;

  select count(*) into nb_parts from public.depense_part where depense_id = la_depense;
  if nb_parts = 0 then
    raise exception 'Cette dépense n''est partagée avec personne : il n''y a rien à confirmer.'
      using errcode = 'check_violation';
  end if;

  create temp table if not exists anciennes_parts
    (user_profile_id uuid, part_cents integer, part_bps integer) on commit drop;
  delete from anciennes_parts where true;
  insert into anciennes_parts
    select user_profile_id, part_cents, part_bps
    from public.depense_part where depense_id = la_depense;

  delete from public.depense_part where depense_id = la_depense;

  update public.depense
     set montant_cents = reel_cents, nature = 'connue', confirme_le = now()
   where id = la_depense;

  insert into public.depense_part
    (depense_id, user_profile_id, household_id, part_cents, part_bps)
  with total as (
    select coalesce(sum(part_bps), 0) as bps, coalesce(sum(part_cents), 0) as cents,
           count(*) as n
    from anciennes_parts
  ),
  /* La CLÉ, pas les centimes déjà arrondis. On ne retombe sur les centimes que
     si les points de base sont tous nuls — ce qui n'arrive que sur une ligne
     posée à la main. */
  pesee as (
    select a.user_profile_id as uid, a.part_bps,
           case when (select bps from total) > 0 then a.part_bps::bigint
                when (select cents from total) > 0 then a.part_cents::bigint
                else 1::bigint end as poids
    from anciennes_parts a
  ),
  somme as (select sum(poids) as t from pesee),
  brut as (
    select p.uid, p.part_bps,
           case when reel_cents < 0 then -1 else 1 end as signe,
           abs(reel_cents)::bigint * p.poids / s.t as base,
           row_number() over (
             order by (abs(reel_cents)::bigint * p.poids) % s.t desc, p.uid) as rang
    from pesee p, somme s where s.t > 0
  ),
  manque as (select abs(reel_cents)::bigint - coalesce(sum(base), 0) as combien from brut)
  select la_depense, b.uid, foyer,
         ((b.base + case when b.rang <= (select combien from manque) then 1 else 0 end)
          * b.signe)::integer,
         b.part_bps
  from brut b;
end $$;
revoke execute on function public.confirme_la_depense(uuid, integer) from public, anon;
grant   execute on function public.confirme_la_depense(uuid, integer) to authenticated, service_role;

-- ── 5 · `parts_du_foyer` : l'égalité ne penche plus ──────────────────────
-- Le −1 de l'ajustement était toujours pris au plus gros revenu. Aux plus
-- forts restes, il va à celui dont la part exacte le mérite.
create or replace function public.parts_du_foyer(
  le_mois date, le_foyer uuid default null, la_cle text default null)
returns table (user_profile_id uuid, part_bps integer)
language sql stable security definer set search_path = public as $$
  with bornes as (
    select (date_trunc('month', le_mois) + interval '1 month - 1 day')::date as fin,
           case when public.is_service_role() and le_foyer is not null
                then le_foyer else public.current_household() end as foyer
  ),
  regle as (
    select coalesce(la_cle, (
      select r.cle from public.regle_partage r, bornes b
      where r.household_id = b.foyer and r.valid_from <= b.fin
      order by r.valid_from desc limit 1
    ), 'prorata') as cle
  ),
  membres as (
    select p.id as uid,
           (select v.net_mensuel_cents
              from public.revenu v, bornes b2
             where v.user_profile_id = p.id
               and v.household_id = b2.foyer
               and v.valid_from <= b2.fin
             order by v.valid_from desc limit 1) as revenu_cents
    from public.user_profile p, bornes b
    where p.household_id = b.foyer and p.entre_le <= b.fin
  ),
  pesee as (
    select uid,
           case when (select cle from regle) = 'moitie'
                     or exists (select 1 from membres where revenu_cents is null)
                     or coalesce((select sum(revenu_cents) from membres), 0) = 0
                then 1::bigint else revenu_cents::bigint end as poids
    from membres
  ),
  somme as (select sum(poids) as total from pesee),
  brut as (
    select p.uid, p.poids,
           (p.poids * 10000) / s.total as base,
           row_number() over (order by (p.poids * 10000) % s.total desc, p.uid) as rang
    from pesee p, somme s where s.total > 0
  ),
  manque as (select 10000 - coalesce(sum(base), 0) as combien from brut)
  select b.uid,
         (b.base + case when b.rang <= (select combien from manque) then 1 else 0 end)::integer
  from brut b
$$;
revoke execute on function public.parts_du_foyer(date, uuid, text) from public, anon;
grant   execute on function public.parts_du_foyer(date, uuid, text) to authenticated, service_role;
