-- Les trois lignes de septembre confirmées à des montants IMPAIRS, centimes compris :
-- 800,01 €, 400,03 € et 100,07 €. Les saisies d'amorce doivent les reprendre au
-- centime, et la clôture de septembre ne rien perdre ni arrondir.
create temporary table nouveaux (libelle text, cents integer) on commit drop;
insert into nouveaux values ('Courses', 80001), ('Restaurants', 40003), ('Sorties et culture', 10007);
create temporary table ses_parts on commit drop as
  select p.depense_id, p.user_profile_id, p.household_id, p.part_bps, n.cents
  from public.depense_part p
  join public.depense d on d.id = p.depense_id
  join nouveaux n on n.libelle = d.libelle
  where d.mois = '2026-09-01' and d.confirme_le is not null;
delete from public.depense_part where depense_id in (select depense_id from ses_parts);
update public.depense d set montant_cents = n.cents
from nouveaux n
where n.libelle = d.libelle and d.mois = '2026-09-01' and d.confirme_le is not null;
insert into public.depense_part (depense_id, user_profile_id, household_id, part_cents, part_bps)
select depense_id, user_profile_id, household_id, cents, part_bps from ses_parts;
